"""Budgets per department and account, variance report and alerts (finance owns budgets)."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status

from app.core.deps import DbSession, read_roles, require_roles
from app.core.errors import ErrorEnvelope
from app.core.pagination import Page, PageParams, page_params
from app.models.budgets import AlertLevel, Budget, BudgetAlert, BudgetStatus
from app.models.identity import RoleName
from app.repositories import budgets as repo
from app.schemas.phase5 import (
    BudgetAlertOut,
    BudgetCheckIn,
    BudgetCheckOut,
    BudgetCreate,
    BudgetLineIn,
    BudgetOut,
    BudgetStatusIn,
    BudgetUpdate,
    VarianceOut,
    VarianceRowOut,
    VarianceTotals,
)
from app.services import budgets
from app.services.audit import Actor
from app.services.budgets import LineSpec, VarianceRow

router = APIRouter(
    prefix="/budgets",
    tags=["budgets"],
    responses={
        401: {"model": ErrorEnvelope},
        403: {"model": ErrorEnvelope},
        404: {"model": ErrorEnvelope},
        409: {"model": ErrorEnvelope},
        422: {"model": ErrorEnvelope},
    },
)

R = RoleName
BudgetRead = Annotated[Actor, Depends(read_roles(R.ACCOUNTANT, R.FINANCE_MANAGER))]
BudgetWrite = Annotated[Actor, Depends(require_roles(R.FINANCE_MANAGER))]
ZERO = Decimal("0.00")
RowStatus = Literal["ok", "warning", "exceeded", "unbudgeted"]


def _specs(lines: list[BudgetLineIn]) -> list[LineSpec]:
    return [LineSpec(ln.account_id, ln.annual, ln.monthly) for ln in lines]


def budget_out(b: Budget) -> BudgetOut:
    return BudgetOut(
        id=b.id,
        year=b.year,
        department_id=b.department_id,
        department_name=b.department.name,
        name=b.name,
        status=BudgetStatus(b.status),
        alert_threshold_percent=b.alert_threshold_percent,
        notes=b.notes,
        annual_total=sum((ln.amount for ln in b.lines), ZERO),
        accounts=len({ln.account_id for ln in b.lines}),
        created_at=b.created_at,
    )


def alert_out(a: BudgetAlert) -> BudgetAlertOut:
    return BudgetAlertOut(
        id=a.id,
        budget_id=a.budget_id,
        budget_name=a.budget.name,
        department_name=a.budget.department.name,
        account_id=a.account_id,
        account_code=a.account.code,
        account_name=a.account.name,
        month=a.month,
        level=AlertLevel(a.level),
        budget_ytd=a.budget_ytd,
        actual_ytd=a.actual_ytd,
        percent_used=a.percent_used,
        message=a.message,
        created_at=a.created_at,
    )


def _row_status(r: VarianceRow, through: int, threshold: Decimal) -> RowStatus:
    planned, actual = r.budget_ytd(through), r.actual_ytd(through)
    if r.annual_budget == 0:
        return "unbudgeted"
    if not r.is_expense:
        return "ok"
    if actual > planned:
        return "exceeded"
    used = budgets.percent(actual, planned)
    return "warning" if used is not None and used >= threshold else "ok"


def _totals(rows: list[VarianceRow], through: int) -> VarianceTotals:
    return VarianceTotals(
        budget_ytd=sum((r.budget_ytd(through) for r in rows), ZERO),
        actual_ytd=sum((r.actual_ytd(through) for r in rows), ZERO),
        variance_ytd=sum((r.variance_ytd(through) for r in rows), ZERO),
        annual_budget=sum((r.annual_budget for r in rows), ZERO),
    )


@router.get("", response_model=Page[BudgetOut])
def list_budgets(
    _: BudgetRead,
    db: DbSession,
    params: Annotated[PageParams, Depends(page_params)],
    year: int | None = None,
    status: BudgetStatus | None = None,
) -> Page[BudgetOut]:
    rows, total = repo.list_budgets(db, params, year=year, status=status.value if status else None)
    return Page(
        items=[budget_out(b) for b in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.post("", response_model=BudgetOut, status_code=status.HTTP_201_CREATED)
def create_budget(body: BudgetCreate, actor: BudgetWrite, db: DbSession) -> BudgetOut:
    budget = budgets.create_budget(
        db,
        actor,
        year=body.year,
        department_id=body.department_id,
        name=body.name,
        alert_threshold_percent=body.alert_threshold_percent,
        lines=_specs(body.lines),
        notes=body.notes,
    )
    return budget_out(budget)


@router.get("/alerts", response_model=Page[BudgetAlertOut])
def list_alerts(
    _: BudgetRead,
    db: DbSession,
    params: Annotated[PageParams, Depends(page_params)],
    budget_id: int | None = None,
    year: int | None = None,
) -> Page[BudgetAlertOut]:
    rows, total = repo.list_alerts(db, params, budget_id=budget_id, year=year)
    return Page(
        items=[alert_out(a) for a in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.post("/alerts/check", response_model=BudgetCheckOut)
def check_alerts(body: BudgetCheckIn, actor: BudgetWrite, db: DbSession) -> BudgetCheckOut:
    """Run the alert check now (the same job runs daily)."""
    created = budgets.check_alerts(db, actor, as_of=body.as_of or datetime.now(UTC).date())
    return BudgetCheckOut(created=len(created), alerts=[alert_out(a) for a in created])


@router.get("/{budget_id}", response_model=BudgetOut)
def get_budget(budget_id: int, _: BudgetRead, db: DbSession) -> BudgetOut:
    return budget_out(budgets.get_budget(db, budget_id))


@router.patch("/{budget_id}", response_model=BudgetOut)
def update_budget(
    budget_id: int, body: BudgetUpdate, actor: BudgetWrite, db: DbSession
) -> BudgetOut:
    budget = budgets.update_budget(
        db,
        actor,
        budget_id,
        name=body.name,
        alert_threshold_percent=body.alert_threshold_percent,
        notes=body.notes,
        lines=_specs(body.lines) if body.lines is not None else None,
    )
    return budget_out(budget)


@router.post("/{budget_id}/status", response_model=BudgetOut)
def set_status(
    budget_id: int, body: BudgetStatusIn, actor: BudgetWrite, db: DbSession
) -> BudgetOut:
    return budget_out(budgets.set_status(db, actor, budget_id, body.status))


@router.get("/{budget_id}/variance", response_model=VarianceOut)
def variance(
    budget_id: int,
    _: BudgetRead,
    db: DbSession,
    through_month: Annotated[int | None, Query(ge=1, le=12)] = None,
) -> VarianceOut:
    """Budget vs actual per account (ledger lines with the department dimension).
    `through_month` defaults to the last complete month for the current year (the current
    month is still being posted), else 12."""
    budget = budgets.get_budget(db, budget_id)
    if through_month is None:
        today = datetime.now(UTC).date()
        through_month = max(today.month - 1, 1) if budget.year == today.year else 12
    report = budgets.variance(db, budget_id, through_month=through_month)
    t = report.through_month
    rows = [
        VarianceRowOut(
            account_id=r.account.id,
            account_code=r.account.code,
            account_name=r.account.name,
            account_type="expense" if r.is_expense else "revenue",
            budgeted=r.annual_budget > 0,
            monthly_budget=r.budget,
            monthly_actual=r.actual,
            annual_budget=r.annual_budget,
            budget_ytd=r.budget_ytd(t),
            actual_ytd=r.actual_ytd(t),
            variance_ytd=r.variance_ytd(t),
            percent_used=budgets.percent(r.actual_ytd(t), r.budget_ytd(t)),
            status=_row_status(r, t, budget.alert_threshold_percent),
        )
        for r in report.rows
    ]
    return VarianceOut(
        budget=budget_out(budget),
        through_month=t,
        rows=rows,
        expense_totals=_totals([r for r in report.rows if r.is_expense], t),
        revenue_totals=_totals([r for r in report.rows if not r.is_expense], t),
    )
