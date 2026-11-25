"""Platform tables: idempotency keys for safely retryable payment endpoints."""

from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IntPK, TimestampMixin


class IdempotencyKey(TimestampMixin, Base):
    """First request with a key stores its response; retries with the same key and the same
    payload get that response back without re-executing (and without posting twice)."""

    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint("scope", "actor_key", "key", name="uq_idempotency_keys_scope_actor_key"),
    )

    id: Mapped[IntPK]
    scope: Mapped[str] = mapped_column(String(80))
    # Keys are namespaced per user ("user:<id>" or "system").
    actor_key: Mapped[str] = mapped_column(String(40))
    key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    actor_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
