"""Generic approval engine: policies (thresholds per kind), requests, comments."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IntPK, TimestampMixin


class ApprovalKind(StrEnum):
    MANUAL_JOURNAL = "manual_journal"
    REFUND = "refund"
    WRITE_OFF = "write_off"
    VENDOR_BILL = "vendor_bill"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


KINDS = tuple(k.value for k in ApprovalKind)


class ApprovalPolicy(TimestampMixin, Base):
    """Amounts strictly above `threshold` need approval by `approver_role`."""

    __tablename__ = "approval_policies"
    __table_args__ = (CheckConstraint("threshold >= 0", name="non_negative_threshold"),)

    id: Mapped[IntPK]
    kind: Mapped[str] = mapped_column(String(30), unique=True)
    threshold: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    approver_role: Mapped[str] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(String(255), default="", server_default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class Approval(TimestampMixin, Base):
    __tablename__ = "approvals"
    __table_args__ = (
        CheckConstraint("status IN ('pending','approved','rejected')", name="valid_status"),
        CheckConstraint("amount >= 0", name="non_negative_amount"),
        UniqueConstraint("kind", "entity_id", name="uq_approvals_kind_entity"),
        Index("ix_approvals_status_kind", "status", "kind"),
    )

    id: Mapped[IntPK]
    kind: Mapped[str] = mapped_column(String(30))
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[int] = mapped_column(BigInteger)
    reference: Mapped[str] = mapped_column(String(40))  # e.g. JE-000012, RFD-000003
    summary: Mapped[str] = mapped_column(String(500))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    threshold: Mapped[Decimal] = mapped_column(Numeric(14, 2))  # policy at request time
    approver_role: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default=ApprovalStatus.PENDING, index=True)
    requested_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    requested_by_label: Mapped[str] = mapped_column(String(255))
    decided_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT")
    )
    decided_by_label: Mapped[str | None] = mapped_column(String(255))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)

    comments: Mapped[list["ApprovalComment"]] = relationship(
        order_by="ApprovalComment.id", lazy="selectin"
    )


class ApprovalComment(TimestampMixin, Base):
    __tablename__ = "approval_comments"

    id: Mapped[IntPK]
    approval_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("approvals.id", ondelete="RESTRICT"), index=True
    )
    author_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT")
    )
    author_label: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
