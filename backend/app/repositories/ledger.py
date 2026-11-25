"""Ledger queries: accounts, periods, journal entries and report aggregates (SQL aggregates)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, Select, and_, exists, func, or_, select, text
from sqlalchemy.orm import Session

from app.core.pagination import PageParams
from app.models.ledger import (
    DEBIT_NORMAL,
    Account,
    EntryStatus,
    FiscalPeriod,
    JournalEntry,
    JournalLine,
    PeriodStatus,
)
from app.models.org import CostCenter, Department

ZERO = Decimal("0.00")

# ---------------------------------------------------------------- accounts


_ACCOUNT_SORTS = {"code": Account.code, "name": Account.name, "type": Account.type}


def get_account(session: Session, account_id: int) -> Account | None:
    return session.get(Account, account_id)


def get_account_by_code(session: Session, code: str) -> Account | None:
    return session.scalars(select(Account).where(Account.code == code)).first()


def accounts_by_ids(session: Session, ids: Sequence[int]) -> dict[int, Account]:
    rows = session.scalars(select(Account).where(Account.id.in_(set(ids)))).all()
    return {a.id: a for a in rows}


def list_accounts(
    session: Session,
    params: PageParams,
    *,
    type_: str | None,
    is_active: bool | None,
    postable_only: bool,
    search: str | None,
) -> tuple[Sequence[Account], int]:
    stmt = select(Account)
    if type_:
        stmt = stmt.where(Account.type == type_)
    if is_active is not None:
        stmt = stmt.where(Account.is_active.is_(is_active))
    if postable_only:
        stmt = stmt.where(Account.is_header.is_(False), Account.is_active.is_(True))
    if search:
        like = f"%{search.lower()}%"
        stmt = stmt.where(or_(Account.code.ilike(like), func.lower(Account.name).like(like)))
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    column = _ACCOUNT_SORTS.get((params.sort or "code").lstrip("-"), Account.code)
    order = column.desc() if (params.sort or "").startswith("-") else column.asc()
    rows = session.scalars(stmt.order_by(order).offset(params.offset).limit(params.page_size)).all()
    return rows, total


def has_children(session: Session, account_id: int) -> bool:
    return bool(session.scalar(select(exists().where(Account.parent_id == account_id))))


def has_postings(session: Session, account_id: int) -> bool:
    return bool(session.scalar(select(exists().where(JournalLine.account_id == account_id))))


def account_balance(session: Session, account_id: int) -> Decimal:
    stmt = (
        select(func.coalesce(func.sum(JournalLine.debit - JournalLine.credit), 0))
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .where(JournalLine.account_id == account_id, JournalEntry.status == EntryStatus.POSTED)
    )
    return Decimal(session.scalar(stmt) or 0)


# ---------------------------------------------------------------- org


def list_departments(session: Session) -> Sequence[Department]:
    return session.scalars(select(Department).order_by(Department.code)).all()


def list_cost_centers(session: Session) -> Sequence[CostCenter]:
    return session.scalars(select(CostCenter).order_by(CostCenter.code)).all()


def department_ids(session: Session, ids: set[int]) -> set[int]:
    return set(session.scalars(select(Department.id).where(Department.id.in_(ids))).all())


def cost_center_ids(session: Session, ids: set[int]) -> set[int]:
    return set(session.scalars(select(CostCenter.id).where(CostCenter.id.in_(ids))).all())


# ---------------------------------------------------------------- periods


def get_period(session: Session, period_id: int) -> FiscalPeriod | None:
    return session.get(FiscalPeriod, period_id)


def period_for_date(session: Session, on: date, *, lock: bool = False) -> FiscalPeriod | None:
    stmt = select(FiscalPeriod).where(FiscalPeriod.start_date <= on, FiscalPeriod.end_date >= on)
    if lock:
        stmt = stmt.with_for_update(read=True)
    return session.scalars(stmt).first()


def list_periods(session: Session) -> Sequence[FiscalPeriod]:
    return session.scalars(select(FiscalPeriod).order_by(FiscalPeriod.start_date.desc())).all()


def overlapping_period_exists(session: Session, start: date, end: date) -> bool:
    stmt = select(exists().where(FiscalPeriod.start_date <= end, FiscalPeriod.end_date >= start))
    return bool(session.scalar(stmt))


def open_periods_before(session: Session, start: date) -> Sequence[FiscalPeriod]:
    stmt = select(FiscalPeriod).where(
        FiscalPeriod.start_date < start, FiscalPeriod.status == PeriodStatus.OPEN
    )
    return session.scalars(stmt.order_by(FiscalPeriod.start_date)).all()


def count_entries(session: Session, start: date, end: date, status: str) -> int:
    stmt = select(func.count(JournalEntry.id)).where(
        JournalEntry.entry_date.between(start, end), JournalEntry.status == status
    )
    return session.scalar(stmt) or 0


# ---------------------------------------------------------------- journal entries


def next_entry_number(session: Session) -> str:
    value = session.scalar(text("SELECT nextval('journal_entry_number_seq')"))
    return f"JE-{int(value or 0):06d}"


def get_entry(session: Session, entry_id: int, *, lock: bool = False) -> JournalEntry | None:
    if lock:
        stmt = select(JournalEntry).where(JournalEntry.id == entry_id).with_for_update()
        return session.scalars(stmt).first()
    return session.get(JournalEntry, entry_id)


def reversal_of(session: Session, entry_ids: Sequence[int]) -> dict[int, int]:
    """Map original entry id -> id of the entry that reversed it."""
    if not entry_ids:
        return {}
    rows = session.execute(
        select(JournalEntry.reversal_of_id, JournalEntry.id).where(
            JournalEntry.reversal_of_id.in_(entry_ids)
        )
    ).all()
    return {int(orig): int(rev) for orig, rev in rows if orig is not None}


_ENTRY_SORTS: dict[str, Any] = {
    "entry_date": JournalEntry.entry_date,
    "entry_number": JournalEntry.entry_number,
    "total": JournalEntry.total,
    "created_at": JournalEntry.created_at,
}


def list_entries(
    session: Session,
    params: PageParams,
    *,
    status: str | None,
    source_type: str | None,
    date_from: date | None,
    date_to: date | None,
    account_id: int | None,
    search: str | None,
) -> tuple[Sequence[JournalEntry], int]:
    stmt: Select[tuple[JournalEntry]] = select(JournalEntry)
    if status:
        stmt = stmt.where(JournalEntry.status == status)
    if source_type:
        stmt = stmt.where(JournalEntry.source_type == source_type)
    if date_from:
        stmt = stmt.where(JournalEntry.entry_date >= date_from)
    if date_to:
        stmt = stmt.where(JournalEntry.entry_date <= date_to)
    if account_id is not None:
        stmt = stmt.where(
            exists().where(
                JournalLine.entry_id == JournalEntry.id, JournalLine.account_id == account_id
            )
        )
    if search:
        like = f"%{search.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(JournalEntry.entry_number).like(like),
                func.lower(JournalEntry.memo).like(like),
            )
        )
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    key = (params.sort or "-entry_number").lstrip("-")
    column = _ENTRY_SORTS.get(key, JournalEntry.entry_number)
    desc = (params.sort or "-entry_number").startswith("-")
    order = [column.desc() if desc else column.asc(), JournalEntry.id.desc()]
    rows = session.scalars(
        stmt.order_by(*order).offset(params.offset).limit(params.page_size)
    ).all()
    return rows, total


def entries_for_source(
    session: Session, source_type: str, source_id: str
) -> Sequence[JournalEntry]:
    stmt = select(JournalEntry).where(
        JournalEntry.source_type == source_type, JournalEntry.source_id == source_id
    )
    return session.scalars(stmt.order_by(JournalEntry.id)).all()


# ---------------------------------------------------------------- report aggregates


@dataclass(frozen=True)
class AccountTotals:
    account_id: int
    code: str
    name: str
    type: str
    debit: Decimal
    credit: Decimal

    @property
    def natural_balance(self) -> Decimal:
        """Balance in the account's normal direction (positive = normal)."""
        if self.type in DEBIT_NORMAL:
            return self.debit - self.credit
        return self.credit - self.debit


