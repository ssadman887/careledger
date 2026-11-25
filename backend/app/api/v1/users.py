from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.core.deps import DbSession, read_roles, require_roles
from app.core.errors import ErrorEnvelope
from app.core.pagination import Page, PageParams, page_params
from app.models.identity import RoleName
from app.repositories import users as users_repo
from app.schemas.users import RoleOut, UserCreate, UserOut, UserUpdate
from app.services import users as users_service
from app.services.audit import Actor

router = APIRouter(
    prefix="/users",
    tags=["users"],
    responses={401: {"model": ErrorEnvelope}, 403: {"model": ErrorEnvelope}},
)

AdminWrite = Annotated[Actor, Depends(require_roles(RoleName.ADMIN))]
AdminRead = Annotated[Actor, Depends(read_roles(RoleName.ADMIN))]


@router.get("", response_model=Page[UserOut])
def list_users(
    _: AdminRead,
    db: DbSession,
    params: Annotated[PageParams, Depends(page_params)],
    search: Annotated[str | None, Query(max_length=100)] = None,
    role: RoleName | None = None,
    is_active: bool | None = None,
) -> Page[UserOut]:
    rows, total = users_repo.list_users(
        db, params, search=search, role=role.value if role else None, is_active=is_active
    )
    return Page(
        items=[UserOut.model_validate(u) for u in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.get("/roles", response_model=list[RoleOut])
def list_roles(_: AdminRead, db: DbSession) -> list[RoleOut]:
    return [RoleOut.model_validate(r) for r in users_repo.all_roles(db)]


@router.post(
    "",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": ErrorEnvelope}},
)
def create_user(body: UserCreate, actor: AdminWrite, db: DbSession) -> UserOut:
    user = users_service.create_user(
        db,
        actor,
        email=body.email,
        username=body.username,
        full_name=body.full_name,
        password=body.password,
        roles=[r.value for r in body.roles],
    )
    return UserOut.model_validate(user)


@router.get("/{user_id}", response_model=UserOut, responses={404: {"model": ErrorEnvelope}})
def get_user(user_id: int, _: AdminRead, db: DbSession) -> UserOut:
    return UserOut.model_validate(users_service.get_user(db, user_id))


@router.patch("/{user_id}", response_model=UserOut, responses={404: {"model": ErrorEnvelope}})
def update_user(user_id: int, body: UserUpdate, actor: AdminWrite, db: DbSession) -> UserOut:
    user = users_service.update_user(
        db,
        actor,
        user_id,
        full_name=body.full_name,
        roles=[r.value for r in body.roles] if body.roles is not None else None,
        is_active=body.is_active,
        password=body.password,
    )
    return UserOut.model_validate(user)
