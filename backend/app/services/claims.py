"""Claims: generation from invoices, the claim state machine, adjudication outcomes, appeals,
closing, short-pay acceptance and insurer payments.

Ledger effects (docs/ARCHITECTURE.md section 4):
  submit            Dr 1110 AR-Insurers        / Cr 1100 AR-Patients   (insurer share)
  partial approval  Dr 4900 Contractual adj.   / Cr 1110               (shortfall)
  accept short pay  Dr 4900                    / Cr 1110               (unpaid remainder)
  close (denied)    Dr 1100 AR-Patients        / Cr 1110               (back to patient)
  insurer payment   Dr 1020 Bank               / Cr 1110               (remittance line)
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation, Conflict, NotFound, ValidationFailed
from app.models.billing import InvoiceStatus, Payment, PaymentKind, PaymentMethod
from app.models.insurance import Claim, ClaimEvent, ClaimLine, ClaimStatus
from app.repositories import billing as billing_repo
from app.repositories import insurance as repo
from app.services import audit, ledger, posting
from app.services.audit import Actor
from app.services.coverage import (
    CoverageResult,
    CoverageTerms,
    allocate,
    cap_insurer,
    compute_coverage,
)
from app.services.insurance import get_policy, policy_covers
from app.services.invoices import get_invoice, refresh_payment_status
from app.services.ledger import EntryDraft

S = ClaimStatus
ZERO = Decimal("0.00")
MAX_APPEALS = 2

# The claim state machine (also drawn in docs/ARCHITECTURE.md section 5).
TRANSITIONS: dict[str, frozenset[str]] = {
    S.DRAFT: frozenset({S.SUBMITTED, S.CANCELLED}),
    S.SUBMITTED: frozenset({S.UNDER_REVIEW}),
    S.UNDER_REVIEW: frozenset({S.APPROVED, S.PARTIALLY_APPROVED, S.DENIED}),
    S.APPROVED: frozenset({S.PAID}),
    S.PARTIALLY_APPROVED: frozenset({S.PAID}),
    S.DENIED: frozenset({S.APPEALED, S.CLOSED}),
    S.APPEALED: frozenset({S.UNDER_REVIEW}),
    S.PAID: frozenset(),
    S.CLOSED: frozenset(),
    S.CANCELLED: frozenset(),
}


def can_transition(current: str, target: str) -> bool:
    return target in TRANSITIONS.get(current, frozenset())


def today() -> date:
    return datetime.now(UTC).date()


def get_claim(session: Session, claim_id: int, *, lock: bool = False) -> Claim:
    claim = repo.get_claim(session, claim_id, lock=lock)
    if claim is None:
        raise NotFound("Claim not found")
    return claim


def _event(
    session: Session,
    actor: Actor,
    claim: Claim,
    event_type: str,
    *,
    from_status: str | None = None,
    to_status: str | None = None,
    amount: Decimal | None = None,
    denial_code: str | None = None,
    note: str = "",
) -> None:
    # Append through the relationship so the in-memory timeline stays current.
    claim.events.append(
        ClaimEvent(
            claim_id=claim.id,
            event_type=event_type,
            from_status=from_status,
            to_status=to_status,
            amount=amount,
            denial_code=denial_code,
            note=note,
            actor_id=actor.id,
            actor_label=actor.label,
        )
    )
    session.flush()


def _transition(
    session: Session,
    actor: Actor,
    claim: Claim,
    target: str,
    *,
    note: str = "",
    amount: Decimal | None = None,
    denial_code: str | None = None,
) -> None:
    if not can_transition(claim.status, target):
        raise Conflict(
            f"Cannot move a claim from {claim.status} to {target}",
            code="invalid_transition",
            details={
                "from": claim.status,
                "to": target,
                "allowed": sorted(TRANSITIONS.get(claim.status, frozenset())),
            },
        )
    before = audit.snapshot(claim)
    previous = claim.status
    claim.status = target
    session.flush()
    _event(
        session,
        actor,
        claim,
        target,
        from_status=previous,
        to_status=target,
        amount=amount,
        denial_code=denial_code,
        note=note,
    )
    audit.record(
        session,
        actor,
        entity_type="claim",
        entity_id=claim.id,
        action="status_change",
        before=before,
        after=audit.snapshot(claim),
    )


def _post(
    session: Session,
    actor: Actor,
    claim: Claim,
    *,
    debit: str,
    credit: str,
    amount: Decimal,
    on: date,
    what: str,
) -> int:
    memo = f"Claim {claim.claim_number}: {what}"
    entry = ledger.post_entry(
        session,
        actor,
        EntryDraft(
            entry_date=on,
            memo=memo,
            source_type="claim",
            source_id=str(claim.id),
            lines=posting.simple_transfer(
                session, debit_code=debit, credit_code=credit, amount=amount, description=memo
            ),
        ),
    )
    return entry.id


# ------------------------------------------------------------------ creation


@dataclass(frozen=True)
class ClaimPreview:
    policy_id: int
    invoice_id: int
    collectible: Decimal
    deductible_met: Decimal
    insurer_used: Decimal
    result: CoverageResult


def preview(
    session: Session, *, invoice_id: int, policy_id: int, exclude_claim_id: int | None = None
) -> ClaimPreview:
    invoice = get_invoice(session, invoice_id)
    policy = get_policy(session, policy_id)
    if policy.patient_id != invoice.patient_id:
        raise ValidationFailed("Policy belongs to another patient", code="policy_mismatch")
    if invoice.status not in (InvoiceStatus.ISSUED, InvoiceStatus.PARTIALLY_PAID):
        raise Conflict(f"Cannot claim a {invoice.status} invoice", code="invoice_not_claimable")
    service_date = invoice.invoice_date or today()
    if not policy_covers(policy, service_date):
        raise BusinessRuleViolation(
            f"Policy is not active on {service_date}", code="policy_not_active"
        )
    deductible_met, insurer_used = repo.benefit_usage(
        session, policy.id, service_date.year, exclude_claim_id=exclude_claim_id
    )
    terms = CoverageTerms(
        policy.coverage_percent, policy.copay, policy.deductible, policy.annual_limit
    )
    result = compute_coverage(
        invoice.total, terms, deductible_met=deductible_met, insurer_used=insurer_used
    )
    collectible = invoice.patient_due
    return ClaimPreview(
        policy.id,
        invoice.id,
        collectible,
        deductible_met,
        insurer_used,
        cap_insurer(result, collectible),
    )


def create_claim(session: Session, actor: Actor, *, invoice_id: int, policy_id: int) -> Claim:
    """Draft a claim that splits the invoice into insurer and patient responsibility."""
    get_invoice(session, invoice_id, lock=True)
    if billing_repo.has_active_claim(session, invoice_id):
        raise Conflict("This invoice already has an open claim", code="claim_exists")
    pv = preview(session, invoice_id=invoice_id, policy_id=policy_id)
    if pv.result.insurer <= 0:
        raise BusinessRuleViolation(
            "Nothing to claim: the insurer share is zero",
            code="nothing_to_claim",
            details={"patient_amount": f"{pv.result.patient:.2f}"},
        )
    invoice = get_invoice(session, invoice_id)
    policy = get_policy(session, policy_id)
    r = pv.result
    claim = Claim(
        claim_number=billing_repo.next_number(session, "claim_number_seq", "CLM"),
        invoice_id=invoice.id,
        policy_id=policy.id,
        patient_id=invoice.patient_id,
        insurer_id=policy.insurer_id,
        status=S.DRAFT,
        service_date=invoice.invoice_date or today(),
        billed_amount=r.billed,
        copay_amount=r.copay,
        deductible_amount=r.deductible,
        coinsurance_amount=r.coinsurance,
        over_limit_amount=r.over_limit,
        insurer_amount=r.insurer,
        patient_amount=r.patient,
        approved_amount=ZERO,
        paid_amount=ZERO,
        adjustment_amount=ZERO,
        created_by_id=actor.id,
    )
    session.add(claim)
    session.flush()
    shares = allocate(r.insurer, [ln.line_total for ln in invoice.lines])
    for ln, share in zip(invoice.lines, shares, strict=True):
        code = ""
        if ln.service_id is not None:
            service = billing_repo.get_service(session, ln.service_id)
            code = service.code if service else ""
        session.add(
            ClaimLine(
                claim_id=claim.id,
                line_no=ln.line_no,
                invoice_line_id=ln.id,
                service_code=code,
                description=ln.description,
                service_date=ln.service_date,
                billed_amount=ln.line_total,
                insurer_amount=share,
            )
        )
    session.flush()
    session.refresh(claim)
    _event(
        session,
        actor,
        claim,
        "created",
        to_status=S.DRAFT,
        amount=r.insurer,
        note=f"Insurer {r.insurer:.2f} / patient {r.patient:.2f}",
    )
    audit.record(
        session,
        actor,
        entity_type="claim",
        entity_id=claim.id,
        action="create",
        after=audit.snapshot(claim),
    )
    return claim


# ------------------------------------------------------------------ lifecycle


def submit_claim(session: Session, actor: Actor, claim_id: int, *, on: date | None = None) -> Claim:
    """Send to the insurer; the insurer share moves from AR-Patients to AR-Insurers."""
    claim = get_claim(session, claim_id, lock=True)
    if claim.status != S.DRAFT:
        _transition(session, actor, claim, S.SUBMITTED)  # raises invalid_transition
    invoice = get_invoice(session, claim.invoice_id, lock=True)
    if invoice.status not in (InvoiceStatus.ISSUED, InvoiceStatus.PARTIALLY_PAID):
        raise Conflict(
            f"Invoice is {invoice.status}; cancel this claim", code="invoice_not_claimable"
        )
    if claim.insurer_amount > invoice.patient_due:
        raise BusinessRuleViolation(
            "The patient has paid since this claim was drafted; cancel and recreate it",
            code="claim_stale",
        )
    when = on or today()
    claim.transfer_entry_id = _post(
        session,
        actor,
        claim,
        debit=posting.AR_INSURERS,
        credit=posting.AR_PATIENTS,
        amount=claim.insurer_amount,
        on=when,
        what="insurer share billed",
    )
    invoice.insurance_pending += claim.insurer_amount
    claim.submitted_at = datetime.now(UTC)
    _transition(session, actor, claim, S.SUBMITTED, amount=claim.insurer_amount)
    return claim


def cancel_claim(session: Session, actor: Actor, claim_id: int, note: str) -> Claim:
    claim = get_claim(session, claim_id, lock=True)
    _transition(session, actor, claim, S.CANCELLED, note=note)
    return claim


def start_review(session: Session, actor: Actor, claim: Claim) -> None:
    _transition(session, actor, claim, S.UNDER_REVIEW)


def record_decision(
    session: Session,
    actor: Actor,
    claim_id: int,
    *,
    outcome: str,
    approved_amount: Decimal | None = None,
    denial_code: str | None = None,
    note: str = "",
    on: date | None = None,
) -> Claim:
    """Apply the insurer's decision to a claim under review."""
    claim = get_claim(session, claim_id, lock=True)
    when = on or today()
    if outcome == "approve":
        claim.approved_amount = claim.insurer_amount
        claim.adjudicated_at = datetime.now(UTC)
        _transition(session, actor, claim, S.APPROVED, amount=claim.approved_amount, note=note)
    elif outcome == "partial":
        if approved_amount is None or not (ZERO < approved_amount < claim.insurer_amount):
            raise ValidationFailed(
                "Partial approval must be between 0 and the claimed amount",
                code="invalid_approved_amount",
            )
        shortfall = claim.insurer_amount - approved_amount
        claim.approved_amount = approved_amount
        claim.adjudicated_at = datetime.now(UTC)
        _transition(session, actor, claim, S.PARTIALLY_APPROVED, amount=approved_amount, note=note)
        _adjust(session, actor, claim, shortfall, when, "contractual adjustment (partial approval)")
    elif outcome == "deny":
        if not denial_code or repo.get_denial_code(session, denial_code) is None:
            raise ValidationFailed("A valid denial code is required", code="invalid_denial_code")
        claim.denial_code = denial_code
        claim.denial_note = note
        claim.adjudicated_at = datetime.now(UTC)
        _transition(session, actor, claim, S.DENIED, denial_code=denial_code, note=note)
    else:
        raise ValidationFailed("Outcome must be approve, partial or deny", code="invalid_outcome")
    return claim


