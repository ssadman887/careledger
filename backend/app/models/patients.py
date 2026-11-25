"""Patients (minimal, synthetic) and visits. CareLedger is not a clinical system."""

from datetime import date
from enum import StrEnum

from sqlalchemy import BigInteger, CheckConstraint, Date, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IntPK, SoftDeleteMixin, TimestampMixin
from app.models.org import Department


class VisitType(StrEnum):
    OUTPATIENT = "outpatient"
    INPATIENT = "inpatient"
    EMERGENCY = "emergency"


class VisitStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class Patient(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "patients"
    __table_args__ = (
        Index("ix_patients_name", "last_name", "first_name"),
        CheckConstraint("sex IN ('female','male','other','unknown')", name="valid_sex"),
    )

    id: Mapped[IntPK]
    mrn: Mapped[str] = mapped_column(String(20), unique=True)
    first_name: Mapped[str] = mapped_column(String(80))
    last_name: Mapped[str] = mapped_column(String(80))
    date_of_birth: Mapped[date] = mapped_column(Date)
    sex: Mapped[str] = mapped_column(String(10), default="unknown")
    phone: Mapped[str] = mapped_column(String(40), default="", server_default="")
    email: Mapped[str] = mapped_column(String(255), default="", server_default="")

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"


class Visit(TimestampMixin, Base):
    __tablename__ = "visits"
    __table_args__ = (
        CheckConstraint("visit_type IN ('outpatient','inpatient','emergency')", name="valid_type"),
        CheckConstraint("status IN ('open','closed','cancelled')", name="valid_status"),
        CheckConstraint(
            "discharge_date IS NULL OR discharge_date >= admit_date", name="valid_dates"
        ),
    )

    id: Mapped[IntPK]
    visit_number: Mapped[str] = mapped_column(String(20), unique=True)
    patient_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("patients.id", ondelete="RESTRICT"), index=True
    )
    department_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("departments.id", ondelete="RESTRICT"), index=True
    )
    visit_type: Mapped[str] = mapped_column(String(20))
    admit_date: Mapped[date] = mapped_column(Date, index=True)
    discharge_date: Mapped[date | None] = mapped_column(Date)
    attending_physician: Mapped[str] = mapped_column(String(120), default="", server_default="")
    status: Mapped[str] = mapped_column(String(20), default=VisitStatus.OPEN, index=True)

    patient: Mapped[Patient] = relationship(lazy="joined")
    department: Mapped[Department] = relationship(lazy="joined")
