"""Payroll: employees with a salary structure, income-tax slabs, monthly runs and payslips."""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
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
from app.models.org import Department


class EmployeeStatus(StrEnum):
    ACTIVE = "active"
    TERMINATED = "terminated"


class PayrollStatus(StrEnum):
    QUEUED = "queued"  # waiting for the background job
    CALCULATED = "calculated"  # payslips computed, can be recalculated
    PENDING_APPROVAL = "pending_approval"
    POSTED = "posted"  # approved and posted to the ledger
    PAID = "paid"
    FAILED = "failed"  # background calculation failed; see error


class Employee(TimestampMixin, Base):
    __tablename__ = "employees"
    __table_args__ = (
        CheckConstraint("status IN ('active','terminated')", name="valid_status"),
        CheckConstraint(
            "basic_salary >= 0 AND housing_allowance >= 0 AND transport_allowance >= 0 "
            "AND other_allowance >= 0 AND other_deduction >= 0",
            name="non_negative_pay",
        ),
        CheckConstraint("pension_rate >= 0 AND pension_rate <= 0.2", name="valid_pension_rate"),
        CheckConstraint(
            "termination_date IS NULL OR termination_date >= hire_date", name="valid_dates"
        ),
    )

    id: Mapped[IntPK]
    employee_number: Mapped[str] = mapped_column(String(20), unique=True)
    first_name: Mapped[str] = mapped_column(String(80))
    last_name: Mapped[str] = mapped_column(String(80))
    email: Mapped[str] = mapped_column(String(255), default="", server_default="")
    department_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("departments.id", ondelete="RESTRICT"), index=True
    )
    position: Mapped[str] = mapped_column(String(120))
    hire_date: Mapped[date] = mapped_column(Date)
    termination_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default=EmployeeStatus.ACTIVE, index=True)
    bank_reference: Mapped[str] = mapped_column(String(80), default="", server_default="")
    basic_salary: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    housing_allowance: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    transport_allowance: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    other_allowance: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    pension_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0.0500"))
    other_deduction: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))

    department: Mapped[Department] = relationship(lazy="joined")

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    @property
    def monthly_gross(self) -> Decimal:
        return (
            self.basic_salary
            + self.housing_allowance
            + self.transport_allowance
            + self.other_allowance
        )


class TaxSlab(TimestampMixin, Base):
    """Annual progressive income-tax band: `rate` applies to income in [lower, upper)."""

    __tablename__ = "tax_slabs"
    __table_args__ = (
        CheckConstraint("lower_bound >= 0", name="non_negative_lower"),
        CheckConstraint("upper_bound IS NULL OR upper_bound > lower_bound", name="valid_band"),
        CheckConstraint("rate >= 0 AND rate < 1", name="valid_rate"),
        UniqueConstraint("year", "lower_bound", name="uq_tax_slabs_year_lower"),
    )

    id: Mapped[IntPK]
    year: Mapped[int] = mapped_column(Integer, index=True)
    lower_bound: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    upper_bound: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    rate: Mapped[Decimal] = mapped_column(Numeric(5, 4))


class PayrollRun(TimestampMixin, Base):
    __tablename__ = "payroll_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','calculated','pending_approval','posted','paid','failed')",
            name="valid_status",
        ),
        CheckConstraint("month BETWEEN 1 AND 12", name="valid_month"),
        CheckConstraint(
            "net_total = gross_total - pension_total - tax_total - other_deduction_total",
            name="net_balances",
        ),
        UniqueConstraint("year", "month", name="uq_payroll_runs_year_month"),
    )

    id: Mapped[IntPK]
    run_number: Mapped[str] = mapped_column(String(20), unique=True)  # PR-2026-11
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    pay_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default=PayrollStatus.QUEUED, index=True)
    employee_count: Mapped[int] = mapped_column(Integer, default=0)
    gross_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    pension_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    tax_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    other_deduction_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    net_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    error: Mapped[str | None] = mapped_column(Text)
    calculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    posting_entry_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("journal_entries.id", ondelete="RESTRICT")
    )
    funding_entry_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("journal_entries.id", ondelete="RESTRICT")
    )
    payment_entry_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("journal_entries.id", ondelete="RESTRICT")
    )
    approved_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT")
    )

    payslips: Mapped[list["Payslip"]] = relationship(
        order_by="Payslip.employee_number", lazy="selectin", cascade="all, delete-orphan"
    )


class Payslip(TimestampMixin, Base):
    """One employee's pay for a run. Employee details are snapshotted at calculation time."""

    __tablename__ = "payslips"
    __table_args__ = (
        UniqueConstraint("payroll_run_id", "employee_id", name="uq_payslips_run_employee"),
        CheckConstraint(
            "gross = basic + housing + transport + other_allowance", name="gross_balances"
        ),
        CheckConstraint(
            "net = gross - pension - income_tax - other_deduction AND net >= 0",
            name="net_balances",
        ),
        CheckConstraint("days_worked BETWEEN 1 AND days_in_month", name="valid_days"),
        Index("ix_payslips_employee", "employee_id"),
    )

    id: Mapped[IntPK]
    payroll_run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("payroll_runs.id", ondelete="CASCADE"), index=True
    )
    employee_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("employees.id", ondelete="RESTRICT")
    )
    employee_number: Mapped[str] = mapped_column(String(20))
    employee_name: Mapped[str] = mapped_column(String(170))
    position: Mapped[str] = mapped_column(String(120))
    department_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("departments.id", ondelete="RESTRICT"), index=True
    )
    days_in_month: Mapped[int] = mapped_column(Integer)
    days_worked: Mapped[int] = mapped_column(Integer)
    basic: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    housing: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    transport: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    other_allowance: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    gross: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    pension: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    taxable: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    income_tax: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    other_deduction: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    net: Mapped[Decimal] = mapped_column(Numeric(14, 2))

    department: Mapped[Department] = relationship(lazy="joined")
