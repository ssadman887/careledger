from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.core.deps import DbSession, read_roles, require_roles
from app.core.errors import ErrorEnvelope
from app.models.identity import RoleName
from app.repositories import ledger as repo
from app.schemas.ledger import CloseCheckOut, FiscalPeriodCreate, FiscalPeriodOut
from app.services import periods as periods_service
from app.services.audit import Actor

router = APIRouter(
    prefix="/fiscal-periods",
    tags=["fiscal-periods"],
    responses={401: {"model": ErrorEnvelope}, 403: {"model": ErrorEnvelope}},
)

R = RoleName
PeriodRead = Annotated[Actor, Depends(read_roles(R.ACCOUNTANT, R.FINANCE_MANAGER))]
PeriodWrite = Annotated[Actor, Depends(require_roles(R.ACCOUNTANT, R.FINANCE_MANAGER))]


@router.get("", response_model=list[FiscalPeriodOut])
def list_periods(_: PeriodRead, db: DbSession) -> list[FiscalPeriodOut]:
    return [FiscalPeriodOut.model_validate(p) for p in repo.list_periods(db)]


@router.post(
    "",
    response_model=FiscalPeriodOut,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": ErrorEnvelope}},
)
def create_period(body: FiscalPeriodCreate, actor: PeriodWrite, db: DbSession) -> FiscalPeriodOut:
    period = periods_service.create_period(
        db, actor, name=body.name, start=body.start_date, end=body.end_date
    )
    return FiscalPeriodOut.model_validate(period)


@router.get(
    "/{period_id}/close-check",
    response_model=CloseCheckOut,
    responses={404: {"model": ErrorEnvelope}},
)
def close_check(period_id: int, _: PeriodRead, db: DbSession) -> CloseCheckOut:
    check = periods_service.close_check(db, periods_service.get_period(db, period_id))
    return CloseCheckOut.model_validate(check, from_attributes=True)


@router.post(
    "/{period_id}/close",
    response_model=FiscalPeriodOut,
    responses={404: {"model": ErrorEnvelope}, 422: {"model": ErrorEnvelope}},
)
def close_period(period_id: int, actor: PeriodWrite, db: DbSession) -> FiscalPeriodOut:
    return FiscalPeriodOut.model_validate(periods_service.close_period(db, actor, period_id))
