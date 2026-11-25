from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.core.deps import CurrentActor, DbSession, read_roles, require_roles
from app.core.errors import ErrorEnvelope
from app.core.pagination import Page, PageParams, page_params
from app.models.identity import RoleName
from app.models.ledger import AccountType
from app.repositories import ledger as repo
from app.schemas.ledger import (
    AccountCreate,
    AccountOut,
    AccountUpdate,
    CostCenterCreate,
    CostCenterOut,
    DepartmentCreate,
    DepartmentOut,
)
from app.services import accounts as accounts_service
from app.services.audit import Actor

router = APIRouter(
    tags=["accounts"],
    responses={401: {"model": ErrorEnvelope}, 403: {"model": ErrorEnvelope}},
)

R = RoleName
CoaRead = Annotated[Actor, Depends(read_roles(R.ADMIN, R.ACCOUNTANT, R.FINANCE_MANAGER))]
CoaWrite = Annotated[Actor, Depends(require_roles(R.ADMIN, R.ACCOUNTANT))]
AdminWrite = Annotated[Actor, Depends(require_roles(R.ADMIN))]


@router.get("/accounts", response_model=Page[AccountOut])
def list_accounts(
    _: CoaRead,
    db: DbSession,
    params: Annotated[PageParams, Depends(page_params)],
    type: AccountType | None = None,
    is_active: bool | None = None,
    postable_only: bool = False,
    search: Annotated[str | None, Query(max_length=100)] = None,
) -> Page[AccountOut]:
    rows, total = repo.list_accounts(
        db,
        params,
        type_=type.value if type else None,
        is_active=is_active,
        postable_only=postable_only,
        search=search,
    )
    return Page(
        items=[AccountOut.model_validate(a) for a in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.post(
    "/accounts",
    response_model=AccountOut,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": ErrorEnvelope}, 422: {"model": ErrorEnvelope}},
)
def create_account(body: AccountCreate, actor: CoaWrite, db: DbSession) -> AccountOut:
    account = accounts_service.create_account(
        db,
        actor,
        code=body.code,
        name=body.name,
        type_=body.type.value,
        parent_id=body.parent_id,
        cost_center_id=body.cost_center_id,
        is_header=body.is_header,
        description=body.description,
    )
    return AccountOut.model_validate(account)


@router.get(
    "/accounts/{account_id}", response_model=AccountOut, responses={404: {"model": ErrorEnvelope}}
)
def get_account(account_id: int, _: CoaRead, db: DbSession) -> AccountOut:
    return AccountOut.model_validate(accounts_service.get_account(db, account_id))


@router.patch(
    "/accounts/{account_id}",
    response_model=AccountOut,
    responses={404: {"model": ErrorEnvelope}, 422: {"model": ErrorEnvelope}},
)
def update_account(
    account_id: int, body: AccountUpdate, actor: CoaWrite, db: DbSession
) -> AccountOut:
    account = accounts_service.update_account(
        db,
        actor,
        account_id,
        name=body.name,
        parent_id=body.parent_id,
        clear_parent=body.clear_parent,
        cost_center_id=body.cost_center_id,
        clear_cost_center=body.clear_cost_center,
        is_active=body.is_active,
        description=body.description,
    )
    return AccountOut.model_validate(account)


@router.get("/departments", response_model=list[DepartmentOut])
def list_departments(_: CurrentActor, db: DbSession) -> list[DepartmentOut]:
    return [DepartmentOut.model_validate(d) for d in repo.list_departments(db)]


@router.post("/departments", response_model=DepartmentOut, status_code=status.HTTP_201_CREATED)
def create_department(body: DepartmentCreate, actor: AdminWrite, db: DbSession) -> DepartmentOut:
    dept = accounts_service.create_department(
        db, actor, code=body.code, name=body.name, revenue_account_id=body.revenue_account_id
    )
    return DepartmentOut.model_validate(dept)


@router.get("/cost-centers", response_model=list[CostCenterOut])
def list_cost_centers(_: CurrentActor, db: DbSession) -> list[CostCenterOut]:
    return [CostCenterOut.model_validate(c) for c in repo.list_cost_centers(db)]


@router.post("/cost-centers", response_model=CostCenterOut, status_code=status.HTTP_201_CREATED)
def create_cost_center(body: CostCenterCreate, actor: AdminWrite, db: DbSession) -> CostCenterOut:
    cc = accounts_service.create_cost_center(
        db, actor, code=body.code, name=body.name, department_id=body.department_id
    )
    return CostCenterOut.model_validate(cc)
