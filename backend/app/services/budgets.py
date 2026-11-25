"""Budgets per department and account, variance against the ledger, and threshold alerts.

* A budget belongs to one department and year and holds monthly amounts per account
  (expense or revenue). An annual amount is split evenly across months, rounded down to the
  cent, with the remainder in December, so the months always add up to the annual figure.
* Actuals come from posted journal lines carrying that department dimension (SQL aggregates).
  Expense actual = debits - credits; revenue actual = credits - debits. Reversals net out.
* Variance is signed so that positive is favourable: budget - actual for expenses,
  actual - budget for revenue. Percent used = actual / budget x 100 (2 dp, half-up).
* Alerts (job `careledger.budget_check`): for active budgets, year-to-date through a month,
  per expense account: `exceeded` when actual > budget, else `warning` when percent used >=
  the budget's threshold (default 90%). Raised once per budget, account, month and level.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation, Conflict, NotFound, ValidationFailed
from app.core.money import CENT, quantize
from app.models.budgets import AlertLevel, Budget, BudgetAlert, BudgetLine, BudgetStatus
from app.models.ledger import Account, AccountType
from app.models.org import Department
from app.repositories import budgets as repo
from app.repositories import ledger as ledger_repo
from app.services import audit, notifications
from app.services.audit import Actor

ZERO = Decimal("0.00")
MONTHS = range(1, 13)


@dataclass(frozen=True)
class LineSpec:
    """Either `annual` (split evenly) or exactly 12 `monthly` amounts."""

    account_id: int
    annual: Decimal | None = None
    monthly: Sequence[Decimal] | None = None


def split_annual(annual: Decimal) -> list[Decimal]:
    """12 monthly amounts summing exactly to `annual`; remainder cents go to December."""
    if annual < 0 or quantize(annual) != annual:
        raise ValidationFailed("Annual amount must be a non-negative amount", code="invalid_amount")
    base = (annual / 12).quantize(CENT, rounding=ROUND_DOWN)
    return [base] * 11 + [annual - base * 11]


def percent(actual: Decimal, budget: Decimal) -> Decimal | None:
    if budget <= 0:
        return None
    return (actual * 100 / budget).quantize(CENT, rounding=ROUND_HALF_UP)


def _monthly(spec: LineSpec) -> list[Decimal]:
    if (spec.annual is None) == (spec.monthly is None):
        raise ValidationFailed(
            "Give either an annual amount or 12 monthly amounts", code="invalid_line"
        )
    if spec.annual is not None:
        return split_annual(spec.annual)
    assert spec.monthly is not None
    months = list(spec.monthly)
    if len(months) != 12 or any(m < 0 or quantize(m) != m for m in months):
        raise ValidationFailed(
            "Monthly amounts must be 12 non-negative amounts", code="invalid_line"
        )
    return months


def _check_account(session: Session, account_id: int) -> Account:
    account = ledger_repo.get_account(session, account_id)
    if account is None or account.is_header or not account.is_active:
        raise ValidationFailed(
            "Budget accounts must be active postable accounts", code="invalid_account"
        )
    if account.type not in (AccountType.EXPENSE, AccountType.REVENUE):
        raise ValidationFailed("Budget expense or revenue accounts only", code="invalid_account")
    return account


def _build_lines(session: Session, specs: Sequence[LineSpec]) -> list[BudgetLine]:
    if not specs:
        raise ValidationFailed("A budget needs at least one account", code="no_lines")
    seen: set[int] = set()
    lines: list[BudgetLine] = []
    for spec in specs:
        if spec.account_id in seen:
            raise ValidationFailed("Each account can appear once", code="duplicate_account")
        seen.add(spec.account_id)
        _check_account(session, spec.account_id)
        lines += [
            BudgetLine(account_id=spec.account_id, month=m, amount=amt)
            for m, amt in zip(MONTHS, _monthly(spec), strict=True)
        ]
    return lines


def get_budget(session: Session, budget_id: int, *, lock: bool = False) -> Budget:
    budget = repo.get_budget(session, budget_id, lock=lock)
    if budget is None:
        raise NotFound("Budget not found")
    return budget


def _check_threshold(value: Decimal) -> None:
    if not (0 < value <= 100) or quantize(value) != value:
        raise ValidationFailed(
            "Alert threshold must be between 0.01 and 100", code="invalid_threshold"
        )


def create_budget(
    session: Session,
    actor: Actor,
    *,
    year: int,
    department_id: int,
    name: str,
    alert_threshold_percent: Decimal,
    lines: Sequence[LineSpec],
    notes: str = "",
) -> Budget:
    if not 2000 <= year <= 2100:
        raise ValidationFailed("Invalid year", code="invalid_year")
    dept = session.get(Department, department_id)
    if dept is None or not dept.is_active:
        raise ValidationFailed("Department must exist and be active", code="invalid_department")
    _check_threshold(alert_threshold_percent)
    if repo.budget_for(session, year, department_id) is not None:
        raise Conflict(f"{dept.name} already has a {year} budget", code="budget_exists")
    budget = Budget(
        year=year,
        department_id=department_id,
        name=name.strip() or f"{dept.name} {year}",
        status=BudgetStatus.DRAFT,
        alert_threshold_percent=quantize(alert_threshold_percent),
        notes=notes,
        created_by_id=actor.id,
        lines=_build_lines(session, lines),
    )
    session.add(budget)
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="budget",
        entity_id=budget.id,
        action="create",
        after=_snapshot(budget),
    )
    return budget


def _snapshot(budget: Budget) -> dict[str, object]:
    annual: dict[int, Decimal] = {}
    for ln in budget.lines:
        annual[ln.account_id] = annual.get(ln.account_id, ZERO) + ln.amount
    return audit.snapshot(
        budget, extra={"annual_by_account": {str(k): v for k, v in annual.items()}}
    )


def update_budget(
    session: Session,
    actor: Actor,
    budget_id: int,
    *,
    name: str | None,
    alert_threshold_percent: Decimal | None,
    notes: str | None,
    lines: Sequence[LineSpec] | None,
) -> Budget:
    """Lines can change while the budget is a draft; name/threshold/notes until archived."""
    budget = get_budget(session, budget_id, lock=True)
    if budget.status == BudgetStatus.ARCHIVED:
        raise Conflict("Archived budgets cannot be changed", code="archived")
    before = _snapshot(budget)
    if lines is not None:
        if budget.status != BudgetStatus.DRAFT:
            raise BusinessRuleViolation(
                "Amounts of an active budget are locked; archive it and create a revision",
                code="budget_locked",
            )
        budget.lines.clear()
        session.flush()
        budget.lines.extend(_build_lines(session, lines))
    if alert_threshold_percent is not None:
        _check_threshold(alert_threshold_percent)
        budget.alert_threshold_percent = quantize(alert_threshold_percent)
    if name is not None and name.strip():
        budget.name = name.strip()
    if notes is not None:
        budget.notes = notes
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="budget",
        entity_id=budget.id,
        action="update",
        before=before,
        after=_snapshot(budget),
    )
    return budget


TRANSITIONS = {
    BudgetStatus.DRAFT: {BudgetStatus.ACTIVE},
    BudgetStatus.ACTIVE: {BudgetStatus.ARCHIVED},
    BudgetStatus.ARCHIVED: set(),
}


def set_status(session: Session, actor: Actor, budget_id: int, status: str) -> Budget:
    budget = get_budget(session, budget_id, lock=True)
    if status not in TRANSITIONS.get(BudgetStatus(budget.status), set()):
        raise Conflict(
            f"Cannot move a {budget.status} budget to {status}", code="invalid_transition"
        )
    before = audit.snapshot(budget)
    budget.status = status
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="budget",
        entity_id=budget.id,
        action="status_change",
        before=before,
        after=audit.snapshot(budget),
    )
    return budget


# --------------------------------------------------------------------------- variance


@dataclass
class VarianceRow:
    account: Account
    budget: list[Decimal] = field(default_factory=lambda: [ZERO] * 12)
    actual: list[Decimal] = field(default_factory=lambda: [ZERO] * 12)

    @property
    def is_expense(self) -> bool:
        return self.account.type == AccountType.EXPENSE

    def budget_ytd(self, through: int) -> Decimal:
        return sum(self.budget[:through], ZERO)

    def actual_ytd(self, through: int) -> Decimal:
        return sum(self.actual[:through], ZERO)

    def variance_ytd(self, through: int) -> Decimal:
        diff = self.budget_ytd(through) - self.actual_ytd(through)
        return diff if self.is_expense else -diff

    @property
    def annual_budget(self) -> Decimal:
        return sum(self.budget, ZERO)


@dataclass
class VarianceReport:
    budget: Budget
    through_month: int
    rows: list[VarianceRow]


def variance(session: Session, budget_id: int, *, through_month: int | None) -> VarianceReport:
    budget = get_budget(session, budget_id)
    through = through_month or 12
    if not 1 <= through <= 12:
        raise ValidationFailed("through_month must be 1-12", code="invalid_month")
    planned = repo.budget_by_account_month(session, budget.id)
    actuals = repo.actual_by_account_month(
        session,
        department_id=budget.department_id,
        start=date(budget.year, 1, 1),
        end=date(budget.year, 12, 31),
    )
    rows: dict[int, VarianceRow] = {}

    def row(account_id: int) -> VarianceRow:
        if account_id not in rows:
            account = ledger_repo.get_account(session, account_id)
            assert account is not None
            rows[account_id] = VarianceRow(account)
        return rows[account_id]

    for (account_id, month), amount in planned.items():
        row(account_id).budget[month - 1] = amount
    for (account_id, month), (acct_type, debit, credit) in actuals.items():
        net = debit - credit if acct_type == AccountType.EXPENSE else credit - debit
        row(account_id).actual[month - 1] = net
    ordered = sorted(rows.values(), key=lambda r: (not r.is_expense, r.account.code))
    return VarianceReport(budget=budget, through_month=through, rows=ordered)


# --------------------------------------------------------------------------- alerts


def check_alerts(session: Session, actor: Actor, *, as_of: date) -> list[BudgetAlert]:
    """Raise warning/exceeded alerts for active budgets of as_of's year, YTD through its month."""
    created: list[BudgetAlert] = []
    month = as_of.month
    for budget in repo.active_budgets(session, as_of.year):
        report = variance(session, budget.id, through_month=month)
        for r in report.rows:
            if not r.is_expense:
                continue
            planned, actual = r.budget_ytd(month), r.actual_ytd(month)
            used = percent(actual, planned)
            if used is None:
                continue
            if actual > planned:
                level = AlertLevel.EXCEEDED
            elif used >= budget.alert_threshold_percent:
                level = AlertLevel.WARNING
            else:
                continue
            if repo.alert_exists(session, budget.id, r.account.id, month, level):
                continue
            verb = "exceeded" if level == AlertLevel.EXCEEDED else "reached"
            alert = BudgetAlert(
                budget_id=budget.id,
                account_id=r.account.id,
                month=month,
                level=level,
                budget_ytd=planned,
                actual_ytd=actual,
                percent_used=used,
                message=(
                    f"{budget.department.name}: {r.account.code} {r.account.name} {verb} "
                    f"{used}% of the year-to-date budget through month {month} "
                    f"({actual:.2f} of {planned:.2f})"
                )[:300],
            )
            session.add(alert)
            session.flush()
            audit.record(
                session,
                actor,
                entity_type="budget_alert",
                entity_id=alert.id,
                action="create",
                after=audit.snapshot(alert),
            )
            created.append(alert)
            notifications.notify_role(
                session,
                "finance_manager",
                kind="budget_alert",
                level="warning",
                title=f"Budget {level}: {budget.department.name} {r.account.code}",
                body=alert.message,
                link=f"/budgets/{budget.id}",
            )
    return created
