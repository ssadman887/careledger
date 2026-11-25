from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Response, status

from app.api.v1.billing_presenters import payment_detail, payment_out, refund_out
from app.core.deps import DbSession, read_roles, require_roles
from app.core.errors import ErrorEnvelope
from app.core.masking import payment_reference
from app.core.pagination import Page, PageParams, page_params
from app.models.billing import PaymentKind, PaymentMethod, RefundStatus
from app.models.identity import RoleName
from app.repositories import billing as repo
from app.schemas.billing import (
    DecisionIn,
    PaymentDetailOut,
    PaymentIn,
    PaymentOut,
    RefundIn,
    RefundOut,
)
from app.services import approvals, idempotency, payments, pdf
from app.services.audit import Actor

router = APIRouter(
    tags=["payments"],
    responses={
        401: {"model": ErrorEnvelope},
        403: {"model": ErrorEnvelope},
        404: {"model": ErrorEnvelope},
        409: {"model": ErrorEnvelope},
        422: {"model": ErrorEnvelope},
    },
)

R = RoleName
PaymentRead = Annotated[
    Actor,
    Depends(read_roles(R.BILLING_CLERK, R.FINANCE_MANAGER, R.ACCOUNTANT, R.INSURANCE_OFFICER)),
]
PaymentWrite = Annotated[Actor, Depends(require_roles(R.BILLING_CLERK))]
Approver = Annotated[Actor, Depends(require_roles(R.FINANCE_MANAGER))]
IdemKey = Annotated[
    str | None,
    Header(
        alias="Idempotency-Key",
        description=(
            "Makes the request safe to retry: the same key and body return the original result."
        ),
    ),
]


@router.get("/payments", response_model=Page[PaymentOut])
def list_payments(
    actor: PaymentRead,
    db: DbSession,
    params: Annotated[PageParams, Depends(page_params)],
    method: PaymentMethod | None = None,
    kind: PaymentKind | None = None,
    patient_id: int | None = None,
    invoice_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
) -> Page[PaymentOut]:
    rows, total = repo.list_payments(
        db,
        params,
        method=method.value if method else None,
        kind=kind.value if kind else None,
        patient_id=patient_id,
        invoice_id=invoice_id,
        date_from=date_from,
        date_to=date_to,
        search=search,
    )
    return Page(
        items=[payment_out(p, actor) for p in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.post("/payments", response_model=PaymentOut, status_code=status.HTTP_201_CREATED)
def create_payment(
    body: PaymentIn, actor: PaymentWrite, db: DbSession, idempotency_key: IdemKey = None
) -> dict[str, Any]:
    """Record a patient payment (with `invoice_id`) or a deposit on account (with `patient_id`).
    Send an `Idempotency-Key` so network retries never charge twice."""

    def run() -> dict[str, Any]:
        if body.invoice_id is not None:
            payment = payments.record_payment(
                db,
                actor,
                invoice_id=body.invoice_id,
                method=body.method.value,
                amount=body.amount,
                received_on=body.received_on,
                reference=body.reference,
                notes=body.notes,
            )
        else:
            assert body.patient_id is not None
            payment = payments.record_deposit(
                db,
                actor,
                patient_id=body.patient_id,
                method=body.method.value,
                amount=body.amount,
                received_on=body.received_on,
                reference=body.reference,
                notes=body.notes,
            )
        return payment_out(payment, actor).model_dump(mode="json")

    return idempotency.execute(
        db,
        actor,
        scope="payments",
        key=idempotency_key,
        payload=body.model_dump(mode="json"),
        run=run,
    )


@router.get("/payments/{payment_id}", response_model=PaymentDetailOut)
def get_payment(payment_id: int, actor: PaymentRead, db: DbSession) -> PaymentDetailOut:
    payment = payments.get_payment(db, payment_id)
    return payment_detail(payment, repo.refunds_for_payments(db, [payment.id]), actor)


@router.get(
    "/payments/{payment_id}/receipt",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}, "description": "PDF receipt"}},
)
def payment_receipt(payment_id: int, actor: PaymentRead, db: DbSession) -> Response:
    payment = payments.get_payment(db, payment_id)
    content = pdf.receipt_pdf(payment, payment_reference(payment.method, payment.reference, actor))
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{payment.payment_number}.pdf"'},
    )


@router.post(
    "/payments/{payment_id}/refunds", response_model=RefundOut, status_code=status.HTTP_201_CREATED
)
def request_refund(
    payment_id: int,
    body: RefundIn,
    actor: PaymentWrite,
    db: DbSession,
    idempotency_key: IdemKey = None,
) -> dict[str, Any]:
    """Refunds above REFUND_APPROVAL_THRESHOLD wait for a finance manager."""

    def run() -> dict[str, Any]:
        refund = payments.request_refund(
            db,
            actor,
            payment_id=payment_id,
            amount=body.amount,
            reason=body.reason,
            approval_threshold=approvals.threshold(db, "refund"),
        )
        return refund_out(refund).model_dump(mode="json")

    return idempotency.execute(
        db,
        actor,
        scope=f"refund:{payment_id}",
        key=idempotency_key,
        payload=body.model_dump(mode="json"),
        run=run,
    )


@router.get("/refunds", response_model=Page[RefundOut])
def list_refunds(
    _: PaymentRead,
    db: DbSession,
    params: Annotated[PageParams, Depends(page_params)],
    status: RefundStatus | None = None,
    payment_id: int | None = None,
) -> Page[RefundOut]:
    rows, total = repo.list_refunds(
        db, params, status=status.value if status else None, payment_id=payment_id
    )
    return Page(
        items=[refund_out(r) for r in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.post("/refunds/{refund_id}/approve", response_model=RefundOut)
def approve_refund(refund_id: int, body: DecisionIn, actor: Approver, db: DbSession) -> RefundOut:
    return refund_out(payments.approve_refund(db, actor, refund_id, body.note))


@router.post("/refunds/{refund_id}/reject", response_model=RefundOut)
def reject_refund(refund_id: int, body: DecisionIn, actor: Approver, db: DbSession) -> RefundOut:
    return refund_out(payments.reject_refund(db, actor, refund_id, body.note))
