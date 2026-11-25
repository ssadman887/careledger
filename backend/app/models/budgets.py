"""Budgets per department and account (monthly amounts), and threshold alerts."""

from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IntPK, TimestampMixin
from app.models.ledger import Account
from app.models.org import Department


class BudgetStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"  # monitored by the alerts job
    ARCHIVED = "archived"


class AlertLevel(StrEnum):
    WARNING = "warning"  # year-to-date actual >= threshold % of year-to-date budget
    EXCEEDED = "exceeded"  # year-to-date actual > year-to-date budget


class Budget(TimestampMixin, Base):
    __tablename__ = "budgets"
    __table_args__ = (
        CheckConstraint("status IN ('draft','active','archived')", name="valid_status"),
        CheckConstraint(
            "alert_threshold_percent > 0 AND alert_threshold_percent <= 100",
            name="valid_threshold",
        ),
        UniqueConstraint("year", "department_id", name="uq_budgets_year_department"),
    )

    id: Mapped[IntPK]
    year: Mapped[int] = mapped_column(Integer, index=True)
    department_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("departments.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(20), default=BudgetStatus.DRAFT, index=True)
    alert_threshold_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("90.00"), server_default="90.00"
    )
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT")
    )

    department: Mapped[Department] = relationship(lazy="joined")
    lines: Mapped[list["BudgetLine"]] = relationship(
        order_by=lambda: [BudgetLine.account_id, BudgetLine.month],
        lazy="selectin",
        cascade="all, delete-orphan",
    )


class BudgetLine(TimestampMixin, Base):
    __tablename__ = "budget_lines"
    __table_args__ = (
        CheckConstraint("month BETWEEN 1 AND 12", name="valid_month"),
        CheckConstraint("amount >= 0", name="non_negative_amount"),
        UniqueConstraint("budget_id", "account_id", "month", name="uq_budget_lines_month"),
    )

    id: Mapped[IntPK]
    budget_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("budgets.id", ondelete="CASCADE"), index=True
    )
    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="RESTRICT"), index=True
    )
    month: Mapped[int] = mapped_column(Integer)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))

    account: Mapped[Account] = relationship(lazy="joined")


class BudgetAlert(TimestampMixin, Base):
    """Raised once per budget, account, month (year-to-date through) and level."""

    __tablename__ = "budget_alerts"
    __table_args__ = (
        CheckConstraint("level IN ('warning','exceeded')", name="valid_level"),
        CheckConstraint("month BETWEEN 1 AND 12", name="valid_month"),
        UniqueConstraint("budget_id", "account_id", "month", "level", name="uq_budget_alerts_once"),
    )

    id: Mapped[IntPK]
    budget_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("budgets.id", ondelete="RESTRICT"), index=True
    )
    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="RESTRICT")
    )
    month: Mapped[int] = mapped_column(Integer)
    level: Mapped[str] = mapped_column(String(20))
    budget_ytd: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    actual_ytd: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    percent_used: Mapped[Decimal] = mapped_column(Numeric(7, 2))
    message: Mapped[str] = mapped_column(String(300))

    account: Mapped[Account] = relationship(lazy="joined")
    budget: Mapped[Budget] = relationship(lazy="joined")
