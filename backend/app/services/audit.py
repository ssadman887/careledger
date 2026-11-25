"""Audit service: records create/update/status changes in the caller's transaction."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

import structlog
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.models.base import Base
from app.repositories import audit as audit_repo

REDACTED_FIELDS = frozenset({"password_hash", "password"})


@dataclass(frozen=True)
class Actor:
    """Who is performing an action. `id=None` means the system (jobs, seed)."""

    id: int | None
    label: str
    roles: frozenset[str]

    def has_any(self, *roles: str) -> bool:
        return bool(self.roles.intersection(roles))


SYSTEM_ACTOR = Actor(id=None, label="system", roles=frozenset())


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_jsonable(v) for v in value]
    return value


def snapshot(obj: Base, *, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Column values of an ORM object as JSON-safe dict (sensitive fields redacted)."""
    mapper = inspect(type(obj), raiseerr=True)
    data: dict[str, Any] = {}
    for column in mapper.column_attrs:
        key = column.key
        if key in REDACTED_FIELDS:
            continue
        data[key] = _jsonable(getattr(obj, key))
    if extra:
        data.update({k: _jsonable(v) for k, v in extra.items()})
    return data


def record(
    session: Session,
    actor: Actor,
    *,
    entity_type: str,
    entity_id: int | str,
    action: str,
    before: Mapping[str, Any] | None = None,
    after: Mapping[str, Any] | None = None,
) -> AuditLog:
    request_id = structlog.contextvars.get_contextvars().get("request_id")
    entry = AuditLog(
        actor_id=actor.id,
        actor_label=actor.label,
        entity_type=entity_type,
        entity_id=str(entity_id),
        action=action,
        before=_jsonable(dict(before)) if before is not None else None,
        after=_jsonable(dict(after)) if after is not None else None,
        request_id=request_id if isinstance(request_id, str) else None,
    )
    audit_repo.add(session, entry)
    session.flush()
    return entry
