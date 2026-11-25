"""Queries for patients, visits, catalog, invoices, payments and refunds."""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, and_, func, or_, select, text
from sqlalchemy.orm import Session

from app.core.pagination import PageParams
from app.models.billing import (
    Invoice,
    Payment,
    PaymentKind,
    PaymentMethod,
    Refund,
    RefundStatus,
)
from app.models.catalog import PriceList, PriceListItem, Service
from app.models.patients import Patient, Visit
from app.models.platform import IdempotencyKey


def next_number(session: Session, sequence: str, prefix: str) -> str:
    value = session.scalar(text(f"SELECT nextval('{sequence}')"))
    return f"{prefix}-{int(value or 0):06d}"


def _page[T](
    session: Session,
    stmt: Select[tuple[T]],
    params: PageParams,
    sorts: dict[str, Any],
    default: str,
    tiebreak: Any,
) -> tuple[Sequence[T], int]:
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    sort = params.sort or default
    column = sorts.get(sort.lstrip("-"), sorts[default.lstrip("-")])
    primary = column.desc() if sort.startswith("-") else column.asc()
    rows = (
        session.scalars(
            stmt.order_by(primary, tiebreak).offset(params.offset).limit(params.page_size)
        )
        .unique()
        .all()
    )
    return rows, total


# ------------------------------------------------------------------ patients & visits


def get_patient(session: Session, patient_id: int, *, lock: bool = False) -> Patient | None:
    if lock:
        stmt = select(Patient).where(Patient.id == patient_id).with_for_update()
        return session.scalars(stmt).first()
    return session.get(Patient, patient_id)


def list_patients(
    session: Session, params: PageParams, *, search: str | None
) -> tuple[Sequence[Patient], int]:
    stmt = select(Patient).where(Patient.deleted_at.is_(None))
    if search:
        like = f"%{search.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Patient.mrn).like(like),
                func.lower(Patient.first_name + " " + Patient.last_name).like(like),
            )
        )
    sorts = {
        "mrn": Patient.mrn,
        "last_name": Patient.last_name,
        "date_of_birth": Patient.date_of_birth,
        "created_at": Patient.created_at,
    }
    return _page(session, stmt, params, sorts, "last_name", Patient.id)


def get_visit(session: Session, visit_id: int) -> Visit | None:
    return session.get(Visit, visit_id)


def list_visits(
    session: Session,
    params: PageParams,
    *,
    patient_id: int | None,
    status: str | None,
    department_id: int | None,
) -> tuple[Sequence[Visit], int]:
    stmt = select(Visit)
    if patient_id is not None:
        stmt = stmt.where(Visit.patient_id == patient_id)
    if status:
        stmt = stmt.where(Visit.status == status)
    if department_id is not None:
        stmt = stmt.where(Visit.department_id == department_id)
    sorts = {"admit_date": Visit.admit_date, "visit_number": Visit.visit_number}
    return _page(session, stmt, params, sorts, "-admit_date", Visit.id.desc())


# ------------------------------------------------------------------ catalog


def get_service(session: Session, service_id: int) -> Service | None:
    return session.get(Service, service_id)


def get_service_by_code(session: Session, code: str) -> Service | None:
    return session.scalars(select(Service).where(Service.code == code)).first()


def services_by_ids(session: Session, ids: set[int]) -> dict[int, Service]:
    return {s.id: s for s in session.scalars(select(Service).where(Service.id.in_(ids))).all()}


def list_services(
    session: Session,
    params: PageParams,
    *,
    search: str | None,
    department_id: int | None,
    active_only: bool,
) -> tuple[Sequence[Service], int]:
    stmt = select(Service)
    if search:
        like = f"%{search.lower()}%"
        stmt = stmt.where(
            or_(func.lower(Service.code).like(like), func.lower(Service.name).like(like))
        )
    if department_id is not None:
        stmt = stmt.where(Service.department_id == department_id)
    if active_only:
        stmt = stmt.where(Service.is_active.is_(True))
    sorts = {"code": Service.code, "name": Service.name}
    return _page(session, stmt, params, sorts, "code", Service.id)


def get_price_list(session: Session, price_list_id: int) -> PriceList | None:
    return session.get(PriceList, price_list_id)


