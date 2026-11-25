from datetime import UTC, date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, status

from app.core.deps import DbSession, read_roles, require_roles
from app.core.errors import ErrorEnvelope
from app.core.masking import mask
from app.core.pagination import Page, PageParams, page_params
from app.models.ap import BillStatus, POStatus, PurchaseOrder, Vendor, VendorBill, VendorPayment
from app.models.identity import RoleName
from app.repositories import ap as repo
from app.schemas.phase4 import (
    APLineIn,
    APLineOut,
    BillCreate,
    PaymentRunIn,
    PaymentRunOut,
    POLineOut,
    PurchaseOrderCreate,
    PurchaseOrderOut,
    ReasonIn,
    ScheduleIn,
    VendorBillOut,
    VendorCreate,
    VendorOut,
    VendorPaymentIn,
    VendorPaymentOut,
    VendorUpdate,
)
from app.services import ap, idempotency
from app.services.ap import APLine
from app.services.audit import Actor

router = APIRouter(
    tags=["payables"],
    responses={
        401: {"model": ErrorEnvelope},
        403: {"model": ErrorEnvelope},
        404: {"model": ErrorEnvelope},
        409: {"model": ErrorEnvelope},
        422: {"model": ErrorEnvelope},
    },
)

R = RoleName
APRead = Annotated[Actor, Depends(read_roles(R.ACCOUNTANT, R.FINANCE_MANAGER))]
APWrite = Annotated[Actor, Depends(require_roles(R.ACCOUNTANT))]
IdemKey = Annotated[str | None, Header(alias="Idempotency-Key")]
BANK_ROLES = frozenset({R.ACCOUNTANT.value, R.FINANCE_MANAGER.value})


def _lines(lines: list[APLineIn]) -> list[APLine]:
    return [
        APLine(ln.description, ln.account_id, ln.quantity, ln.unit_price, ln.department_id)
        for ln in lines
    ]


def vendor_out(v: Vendor, actor: Actor) -> VendorOut:
    reveal = bool(actor.roles & BANK_ROLES)
    return VendorOut(
        id=v.id,
        code=v.code,
        name=v.name,
        email=v.email,
        tax_id=v.tax_id if reveal else mask(v.tax_id),
        bank_reference=v.bank_reference if reveal else mask(v.bank_reference),
        payment_terms_days=v.payment_terms_days,
        default_expense_account_id=v.default_expense_account_id,
        is_active=v.is_active,
    )


def po_out(db: DbSession, po: PurchaseOrder) -> PurchaseOrderOut:
    return PurchaseOrderOut(
        id=po.id,
        po_number=po.po_number,
        vendor_id=po.vendor_id,
        vendor_name=po.vendor.name,
        status=POStatus(po.status),
        order_date=po.order_date,
        expected_date=po.expected_date,
        received_on=po.received_on,
        total=po.total,
        billed=repo.billed_total_for_po(db, po.id),
        notes=po.notes,
        lines=[POLineOut.model_validate(ln) for ln in po.lines],
    )


def bill_out(b: VendorBill) -> VendorBillOut:
    return VendorBillOut(
        id=b.id,
        bill_number=b.bill_number,
        vendor_id=b.vendor_id,
        vendor_name=b.vendor.name,
        vendor_invoice_number=b.vendor_invoice_number,
        purchase_order_id=b.purchase_order_id,
        po_number=b.purchase_order.po_number if b.purchase_order else None,
        status=BillStatus(b.status),
        match_status=b.match_status,
        match_note=b.match_note,
        bill_date=b.bill_date,
        due_date=b.due_date,
        scheduled_payment_date=b.scheduled_payment_date,
        total=b.total,
        amount_paid=b.amount_paid,
        balance_due=b.balance_due,
        notes=b.notes,
        approval_entry_id=b.approval_entry_id,
        lines=[APLineOut.model_validate(ln) for ln in b.lines],
    )


