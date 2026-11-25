"""Accounts payable: vendors, purchase orders, vendor bills with three-way match, payments.

Three-way match compares the bill with its purchase order and the goods-received flag:
  no_po         bill without a PO (two-way; allowed)
  not_received  PO not yet received
  variance      bill total plus earlier bills on the PO exceed the PO total
  matched       PO received and bills within the PO amount
Submitting a bill approves it immediately when it is matched/no_po and at or under the
vendor_bill threshold; otherwise it waits for a finance manager. Approval posts
Dr expense lines / Cr 2010 Accounts Payable; payments post Dr 2010 / Cr 1020 Bank.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
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
from app.models.ap import (
    BillStatus,
    MatchResult,
    POStatus,
    PurchaseOrder,
    PurchaseOrderLine,
    Vendor,
    VendorBill,
    VendorBillLine,
    VendorPayment,
)
from app.models.ledger import AccountType
from app.repositories import ap as repo
from app.repositories import billing as billing_repo
from app.repositories import ledger as ledger_repo
from app.services import approvals, audit, ledger, posting
from app.services.audit import Actor
from app.services.ledger import EntryDraft, LineInput

ZERO = Decimal("0.00")
PAY_METHODS = {"bank_transfer", "cheque"}


@dataclass(frozen=True)
class APLine:
    description: str
    account_id: int
    quantity: Decimal
    unit_price: Decimal
    department_id: int | None = None


def today() -> date:
    return datetime.now(UTC).date()


def _check_lines(session: Session, lines: Sequence[APLine]) -> list[tuple[APLine, Decimal]]:
    if not lines:
        raise ValidationFailed("At least one line is required", code="no_lines")
    out = []
    for i, ln in enumerate(lines, start=1):
        account = ledger_repo.get_account(session, ln.account_id)
        if account is None or account.is_header or not account.is_active:
            raise ValidationFailed(
                f"Line {i}: account must be an active postable account", code="invalid_account"
            )
        if account.type not in (AccountType.EXPENSE, AccountType.ASSET):
            raise ValidationFailed(
                f"Line {i}: use an expense or asset account", code="invalid_account"
            )
        if ln.quantity <= 0 or ln.unit_price < 0 or quantize(ln.unit_price) != ln.unit_price:
            raise ValidationFailed(f"Line {i}: invalid quantity or price", code="invalid_line")
        if not ln.description.strip():
            raise ValidationFailed(f"Line {i}: description is required", code="invalid_line")
        out.append((ln, quantize(ln.quantity * ln.unit_price)))
    return out


# ------------------------------------------------------------------ vendors


def get_vendor(session: Session, vendor_id: int) -> Vendor:
    vendor = repo.get_vendor(session, vendor_id)
    if vendor is None:
        raise NotFound("Vendor not found")
    return vendor


def create_vendor(
    session: Session,
    actor: Actor,
    *,
    code: str,
    name: str,
    email: str,
    tax_id: str,
    bank_reference: str,
    payment_terms_days: int,
    default_expense_account_id: int | None,
) -> Vendor:
    if repo.vendor_code_taken(session, code):
        raise Conflict(f"Vendor {code} already exists", code="vendor_exists")
    if not (0 <= payment_terms_days <= 180):
        raise ValidationFailed("Payment terms must be 0-180 days", code="invalid_terms")
    if default_expense_account_id is not None:
        _check_lines(session, [APLine("x", default_expense_account_id, Decimal(1), ZERO)])
    vendor = Vendor(
        code=code,
        name=name,
        email=email,
        tax_id=tax_id,
        bank_reference=bank_reference,
        payment_terms_days=payment_terms_days,
        default_expense_account_id=default_expense_account_id,
    )
    session.add(vendor)
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="vendor",
        entity_id=vendor.id,
        action="create",
        after=audit.snapshot(vendor),
    )
    return vendor


def update_vendor(
    session: Session,
    actor: Actor,
    vendor_id: int,
    *,
    name: str | None,
    email: str | None,
    bank_reference: str | None,
    payment_terms_days: int | None,
    is_active: bool | None,
) -> Vendor:
    vendor = get_vendor(session, vendor_id)
    before = audit.snapshot(vendor)
    if payment_terms_days is not None and not (0 <= payment_terms_days <= 180):
        raise ValidationFailed("Payment terms must be 0-180 days", code="invalid_terms")
    for field, value in (
        ("name", name),
        ("email", email),
        ("bank_reference", bank_reference),
        ("payment_terms_days", payment_terms_days),
        ("is_active", is_active),
    ):
        if value is not None:
            setattr(vendor, field, value)
    session.flush()
    action = "status_change" if before["is_active"] != vendor.is_active else "update"
    audit.record(
        session,
        actor,
        entity_type="vendor",
        entity_id=vendor.id,
        action=action,
        before=before,
        after=audit.snapshot(vendor),
    )
    return vendor


# ------------------------------------------------------------------ purchase orders


def get_po(session: Session, po_id: int, *, lock: bool = False) -> PurchaseOrder:
    po = repo.get_po(session, po_id, lock=lock)
    if po is None:
        raise NotFound("Purchase order not found")
    return po


def create_po(
    session: Session,
    actor: Actor,
    *,
    vendor_id: int,
    order_date: date,
    expected_date: date | None,
    lines: Sequence[APLine],
    notes: str,
) -> PurchaseOrder:
    vendor = get_vendor(session, vendor_id)
    if not vendor.is_active:
        raise BusinessRuleViolation("Vendor is inactive", code="vendor_inactive")
    checked = _check_lines(session, lines)
    po = PurchaseOrder(
        po_number=billing_repo.next_number(session, "po_number_seq", "PO"),
        vendor_id=vendor.id,
        status=POStatus.DRAFT,
        order_date=order_date,
        expected_date=expected_date,
        total=sum((amt for _, amt in checked), ZERO),
        notes=notes,
        created_by_id=actor.id,
        lines=[
            PurchaseOrderLine(
                line_no=i,
                description=ln.description,
                account_id=ln.account_id,
                quantity=ln.quantity,
                unit_price=ln.unit_price,
                amount=amt,
                received_quantity=ZERO,
            )
            for i, (ln, amt) in enumerate(checked, start=1)
        ],
    )
    session.add(po)
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="purchase_order",
        entity_id=po.id,
        action="create",
        after=audit.snapshot(po, extra={"lines": len(po.lines)}),
    )
    return po


def _po_status(
    session: Session, actor: Actor, po: PurchaseOrder, target: str, **changes: object
) -> PurchaseOrder:
    before = audit.snapshot(po)
    po.status = target
    for key, value in changes.items():
        setattr(po, key, value)
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="purchase_order",
        entity_id=po.id,
        action="status_change",
        before=before,
        after=audit.snapshot(po),
    )
    return po


def issue_po(session: Session, actor: Actor, po_id: int) -> PurchaseOrder:
    po = get_po(session, po_id, lock=True)
    if po.status != POStatus.DRAFT:
        raise Conflict("Only draft purchase orders can be issued", code="invalid_transition")
    return _po_status(session, actor, po, POStatus.ISSUED)


def receive_po(
    session: Session, actor: Actor, po_id: int, *, received_on: date | None = None
) -> PurchaseOrder:
    """Goods-received flag (the third leg of the three-way match). Receives all lines in full."""
    po = get_po(session, po_id, lock=True)
    if po.status != POStatus.ISSUED:
        raise Conflict("Only issued purchase orders can be received", code="invalid_transition")
    for line in po.lines:
        line.received_quantity = line.quantity
    return _po_status(session, actor, po, POStatus.RECEIVED, received_on=received_on or today())


def cancel_po(session: Session, actor: Actor, po_id: int) -> PurchaseOrder:
    po = get_po(session, po_id, lock=True)
    if po.status not in (POStatus.DRAFT, POStatus.ISSUED):
        raise Conflict(
            "Only draft or issued purchase orders can be cancelled", code="invalid_transition"
        )
    if repo.billed_total_for_po(session, po.id) > 0:
        raise BusinessRuleViolation("Purchase order already has bills", code="po_has_bills")
    return _po_status(session, actor, po, POStatus.CANCELLED)


# ------------------------------------------------------------------ bills


def get_bill(session: Session, bill_id: int, *, lock: bool = False) -> VendorBill:
    bill = repo.get_bill(session, bill_id, lock=lock)
    if bill is None:
        raise NotFound("Vendor bill not found")
    return bill


def three_way_match(session: Session, bill: VendorBill) -> tuple[str, str]:
    if bill.purchase_order_id is None:
        return MatchResult.NO_PO, "No purchase order (two-way match)"
    po = get_po(session, bill.purchase_order_id)
    if po.status not in (POStatus.RECEIVED, POStatus.CLOSED):
        return MatchResult.NOT_RECEIVED, f"{po.po_number} has not been received"
    billed = repo.billed_total_for_po(session, po.id, exclude_bill_id=bill.id) + bill.total
    if billed > po.total:
        return (
            MatchResult.VARIANCE,
            f"Bills total {billed:.2f} exceeds {po.po_number} ({po.total:.2f})",
        )
    return MatchResult.MATCHED, f"Matches {po.po_number} and its receipt"


def create_bill(
    session: Session,
    actor: Actor,
    *,
    vendor_id: int,
    vendor_invoice_number: str,
    bill_date: date,
    due_date: date | None,
    purchase_order_id: int | None,
    lines: Sequence[APLine] | None,
    notes: str,
) -> VendorBill:
    vendor = get_vendor(session, vendor_id)
    number = vendor_invoice_number.strip()
    if not number:
        raise ValidationFailed(
            "The vendor's invoice number is required", code="invoice_number_required"
        )
    if repo.bill_number_exists(session, vendor.id, number):
        raise Conflict("This vendor invoice was already entered", code="duplicate_bill")
    po = None
    if purchase_order_id is not None:
        po = get_po(session, purchase_order_id)
        if po.vendor_id != vendor.id:
            raise ValidationFailed("Purchase order belongs to another vendor", code="po_mismatch")
        if po.status in (POStatus.DRAFT, POStatus.CANCELLED):
            raise BusinessRuleViolation(f"Purchase order is {po.status}", code="po_not_billable")
    if not lines:
        if po is None:
            raise ValidationFailed(
                "Give lines or a purchase order to copy them from", code="no_lines"
            )
        lines = [
            APLine(ln.description, ln.account_id, ln.quantity, ln.unit_price) for ln in po.lines
        ]
    checked = _check_lines(session, lines)
    if due_date is not None and due_date < bill_date:
        raise ValidationFailed("Due date is before the bill date", code="invalid_dates")
    bill = VendorBill(
        bill_number=billing_repo.next_number(session, "bill_number_seq", "BILL"),
        vendor_id=vendor.id,
        vendor_invoice_number=number,
        purchase_order_id=po.id if po else None,
        status=BillStatus.DRAFT,
        bill_date=bill_date,
        due_date=due_date or bill_date + timedelta(days=vendor.payment_terms_days),
        total=sum((amt for _, amt in checked), ZERO),
        amount_paid=ZERO,
        notes=notes,
        created_by_id=actor.id,
        lines=[
            VendorBillLine(
                line_no=i,
                description=ln.description,
                account_id=ln.account_id,
                department_id=ln.department_id,
                quantity=ln.quantity,
                unit_price=ln.unit_price,
                amount=amt,
            )
            for i, (ln, amt) in enumerate(checked, start=1)
        ],
    )
    session.add(bill)
    session.flush()
    bill.match_status, bill.match_note = three_way_match(session, bill)
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="vendor_bill",
        entity_id=bill.id,
        action="create",
        after=audit.snapshot(bill),
    )
    return bill


def _approve(session: Session, actor: Actor, bill: VendorBill) -> None:
    memo = f"Bill {bill.bill_number} - {bill.vendor.name} #{bill.vendor_invoice_number}"
    lines = [
        LineInput(
            ln.account_id,
            debit=ln.amount,
            description=ln.description[:200],
            department_id=ln.department_id,
        )
        for ln in bill.lines
        if ln.amount > 0
    ]
    lines.append(
        LineInput(
            posting.account_id(session, posting.ACCOUNTS_PAYABLE),
            credit=bill.total,
            description=memo[:200],
        )
    )
    entry = ledger.post_entry(
        session,
        actor,
        EntryDraft(
            entry_date=bill.bill_date,
            memo=memo,
            source_type="vendor_bill",
            source_id=str(bill.id),
            lines=lines,
        ),
    )
    bill.approval_entry_id = entry.id
    bill.status = BillStatus.APPROVED
    bill.approved_at = datetime.now(UTC)
    if bill.purchase_order_id is not None:
        po = get_po(session, bill.purchase_order_id, lock=True)
        if po.status == POStatus.RECEIVED and repo.billed_total_for_po(session, po.id) >= po.total:
            po.status = POStatus.CLOSED
    session.flush()


def submit_bill(session: Session, actor: Actor, bill_id: int) -> VendorBill:
    bill = get_bill(session, bill_id, lock=True)
    if bill.status != BillStatus.DRAFT:
        raise Conflict("Only draft bills can be submitted", code="invalid_transition")
    if bill.total <= 0:
        raise BusinessRuleViolation("Bill total must be positive", code="empty_bill")
    before = audit.snapshot(bill)
    bill.match_status, bill.match_note = three_way_match(session, bill)
    clean = bill.match_status in (MatchResult.MATCHED, MatchResult.NO_PO)
    if clean and not approvals.needs_approval(session, "vendor_bill", bill.total):
        _approve(session, actor, bill)
    else:
        bill.status = BillStatus.PENDING_APPROVAL
        session.flush()
        reason = bill.match_note if not clean else "Above approval threshold"
        approvals.request(
            session,
            actor,
            kind="vendor_bill",
            entity_type="vendor_bill",
            entity_id=bill.id,
            reference=bill.bill_number,
            summary=f"{bill.vendor.name} invoice {bill.vendor_invoice_number} for "
            f"{bill.total:.2f}. {reason}",
            amount=bill.total,
        )
    audit.record(
        session,
        actor,
        entity_type="vendor_bill",
        entity_id=bill.id,
        action="status_change",
        before=before,
        after=audit.snapshot(bill),
    )
    return bill


def _pending_bill(session: Session, actor: Actor, bill_id: int) -> VendorBill:
    bill = get_bill(session, bill_id, lock=True)
    if bill.status != BillStatus.PENDING_APPROVAL:
        raise Conflict("Bill is not awaiting approval", code="not_pending")
    if bill.created_by_id is not None and bill.created_by_id == actor.id:
        raise PermissionDenied("You cannot approve a bill you entered", code="self_approval")
    return bill


def approve_bill(session: Session, actor: Actor, bill_id: int, note: str) -> VendorBill:
    bill = _pending_bill(session, actor, bill_id)
    before = audit.snapshot(bill)
    _approve(session, actor, bill)
    audit.record(
        session,
        actor,
        entity_type="vendor_bill",
        entity_id=bill.id,
        action="status_change",
        before=before,
        after=audit.snapshot(bill),
    )
    approvals.record_decision(
        session, actor, kind="vendor_bill", entity_id=bill.id, approved=True, note=note
    )
    return bill


def reject_bill(session: Session, actor: Actor, bill_id: int, note: str) -> VendorBill:
    bill = _pending_bill(session, actor, bill_id)
    before = audit.snapshot(bill)
    bill.status = BillStatus.REJECTED
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="vendor_bill",
        entity_id=bill.id,
        action="status_change",
        before=before,
        after=audit.snapshot(bill),
    )
    approvals.record_decision(
        session, actor, kind="vendor_bill", entity_id=bill.id, approved=False, note=note
    )
    return bill


def void_bill(session: Session, actor: Actor, bill_id: int, reason: str) -> VendorBill:
    bill = get_bill(session, bill_id, lock=True)
    if bill.status not in (BillStatus.DRAFT, BillStatus.REJECTED):
        raise Conflict("Only draft or rejected bills can be voided", code="invalid_transition")
    before = audit.snapshot(bill)
    bill.status = BillStatus.VOID
    bill.notes = f"{bill.notes}\nVoided: {reason}".strip()
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="vendor_bill",
        entity_id=bill.id,
        action="status_change",
        before=before,
        after=audit.snapshot(bill),
    )
    return bill


def schedule_payment(session: Session, actor: Actor, bill_id: int, pay_on: date) -> VendorBill:
    bill = get_bill(session, bill_id, lock=True)
    if bill.status not in (BillStatus.APPROVED, BillStatus.PARTIALLY_PAID):
        raise Conflict("Only approved bills can be scheduled", code="not_payable")
    before = audit.snapshot(bill)
    bill.scheduled_payment_date = pay_on
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="vendor_bill",
        entity_id=bill.id,
        action="update",
        before=before,
        after=audit.snapshot(bill),
    )
    return bill


def pay_bill(
    session: Session,
    actor: Actor,
    bill_id: int,
    *,
    amount: Decimal | None,
    paid_on: date | None,
    method: str,
    reference: str,
) -> VendorPayment:
    bill = get_bill(session, bill_id, lock=True)
    if bill.status not in (BillStatus.APPROVED, BillStatus.PARTIALLY_PAID):
        raise Conflict(
            f"Bill is {bill.status}; only approved bills can be paid", code="not_payable"
        )
    if method not in PAY_METHODS:
        raise ValidationFailed("Method must be bank_transfer or cheque", code="invalid_method")
    pay = bill.balance_due if amount is None else amount
    if pay <= 0 or quantize(pay) != pay or pay > bill.balance_due:
        raise BusinessRuleViolation(
            f"Amount must be between 0.01 and {bill.balance_due:.2f}", code="invalid_amount"
        )
    payment = VendorPayment(
        payment_number=billing_repo.next_number(session, "vendor_payment_number_seq", "VPAY"),
        vendor_bill_id=bill.id,
        vendor_id=bill.vendor_id,
        amount=pay,
        paid_on=paid_on or today(),
        method=method,
        reference=reference,
        created_by_id=actor.id,
    )
    session.add(payment)
    session.flush()
    memo = f"Payment {payment.payment_number} for {bill.bill_number} ({bill.vendor.name})"
    entry = ledger.post_entry(
        session,
        actor,
        EntryDraft(
            entry_date=payment.paid_on,
            memo=memo,
            source_type="vendor_payment",
            source_id=str(payment.id),
            lines=posting.simple_transfer(
                session,
                debit_code=posting.ACCOUNTS_PAYABLE,
                credit_code=posting.BANK,
                amount=pay,
                description=memo,
            ),
        ),
    )
    payment.journal_entry_id = entry.id
    before = audit.snapshot(bill)
    bill.amount_paid += pay
    bill.status = BillStatus.PAID if bill.balance_due == 0 else BillStatus.PARTIALLY_PAID
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="vendor_payment",
        entity_id=payment.id,
        action="create",
        after=audit.snapshot(payment),
    )
    audit.record(
        session,
        actor,
        entity_type="vendor_bill",
        entity_id=bill.id,
        action="status_change",
        before=before,
        after=audit.snapshot(bill),
    )
    return payment


def run_scheduled_payments(session: Session, actor: Actor, *, as_of: date) -> list[VendorPayment]:
    """Pay the balance of every approved bill whose scheduled date has arrived (payment run)."""
    return [
        pay_bill(
            session,
            actor,
            bill.id,
            amount=None,
            paid_on=as_of,
            method="bank_transfer",
            reference=f"RUN-{as_of.isoformat()}",
        )
        for bill in repo.bills_due_for_payment(session, as_of)
    ]