def default_price_list(session: Session) -> PriceList | None:
    return session.scalars(select(PriceList).where(PriceList.is_default.is_(True))).first()


def list_price_lists(session: Session) -> Sequence[PriceList]:
    return session.scalars(select(PriceList).order_by(PriceList.code)).all()


def price_items(
    session: Session, price_list_id: int, service_id: int | None
) -> Sequence[PriceListItem]:
    stmt = select(PriceListItem).where(PriceListItem.price_list_id == price_list_id)
    if service_id is not None:
        stmt = stmt.where(PriceListItem.service_id == service_id)
    return session.scalars(
        stmt.order_by(PriceListItem.service_id, PriceListItem.effective_from)
    ).all()


def price_on(
    session: Session, price_list_id: int, service_ids: set[int], on: date
) -> dict[int, Decimal]:
    stmt = select(PriceListItem.service_id, PriceListItem.unit_price).where(
        PriceListItem.price_list_id == price_list_id,
        PriceListItem.service_id.in_(service_ids),
        PriceListItem.effective_from <= on,
        or_(PriceListItem.effective_to.is_(None), PriceListItem.effective_to >= on),
    )
    return {int(sid): Decimal(price) for sid, price in session.execute(stmt).all()}


def open_ended_item(session: Session, price_list_id: int, service_id: int) -> PriceListItem | None:
    stmt = select(PriceListItem).where(
        PriceListItem.price_list_id == price_list_id,
        PriceListItem.service_id == service_id,
        PriceListItem.effective_to.is_(None),
    )
    return session.scalars(stmt).first()


# ------------------------------------------------------------------ invoices


def get_invoice(session: Session, invoice_id: int, *, lock: bool = False) -> Invoice | None:
    if lock:
        stmt = select(Invoice).where(Invoice.id == invoice_id).with_for_update(of=Invoice)
        return session.scalars(stmt).unique().first()
    return session.get(Invoice, invoice_id)


def list_invoices(
    session: Session,
    params: PageParams,
    *,
    status: str | None,
    patient_id: int | None,
    search: str | None,
    date_from: date | None,
    date_to: date | None,
    overdue: bool,
) -> tuple[Sequence[Invoice], int]:
    stmt = select(Invoice).join(Patient, Patient.id == Invoice.patient_id)
    if status:
        stmt = stmt.where(Invoice.status == status)
    if patient_id is not None:
        stmt = stmt.where(Invoice.patient_id == patient_id)
    if search:
        like = f"%{search.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Invoice.invoice_number).like(like),
                func.lower(Patient.mrn).like(like),
                func.lower(Patient.first_name + " " + Patient.last_name).like(like),
            )
        )
    if date_from:
        stmt = stmt.where(Invoice.invoice_date >= date_from)
    if date_to:
        stmt = stmt.where(Invoice.invoice_date <= date_to)
    if overdue:
        stmt = stmt.where(
            Invoice.status.in_(["issued", "partially_paid"]),
            Invoice.due_date < func.current_date(),
        )
    sorts = {
        "invoice_number": Invoice.invoice_number,
        "invoice_date": Invoice.invoice_date,
        "due_date": Invoice.due_date,
        "total": Invoice.total,
        "created_at": Invoice.created_at,
    }
    return _page(session, stmt, params, sorts, "-created_at", Invoice.id.desc())


def payments_for_invoice(session: Session, invoice_id: int) -> Sequence[Payment]:
    stmt = select(Payment).where(Payment.invoice_id == invoice_id).order_by(Payment.id)
    return session.scalars(stmt).unique().all()


# ------------------------------------------------------------------ payments & refunds


def get_payment(session: Session, payment_id: int, *, lock: bool = False) -> Payment | None:
    if lock:
        stmt = select(Payment).where(Payment.id == payment_id).with_for_update(of=Payment)
        return session.scalars(stmt).unique().first()
    return session.get(Payment, payment_id)


