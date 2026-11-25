from datetime import datetime
from typing import Any

from app.schemas.common import OrmModel


class AuditLogOut(OrmModel):
    id: int
    occurred_at: datetime
    actor_id: int | None
    actor_label: str
    entity_type: str
    entity_id: str
    action: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    request_id: str | None
