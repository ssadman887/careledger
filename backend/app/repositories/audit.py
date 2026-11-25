"""Audit log queries."""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.pagination import PageParams
from app.models.audit import AuditLog


def add(session: Session, entry: AuditLog) -> None:
    session.add(entry)


def list_entries(
    session: Session,
    params: PageParams,
    *,
    entity_type: str | None,
    entity_id: str | None,
    actor_id: int | None,
    action: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> tuple[Sequence[AuditLog], int]:
    stmt = select(AuditLog)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if actor_id is not None:
        stmt = stmt.where(AuditLog.actor_id == actor_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if date_from:
        stmt = stmt.where(AuditLog.occurred_at >= date_from)
    if date_to:
        stmt = stmt.where(AuditLog.occurred_at <= date_to)
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    order = AuditLog.id.asc() if params.sort == "id" else AuditLog.id.desc()
    rows = session.scalars(stmt.order_by(order).offset(params.offset).limit(params.page_size)).all()
    return rows, total