def list_payments(
    session: Session,
    params: PageParams,
    *,
    method: str | None,
    kind: str | None,
    patient_id: int | None,
    invoice_id: int | None,
    date_from: date | None,
    date_to: date | None,
    search: str | None,
) -> tuple[Sequence[Payment], int]:
    stmt = select(Payment).join(Patient, Patient.id == Payment.patient_id)
    if method:
        stmt = stmt.where(Payment.method == method)
    if kind:
        stmt = stmt.where(Payment.kind == kind)
    if patient_id is not None:
        stmt = stmt.where(Payment.patient_id == patient_id)
    if invoice_id is not None:
        stmt = stmt.where(Payment.invoice_id == invoice_id)
    if date_from:
        stmt = stmt.where(Payment.received_on >= date_from)
    if date_to:
        stmt = stmt.where(Payment.received_on <= date_to)
    if search:
        like = f"%{search.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Payment.payment_number).like(like),
                func.lower(Patient.mrn).like(like),
                func.lower(Patient.first_name + " " + Patient.last_name).like(like),
            )
        )
    sorts = {
        "payment_number": Payment.payment_number,
        "received_on": Payment.received_on,
        "amount": Payment.amount,
        "created_at": Payment.created_at,
    }
    return _page(session, stmt, params, sorts, "-created_at", Payment.id.desc())


def deposit_balance(session: Session, patient_id: int) -> Decimal:
    """Unapplied deposits: deposits received (net of refunds) minus deposits applied to invoices
    (net of refunds of those applications, which return money to the deposit)."""
    received = select(func.coalesce(func.sum(Payment.amount - Payment.refunded_amount), 0)).where(
        Payment.patient_id == patient_id, Payment.kind == PaymentKind.DEPOSIT
    )
    applied = select(func.coalesce(func.sum(Payment.amount - Payment.refunded_amount), 0)).where(
        Payment.patient_id == patient_id,
        Payment.kind == PaymentKind.INVOICE,
        Payment.method == PaymentMethod.DEPOSIT,
    )
    return Decimal(session.scalar(received) or 0) - Decimal(session.scalar(applied) or 0)


def pending_refund_total(session: Session, payment_id: int) -> Decimal:
    stmt = select(func.coalesce(func.sum(Refund.amount), 0)).where(
        Refund.payment_id == payment_id, Refund.status == RefundStatus.PENDING_APPROVAL
    )
    return Decimal(session.scalar(stmt) or 0)


def get_refund(session: Session, refund_id: int, *, lock: bool = False) -> Refund | None:
    if lock:
        stmt = select(Refund).where(Refund.id == refund_id).with_for_update(of=Refund)
        return session.scalars(stmt).unique().first()
    return session.get(Refund, refund_id)


def list_refunds(
    session: Session, params: PageParams, *, status: str | None, payment_id: int | None
) -> tuple[Sequence[Refund], int]:
    stmt = select(Refund)
    if status:
        stmt = stmt.where(Refund.status == status)
    if payment_id is not None:
        stmt = stmt.where(Refund.payment_id == payment_id)
    sorts = {"created_at": Refund.created_at, "amount": Refund.amount}
    return _page(session, stmt, params, sorts, "-created_at", Refund.id.desc())


def refunds_for_payments(session: Session, payment_ids: Sequence[int]) -> Sequence[Refund]:
    if not payment_ids:
        return []
    stmt = select(Refund).where(Refund.payment_id.in_(payment_ids)).order_by(Refund.id)
    return session.scalars(stmt).unique().all()


# ------------------------------------------------------------------ idempotency


def get_idempotency_key(
    session: Session, scope: str, actor_key: str, key: str, *, lock: bool = True
) -> IdempotencyKey | None:
    stmt = select(IdempotencyKey).where(
        and_(
            IdempotencyKey.scope == scope,
            IdempotencyKey.actor_key == actor_key,
            IdempotencyKey.key == key,
        )
    )
    if lock:
        stmt = stmt.with_for_update()
    return session.scalars(stmt).first()


def has_active_claim(session: Session, invoice_id: int) -> bool:
    from app.models.insurance import ACTIVE_CLAIM_STATUSES, Claim

    stmt = select(func.count(Claim.id)).where(
        Claim.invoice_id == invoice_id, Claim.status.in_(ACTIVE_CLAIM_STATUSES)
    )
    return bool(session.scalar(stmt))
