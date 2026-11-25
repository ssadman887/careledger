"""In-app notifications. Rows are never deleted; users mark them read."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IntPK, TimestampMixin

LEVELS = ("info", "success", "warning", "action")


class Notification(TimestampMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint("level IN ('info','success','warning','action')", name="valid_level"),
        Index("ix_notifications_user_unread", "user_id", "read_at"),
    )

    id: Mapped[IntPK]
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    kind: Mapped[str] = mapped_column(String(40))  # e.g. approval_requested, budget_alert
    level: Mapped[str] = mapped_column(String(10), default="info")
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(String(500), default="", server_default="")
    link: Mapped[str] = mapped_column(String(200), default="", server_default="")
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
