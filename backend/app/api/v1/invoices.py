from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Response, status

from app.api.v1.billing_presenters import invoice_out, invoice_summary, payment_out
from app.core.deps import DbSession, read_roles, require_roles
from app.core.errors import ErrorEnvelope
from app.core.pagination import Page, PageParams, page_params
from app.models.billing import InvoiceStatus
from app.models.identity import RoleName
from app.repositories import billing as repo
from app.schemas.billing import (
    ApplyDepositIn,
    InvoiceCreate,
    InvoiceIssueIn,
    InvoiceLineIn,
    InvoiceOut,
    InvoiceSummaryOut,
    InvoiceUpdate,
    PaymentOut,
    ReasonIn,
)
from app.services import idempotency, invoices, payments, pdf
from app.services.audit import Actor
from app.services.invoices import LineSpec

router = APIRouter(
    prefix="/invoices",
    tags=["invoices"],
    responses={
        401: {"model": ErrorEnvelope},
        403: {"model": ErrorEnvelope},
        404: {"model": ErrorEnvelope},
        409: {"model": ErrorEnvelope},
        422: {"model": ErrorEnvelope},
    },
)

R = RoleName
InvoiceRead = Annotated[
    Actor,
    Depends(read_roles(R.BILLING_CLERK, R.INSURANCE_OFFICER, R.FINANCE_MANAGER, R.ACCOUNTANT)),
]
InvoiceWrite = Annotated[Actor, Depends(require_roles(R.BILLING_CLERK))]
InvoiceVoid = Annotated[Actor, Depends(require_roles(R.BILLING_CLERK, R.FINANCE_MANAGER))]
IdemKey = Annotated[
    str | None,
    Header(
        alias="Idempotency-Key",
        description=(
            "Makes the request safe to retry: the same key and body return the original result."
        ),
    ),
]
PDF_RESPONSE: dict[int | str, dict[str, Any]] = {
    200: {"content": {"application/pdf": {}}, "description": "PDF document"}
}


def _specs(lines: list[InvoiceLineIn]) -> list[LineSpec]:
    return [
        LineSpec(
            quantity=ln.quantity,
            service_id=ln.service_id,
            description=ln.description,
            department_id=ln.department_id,
            unit_price=ln.unit_price,
            service_date=ln.service_date,
            discount_percent=ln.discount_percent,
            discount_amount=ln.discount_amount,
        )
        for ln in lines
    ]


@router.get("", response_model=Page[InvoiceSummaryOut])
def list_invoices(
    _: InvoiceRead,
    db: DbSession,
    params: Annotated[PageParams, Depends(page_params)],
    status: InvoiceStatus | None = None,
    patient_id: int | None = None,
    search: Annotated[
        str | None, Query(max_length=100, description="Invoice number, MRN or name")
    ] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    overdue: bool = False,
) -> Page[InvoiceSummaryOut]:
    rows, total = repo.list_invoices(
        db,
        params,
        status=status.value if status else None,
        patient_id=patient_id,
        search=search,
        date_from=date_from,
        date_to=date_to,
        overdue=overdue,
    )
    return Page(
        items=[invoice_summary(i) for i in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.post("", response_model=InvoiceOut, status_code=status.HTTP_201_CREATED)
def create_invoice(body: InvoiceCreate, actor: InvoiceWrite, db: DbSession) -> InvoiceOut:
    """Create a draft invoice (charge capture). Lines can be edited until it is issued."""
    invoice = invoices.create_invoice(
        db,
        actor,
        patient_id=body.patient_id,
        visit_id=body.visit_id,
        price_list_id=body.price_list_id,
        notes=body.notes,
        lines=_specs(body.lines),
    )
    return invoice_out(invoice)


@router.get("/{invoice_id}", response_model=InvoiceOut)
def get_invoice(invoice_id: int, _: InvoiceRead, db: DbSession) -> InvoiceOut:
    return invoice_out(invoices.get_invoice(db, invoice_id))


@router.patch("/{invoice_id}", response_model=InvoiceOut)
def update_invoice(
    invoice_id: int, body: InvoiceUpdate, actor: InvoiceWrite, db: DbSession
) -> InvoiceOut:
    invoice = invoices.update_draft(
        db,
        actor,
        invoice_id,
        notes=body.notes,
        lines=_specs(body.lines) if body.lines is not None else None,
    )
    return invoice_out(invoice)


@router.post("/{invoice_id}/issue", response_model=InvoiceOut)
def issue_invoice(
    invoice_id: int, body: InvoiceIssueIn, actor: InvoiceWrite, db: DbSession
) -> InvoiceOut:
    """Issue: posts Dr Accounts Receivable / Cr departmental revenue (and tax, discounts)."""
    return invoice_out(
        invoices.issue_invoice(db, actor, invoice_id, invoice_date=body.invoice_date)
    )


@router.post("/{invoice_id}/void", response_model=InvoiceOut)
def void_invoice(invoice_id: int, body: ReasonIn, actor: InvoiceVoid, db: DbSession) -> InvoiceOut:
    """Void: issued invoices get a reversing journal entry. Refund payments first."""
    return invoice_out(invoices.void_invoice(db, actor, invoice_id, body.reason))


@router.get("/{invoice_id}/payments", response_model=list[PaymentOut])
def invoice_payments(invoice_id: int, actor: InvoiceRead, db: DbSession) -> list[PaymentOut]:
    invoices.get_invoice(db, invoice_id)
    return [payment_out(p, actor) for p in repo.payments_for_invoice(db, invoice_id)]


@router.post(
    "/{invoice_id}/apply-deposit", response_model=PaymentOut, status_code=status.HTTP_201_CREATED
)
def apply_deposit(
    invoice_id: int,
    body: ApplyDepositIn,
    actor: InvoiceWrite,
    db: DbSession,
    idempotency_key: IdemKey = None,
) -> dict[str, Any]:
    def run() -> dict[str, Any]:
        payment = payments.apply_deposit(
            db, actor, invoice_id=invoice_id, amount=body.amount, applied_on=body.applied_on
        )
        return payment_out(payment, actor).model_dump(mode="json")

    return idempotency.execute(
        db,
        actor,
        scope=f"apply-deposit:{invoice_id}",
        key=idempotency_key,
        payload=body.model_dump(mode="json"),
        run=run,
    )


@router.get("/{invoice_id}/pdf", response_class=Response, responses=PDF_RESPONSE)
def invoice_pdf(invoice_id: int, _: InvoiceRead, db: DbSession) -> Response:
    invoice = invoices.get_invoice(db, invoice_id)
    content = pdf.invoice_pdf(invoice, repo.payments_for_invoice(db, invoice_id))
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{invoice.invoice_number}.pdf"'},
    )