def payment_out(p: VendorPayment) -> VendorPaymentOut:
    return VendorPaymentOut(
        id=p.id,
        payment_number=p.payment_number,
        vendor_bill_id=p.vendor_bill_id,
        bill_number=p.bill.bill_number,
        vendor_id=p.vendor_id,
        vendor_name=p.vendor.name,
        amount=p.amount,
        paid_on=p.paid_on,
        method=p.method,
        reference=p.reference,
        journal_entry_id=p.journal_entry_id,
    )


# ------------------------------------------------------------------ vendors


@router.get("/vendors", response_model=Page[VendorOut])
def list_vendors(
    actor: APRead,
    db: DbSession,
    params: Annotated[PageParams, Depends(page_params)],
    search: Annotated[str | None, Query(max_length=100)] = None,
    active_only: bool = False,
) -> Page[VendorOut]:
    rows, total = repo.list_vendors(db, params, search=search, active_only=active_only)
    return Page(
        items=[vendor_out(v, actor) for v in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.post("/vendors", response_model=VendorOut, status_code=status.HTTP_201_CREATED)
def create_vendor(body: VendorCreate, actor: APWrite, db: DbSession) -> VendorOut:
    vendor = ap.create_vendor(
        db,
        actor,
        code=body.code,
        name=body.name,
        email=body.email,
        tax_id=body.tax_id,
        bank_reference=body.bank_reference,
        payment_terms_days=body.payment_terms_days,
        default_expense_account_id=body.default_expense_account_id,
    )
    return vendor_out(vendor, actor)


@router.patch("/vendors/{vendor_id}", response_model=VendorOut)
def update_vendor(vendor_id: int, body: VendorUpdate, actor: APWrite, db: DbSession) -> VendorOut:
    vendor = ap.update_vendor(
        db,
        actor,
        vendor_id,
        name=body.name,
        email=body.email,
        bank_reference=body.bank_reference,
        payment_terms_days=body.payment_terms_days,
        is_active=body.is_active,
    )
    return vendor_out(vendor, actor)


# ------------------------------------------------------------------ purchase orders


@router.get("/purchase-orders", response_model=Page[PurchaseOrderOut])
def list_pos(
    _: APRead,
    db: DbSession,
    params: Annotated[PageParams, Depends(page_params)],
    status: POStatus | None = None,
    vendor_id: int | None = None,
) -> Page[PurchaseOrderOut]:
    rows, total = repo.list_pos(
        db, params, status=status.value if status else None, vendor_id=vendor_id
    )
    return Page(
        items=[po_out(db, po) for po in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.post(
    "/purchase-orders", response_model=PurchaseOrderOut, status_code=status.HTTP_201_CREATED
)
def create_po(body: PurchaseOrderCreate, actor: APWrite, db: DbSession) -> PurchaseOrderOut:
    po = ap.create_po(
        db,
        actor,
        vendor_id=body.vendor_id,
        order_date=body.order_date,
        expected_date=body.expected_date,
        lines=_lines(body.lines),
        notes=body.notes,
    )
    return po_out(db, po)


@router.get("/purchase-orders/{po_id}", response_model=PurchaseOrderOut)
def get_po(po_id: int, _: APRead, db: DbSession) -> PurchaseOrderOut:
    return po_out(db, ap.get_po(db, po_id))


@router.post("/purchase-orders/{po_id}/issue", response_model=PurchaseOrderOut)
def issue_po(po_id: int, actor: APWrite, db: DbSession) -> PurchaseOrderOut:
    return po_out(db, ap.issue_po(db, actor, po_id))


@router.post("/purchase-orders/{po_id}/receive", response_model=PurchaseOrderOut)
def receive_po(po_id: int, actor: APWrite, db: DbSession) -> PurchaseOrderOut:
    """Record goods/services received (the receipt leg of the three-way match)."""
    return po_out(db, ap.receive_po(db, actor, po_id))


@router.post("/purchase-orders/{po_id}/cancel", response_model=PurchaseOrderOut)
def cancel_po(po_id: int, actor: APWrite, db: DbSession) -> PurchaseOrderOut:
    return po_out(db, ap.cancel_po(db, actor, po_id))


# ------------------------------------------------------------------ bills


@router.get("/vendor-bills", response_model=Page[VendorBillOut])
def list_bills(
    _: APRead,
    db: DbSession,
    params: Annotated[PageParams, Depends(page_params)],
    status: BillStatus | None = None,
    vendor_id: int | None = None,
    due_before: date | None = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
) -> Page[VendorBillOut]:
    rows, total = repo.list_bills(
        db,
        params,
        status=status.value if status else None,
        vendor_id=vendor_id,
        due_before=due_before,
        search=search,
    )
    return Page(
        items=[bill_out(b) for b in rows], total=total, page=params.page, page_size=params.page_size
    )


@router.post("/vendor-bills", response_model=VendorBillOut, status_code=status.HTTP_201_CREATED)
def create_bill(body: BillCreate, actor: APWrite, db: DbSession) -> VendorBillOut:
    bill = ap.create_bill(
        db,
        actor,
        vendor_id=body.vendor_id,
        vendor_invoice_number=body.vendor_invoice_number,
        bill_date=body.bill_date,
        due_date=body.due_date,
        purchase_order_id=body.purchase_order_id,
        lines=_lines(body.lines) if body.lines else None,
        notes=body.notes,
    )
    return bill_out(bill)


@router.get("/vendor-bills/{bill_id}", response_model=VendorBillOut)
def get_bill(bill_id: int, _: APRead, db: DbSession) -> VendorBillOut:
    return bill_out(ap.get_bill(db, bill_id))


@router.post("/vendor-bills/{bill_id}/submit", response_model=VendorBillOut)
def submit_bill(bill_id: int, actor: APWrite, db: DbSession) -> VendorBillOut:
    """Run the three-way match; approve now or route to a finance manager."""
    return bill_out(ap.submit_bill(db, actor, bill_id))


@router.post("/vendor-bills/{bill_id}/void", response_model=VendorBillOut)
def void_bill(bill_id: int, body: ReasonIn, actor: APWrite, db: DbSession) -> VendorBillOut:
    return bill_out(ap.void_bill(db, actor, bill_id, body.reason))


@router.post("/vendor-bills/{bill_id}/schedule", response_model=VendorBillOut)
def schedule_bill(bill_id: int, body: ScheduleIn, actor: APWrite, db: DbSession) -> VendorBillOut:
    return bill_out(ap.schedule_payment(db, actor, bill_id, body.pay_on))


@router.post(
    "/vendor-bills/{bill_id}/pay",
    response_model=VendorPaymentOut,
    status_code=status.HTTP_201_CREATED,
)
def pay_bill(
    bill_id: int,
    body: VendorPaymentIn,
    actor: APWrite,
    db: DbSession,
    idempotency_key: IdemKey = None,
) -> dict[str, Any]:
    """Pay a vendor bill (Dr Accounts Payable / Cr Bank). Send an Idempotency-Key."""

    def run() -> dict[str, Any]:
        payment = ap.pay_bill(
            db,
            actor,
            bill_id,
            amount=body.amount,
            paid_on=body.paid_on,
            method=body.method,
            reference=body.reference,
        )
        return payment_out(payment).model_dump(mode="json")

    return idempotency.execute(
        db,
        actor,
        scope=f"vendor-pay:{bill_id}",
        key=idempotency_key,
        payload=body.model_dump(mode="json"),
        run=run,
    )


@router.post("/vendor-bills/payment-run", response_model=PaymentRunOut)
def payment_run(body: PaymentRunIn, actor: APWrite, db: DbSession) -> PaymentRunOut:
    """Pay every approved bill whose scheduled payment date has arrived."""
    paid = ap.run_scheduled_payments(db, actor, as_of=body.as_of or datetime.now(UTC).date())
    return PaymentRunOut(paid=len(paid), payments=[payment_out(p) for p in paid])


@router.get("/vendor-payments", response_model=Page[VendorPaymentOut])
def list_vendor_payments(
    _: APRead,
    db: DbSession,
    params: Annotated[PageParams, Depends(page_params)],
    vendor_id: int | None = None,
    bill_id: int | None = None,
) -> Page[VendorPaymentOut]:
    rows, total = repo.list_vendor_payments(db, params, vendor_id=vendor_id, bill_id=bill_id)
    return Page(
        items=[payment_out(p) for p in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )
