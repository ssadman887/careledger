"""Accounts receivable: write-offs and dunning notices."""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IntPK, TimestampMixin
from app.models.billing import Invoice


class WriteOffStatus(StrEnum):
    PENDING_APPROVAL = "pending_approval"
    POSTED = "posted"
    REJECTED = "rejected"


class WriteOff(TimestampMixin, Base):
    """Bad-debt write-off of (part of) a patient balance: Dr 5400 / Cr 1100 once approved."""

    __tablename__ = "write_offs"
    __table_args__ = (
        CheckConstraint("amount > 0", name="positive_amount"),
        CheckConstraint("status IN ('pending_approval','posted','rejected')", name="valid_status"),
    )

    id: Mapped[IntPK]
    write_off_number: Mapped[str] = mapped_column(String(20), unique=True)
    invoice_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("invoices.id", ondelete="RESTRICT"), index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), index=True)
    posted_on: Mapped[date | None] = mapped_column(Date)
    journal_entry_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("journal_entries.id", ondelete="RESTRICT")
    )
    requested_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT")
    )
    decided_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT")
    )

    invoice: Mapped[Invoice] = relationship(lazy="joined")


class DunningNotice(TimestampMixin, Base):
    """A (simulated) payment reminder. One per invoice per level."""

    __tablename__ = "dunning_notices"
    __table_args__ = (
        CheckConstraint("level BETWEEN 1 AND 3", name="valid_level"),
        CheckConstraint("amount_due > 0", name="positive_amount"),
        UniqueConstraint("invoice_id", "level", name="uq_dunning_notices_invoice_level"),
    )

    id: Mapped[IntPK]
    invoice_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("invoices.id", ondelete="RESTRICT"), index=True
    )
    patient_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("patients.id", ondelete="RESTRICT"), index=True
    )
    level: Mapped[int] = mapped_column(Integer)
    days_overdue: Mapped[int] = mapped_column(Integer)
    amount_due: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    channel: Mapped[str] = mapped_column(String(20), default="email", server_default="email")
    message: Mapped[str] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    invoice: Mapped[Invoice] = relationship(lazy="joined")
