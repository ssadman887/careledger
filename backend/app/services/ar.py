"""Accounts receivable: aging, dunning reminders, bad-debt write-offs.

Aging age = days since the invoice date (patient balances) or since claim submission (insurer
balances), bucketed 0-30 / 31-60 / 61-90 / 90+ (inclusive bounds). Balances are current
outstanding amounts for documents dated on or before `as_of`.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.errors import (
    BusinessRuleViolation,
    Conflict,
    NotFound,
    PermissionDenied,
    ValidationFailed,
)
from app.core.money import quantize
from app.models.ar import DunningNotice, WriteOff, WriteOffStatus
from app.models.billing import InvoiceStatus
from app.repositories import ar as repo
from app.repositories import billing as billing_repo
from app.services import approvals, audit, ledger, posting
from app.services.audit import Actor
from app.services.invoices import get_invoice, refresh_payment_status
from app.services.ledger import EntryDraft

ZERO = Decimal("0.00")
BUCKET_LABELS = tuple(label for label, _, _ in repo.BUCKETS)


def bucket_for(days: int) -> str:
    """Aging bucket for an age in days (negative ages count as current, 0-30)."""
    for label, low, high in repo.BUCKETS:
        if (high is None and days >= low) or (high is not None and days <= high):
            return label
    return BUCKET_LABELS[-1]


def dunning_level(days_overdue: int) -> int:
    if days_overdue <= 0:
        return 0
    if days_overdue <= 30:
        return 1
    if days_overdue <= 60:
        return 2
    return 3


@dataclass(frozen=True)
class AgingRow:
    party_id: int
    name: str
    code: str
    buckets: dict[str, Decimal]
    total: Decimal


@dataclass(frozen=True)
class AgingReport:
    as_of: date
    by: str
    rows: list[AgingRow]
    totals: dict[str, Decimal]
    total: Decimal


def _report(as_of: date, by: str, raw: list[tuple[int, str, str, list[Decimal]]]) -> AgingReport:
    rows = [
        AgingRow(pid, name, code, dict(zip(BUCKET_LABELS, values, strict=True)), sum(values, ZERO))
        for pid, name, code, values in raw
    ]
    totals = {label: sum((r.buckets[label] for r in rows), ZERO) for label in BUCKET_LABELS}
    return AgingReport(as_of, by, rows, totals, sum(totals.values(), ZERO))


def aging(session: Session, *, by: str, as_of: date) -> AgingReport:
    if by == "patient":
        return _report(as_of, by, repo.aging_by_patient(session, as_of))
    if by == "insurer":
        return _report(as_of, by, repo.aging_by_insurer(session, as_of))
    raise ValidationFailed("Group by 'patient' or 'insurer'", code="invalid_grouping")


# ------------------------------------------------------------------ dunning

MESSAGES = {
    1: "Friendly reminder: invoice {inv} has {amt} outstanding, {days} days past due.",
    2: "Second notice: invoice {inv} is {days} days overdue with {amt} outstanding. Please pay "
    "or contact billing to arrange a plan.",
    3: "Final notice: invoice {inv} is {days} days overdue ({amt}). The account may be referred "
    "for collection or written off.",
}


def run_dunning(session: Session, actor: Actor, *, as_of: date) -> list[DunningNotice]:
    """Create (simulated) reminders for overdue patient balances: one per invoice per level."""
    created: list[DunningNotice] = []
    for invoice in repo.dunning_candidates(session, as_of):
        assert invoice.due_date is not None
        days = (as_of - invoice.due_date).days
        level = dunning_level(days)
        if level == 0 or level in repo.notice_levels(session, invoice.id):
            continue
        notice = DunningNotice(
            invoice_id=invoice.id,
            patient_id=invoice.patient_id,
            level=level,
            days_overdue=days,
            amount_due=invoice.patient_due,
            channel="email",
            message=MESSAGES[level].format(
                inv=invoice.invoice_number, amt=f"{invoice.patient_due:.2f}", days=days
            ),
            sent_at=datetime.now(UTC),
        )
        session.add(notice)
        session.flush()
        audit.record(
            session,
            actor,
            entity_type="dunning_notice",
            entity_id=notice.id,
            action="create",
            after=audit.snapshot(notice),
        )
        created.append(notice)
    return created


# ------------------------------------------------------------------ write-offs


def get_write_off(session: Session, write_off_id: int, *, lock: bool = False) -> WriteOff:
    write_off = repo.get_write_off(session, write_off_id, lock=lock)
    if write_off is None:
        raise NotFound("Write-off not found")
    return write_off


def _post(session: Session, actor: Actor, write_off: WriteOff, on: date) -> None:
    invoice = get_invoice(session, write_off.invoice_id, lock=True)
    if invoice.status not in (InvoiceStatus.ISSUED, InvoiceStatus.PARTIALLY_PAID):
        raise Conflict(f"Invoice is {invoice.status}", code="invoice_not_open")
    if write_off.amount > invoice.patient_due:
        raise BusinessRuleViolation(
            f"Write-off exceeds the patient balance ({invoice.patient_due:.2f})",
            code="exceeds_balance",
        )
    memo = f"Write-off {write_off.write_off_number}: {invoice.invoice_number} ({write_off.reason})"
    entry = ledger.post_entry(
        session,
        actor,
        EntryDraft(
            entry_date=on,
            memo=memo[:500],
            source_type="write_off",
            source_id=str(write_off.id),
            lines=posting.simple_transfer(
                session,
                debit_code=posting.BAD_DEBT,
                credit_code=posting.AR_PATIENTS,
                amount=write_off.amount,
                description=memo[:200],
            ),
        ),
    )
    write_off.journal_entry_id = entry.id
    write_off.status = WriteOffStatus.POSTED
    write_off.posted_on = on
    invoice.adjusted_amount += write_off.amount
    refresh_payment_status(invoice)
    session.flush()


def request_write_off(
    session: Session,
    actor: Actor,
    *,
    invoice_id: int,
    amount: Decimal,
    reason: str,
    on: date | None = None,
) -> WriteOff:
    if amount <= 0 or quantize(amount) != amount:
        raise ValidationFailed(
            "Amount must be positive with at most 2 decimals", code="invalid_amount"
        )
    if not reason.strip():
        raise ValidationFailed("A write-off needs a reason", code="reason_required")
    invoice = get_invoice(session, invoice_id, lock=True)
    if invoice.status not in (InvoiceStatus.ISSUED, InvoiceStatus.PARTIALLY_PAID):
        raise Conflict(f"Cannot write off a {invoice.status} invoice", code="invoice_not_open")
    available = invoice.patient_due - repo.pending_write_off_total(session, invoice.id)
    if amount > available:
        raise BusinessRuleViolation(
            f"Only {max(available, ZERO):.2f} of the patient balance can be written off",
            code="exceeds_balance",
        )
    write_off = WriteOff(
        write_off_number=billing_repo.next_number(session, "write_off_number_seq", "WO"),
        invoice_id=invoice.id,
        amount=amount,
        reason=reason,
        status=WriteOffStatus.PENDING_APPROVAL,
        requested_by_id=actor.id,
    )
    session.add(write_off)
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="write_off",
        entity_id=write_off.id,
        action="create",
        after=audit.snapshot(write_off),
    )
    if approvals.needs_approval(session, "write_off", amount):
        approvals.request(
            session,
            actor,
            kind="write_off",
            entity_type="write_off",
            entity_id=write_off.id,
            reference=write_off.write_off_number,
            summary=f"Write off {amount:.2f} on {invoice.invoice_number} "
            f"({invoice.patient.full_name}): {reason}",
            amount=amount,
        )
    else:
        _post(session, actor, write_off, on or datetime.now(UTC).date())
        write_off.decided_by_id = actor.id
    return write_off


def _pending(session: Session, actor: Actor, write_off_id: int) -> WriteOff:
    write_off = get_write_off(session, write_off_id, lock=True)
    if write_off.status != WriteOffStatus.PENDING_APPROVAL:
        raise Conflict("Write-off is not awaiting approval", code="not_pending")
    if write_off.requested_by_id is not None and write_off.requested_by_id == actor.id:
        raise PermissionDenied("You cannot approve your own write-off", code="self_approval")
    return write_off


def approve_write_off(
    session: Session, actor: Actor, write_off_id: int, note: str, on: date | None = None
) -> WriteOff:
    write_off = _pending(session, actor, write_off_id)
    before = audit.snapshot(write_off)
    _post(session, actor, write_off, on or datetime.now(UTC).date())
    write_off.decided_by_id = actor.id
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="write_off",
        entity_id=write_off.id,
        action="status_change",
        before=before,
        after=audit.snapshot(write_off),
    )
    approvals.record_decision(
        session, actor, kind="write_off", entity_id=write_off.id, approved=True, note=note
    )
    return write_off


def reject_write_off(session: Session, actor: Actor, write_off_id: int, note: str) -> WriteOff:
    write_off = _pending(session, actor, write_off_id)
    before = audit.snapshot(write_off)
    write_off.status = WriteOffStatus.REJECTED
    write_off.decided_by_id = actor.id
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="write_off",
        entity_id=write_off.id,
        action="status_change",
        before=before,
        after=audit.snapshot(write_off),
    )
    approvals.record_decision(
        session, actor, kind="write_off", entity_id=write_off.id, approved=False, note=note
    )
    return write_off
