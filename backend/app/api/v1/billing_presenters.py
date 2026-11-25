"""Map billing models to response schemas (presentation only: naming, masking)."""

from collections.abc import Sequence

from app.core.masking import payment_reference
from app.models.billing import Invoice, Payment, Refund
from app.models.patients import Visit
from app.schemas.billing import (
    InvoiceLineOut,
    InvoiceOut,
    InvoiceSummaryOut,
    PaymentDetailOut,
    PaymentOut,
    RefundOut,
    VisitOut,
)
from app.services.audit import Actor


def visit_out(v: Visit) -> VisitOut:
    return VisitOut(
        id=v.id,
        visit_number=v.visit_number,
        patient_id=v.patient_id,
        patient_name=v.patient.full_name,
        department_id=v.department_id,
        department_name=v.department.name,
        visit_type=v.visit_type,
        admit_date=v.admit_date,
        discharge_date=v.discharge_date,
        attending_physician=v.attending_physician,
        status=v.status,
    )


def _summary_fields(i: Invoice) -> dict[str, object]:
    return {
        "id": i.id,
        "invoice_number": i.invoice_number,
        "patient_id": i.patient_id,
        "patient_name": i.patient.full_name,
        "patient_mrn": i.patient.mrn,
        "visit_id": i.visit_id,
        "status": i.status,
        "invoice_date": i.invoice_date,
        "due_date": i.due_date,
        "total": i.total,
        "amount_paid": i.amount_paid,
        "balance_due": i.balance_due,
        "created_at": i.created_at,
    }


def invoice_summary(i: Invoice) -> InvoiceSummaryOut:
    return InvoiceSummaryOut.model_validate(_summary_fields(i))


def invoice_out(i: Invoice) -> InvoiceOut:
    return InvoiceOut.model_validate(
        {
            **_summary_fields(i),
            "visit_number": i.visit.visit_number if i.visit else None,
            "price_list_id": i.price_list_id,
            "subtotal": i.subtotal,
            "discount_total": i.discount_total,
            "tax_total": i.tax_total,
            "notes": i.notes,
            "issue_entry_id": i.issue_entry_id,
            "void_entry_id": i.void_entry_id,
            "issued_at": i.issued_at,
            "voided_at": i.voided_at,
            "void_reason": i.void_reason,
            "lines": [InvoiceLineOut.model_validate(ln) for ln in i.lines],
        }
    )


def _payment_fields(p: Payment, actor: Actor) -> dict[str, object]:
    return {
        "id": p.id,
        "payment_number": p.payment_number,
        "kind": p.kind,
        "patient_id": p.patient_id,
        "patient_name": p.patient.full_name,
        "patient_mrn": p.patient.mrn,
        "invoice_id": p.invoice_id,
        "invoice_number": p.invoice.invoice_number if p.invoice else None,
        "method": p.method,
        "amount": p.amount,
        "refunded_amount": p.refunded_amount,
        "received_on": p.received_on,
        "reference": payment_reference(p.method, p.reference, actor),
        "notes": p.notes,
        "journal_entry_id": p.journal_entry_id,
        "created_at": p.created_at,
    }


def payment_out(p: Payment, actor: Actor) -> PaymentOut:
    return PaymentOut.model_validate(_payment_fields(p, actor))


def refund_out(r: Refund) -> RefundOut:
    return RefundOut(
        id=r.id,
        refund_number=r.refund_number,
        payment_id=r.payment_id,
        payment_number=r.payment.payment_number,
        patient_name=r.payment.patient.full_name,
        amount=r.amount,
        reason=r.reason,
        status=r.status,
        refunded_on=r.refunded_on,
        journal_entry_id=r.journal_entry_id,
        requested_by_id=r.requested_by_id,
        decided_by_id=r.decided_by_id,
        decision_note=r.decision_note,
        created_at=r.created_at,
    )


def payment_detail(p: Payment, refunds: Sequence[Refund], actor: Actor) -> PaymentDetailOut:
    return PaymentDetailOut.model_validate(
        {**_payment_fields(p, actor), "refunds": [refund_out(r) for r in refunds]}
    )
