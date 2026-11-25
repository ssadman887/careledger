"""Budget queries, including the SQL aggregates behind the variance report."""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from sqlalchemy import Integer, cast, extract, func, select
from sqlalchemy.orm import Session

from app.core.pagination import PageParams
from app.models.budgets import Budget, BudgetAlert, BudgetLine
from app.models.ledger import Account, EntryStatus, JournalEntry, JournalLine
from app.repositories.billing import _page


def get_budget(session: Session, budget_id: int, *, lock: bool = False) -> Budget | None:
    if lock:
        stmt = select(Budget).where(Budget.id == budget_id).with_for_update(of=Budget)
        return session.scalars(stmt).unique().first()
    return session.get(Budget, budget_id)


def budget_for(session: Session, year: int, department_id: int) -> Budget | None:
    stmt = select(Budget).where(Budget.year == year, Budget.department_id == department_id)
    return session.scalars(stmt).unique().first()


def list_budgets(
    session: Session, params: PageParams, *, year: int | None, status: str | None
) -> tuple[Sequence[Budget], int]:
    stmt = select(Budget)
    if year is not None:
        stmt = stmt.where(Budget.year == year)
    if status:
        stmt = stmt.where(Budget.status == status)
    sorts = {"year": Budget.year, "name": Budget.name}
    return _page(session, stmt, params, sorts, "-year", Budget.id)


def active_budgets(session: Session, year: int) -> Sequence[Budget]:
    stmt = select(Budget).where(Budget.year == year, Budget.status == "active").order_by(Budget.id)
    return session.scalars(stmt).unique().all()


def budget_by_account_month(session: Session, budget_id: int) -> dict[tuple[int, int], Decimal]:
    stmt = (
        select(BudgetLine.account_id, BudgetLine.month, func.sum(BudgetLine.amount))
        .where(BudgetLine.budget_id == budget_id)
        .group_by(BudgetLine.account_id, BudgetLine.month)
    )
    return {(a, m): amt for a, m, amt in session.execute(stmt).all()}


def actual_by_account_month(
    session: Session, *, department_id: int, start: date, end: date
) -> dict[tuple[int, int], tuple[str, Decimal, Decimal]]:
    """Posted debits and credits per (account, month) on revenue and expense accounts for one
    department (journal line dimension). Returns {(account_id, month): (type, debit, credit)}."""
    month = cast(extract("month", JournalEntry.entry_date), Integer)
    stmt = (
        select(
            JournalLine.account_id,
            month,
            Account.type,
            func.sum(JournalLine.debit),
            func.sum(JournalLine.credit),
        )
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .join(Account, Account.id == JournalLine.account_id)
        .where(JournalEntry.status == EntryStatus.POSTED)
        .where(JournalEntry.entry_date >= start, JournalEntry.entry_date <= end)
        .where(JournalLine.department_id == department_id)
        .where(Account.type.in_(("revenue", "expense")))
        .group_by(JournalLine.account_id, month, Account.type)
    )
    return {(a, m): (t, d, c) for a, m, t, d, c in session.execute(stmt).all()}


def alert_exists(session: Session, budget_id: int, account_id: int, month: int, level: str) -> bool:
    stmt = select(func.count(BudgetAlert.id)).where(
        BudgetAlert.budget_id == budget_id,
        BudgetAlert.account_id == account_id,
        BudgetAlert.month == month,
        BudgetAlert.level == level,
    )
    return bool(session.scalar(stmt))


def list_alerts(
    session: Session, params: PageParams, *, budget_id: int | None, year: int | None
) -> tuple[Sequence[BudgetAlert], int]:
    stmt = select(BudgetAlert)
    if budget_id is not None:
        stmt = stmt.where(BudgetAlert.budget_id == budget_id)
    if year is not None:
        stmt = stmt.join(Budget, Budget.id == BudgetAlert.budget_id).where(Budget.year == year)
    sorts = {"created_at": BudgetAlert.created_at}
    return _page(session, stmt, params, sorts, "-created_at", BudgetAlert.id.desc())
