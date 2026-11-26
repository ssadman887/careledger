"""General ledger: chart of accounts, fiscal periods, journal entries and lines.

DB-level safeguards (see migration 0004): balanced posted entries (deferred constraint trigger),
immutable posted entries/lines, no posting outside an open fiscal period, no reopening periods.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IntPK, TimestampMixin


class AccountType(StrEnum):
    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    REVENUE = "revenue"
    EXPENSE = "expense"


DEBIT_NORMAL = frozenset({AccountType.ASSET, AccountType.EXPENSE})


class PeriodStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class EntryStatus(StrEnum):
    PENDING_APPROVAL = "pending_approval"
    POSTED = "posted"
    REJECTED = "rejected"


class Account(TimestampMixin, Base):
    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint(
            "type IN ('asset','liability','equity','revenue','expense')", name="valid_type"
        ),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="not_own_parent"),
    )

    id: Mapped[IntPK]
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    type: Mapped[str] = mapped_column(String(20), index=True)
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="RESTRICT"), index=True
    )
    cost_center_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("cost_centers.id", ondelete="RESTRICT"), index=True
    )
    # Header (summary) accounts group children and cannot be posted to.
    is_header: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    description: Mapped[str] = mapped_column(Text, default="", server_default="")

    @property
    def normal_balance(self) -> str:
        return "debit" if self.type in DEBIT_NORMAL else "credit"


class FiscalPeriod(TimestampMixin, Base):
    __tablename__ = "fiscal_periods"
    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="valid_range"),
        CheckConstraint("status IN ('open','closed')", name="valid_status"),
    )

    id: Mapped[IntPK]
    name: Mapped[str] = mapped_column(String(20), unique=True)
    start_date: Mapped[date] = mapped_column(Date, unique=True)
    end_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(10), default=PeriodStatus.OPEN, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT")
    )


class JournalEntry(TimestampMixin, Base):
    __tablename__ = "journal_entries"
    __table_args__ = (
        CheckConstraint("status IN ('pending_approval','posted','rejected')", name="valid_status"),
        CheckConstraint("total >= 0", name="non_negative_total"),
        CheckConstraint(
            "(status = 'posted') = (posted_at IS NOT NULL)", name="posted_at_matches_status"
        ),
        Index("ix_journal_entries_source", "source_type", "source_id"),
        # Reports and dashboards filter posted entries by date range.
        Index("ix_journal_entries_status_date", "status", "entry_date"),
    )

    id: Mapped[IntPK]
    entry_number: Mapped[str] = mapped_column(String(20), unique=True)
    entry_date: Mapped[date] = mapped_column(Date, index=True)
    memo: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(40))
    source_id: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), index=True)
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    reversal_of_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("journal_entries.id", ondelete="RESTRICT"), unique=True
    )
    reversal_reason: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    approved_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT")
    )
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text)

    lines: Mapped[list["JournalLine"]] = relationship(
        back_populates="entry", order_by="JournalLine.line_no", lazy="selectin"
    )


class JournalLine(TimestampMixin, Base):
    __tablename__ = "journal_lines"
    __table_args__ = (
        CheckConstraint("debit >= 0 AND credit >= 0", name="non_negative"),
        CheckConstraint("(debit > 0) <> (credit > 0)", name="one_sided"),
        UniqueConstraint("entry_id", "line_no", name="uq_journal_lines_entry_line"),
    )

    id: Mapped[IntPK]
    entry_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("journal_entries.id", ondelete="RESTRICT"), index=True
    )
    line_no: Mapped[int] = mapped_column(Integer)
    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="RESTRICT"), index=True
    )
    debit: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    credit: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    department_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("departments.id", ondelete="RESTRICT"), index=True
    )
    cost_center_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("cost_centers.id", ondelete="RESTRICT"), index=True
    )

    entry: Mapped[JournalEntry] = relationship(back_populates="lines")
    account: Mapped[Account] = relationship(lazy="joined")
