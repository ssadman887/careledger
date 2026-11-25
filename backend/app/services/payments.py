"""Payments, patient deposits and refunds. Every money movement posts to the ledger in the same
transaction (account mapping: services/posting.py, docs/ARCHITECTURE.md section 4)."""

import re
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
from app.models.billing import (
    InvoiceStatus,
    Payment,
    PaymentKind,
    PaymentMethod,
    Refund,
    RefundStatus,
)
from app.repositories import billing as repo
from app.services import audit, ledger, posting
from app.services.audit import Actor
from app.services.invoices import get_invoice, refresh_payment_status
from app.services.ledger import EntryDraft
from app.services.patients import get_patient

ZERO = Decimal("0.00")
RECEIPT_METHODS = {PaymentMethod.CASH, PaymentMethod.CARD, PaymentMethod.BANK_TRANSFER}


def today() -> date:
    return datetime.now(UTC).date()


def _check_amount(amount: Decimal) -> None:
    if amount <= 0 or quantize(amount) != amount:
        raise ValidationFailed(
            "Amount must be positive with at most 2 decimals", code="invalid_amount"
        )


def _normalise_reference(method: str, reference: str) -> str:
    reference = reference.strip()
    # Mock card payments: we only ever accept/store the last 4 digits, never a PAN.
    if method == PaymentMethod.CARD and not re.fullmatch(r"\d{4}", reference):
        raise ValidationFailed(
            "Card payments need the card's last 4 digits only", code="invalid_card_reference"
        )
    return reference


def _post(
    session: Session, actor: Actor, payment: Payment, debit: str, credit: str, memo: str
) -> None:
    entry = ledger.post_entry(
        session,
        actor,
        EntryDraft(
            entry_date=payment.received_on,
            memo=memo,
            source_type="payment",
            source_id=str(payment.id),
            lines=posting.simple_transfer(
                session,
                debit_code=debit,
                credit_code=credit,
                amount=payment.amount,
                description=memo,
            ),
        ),
    )
    payment.journal_entry_id = entry.id


def get_payment(session: Session, payment_id: int, *, lock: bool = False) -> Payment:
    payment = repo.get_payment(session, payment_id, lock=lock)
    if payment is None:
        raise NotFound("Payment not found")
    return payment


def record_payment(
    session: Session,
    actor: Actor,
    *,
    invoice_id: int,
    method: str,
    amount: Decimal,
    received_on: date | None,
    reference: str,
    notes: str,
) -> Payment:
    """Patient payment against an issued invoice: Dr Cash/Bank, Cr AR-Patients."""
    _check_amount(amount)
    if method == PaymentMethod.DEPOSIT:
        raise ValidationFailed(
            "Use apply-deposit to settle an invoice from a deposit", code="use_apply_deposit"
        )
    if method not in RECEIPT_METHODS:
        raise ValidationFailed(
            "Insurer payments arrive via remittances (Phase 3)", code="invalid_method"
        )
    invoice = get_invoice(session, invoice_id, lock=True)
    if invoice.status not in (InvoiceStatus.ISSUED, InvoiceStatus.PARTIALLY_PAID):
        raise Conflict(
            f"Cannot take payment on a {invoice.status} invoice", code="invoice_not_payable"
        )
    if amount > invoice.balance_due:
        raise BusinessRuleViolation(
            f"Payment exceeds the balance due ({invoice.balance_due:.2f})",
            code="overpayment",
            details={"balance_due": f"{invoice.balance_due:.2f}"},
        )
    before = audit.snapshot(invoice)
    payment = Payment(
        payment_number=repo.next_number(session, "payment_number_seq", "PAY"),
        kind=PaymentKind.INVOICE,
        patient_id=invoice.patient_id,
        invoice_id=invoice.id,
        method=method,
        amount=amount,
        refunded_amount=ZERO,
        received_on=received_on or today(),
        reference=_normalise_reference(method, reference),
        notes=notes,
        created_by_id=actor.id,
    )
    session.add(payment)
    session.flush()
    _post(
        session,
        actor,
        payment,
        posting.money_account_code(method),
        posting.AR_PATIENTS,
        f"Payment {payment.payment_number} for {invoice.invoice_number}",
    )
    invoice.amount_paid += amount
    refresh_payment_status(invoice)
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="payment",
        entity_id=payment.id,
        action="create",
        after=audit.snapshot(payment),
    )
    audit.record(
        session,
        actor,
        entity_type="invoice",
        entity_id=invoice.id,
        action="status_change",
        before=before,
        after=audit.snapshot(invoice),
    )
    return payment