def account_totals(
    session: Session, *, date_from: date | None, date_to: date | None
) -> list[AccountTotals]:
    """Posted debit/credit totals per account within an optional date range."""
    conditions = [JournalEntry.status == EntryStatus.POSTED]
    if date_from:
        conditions.append(JournalEntry.entry_date >= date_from)
    if date_to:
        conditions.append(JournalEntry.entry_date <= date_to)
    stmt = (
        select(
            Account.id,
            Account.code,
            Account.name,
            Account.type,
            func.coalesce(func.sum(JournalLine.debit), 0),
            func.coalesce(func.sum(JournalLine.credit), 0),
        )
        .join(JournalLine, JournalLine.account_id == Account.id)
        .join(JournalEntry, and_(JournalEntry.id == JournalLine.entry_id, *conditions))
        .group_by(Account.id, Account.code, Account.name, Account.type)
        .order_by(Account.code)
    )
    return [
        AccountTotals(int(r[0]), r[1], r[2], r[3], Decimal(r[4]), Decimal(r[5]))
        for r in session.execute(stmt).all()
    ]


def ledger_sums(
    session: Session, *, date_from: date | None, date_to: date | None
) -> tuple[Decimal, Decimal]:
    conditions = [JournalEntry.status == EntryStatus.POSTED]
    if date_from:
        conditions.append(JournalEntry.entry_date >= date_from)
    if date_to:
        conditions.append(JournalEntry.entry_date <= date_to)
    stmt = select(
        func.coalesce(func.sum(JournalLine.debit), 0),
        func.coalesce(func.sum(JournalLine.credit), 0),
    ).join(JournalEntry, and_(JournalEntry.id == JournalLine.entry_id, *conditions))
    row = session.execute(stmt).one()
    return Decimal(row[0]), Decimal(row[1])


