"""AR queries: aging (SQL aggregates), dunning candidates, write-offs, notices."""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, Date, Label, case, cast, func, literal, select
from sqlalchemy.orm import Session

from app.core.pagination import PageParams
from app.models.ar import DunningNotice, WriteOff
from app.models.billing import Invoice
from app.models.insurance import Claim, Insurer
from app.models.patients import Patient
from app.repositories.billing import _page

OPEN_INVOICE = ("issued", "partially_paid")
INSURER_EXPOSED = (
    "submitted",
    "under_review",
    "approved",
    "partially_approved",
    "denied",
    "appealed",
)

# (label, lower bound in days, upper bound in days or None). Boundaries are inclusive.
BUCKETS: tuple[tuple[str, int, int | None], ...] = (
    ("0-30", 0, 30),
    ("31-60", 31, 60),
    ("61-90", 61, 90),
    ("90+", 91, None),
)


def _bucket_sums(age: ColumnElement[Any], amount: ColumnElement[Any]) -> list[Label[Any]]:
    cols: list[Label[Any]] = []
    for label, low, high in BUCKETS:
        cond = age >= low if high is None else age.between(low, high)
        cols.append(func.coalesce(func.sum(case((cond, amount), else_=0)), 0).label(label))
    return cols


def patient_due_expr() -> ColumnElement[Decimal]:
    return Invoice.total - Invoice.amount_paid - Invoice.adjusted_amount - Invoice.insurance_pending


def aging_by_patient(session: Session, as_of: date) -> list[tuple[int, str, str, list[Decimal]]]:
    due = patient_due_expr()
    age = literal(as_of, Date) - Invoice.invoice_date
    stmt = (
        select(
            Patient.id,
            Patient.first_name + " " + Patient.last_name,
            Patient.mrn,
            *_bucket_sums(age, due),
        )
        .join(Patient, Patient.id == Invoice.patient_id)
        .where(Invoice.status.in_(OPEN_INVOICE), Invoice.invoice_date <= as_of, due > 0)
        .group_by(Patient.id, Patient.first_name, Patient.last_name, Patient.mrn)
        .order_by(func.sum(due).desc())
    )
    return [
        (int(r[0]), r[1], r[2], [Decimal(v) for v in r[3:]]) for r in session.execute(stmt).all()
    ]


def aging_by_insurer(session: Session, as_of: date) -> list[tuple[int, str, str, list[Decimal]]]:
    exposure = Claim.insurer_amount - Claim.paid_amount - Claim.adjustment_amount
    since = func.coalesce(cast(Claim.submitted_at, Date), Claim.service_date)
    age = literal(as_of, Date) - since
    stmt = (
        select(Insurer.id, Insurer.name, Insurer.code, *_bucket_sums(age, exposure))
        .join(Insurer, Insurer.id == Claim.insurer_id)
        .where(Claim.status.in_(INSURER_EXPOSED), since <= as_of, exposure > 0)
        .group_by(Insurer.id, Insurer.name, Insurer.code)
        .order_by(func.sum(exposure).desc())
    )
    return [
        (int(r[0]), r[1], r[2], [Decimal(v) for v in r[3:]]) for r in session.execute(stmt).all()
    ]


def dunning_candidates(session: Session, as_of: date) -> Sequence[Invoice]:
    due = patient_due_expr()
    stmt = (
        select(Invoice)
        .where(Invoice.status.in_(OPEN_INVOICE), Invoice.due_date < as_of, due > 0)
        .order_by(Invoice.due_date, Invoice.id)
    )
    return session.scalars(stmt).unique().all()


def notice_levels(session: Session, invoice_id: int) -> set[int]:
    stmt = select(DunningNotice.level).where(DunningNotice.invoice_id == invoice_id)
    return set(session.scalars(stmt).all())


def list_notices(
    session: Session, params: PageParams, *, patient_id: int | None, level: int | None
) -> tuple[Sequence[DunningNotice], int]:
    stmt = select(DunningNotice)
    if patient_id is not None:
        stmt = stmt.where(DunningNotice.patient_id == patient_id)
    if level is not None:
        stmt = stmt.where(DunningNotice.level == level)
    sorts = {"sent_at": DunningNotice.sent_at, "days_overdue": DunningNotice.days_overdue}
    return _page(session, stmt, params, sorts, "-sent_at", DunningNotice.id.desc())


def get_write_off(session: Session, write_off_id: int, *, lock: bool = False) -> WriteOff | None:
    if lock:
        stmt = select(WriteOff).where(WriteOff.id == write_off_id).with_for_update(of=WriteOff)
        return session.scalars(stmt).unique().first()
    return session.get(WriteOff, write_off_id)


def pending_write_off_total(session: Session, invoice_id: int) -> Decimal:
    stmt = select(func.coalesce(func.sum(WriteOff.amount), 0)).where(
        WriteOff.invoice_id == invoice_id, WriteOff.status == "pending_approval"
    )
    return Decimal(session.scalar(stmt) or 0)


def list_write_offs(
    session: Session, params: PageParams, *, status: str | None, invoice_id: int | None
) -> tuple[Sequence[WriteOff], int]:
    stmt = select(WriteOff)
    if status:
        stmt = stmt.where(WriteOff.status == status)
    if invoice_id is not None:
        stmt = stmt.where(WriteOff.invoice_id == invoice_id)
    sorts = {"created_at": WriteOff.created_at, "amount": WriteOff.amount}
    return _page(session, stmt, params, sorts, "-created_at", WriteOff.id.desc())
