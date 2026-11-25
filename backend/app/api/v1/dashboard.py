"""Dashboard metrics, notifications and global search (any signed-in user; content by role)."""

from dataclasses import asdict
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.deps import CurrentActor, DbSession
from app.core.errors import AuthenticationFailed, ErrorEnvelope
from app.core.pagination import Page, PageParams, page_params
from app.schemas.phase6 import (
    DashboardOut,
    MarkedOut,
    NotificationOut,
    SearchOut,
    UnreadCountOut,
)
from app.services import dashboard, notifications, search
from app.services.audit import Actor

router = APIRouter(
    tags=["dashboard"],
    responses={401: {"model": ErrorEnvelope}, 404: {"model": ErrorEnvelope}},
)


def _user_id(actor: Actor) -> int:
    if actor.id is None:  # pragma: no cover - API actors always have an id
        raise AuthenticationFailed("A user is required")
    return actor.id


@router.get("/dashboard", response_model=DashboardOut)
def get_dashboard(actor: CurrentActor, db: DbSession, as_of: date | None = None) -> DashboardOut:
    """KPI sections for the signed-in user's roles (finance, revenue cycle, insurance, admin)."""
    board = dashboard.build(db, actor, as_of or datetime.now(UTC).date())
    return DashboardOut.model_validate(asdict(board))


@router.get("/notifications", response_model=Page[NotificationOut])
def list_notifications(
    actor: CurrentActor,
    db: DbSession,
    params: Annotated[PageParams, Depends(page_params)],
    unread_only: bool = False,
) -> Page[NotificationOut]:
    rows, total = notifications.list_for(db, _user_id(actor), params, unread_only=unread_only)
    return Page(
        items=[NotificationOut.model_validate(n) for n in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.get("/notifications/unread-count", response_model=UnreadCountOut)
def unread_count(actor: CurrentActor, db: DbSession) -> UnreadCountOut:
    return UnreadCountOut(unread=notifications.unread_count(db, _user_id(actor)))


@router.post("/notifications/{notification_id}/read", response_model=NotificationOut)
def mark_read(notification_id: int, actor: CurrentActor, db: DbSession) -> NotificationOut:
    return NotificationOut.model_validate(
        notifications.mark_read(db, _user_id(actor), notification_id)
    )


@router.post("/notifications/read-all", response_model=MarkedOut)
def mark_all_read(actor: CurrentActor, db: DbSession) -> MarkedOut:
    return MarkedOut(marked=notifications.mark_all_read(db, _user_id(actor)))


@router.get("/search", response_model=SearchOut)
def global_search(
    actor: CurrentActor, db: DbSession, q: Annotated[str, Query(max_length=100)] = ""
) -> SearchOut:
    """Search records you may read: patients, invoices, claims, journal entries, accounts,
    payables, employees and (admins) users. At least 2 characters."""
    groups = search.search(db, actor, q)
    return SearchOut.model_validate({"query": q, "groups": [asdict(g) for g in groups]})
