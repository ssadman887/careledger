"""Financial statements built from SQL aggregates of posted journal lines."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.errors import ValidationFailed
from app.core.pagination import PageParams
from app.models.ledger import AccountType
from app.repositories import ledger as repo
from app.repositories.ledger import AccountTotals, LedgerRow
from app.services.accounts import get_account

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class TrialBalanceRow:
    account_id: int
    code: str
    name: str
    type: str
    debit: Decimal  # period debit total
    credit: Decimal  # period credit total
    balance_debit: Decimal  # net balance shown on its natural side
    balance_credit: Decimal


@dataclass(frozen=True)
class TrialBalance:
    date_from: date | None
    date_to: date | None
    rows: list[TrialBalanceRow]
    total_debit: Decimal
    total_credit: Decimal
    total_balance_debit: Decimal
    total_balance_credit: Decimal
    balanced: bool


@dataclass(frozen=True)
class StatementLine:
    account_id: int
    code: str
    name: str
    amount: Decimal


@dataclass(frozen=True)
class StatementSection:
    title: str
    lines: list[StatementLine]
    total: Decimal


@dataclass(frozen=True)
class IncomeStatement:
    date_from: date | None
    date_to: date | None
    revenue: StatementSection
    expenses: StatementSection
    net_income: Decimal


@dataclass(frozen=True)
class BalanceSheet:
    as_of: date
    assets: StatementSection
    liabilities: StatementSection
    equity: StatementSection
    total_assets: Decimal
    total_liabilities_and_equity: Decimal
    balanced: bool


@dataclass(frozen=True)
class AccountLedger:
    account_id: int
    code: str
    name: str
    normal_balance: str
    date_from: date | None
    date_to: date | None
    opening_balance: Decimal
    closing_balance: Decimal
    rows: list[LedgerRow]
    total: int
    page: int
    page_size: int


def _check_range(date_from: date | None, date_to: date | None) -> None:
    if date_from and date_to and date_to < date_from:
        raise ValidationFailed("date_to must be on or after date_from", code="invalid_range")


def trial_balance(session: Session, date_from: date | None, date_to: date | None) -> TrialBalance:
    _check_range(date_from, date_to)
    rows: list[TrialBalanceRow] = []
    for t in repo.account_totals(session, date_from=date_from, date_to=date_to):
        net = t.debit - t.credit
        rows.append(
            TrialBalanceRow(
                account_id=t.account_id,
                code=t.code,
                name=t.name,
                type=t.type,
                debit=t.debit,
                credit=t.credit,
                balance_debit=net if net > 0 else ZERO,
                balance_credit=-net if net < 0 else ZERO,
            )
        )
    td = sum((r.debit for r in rows), ZERO)
    tc = sum((r.credit for r in rows), ZERO)
    bd = sum((r.balance_debit for r in rows), ZERO)
    bc = sum((r.balance_credit for r in rows), ZERO)
    return TrialBalance(date_from, date_to, rows, td, tc, bd, bc, td == tc and bd == bc)


def _section(title: str, totals: list[AccountTotals]) -> StatementSection:
    lines = [
        StatementLine(t.account_id, t.code, t.name, t.natural_balance)
        for t in totals
        if t.natural_balance != 0
    ]
    return StatementSection(title, lines, sum((ln.amount for ln in lines), ZERO))


def income_statement(
    session: Session, date_from: date | None, date_to: date | None
) -> IncomeStatement:
    _check_range(date_from, date_to)
    totals = repo.account_totals(session, date_from=date_from, date_to=date_to)
    revenue = _section("Revenue", [t for t in totals if t.type == AccountType.REVENUE])
    expenses = _section("Expenses", [t for t in totals if t.type == AccountType.EXPENSE])
    return IncomeStatement(date_from, date_to, revenue, expenses, revenue.total - expenses.total)


def balance_sheet(session: Session, as_of: date) -> BalanceSheet:
    totals = repo.account_totals(session, date_from=None, date_to=as_of)
    assets = _section("Assets", [t for t in totals if t.type == AccountType.ASSET])
    liabilities = _section("Liabilities", [t for t in totals if t.type == AccountType.LIABILITY])
    equity_accounts = _section("Equity", [t for t in totals if t.type == AccountType.EQUITY])
    revenue = sum((t.natural_balance for t in totals if t.type == AccountType.REVENUE), ZERO)
    expense = sum((t.natural_balance for t in totals if t.type == AccountType.EXPENSE), ZERO)
    earnings = revenue - expense
    # Revenue/expense are not closed to retained earnings by entries (see DECISIONS.md);
    # cumulative earnings are presented as a computed equity line.
    equity_lines = [*equity_accounts.lines]
    if earnings != 0:
        equity_lines.append(StatementLine(0, "—", "Retained earnings (computed)", earnings))
    equity = StatementSection("Equity", equity_lines, equity_accounts.total + earnings)
    total_le = liabilities.total + equity.total
    return BalanceSheet(
        as_of, assets, liabilities, equity, assets.total, total_le, assets.total == total_le
    )


def account_ledger(
    session: Session,
    account_id: int,
    date_from: date | None,
    date_to: date | None,
    params: PageParams,
) -> AccountLedger:
    _check_range(date_from, date_to)
    account = get_account(session, account_id)
    opening = repo.account_opening_balance(session, account, date_from)
    rows, total, movement = repo.account_ledger(
        session, account, date_from=date_from, date_to=date_to, opening=opening, params=params
    )
    return AccountLedger(
        account_id=account.id,
        code=account.code,
        name=account.name,
        normal_balance=account.normal_balance,
        date_from=date_from,
        date_to=date_to,
        opening_balance=opening,
        closing_balance=opening + movement,
        rows=rows,
        total=total,
        page=params.page,
        page_size=params.page_size,
    )