@dataclass(frozen=True)
class LedgerRow:
    entry_id: int
    entry_number: str
    entry_date: date
    memo: str
    source_type: str
    line_description: str
    debit: Decimal
    credit: Decimal
    running_balance: Decimal


def _signed(account: Account) -> ColumnElement[Decimal]:
    if account.type in DEBIT_NORMAL:
        return JournalLine.debit - JournalLine.credit
    return JournalLine.credit - JournalLine.debit


def account_opening_balance(session: Session, account: Account, before: date | None) -> Decimal:
    if before is None:
        return ZERO
    stmt = (
        select(func.coalesce(func.sum(_signed(account)), 0))
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .where(
            JournalLine.account_id == account.id,
            JournalEntry.status == EntryStatus.POSTED,
            JournalEntry.entry_date < before,
        )
    )
    return Decimal(session.scalar(stmt) or 0)


def account_ledger(
    session: Session,
    account: Account,
    *,
    date_from: date | None,
    date_to: date | None,
    opening: Decimal,
    params: PageParams,
) -> tuple[list[LedgerRow], int, Decimal]:
    """Lines in range with a running balance computed by a window function.

    Returns (page rows, total line count, period movement).
    """
    signed = _signed(account)
    conditions = [
        JournalLine.account_id == account.id,
        JournalEntry.status == EntryStatus.POSTED,
    ]
    if date_from:
        conditions.append(JournalEntry.entry_date >= date_from)
    if date_to:
        conditions.append(JournalEntry.entry_date <= date_to)
    ordering = (JournalEntry.entry_date, JournalEntry.id, JournalLine.line_no)
    inner = (
        select(
            JournalEntry.id.label("entry_id"),
            JournalEntry.entry_number,
            JournalEntry.entry_date,
            JournalEntry.memo,
            JournalEntry.source_type,
            JournalLine.description.label("line_description"),
            JournalLine.debit,
            JournalLine.credit,
            (func.sum(signed).over(order_by=ordering) + opening).label("running_balance"),
            func.row_number().over(order_by=ordering).label("rn"),
        )
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .where(*conditions)
        .subquery()
    )
    totals = session.execute(
        select(func.count(), func.coalesce(func.sum(signed), 0))
        .select_from(JournalLine)
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .where(*conditions)
    ).one()
    rows = session.execute(
        select(inner).order_by(inner.c.rn).offset(params.offset).limit(params.page_size)
    ).all()
    items = [
        LedgerRow(
            entry_id=int(r.entry_id),
            entry_number=r.entry_number,
            entry_date=r.entry_date,
            memo=r.memo,
            source_type=r.source_type,
            line_description=r.line_description,
            debit=Decimal(r.debit),
            credit=Decimal(r.credit),
            running_balance=Decimal(r.running_balance),
        )
        for r in rows
    ]
    return items, int(totals[0]), Decimal(totals[1])
