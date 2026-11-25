"""AP queries: vendors, purchase orders, vendor bills, vendor payments."""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.pagination import PageParams
from app.models.ap import PurchaseOrder, Vendor, VendorBill, VendorPayment
from app.repositories.billing import _page


def get_vendor(session: Session, vendor_id: int) -> Vendor | None:
    return session.get(Vendor, vendor_id)


def vendor_code_taken(session: Session, code: str) -> bool:
    return bool(session.scalar(select(func.count(Vendor.id)).where(Vendor.code == code)))


def list_vendors(
    session: Session, params: PageParams, *, search: str | None, active_only: bool
) -> tuple[Sequence[Vendor], int]:
    stmt = select(Vendor)
    if search:
        like = f"%{search.lower()}%"
        stmt = stmt.where(
            or_(func.lower(Vendor.name).like(like), func.lower(Vendor.code).like(like))
        )
    if active_only:
        stmt = stmt.where(Vendor.is_active.is_(True))
    sorts = {"name": Vendor.name, "code": Vendor.code}
    return _page(session, stmt, params, sorts, "name", Vendor.id)


def get_po(session: Session, po_id: int, *, lock: bool = False) -> PurchaseOrder | None:
    if lock:
        stmt = (
            select(PurchaseOrder).where(PurchaseOrder.id == po_id).with_for_update(of=PurchaseOrder)
        )
        return session.scalars(stmt).unique().first()
    return session.get(PurchaseOrder, po_id)


def list_pos(
    session: Session, params: PageParams, *, status: str | None, vendor_id: int | None
) -> tuple[Sequence[PurchaseOrder], int]:
    stmt = select(PurchaseOrder)
    if status:
        stmt = stmt.where(PurchaseOrder.status == status)
    if vendor_id is not None:
        stmt = stmt.where(PurchaseOrder.vendor_id == vendor_id)
    sorts = {
        "order_date": PurchaseOrder.order_date,
        "po_number": PurchaseOrder.po_number,
        "total": PurchaseOrder.total,
    }
    return _page(session, stmt, params, sorts, "-order_date", PurchaseOrder.id.desc())


def billed_total_for_po(
    session: Session, po_id: int, *, exclude_bill_id: int | None = None
) -> Decimal:
    stmt = select(func.coalesce(func.sum(VendorBill.total), 0)).where(
        VendorBill.purchase_order_id == po_id,
        VendorBill.status.notin_(["rejected", "void"]),
    )
    if exclude_bill_id is not None:
        stmt = stmt.where(VendorBill.id != exclude_bill_id)
    return Decimal(session.scalar(stmt) or 0)


def get_bill(session: Session, bill_id: int, *, lock: bool = False) -> VendorBill | None:
    if lock:
        stmt = select(VendorBill).where(VendorBill.id == bill_id).with_for_update(of=VendorBill)
        return session.scalars(stmt).unique().first()
    return session.get(VendorBill, bill_id)


def bill_number_exists(session: Session, vendor_id: int, vendor_invoice_number: str) -> bool:
    stmt = select(func.count(VendorBill.id)).where(
        VendorBill.vendor_id == vendor_id, VendorBill.vendor_invoice_number == vendor_invoice_number
    )
    return bool(session.scalar(stmt))


def list_bills(
    session: Session,
    params: PageParams,
    *,
    status: str | None,
    vendor_id: int | None,
    due_before: date | None,
    search: str | None,
) -> tuple[Sequence[VendorBill], int]:
    stmt = select(VendorBill).join(Vendor, Vendor.id == VendorBill.vendor_id)
    if status:
        stmt = stmt.where(VendorBill.status == status)
    if vendor_id is not None:
        stmt = stmt.where(VendorBill.vendor_id == vendor_id)
    if due_before:
        stmt = stmt.where(VendorBill.due_date <= due_before)
    if search:
        like = f"%{search.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(VendorBill.bill_number).like(like),
                func.lower(VendorBill.vendor_invoice_number).like(like),
                func.lower(Vendor.name).like(like),
            )
        )
    sorts = {
        "bill_date": VendorBill.bill_date,
        "due_date": VendorBill.due_date,
        "total": VendorBill.total,
        "bill_number": VendorBill.bill_number,
    }
    return _page(session, stmt, params, sorts, "-bill_date", VendorBill.id.desc())


def bills_due_for_payment(session: Session, as_of: date) -> Sequence[VendorBill]:
    stmt = (
        select(VendorBill)
        .where(
            VendorBill.status.in_(["approved", "partially_paid"]),
            VendorBill.scheduled_payment_date.is_not(None),
            VendorBill.scheduled_payment_date <= as_of,
        )
        .order_by(VendorBill.scheduled_payment_date, VendorBill.id)
    )
    return session.scalars(stmt).unique().all()


def list_vendor_payments(
    session: Session, params: PageParams, *, vendor_id: int | None, bill_id: int | None
) -> tuple[Sequence[VendorPayment], int]:
    stmt = select(VendorPayment)
    if vendor_id is not None:
        stmt = stmt.where(VendorPayment.vendor_id == vendor_id)
    if bill_id is not None:
        stmt = stmt.where(VendorPayment.vendor_bill_id == bill_id)
    sorts = {"paid_on": VendorPayment.paid_on, "amount": VendorPayment.amount}
    return _page(session, stmt, params, sorts, "-paid_on", VendorPayment.id.desc())


def ap_open_total(session: Session) -> Decimal:
    stmt = select(func.coalesce(func.sum(VendorBill.total - VendorBill.amount_paid), 0)).where(
        VendorBill.status.in_(["approved", "partially_paid"])
    )
    return Decimal(session.scalar(stmt) or 0)