def record_deposit(
    session: Session,
    actor: Actor,
    *,
    patient_id: int,
    method: str,
    amount: Decimal,
    received_on: date | None,
    reference: str,
    notes: str,
) -> Payment:
    """Money received in advance: Dr Cash/Bank, Cr Patient Deposits (a liability)."""
    _check_amount(amount)
    if method not in RECEIPT_METHODS:
        raise ValidationFailed(
            "Deposits are taken in cash, card or bank transfer", code="invalid_method"
        )
    get_patient(session, patient_id)
    payment = Payment(
        payment_number=repo.next_number(session, "payment_number_seq", "PAY"),
        kind=PaymentKind.DEPOSIT,
        patient_id=patient_id,
        invoice_id=None,
        method=method,
        amount=amount,
        refunded_amount=ZERO,
        received_on=received_on or today(),
        reference=_normalise_reference(method, reference),
        notes=notes,
        created_by_id=actor.id,
    )
    session.add(payment)
    session.flush()
    _post(
        session,
        actor,
        payment,
        posting.money_account_code(method),
        posting.PATIENT_DEPOSITS,
        f"Deposit {payment.payment_number}",
    )
    audit.record(
        session,
        actor,
        entity_type="payment",
        entity_id=payment.id,
        action="create",
        after=audit.snapshot(payment),
    )
    return payment


def apply_deposit(
    session: Session,
    actor: Actor,
    *,
    invoice_id: int,
    amount: Decimal,
    applied_on: date | None,
) -> Payment:
    """Settle (part of) an invoice from the patient's deposit: Dr Deposits, Cr AR-Patients."""
    _check_amount(amount)
    invoice = get_invoice(session, invoice_id, lock=True)
    repo.get_patient(session, invoice.patient_id, lock=True)  # serialise deposit usage
    if invoice.status not in (InvoiceStatus.ISSUED, InvoiceStatus.PARTIALLY_PAID):
        raise Conflict(
            f"Cannot apply a deposit to a {invoice.status} invoice", code="invoice_not_payable"
        )
    available = repo.deposit_balance(session, invoice.patient_id)
    if amount > available:
        raise BusinessRuleViolation(
            f"Deposit balance is only {available:.2f}",
            code="insufficient_deposit",
            details={"deposit_balance": f"{available:.2f}"},
        )
    if amount > invoice.balance_due:
        raise BusinessRuleViolation(
            f"Amount exceeds the balance due ({invoice.balance_due:.2f})", code="overpayment"
        )
    before = audit.snapshot(invoice)
    payment = Payment(
        payment_number=repo.next_number(session, "payment_number_seq", "PAY"),
        kind=PaymentKind.INVOICE,
        patient_id=invoice.patient_id,
        invoice_id=invoice.id,
        method=PaymentMethod.DEPOSIT,
        amount=amount,
        refunded_amount=ZERO,
        received_on=applied_on or today(),
        reference="",
        notes="Applied from deposit",
        created_by_id=actor.id,
    )
    session.add(payment)
    session.flush()
    _post(
        session,
        actor,
        payment,
        posting.PATIENT_DEPOSITS,
        posting.AR_PATIENTS,
        f"Deposit applied {payment.payment_number} to {invoice.invoice_number}",
    )
    invoice.amount_paid += amount
    refresh_payment_status(invoice)
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="payment",
        entity_id=payment.id,
        action="create",
        after=audit.snapshot(payment),
    )
    audit.record(
        session,
        actor,
        entity_type="invoice",
        entity_id=invoice.id,
        action="status_change",
        before=before,
        after=audit.snapshot(invoice),
    )
    return payment


# ------------------------------------------------------------------ refunds


def _refundable(session: Session, payment: Payment) -> Decimal:
    available = (
        payment.amount - payment.refunded_amount - repo.pending_refund_total(session, payment.id)
    )
    if payment.kind == PaymentKind.DEPOSIT:
        # Money already applied to invoices cannot be refunded from the deposit.
        available = min(available, repo.deposit_balance(session, payment.patient_id))
    return available


def _complete(session: Session, actor: Actor, refund: Refund, payment: Payment, on: date) -> None:
    if refund.amount > payment.amount - payment.refunded_amount:
        raise BusinessRuleViolation("Refund exceeds the refundable amount", code="over_refund")
    if payment.kind == PaymentKind.DEPOSIT:
        if refund.amount > repo.deposit_balance(session, payment.patient_id):
            raise BusinessRuleViolation(
                "Deposit balance is insufficient for this refund", code="insufficient_deposit"
            )
        debit, credit = posting.PATIENT_DEPOSITS, posting.money_account_code(payment.method)
    else:
        # Re-open the receivable; money goes back the way it came (deposit -> back to deposit).
        debit, credit = posting.AR_PATIENTS, posting.money_account_code(payment.method)
    memo = f"Refund {refund.refund_number} of {payment.payment_number}"
    entry = ledger.post_entry(
        session,
        actor,
        EntryDraft(
            entry_date=on,
            memo=memo,
            source_type="refund",
            source_id=str(refund.id),
            lines=posting.simple_transfer(
                session,
                debit_code=debit,
                credit_code=credit,
                amount=refund.amount,
                description=memo,
            ),
        ),
    )
    refund.journal_entry_id = entry.id
    refund.status = RefundStatus.COMPLETED
    refund.refunded_on = on
    payment.refunded_amount += refund.amount
    if payment.invoice_id is not None:
        invoice = get_invoice(session, payment.invoice_id, lock=True)
        before = audit.snapshot(invoice)
        invoice.amount_paid -= refund.amount
        refresh_payment_status(invoice)
        session.flush()
        audit.record(
            session,
            actor,
            entity_type="invoice",
            entity_id=invoice.id,
            action="status_change",
            before=before,
            after=audit.snapshot(invoice),
        )
    session.flush()


def request_refund(
    session: Session,
    actor: Actor,
    *,
    payment_id: int,
    amount: Decimal,
    reason: str,
    approval_threshold: Decimal,
    refunded_on: date | None = None,
) -> Refund:
    """Refunds above the threshold wait for a finance manager; smaller ones complete now."""
    _check_amount(amount)
    if not reason.strip():
        raise ValidationFailed("A refund reason is required", code="reason_required")
    payment = get_payment(session, payment_id, lock=True)
    if payment.method == PaymentMethod.INSURANCE:
        raise BusinessRuleViolation(
            "Insurer payments are adjusted via remittances", code="invalid_method"
        )
    available = _refundable(session, payment)
    if amount > available:
        raise BusinessRuleViolation(
            f"Only {max(available, ZERO):.2f} can be refunded",
            code="over_refund",
            details={"refundable": f"{max(available, ZERO):.2f}"},
        )
    refund = Refund(
        refund_number=repo.next_number(session, "refund_number_seq", "RFD"),
        payment_id=payment.id,
        amount=amount,
        reason=reason,
        status=RefundStatus.PENDING_APPROVAL,
        requested_by_id=actor.id,
    )
    session.add(refund)
    session.flush()
    if amount <= approval_threshold:
        _complete(session, actor, refund, payment, refunded_on or today())
        refund.decided_by_id = actor.id
        refund.decision_note = "Below approval threshold"
        session.flush()
    audit.record(
        session,
        actor,
        entity_type="refund",
        entity_id=refund.id,
        action="create",
        after=audit.snapshot(refund),
    )
    return refund


def _pending_refund(session: Session, actor: Actor, refund_id: int) -> Refund:
    refund = repo.get_refund(session, refund_id, lock=True)
    if refund is None:
        raise NotFound("Refund not found")
    if refund.status != RefundStatus.PENDING_APPROVAL:
        raise Conflict("Refund is not awaiting approval", code="not_pending")
    if refund.requested_by_id is not None and refund.requested_by_id == actor.id:
        raise PermissionDenied("You cannot approve your own refund", code="self_approval")
    return refund


def approve_refund(
    session: Session, actor: Actor, refund_id: int, note: str, refunded_on: date | None = None
) -> Refund:
    refund = _pending_refund(session, actor, refund_id)
    before = audit.snapshot(refund)
    payment = get_payment(session, refund.payment_id, lock=True)
    _complete(session, actor, refund, payment, refunded_on or today())
    refund.decided_by_id = actor.id
    refund.decision_note = note
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="refund",
        entity_id=refund.id,
        action="status_change",
        before=before,
        after=audit.snapshot(refund),
    )
    return refund


def reject_refund(session: Session, actor: Actor, refund_id: int, note: str) -> Refund:
    refund = _pending_refund(session, actor, refund_id)
    if not note.strip():
        raise ValidationFailed("A rejection note is required", code="reason_required")
    before = audit.snapshot(refund)
    refund.status = RefundStatus.REJECTED
    refund.decided_by_id = actor.id
    refund.decision_note = note
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="refund",
        entity_id=refund.id,
        action="status_change",
        before=before,
        after=audit.snapshot(refund),
    )
    return refund