def _adjust(
    session: Session, actor: Actor, claim: Claim, amount: Decimal, on: date, what: str
) -> None:
    """Contractual adjustment: the hospital accepts less from the insurer."""
    if amount <= 0:
        return
    _post(
        session,
        actor,
        claim,
        debit=posting.CONTRACTUAL_ADJ,
        credit=posting.AR_INSURERS,
        amount=amount,
        on=on,
        what=what,
    )
    claim.adjustment_amount += amount
    invoice = get_invoice(session, claim.invoice_id, lock=True)
    invoice.insurance_pending -= amount
    invoice.adjusted_amount += amount
    refresh_payment_status(invoice)
    session.flush()
    _event(session, actor, claim, "adjustment", amount=amount, note=what)


def appeal_claim(session: Session, actor: Actor, claim_id: int, note: str) -> Claim:
    claim = get_claim(session, claim_id, lock=True)
    if not note.strip():
        raise ValidationFailed(
            "An appeal needs a note explaining the grounds", code="note_required"
        )
    if claim.status == S.DENIED and claim.appeal_count >= MAX_APPEALS:
        raise BusinessRuleViolation(
            f"A claim can be appealed at most {MAX_APPEALS} times", code="appeal_limit"
        )
    _transition(session, actor, claim, S.APPEALED, note=note)
    claim.appeal_count += 1
    session.flush()
    return claim


