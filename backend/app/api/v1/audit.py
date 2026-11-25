from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.deps import DbSession, read_roles
from app.core.errors import ErrorEnvelope
from app.core.pagination import Page, PageParams, page_params
from app.models.identity import RoleName
from app.repositories import audit as audit_repo
from app.schemas.audit import AuditFacetsOut, AuditLogOut
from app.services.audit import Actor

router = APIRouter(
    prefix="/audit-log",
    tags=["audit"],
    responses={401: {"model": ErrorEnvelope}, 403: {"model": ErrorEnvelope}},
)

AuditReader = Annotated[Actor, Depends(read_roles(RoleName.ADMIN, RoleName.FINANCE_MANAGER))]


@router.get("/facets", response_model=AuditFacetsOut)
def facets(_: AuditReader, db: DbSession) -> AuditFacetsOut:
    entity_types, actions = audit_repo.facets(db)
    return AuditFacetsOut(entity_types=entity_types, actions=actions)


@router.get("", response_model=Page[AuditLogOut])
def list_audit_log(
    _: AuditReader,
    db: DbSession,
    params: Annotated[PageParams, Depends(page_params)],
    entity_type: Annotated[str | None, Query(max_length=64)] = None,
    entity_id: Annotated[str | None, Query(max_length=64)] = None,
    actor_id: int | None = None,
    action: Annotated[str | None, Query(max_length=64)] = None,
    actor_label: Annotated[str | None, Query(max_length=255)] = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> Page[AuditLogOut]:
    rows, total = audit_repo.list_entries(
        db,
        params,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_id=actor_id,
        action=action,
        date_from=date_from,
        date_to=date_to,
        actor_label=actor_label,
    )
    return Page(
        items=[AuditLogOut.model_validate(r) for r in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )
