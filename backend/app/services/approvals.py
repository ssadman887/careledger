"""Generic approval engine.

* Policies (`approval_policies`) set, per kind, the threshold above which approval is needed and
  the role that approves. Admins and finance managers can change them at runtime.
* Domain services call `needs_approval()` and `request()` when something must wait; decisions go
  through `decide()`, which enforces segregation of duties (requester != approver, approver role)
  and dispatches to the kind's handler (e.g. post the journal entry, pay the refund).
* Handlers in domain services call `record_decision()`, so a decision taken through a
  domain-specific endpoint is reflected here too.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from app.core.pagination import PageParams
from app.models.approvals import (
    KINDS,
    Approval,
    ApprovalComment,
    ApprovalKind,
    ApprovalPolicy,
    ApprovalStatus,
)
from app.models.identity import RoleName
from app.repositories import approvals as repo
from app.services import audit
from app.services.audit import Actor

K = ApprovalKind


@dataclass(frozen=True)
class PolicyDefault:
    threshold: Decimal
    approver_role: str
    description: str


DEFAULTS: dict[str, PolicyDefault] = {
    K.MANUAL_JOURNAL: PolicyDefault(
        Decimal("10000.00"), RoleName.FINANCE_MANAGER, "Manual journal entries above the threshold"
    ),
    K.REFUND: PolicyDefault(
        Decimal("500.00"), RoleName.FINANCE_MANAGER, "Patient refunds above the threshold"
    ),
    K.WRITE_OFF: PolicyDefault(
        Decimal("0.00"), RoleName.FINANCE_MANAGER, "Bad-debt write-offs (any amount)"
    ),
    K.VENDOR_BILL: PolicyDefault(
        Decimal("5000.00"),
        RoleName.FINANCE_MANAGER,
        "Vendor bills above the threshold or failing three-way match",
    ),
    K.PAYROLL_RUN: PolicyDefault(
        Decimal("0.00"), RoleName.FINANCE_MANAGER, "Monthly payroll runs (any amount)"
    ),
}


def policy(session: Session, kind: str) -> ApprovalPolicy:
    """The stored policy, or an unsaved default if none has been seeded."""
    if kind not in KINDS:
        raise ValidationFailed(f"Unknown approval kind {kind}", code="invalid_kind")
    stored = repo.get_policy(session, kind)
    if stored is not None:
        return stored
    d = DEFAULTS[kind]
    return ApprovalPolicy(
        kind=kind,
        threshold=d.threshold,
        approver_role=d.approver_role,
        description=d.description,
        is_active=True,
    )


def threshold(session: Session, kind: str) -> Decimal:
    p = policy(session, kind)
    # An inactive policy disables approvals for that kind.
    return p.threshold if p.is_active else Decimal("999999999999.99")


def needs_approval(session: Session, kind: str, amount: Decimal) -> bool:
    return amount > threshold(session, kind)


def request(
    session: Session,
    actor: Actor,
    *,
    kind: str,
    entity_type: str,
    entity_id: int,
    reference: str,
    summary: str,
    amount: Decimal,
) -> Approval:
    p = policy(session, kind)
    existing = repo.get_by_entity(session, kind, entity_id)
    if existing is not None:
        return _reopen(session, actor, existing, summary=summary, amount=amount, policy_=p)
    approval = Approval(
        kind=kind,
        entity_type=entity_type,
        entity_id=entity_id,
        reference=reference,
        summary=summary[:500],
        amount=amount,
        threshold=p.threshold,
        approver_role=p.approver_role,
        status=ApprovalStatus.PENDING,
        requested_by_id=actor.id,
        requested_by_label=actor.label,
    )
    session.add(approval)
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="approval",
        entity_id=approval.id,
        action="create",
        after=audit.snapshot(approval),
    )
    return approval


def _reopen(
    session: Session,
    actor: Actor,
    approval: Approval,
    *,
    summary: str,
    amount: Decimal,
    policy_: ApprovalPolicy,
) -> Approval:
    """Resubmission of a corrected record (e.g. a rejected payroll run): the same request goes
    back to pending. The earlier decision stays in the audit log and as a comment."""
    if approval.status == ApprovalStatus.PENDING:
        raise Conflict("An approval request is already pending", code="already_pending")
    before = audit.snapshot(approval)
    approval.comments.append(
        ApprovalComment(
            approval_id=approval.id,
            author_id=actor.id,
            author_label=actor.label,
            body=f"Resubmitted. Previous decision: {approval.status} by "
            f"{approval.decided_by_label or '-'}"
            + (f" ({approval.decision_note})" if approval.decision_note else ""),
        )
    )
    approval.status = ApprovalStatus.PENDING
    approval.summary = summary[:500]
    approval.amount = amount
    approval.threshold = policy_.threshold
    approval.approver_role = policy_.approver_role
    approval.requested_by_id = actor.id
    approval.requested_by_label = actor.label
    approval.decided_by_id = None
    approval.decided_by_label = None
    approval.decided_at = None
    approval.decision_note = None
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="approval",
        entity_id=approval.id,
        action="resubmit",
        before=before,
        after=audit.snapshot(approval),
    )
    return approval


def get_approval(session: Session, approval_id: int, *, lock: bool = False) -> Approval:
    approval = repo.get_approval(session, approval_id, lock=lock)
    if approval is None:
        raise NotFound("Approval not found")
    return approval


def record_decision(
    session: Session, actor: Actor, *, kind: str, entity_id: int, approved: bool, note: str
) -> Approval | None:
    """Mark the pending approval for (kind, entity) decided. Called by domain handlers."""
    approval = repo.get_by_entity(session, kind, entity_id)
    if approval is None or approval.status != ApprovalStatus.PENDING:
        return approval
    before = audit.snapshot(approval)
    approval.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
    approval.decided_by_id = actor.id
    approval.decided_by_label = actor.label
    approval.decided_at = datetime.now(UTC)
    approval.decision_note = note or None
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="approval",
        entity_id=approval.id,
        action="status_change",
        before=before,
        after=audit.snapshot(approval),
    )
    return approval


Handler = Callable[[Session, Actor, int, str], object]


def _handlers() -> dict[str, tuple[Handler, Handler]]:
    # Imported lazily: domain services import this module.
    from app.services import ap, ar, ledger, payments, payroll

    return {
        K.MANUAL_JOURNAL: (
            lambda s, a, i, n: ledger.approve_entry(s, a, i),
            lambda s, a, i, n: ledger.reject_entry(s, a, i, n),
        ),
        K.REFUND: (
            lambda s, a, i, n: payments.approve_refund(s, a, i, n),
            lambda s, a, i, n: payments.reject_refund(s, a, i, n),
        ),
        K.WRITE_OFF: (
            lambda s, a, i, n: ar.approve_write_off(s, a, i, n),
            lambda s, a, i, n: ar.reject_write_off(s, a, i, n),
        ),
        K.VENDOR_BILL: (
            lambda s, a, i, n: ap.approve_bill(s, a, i, n),
            lambda s, a, i, n: ap.reject_bill(s, a, i, n),
        ),
        K.PAYROLL_RUN: (
            lambda s, a, i, n: payroll.approve_run(s, a, i, n),
            lambda s, a, i, n: payroll.reject_run(s, a, i, n),
        ),
    }


def check_can_decide(actor: Actor, approval: Approval) -> None:
    if approval.status != ApprovalStatus.PENDING:
        raise Conflict("This request has already been decided", code="not_pending")
    if approval.requested_by_id is not None and approval.requested_by_id == actor.id:
        raise PermissionDenied("You cannot decide your own request", code="self_approval")
    if approval.approver_role not in actor.roles:
        raise PermissionDenied(
            f"Only a {approval.approver_role} can decide this request", code="not_approver"
        )


def decide(
    session: Session, actor: Actor, approval_id: int, *, approve: bool, note: str
) -> Approval:
    approval = get_approval(session, approval_id, lock=True)
    check_can_decide(actor, approval)
    if not approve and not note.strip():
        raise ValidationFailed("A rejection needs a reason", code="reason_required")
    on_approve, on_reject = _handlers()[approval.kind]
    (on_approve if approve else on_reject)(session, actor, approval.entity_id, note)
    # Handlers record the decision; make sure it is recorded even if one did not.
    record_decision(
        session,
        actor,
        kind=approval.kind,
        entity_id=approval.entity_id,
        approved=approve,
        note=note,
    )
    session.refresh(approval)
    return approval


def comment(session: Session, actor: Actor, approval_id: int, body: str) -> Approval:
    approval = get_approval(session, approval_id)
    if not body.strip():
        raise ValidationFailed("Comment is empty", code="comment_required")
    approval.comments.append(
        ApprovalComment(
            approval_id=approval.id, author_id=actor.id, author_label=actor.label, body=body.strip()
        )
    )
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="approval",
        entity_id=approval.id,
        action="comment",
        after={"body": body.strip()},
    )
    return approval


def list_approvals(
    session: Session,
    actor: Actor,
    params: PageParams,
    *,
    status: str | None,
    kind: str | None,
    scope: str,
) -> tuple[Sequence[Approval], int]:
    """scope: 'all' (auditors, finance), 'to_decide' (my approver roles), 'mine' (I requested)."""
    roles = sorted(actor.roles) if scope == "to_decide" else None
    requested_by = actor.id if scope == "mine" else None
    return repo.list_approvals(
        session, params, status=status, kind=kind, approver_roles=roles, requested_by=requested_by
    )


def update_policy(
    session: Session,
    actor: Actor,
    kind: str,
    *,
    threshold_amount: Decimal | None,
    approver_role: str | None,
    is_active: bool | None,
) -> ApprovalPolicy:
    current = policy(session, kind)
    if current.id is None:  # unsaved default: persist it first
        session.add(current)
        session.flush()
    before = audit.snapshot(current)
    if threshold_amount is not None:
        if threshold_amount < 0:
            raise ValidationFailed("Threshold cannot be negative", code="invalid_threshold")
        current.threshold = threshold_amount
    if approver_role is not None:
        if approver_role not in {r.value for r in RoleName} or approver_role == RoleName.AUDITOR:
            raise ValidationFailed("Invalid approver role", code="invalid_role")
        current.approver_role = approver_role
    if is_active is not None:
        current.is_active = is_active
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="approval_policy",
        entity_id=current.id,
        action="update",
        before=before,
        after=audit.snapshot(current),
    )
    return current


def ensure_policies(session: Session) -> list[ApprovalPolicy]:
    """Seed default policies (idempotent)."""
    existing = {p.kind for p in session.scalars(select(ApprovalPolicy)).all()}
    for kind, d in DEFAULTS.items():
        if kind not in existing:
            session.add(
                ApprovalPolicy(
                    kind=kind,
                    threshold=d.threshold,
                    approver_role=d.approver_role,
                    description=d.description,
                )
            )
    session.flush()
    return list(session.scalars(select(ApprovalPolicy).order_by(ApprovalPolicy.kind)).all())