def close_claim(
    session: Session, actor: Actor, claim_id: int, note: str, on: date | None = None
) -> Claim:
    """Give up on a denied claim: the insurer share becomes patient responsibility again."""
    claim = get_claim(session, claim_id, lock=True)
    if not can_transition(claim.status, S.CLOSED):
        _transition(session, actor, claim, S.CLOSED)  # raises invalid_transition
    remaining = claim.insurer_amount - claim.paid_amount - claim.adjustment_amount
    if remaining > 0:
        _post(
            session,
            actor,
            claim,
            debit=posting.AR_PATIENTS,
            credit=posting.AR_INSURERS,
            amount=remaining,
            on=on or today(),
            what="denied; balance back to patient",
        )
        invoice = get_invoice(session, claim.invoice_id, lock=True)
        invoice.insurance_pending -= remaining
        refresh_payment_status(invoice)
    _transition(session, actor, claim, S.CLOSED, amount=remaining, note=note)
    return claim


def accept_short_pay(
    session: Session, actor: Actor, claim_id: int, note: str, on: date | None = None
) -> Claim:
    """Write off the unpaid remainder of an approved claim as a contractual adjustment."""
    claim = get_claim(session, claim_id, lock=True)
    if claim.status not in (S.APPROVED, S.PARTIALLY_APPROVED):
        raise Conflict("Only approved claims can be settled", code="invalid_transition")
    if claim.paid_amount <= 0:
        raise BusinessRuleViolation(
            "Nothing has been paid yet; wait for the remittance", code="no_payment_yet"
        )
    _adjust(
        session,
        actor,
        claim,
        claim.outstanding,
        on or today(),
        f"short pay accepted{': ' + note if note else ''}",
    )
    _transition(session, actor, claim, S.PAID, amount=claim.paid_amount, note=note)
    return claim


