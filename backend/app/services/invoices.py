"""Invoice lifecycle: draft (charge capture) -> issued -> partially_paid -> paid, or void.

Issuing posts Dr AR / Cr revenue (per department) in the same transaction; voiding an issued
invoice posts the reversing entry. Payments live in services/payments.py.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation, Conflict, NotFound, ValidationFailed
from app.models.billing import Invoice, InvoiceLine, InvoiceStatus
from app.models.org import Department
from app.models.patients import VisitStatus
from app.repositories import billing as repo
from app.services import audit, ledger, posting
from app.services.audit import Actor
from app.services.billing_math import invoice_totals, line_amounts
from app.services.catalog import default_price_list, get_price_list
from app.services.ledger import EntryDraft
from app.services.patients import get_patient, get_visit

PAYMENT_TERMS_DAYS = 30
ZERO = Decimal("0.00")


@dataclass(frozen=True)
class LineSpec:
    """A charge. Catalog lines take their price from the invoice's price list on the service date;
    ad-hoc lines (no service) must give description, department and unit price."""

    quantity: Decimal
    service_id: int | None = None
    description: str | None = None
    department_id: int | None = None
    unit_price: Decimal | None = None
    service_date: date | None = None
    discount_percent: Decimal | None = None
    discount_amount: Decimal | None = None


def today() -> date:
    return datetime.now(UTC).date()


def get_invoice(session: Session, invoice_id: int, *, lock: bool = False) -> Invoice:
    invoice = repo.get_invoice(session, invoice_id, lock=lock)
    if invoice is None:
        raise NotFound("Invoice not found")
    return invoice


def snapshot(invoice: Invoice) -> dict[str, object]:
    lines = [
        {
            "line_no": ln.line_no,
            "service_id": ln.service_id,
            "description": ln.description,
            "quantity": f"{ln.quantity}",
            "unit_price": ln.unit_price,
            "discount": ln.discount_amount,
            "tax": ln.tax_amount,
            "line_total": ln.line_total,
        }
        for ln in invoice.lines
    ]
    return audit.snapshot(invoice, extra={"lines": lines})


def _build_lines(
    session: Session, invoice: Invoice, specs: Sequence[LineSpec]
) -> list[InvoiceLine]:
    default_date = invoice.visit.admit_date if invoice.visit else today()
    service_ids = {s.service_id for s in specs if s.service_id is not None}
    services = repo.services_by_ids(session, service_ids)
    lines: list[InvoiceLine] = []
    for i, spec in enumerate(specs, start=1):
        service_date = spec.service_date or default_date
        if spec.service_id is not None:
            service = services.get(spec.service_id)
            if service is None:
                raise NotFound(f"Line {i}: service not found", code="service_not_found")
            if not service.is_active:
                raise BusinessRuleViolation(
                    f"Line {i}: {service.code} is inactive", code="service_inactive"
                )
            if spec.unit_price is not None:
                raise ValidationFailed(
                    f"Line {i}: catalog lines are priced by the price list",
                    code="price_override_not_allowed",
                )
            price = repo.price_on(session, invoice.price_list_id, {service.id}, service_date)
            if service.id not in price:
                raise BusinessRuleViolation(
                    f"Line {i}: no price for {service.code} on {service_date}", code="no_price"
                )
            unit_price, tax_rate = price[service.id], service.tax_rate
            description = spec.description or service.name
            department_id = service.department_id
        else:
            if not spec.description or spec.department_id is None or spec.unit_price is None:
                raise ValidationFailed(
                    f"Line {i}: ad-hoc lines need description, department and unit price",
                    code="incomplete_line",
                )
            if session.get(Department, spec.department_id) is None:
                raise NotFound(f"Line {i}: department not found", code="department_not_found")
            unit_price, tax_rate = spec.unit_price, Decimal("0")
            description, department_id = spec.description, spec.department_id
        amounts = line_amounts(
            spec.quantity,
            unit_price,
            tax_rate,
            discount_percent=spec.discount_percent,
            discount_amount=spec.discount_amount,
        )
        lines.append(
            InvoiceLine(
                line_no=i,
                service_id=spec.service_id,
                description=description,
                department_id=department_id,
                service_date=service_date,
                quantity=spec.quantity,
                unit_price=unit_price,
                gross_amount=amounts.gross,
                discount_amount=amounts.discount,
                tax_rate=tax_rate,
                tax_amount=amounts.tax,
                line_total=amounts.total,
            )
        )
    return lines


def _apply_totals(invoice: Invoice) -> None:
    from app.services.billing_math import LineAmounts

    totals = invoice_totals(
        LineAmounts(ln.gross_amount, ln.discount_amount, ln.tax_amount, ln.line_total)
        for ln in invoice.lines
    )
    invoice.subtotal, invoice.discount_total = totals.subtotal, totals.discount_total
    invoice.tax_total, invoice.total = totals.tax_total, totals.total


def create_invoice(
    session: Session,
    actor: Actor,
    *,
    patient_id: int,
    visit_id: int | None,
    price_list_id: int | None,
    notes: str,
    lines: Sequence[LineSpec],
) -> Invoice:
    get_patient(session, patient_id)
    if visit_id is not None:
        visit = get_visit(session, visit_id)
        if visit.patient_id != patient_id:
            raise ValidationFailed("Visit belongs to another patient", code="visit_mismatch")
        if visit.status == VisitStatus.CANCELLED:
            raise BusinessRuleViolation("Cannot bill a cancelled visit", code="visit_cancelled")
    price_list = (
        get_price_list(session, price_list_id) if price_list_id else default_price_list(session)
    )
    invoice = Invoice(
        invoice_number=repo.next_number(session, "invoice_number_seq", "INV"),
        patient_id=patient_id,
        visit_id=visit_id,
        price_list_id=price_list.id,
        status=InvoiceStatus.DRAFT,
        notes=notes,
        created_by_id=actor.id,
        subtotal=ZERO,
        discount_total=ZERO,
        tax_total=ZERO,
        total=ZERO,
        amount_paid=ZERO,
    )
    session.add(invoice)
    session.flush()
    session.refresh(invoice)
    invoice.lines = _build_lines(session, invoice, lines)
    _apply_totals(invoice)
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="invoice",
        entity_id=invoice.id,
        action="create",
        after=snapshot(invoice),
    )
    return invoice


def update_draft(
    session: Session,
    actor: Actor,
    invoice_id: int,
    *,
    notes: str | None,
    lines: Sequence[LineSpec] | None,
) -> Invoice:
    invoice = get_invoice(session, invoice_id, lock=True)
    if invoice.status != InvoiceStatus.DRAFT:
        raise Conflict("Only draft invoices can be edited", code="not_draft")
    before = snapshot(invoice)
    if notes is not None:
        invoice.notes = notes
    if lines is not None:
        invoice.lines.clear()
        session.flush()  # delete old lines before renumbering
        invoice.lines.extend(_build_lines(session, invoice, lines))
        _apply_totals(invoice)
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="invoice",
        entity_id=invoice.id,
        action="update",
        before=before,
        after=snapshot(invoice),
    )
    return invoice


def issue_invoice(
    session: Session, actor: Actor, invoice_id: int, *, invoice_date: date | None = None
) -> Invoice:
    invoice = get_invoice(session, invoice_id, lock=True)
    if invoice.status != InvoiceStatus.DRAFT:
        raise Conflict("Only draft invoices can be issued", code="not_draft")
    if not invoice.lines or invoice.total <= 0:
        raise BusinessRuleViolation(
            "Cannot issue an invoice without a positive total", code="empty_invoice"
        )
    before = snapshot(invoice)
    issued_on = invoice_date or today()
    departments = {
        d.id: d
        for d in session.query(Department)
        .filter(Department.id.in_({ln.department_id for ln in invoice.lines}))
        .all()
    }
    revenue = [
        posting.RevenueLine(
            ln.department_id, departments[ln.department_id].revenue_account_id, ln.gross_amount
        )
        for ln in invoice.lines
    ]
    memo = f"Invoice {invoice.invoice_number} - {invoice.patient.full_name}"
    entry = ledger.post_entry(
        session,
        actor,
        EntryDraft(
            entry_date=issued_on,
            memo=memo,
            source_type="invoice",
            source_id=str(invoice.id),
            lines=posting.invoice_issue_lines(
                session,
                total=invoice.total,
                discount_total=invoice.discount_total,
                tax_total=invoice.tax_total,
                revenue=revenue,
                memo=memo,
            ),
        ),
    )
    invoice.status = InvoiceStatus.ISSUED
    invoice.invoice_date = issued_on
    invoice.due_date = issued_on + timedelta(days=PAYMENT_TERMS_DAYS)
    invoice.issued_at = datetime.now(UTC)
    invoice.issue_entry_id = entry.id
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="invoice",
        entity_id=invoice.id,
        action="status_change",
        before=before,
        after=snapshot(invoice),
    )
    return invoice


def void_invoice(session: Session, actor: Actor, invoice_id: int, reason: str) -> Invoice:
    invoice = get_invoice(session, invoice_id, lock=True)
    if not reason.strip():
        raise ValidationFailed("A void reason is required", code="reason_required")
    if invoice.status == InvoiceStatus.VOID:
        raise Conflict("Invoice is already void", code="already_void")
    if invoice.insurance_pending > 0 or repo.has_active_claim(session, invoice.id):
        raise BusinessRuleViolation(
            "Invoice has an open insurance claim; cancel or close it first", code="has_claim"
        )
    if invoice.amount_paid > 0 or invoice.adjusted_amount > 0:
        raise BusinessRuleViolation(
            "Invoice has payments; refund them before voiding", code="has_payments"
        )
    before = snapshot(invoice)
    if invoice.issue_entry_id is not None:
        reversal = ledger.reverse_entry(
            session,
            actor,
            invoice.issue_entry_id,
            f"Void invoice {invoice.invoice_number}: {reason}",
        )
        invoice.void_entry_id = reversal.id
    invoice.status = InvoiceStatus.VOID
    invoice.voided_at = datetime.now(UTC)
    invoice.void_reason = reason
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="invoice",
        entity_id=invoice.id,
        action="status_change",
        before=before,
        after=snapshot(invoice),
    )
    return invoice


def refresh_payment_status(invoice: Invoice) -> None:
    """Derive issued / partially_paid / paid from what has been settled (payments by patient or
    insurer, plus adjustments). Void and draft invoices are untouched."""
    if invoice.status in (InvoiceStatus.VOID, InvoiceStatus.DRAFT):
        return
    settled = invoice.amount_paid + invoice.adjusted_amount
    if invoice.balance_due <= 0:
        invoice.status = InvoiceStatus.PAID
    elif settled > 0:
        invoice.status = InvoiceStatus.PARTIALLY_PAID
    else:
        invoice.status = InvoiceStatus.ISSUED
