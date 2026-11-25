from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.deps import DbSession, read_roles
from app.core.errors import ErrorEnvelope
from app.core.pagination import PageParams, page_params
from app.models.identity import RoleName
from app.schemas.ledger import (
    AccountLedgerOut,
    BalanceSheetOut,
    IncomeStatementOut,
    TrialBalanceOut,
)
from app.services import reports
from app.services.audit import Actor

router = APIRouter(
    prefix="/reports",
    tags=["reports"],
    responses={
        401: {"model": ErrorEnvelope},
        403: {"model": ErrorEnvelope},
        422: {"model": ErrorEnvelope},
    },
)

ReportRead = Annotated[Actor, Depends(read_roles(RoleName.ACCOUNTANT, RoleName.FINANCE_MANAGER))]


@router.get("/trial-balance", response_model=TrialBalanceOut)
def trial_balance(
    _: ReportRead, db: DbSession, date_from: date | None = None, date_to: date | None = None
) -> TrialBalanceOut:
    return TrialBalanceOut.model_validate(reports.trial_balance(db, date_from, date_to))


@router.get("/income-statement", response_model=IncomeStatementOut)
def income_statement(
    _: ReportRead, db: DbSession, date_from: date | None = None, date_to: date | None = None
) -> IncomeStatementOut:
    return IncomeStatementOut.model_validate(reports.income_statement(db, date_from, date_to))


@router.get("/balance-sheet", response_model=BalanceSheetOut)
def balance_sheet(_: ReportRead, db: DbSession, as_of: date | None = None) -> BalanceSheetOut:
    as_of_date = as_of or datetime.now(UTC).date()
    return BalanceSheetOut.model_validate(reports.balance_sheet(db, as_of_date))


@router.get(
    "/account-ledger/{account_id}",
    response_model=AccountLedgerOut,
    responses={404: {"model": ErrorEnvelope}},
)
def account_ledger(
    account_id: int,
    _: ReportRead,
    db: DbSession,
    params: Annotated[PageParams, Depends(page_params)],
    date_from: date | None = None,
    date_to: date | None = None,
) -> AccountLedgerOut:
    return AccountLedgerOut.model_validate(
        reports.account_ledger(db, account_id, date_from, date_to, params)
    )