def record_insurer_payment(
    session: Session,
    actor: Actor,
    claim: Claim,
    amount: Decimal,
    *,
    on: date,
    reference: str,
) -> Payment:
    """Insurer money for a claim: Dr Bank / Cr AR-Insurers; marks the claim paid when settled."""
    if claim.status not in (S.APPROVED, S.PARTIALLY_APPROVED):
        raise Conflict(
            f"Claim {claim.claim_number} is {claim.status}, not payable", code="claim_not_payable"
        )
    if amount <= 0 or amount > claim.outstanding:
        raise BusinessRuleViolation(
            "Insurer payment exceeds the approved outstanding amount", code="over_payment"
        )
    invoice = get_invoice(session, claim.invoice_id, lock=True)
    payment = Payment(
        payment_number=billing_repo.next_number(session, "payment_number_seq", "PAY"),
        kind=PaymentKind.INVOICE,
        patient_id=claim.patient_id,
        invoice_id=invoice.id,
        method=PaymentMethod.INSURANCE,
        amount=amount,
        refunded_amount=ZERO,
        received_on=on,
        reference=reference,
        notes=f"{claim.insurer.name} for {claim.claim_number}",
        created_by_id=actor.id,
    )
    session.add(payment)
    session.flush()
    payment.journal_entry_id = _post(
        session,
        actor,
        claim,
        debit=posting.BANK,
        credit=posting.AR_INSURERS,
        amount=amount,
        on=on,
        what=f"insurer payment {payment.payment_number}",
    )
    invoice.amount_paid += amount
    invoice.insurance_pending -= amount
    refresh_payment_status(invoice)
    claim.paid_amount += amount
    session.flush()
    _event(session, actor, claim, "payment", amount=amount, note=f"Remittance {reference}")
    audit.record(
        session,
        actor,
        entity_type="payment",
        entity_id=payment.id,
        action="create",
        after=audit.snapshot(payment),
    )
    if claim.outstanding == 0:
        _transition(session, actor, claim, S.PAID, amount=claim.paid_amount)
    return payment


def add_note(session: Session, actor: Actor, claim_id: int, note: str) -> Claim:
    claim = get_claim(session, claim_id)
    if not note.strip():
        raise ValidationFailed("Note is empty", code="note_required")
    _event(session, actor, claim, "note", note=note)
    return claim
