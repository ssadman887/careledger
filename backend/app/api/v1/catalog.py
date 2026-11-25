from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.core.deps import DbSession, read_roles, require_roles
from app.core.errors import ErrorEnvelope
from app.core.pagination import Page, PageParams, page_params
from app.models.identity import RoleName
from app.repositories import billing as repo
from app.schemas.billing import (
    PriceItemCreate,
    PriceItemOut,
    PriceListCreate,
    PriceListOut,
    ServiceCreate,
    ServiceOut,
    ServiceUpdate,
)
from app.services import catalog as catalog_service
from app.services.audit import Actor

router = APIRouter(
    tags=["catalog"],
    responses={
        401: {"model": ErrorEnvelope},
        403: {"model": ErrorEnvelope},
        404: {"model": ErrorEnvelope},
        409: {"model": ErrorEnvelope},
        422: {"model": ErrorEnvelope},
    },
)

R = RoleName
CatalogRead = Annotated[
    Actor,
    Depends(
        read_roles(R.ADMIN, R.BILLING_CLERK, R.INSURANCE_OFFICER, R.FINANCE_MANAGER, R.ACCOUNTANT)
    ),
]
CatalogWrite = Annotated[Actor, Depends(require_roles(R.ADMIN, R.FINANCE_MANAGER))]


@router.get("/services", response_model=Page[ServiceOut])
def list_services(
    _: CatalogRead,
    db: DbSession,
    params: Annotated[PageParams, Depends(page_params)],
    search: Annotated[str | None, Query(max_length=100)] = None,
    department_id: int | None = None,
    active_only: bool = True,
    price_on: Annotated[
        date | None, Query(description="Include price from the default list")
    ] = None,
) -> Page[ServiceOut]:
    rows, total = repo.list_services(
        db, params, search=search, department_id=department_id, active_only=active_only
    )
    on = price_on or datetime.now(UTC).date()
    default = repo.default_price_list(db)
    prices = repo.price_on(db, default.id, {s.id for s in rows}, on) if default and rows else {}
    items = [
        ServiceOut.model_validate(
            {**ServiceOut.model_validate(s).model_dump(), "current_price": prices.get(s.id)}
        )
        for s in rows
    ]
    return Page(items=items, total=total, page=params.page, page_size=params.page_size)


@router.post("/services", response_model=ServiceOut, status_code=status.HTTP_201_CREATED)
def create_service(body: ServiceCreate, actor: CatalogWrite, db: DbSession) -> ServiceOut:
    service = catalog_service.create_service(
        db,
        actor,
        code=body.code,
        name=body.name,
        department_id=body.department_id,
        tax_rate=body.tax_rate,
    )
    return ServiceOut.model_validate(service)


@router.patch("/services/{service_id}", response_model=ServiceOut)
def update_service(
    service_id: int, body: ServiceUpdate, actor: CatalogWrite, db: DbSession
) -> ServiceOut:
    service = catalog_service.update_service(
        db, actor, service_id, name=body.name, tax_rate=body.tax_rate, is_active=body.is_active
    )
    return ServiceOut.model_validate(service)


@router.get("/price-lists", response_model=list[PriceListOut])
def list_price_lists(_: CatalogRead, db: DbSession) -> list[PriceListOut]:
    return [PriceListOut.model_validate(p) for p in repo.list_price_lists(db)]


@router.post("/price-lists", response_model=PriceListOut, status_code=status.HTTP_201_CREATED)
def create_price_list(body: PriceListCreate, actor: CatalogWrite, db: DbSession) -> PriceListOut:
    price_list = catalog_service.create_price_list(
        db, actor, code=body.code, name=body.name, is_default=body.is_default
    )
    return PriceListOut.model_validate(price_list)


@router.get("/price-lists/{price_list_id}/items", response_model=list[PriceItemOut])
def list_price_items(
    price_list_id: int, _: CatalogRead, db: DbSession, service_id: int | None = None
) -> list[PriceItemOut]:
    catalog_service.get_price_list(db, price_list_id)
    return [PriceItemOut.model_validate(i) for i in repo.price_items(db, price_list_id, service_id)]


@router.post(
    "/price-lists/{price_list_id}/items",
    response_model=PriceItemOut,
    status_code=status.HTTP_201_CREATED,
)
def set_price(
    price_list_id: int, body: PriceItemCreate, actor: CatalogWrite, db: DbSession
) -> PriceItemOut:
    item = catalog_service.set_price(
        db,
        actor,
        price_list_id=price_list_id,
        service_id=body.service_id,
        unit_price=body.unit_price,
        effective_from=body.effective_from,
    )
    return PriceItemOut.model_validate(item)
