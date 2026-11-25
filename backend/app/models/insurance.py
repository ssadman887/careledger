"""Insurance: insurers, policies, claims (+ lines, events, attachments), denial codes,
remittances (+ lines)."""

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
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, deferred, mapped_column, relationship

from app.models.base import Base, IntPK, TimestampMixin
from app.models.billing import Invoice
from app.models.patients import Patient


class ClaimStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    PARTIALLY_APPROVED = "partially_approved"
    DENIED = "denied"
    APPEALED = "appealed"
    PAID = "paid"
    CLOSED = "closed"
    CANCELLED = "cancelled"


CLAIM_STATUSES = tuple(s.value for s in ClaimStatus)
ACTIVE_CLAIM_STATUSES = frozenset(
    {"draft", "submitted", "under_review", "approved", "partially_approved", "denied", "appealed"}
)


class RemittanceStatus(StrEnum):
    IMPORTED = "imported"
    POSTED = "posted"


class MatchStatus(StrEnum):
    MATCHED = "matched"
    SHORT_PAID = "short_paid"
    OVERPAID = "overpaid"
    UNMATCHED = "unmatched"


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Insurer(TimestampMixin, Base):
    __tablename__ = "insurers"
    __table_args__ = (
        CheckConstraint(
            "approval_rate >= 0 AND partial_rate >= 0 AND denial_rate >= 0 AND "
            "approval_rate + partial_rate + denial_rate = 1",
            name="valid_rates",
        ),
    )

    id: Mapped[IntPK]
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    payer_id: Mapped[str] = mapped_column(String(40), default="", server_default="")
    contact_email: Mapped[str] = mapped_column(String(255), default="", server_default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # Mock adjudication behaviour (fractions summing to 1).
    approval_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0.7"))
    partial_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0.2"))
    denial_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0.1"))


class Policy(TimestampMixin, Base):
    """Coverage rules: coverage %, copay per claim, annual deductible, annual insurer limit.
    The benefit year is the calendar year."""

    __tablename__ = "policies"
    __table_args__ = (
        CheckConstraint("coverage_percent >= 0 AND coverage_percent <= 100", name="valid_coverage"),
        CheckConstraint(
            "copay >= 0 AND deductible >= 0 AND annual_limit >= 0", name="non_negative"
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from", name="valid_range"
        ),
        UniqueConstraint("insurer_id", "policy_number", name="uq_policies_insurer_number"),
    )

    id: Mapped[IntPK]
    policy_number: Mapped[str] = mapped_column(String(40))
    patient_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("patients.id", ondelete="RESTRICT"), index=True
    )
    insurer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("insurers.id", ondelete="RESTRICT"), index=True
    )
    plan_name: Mapped[str] = mapped_column(String(120))
    coverage_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    copay: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    deductible: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    annual_limit: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    insurer: Mapped[Insurer] = relationship(lazy="joined")
    patient: Mapped[Patient] = relationship(lazy="joined")


class DenialCode(TimestampMixin, Base):
    __tablename__ = "denial_codes"

    id: Mapped[IntPK]
    code: Mapped[str] = mapped_column(String(20), unique=True)
    description: Mapped[str] = mapped_column(String(255))
    patient_responsibility: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )


class Claim(TimestampMixin, Base):
    __tablename__ = "claims"
    __table_args__ = (
        CheckConstraint(_in("status", CLAIM_STATUSES), name="valid_status"),
        CheckConstraint(
            "billed_amount >= 0 AND insurer_amount >= 0 AND patient_amount >= 0 AND "
            "approved_amount >= 0 AND paid_amount >= 0 AND adjustment_amount >= 0",
            name="non_negative",
        ),
        CheckConstraint("insurer_amount + patient_amount = billed_amount", name="split_formula"),
        CheckConstraint("approved_amount <= insurer_amount", name="approved_within_claimed"),
        CheckConstraint(
            "paid_amount + adjustment_amount <= insurer_amount", name="settled_within_claimed"
        ),
        Index("ix_claims_status_insurer", "status", "insurer_id"),
    )

    id: Mapped[IntPK]
    claim_number: Mapped[str] = mapped_column(String(20), unique=True)
    invoice_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("invoices.id", ondelete="RESTRICT"), index=True
    )
    policy_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("policies.id", ondelete="RESTRICT"), index=True
    )
    patient_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("patients.id", ondelete="RESTRICT"), index=True
    )
    insurer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("insurers.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[str] = mapped_column(String(30), default=ClaimStatus.DRAFT, index=True)
    service_date: Mapped[date] = mapped_column(Date, index=True)
    billed_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    # Coverage split (computed at creation).
    copay_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    deductible_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    coinsurance_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    over_limit_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    insurer_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    patient_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    # Adjudication and settlement.
    approved_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    adjustment_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    denial_code: Mapped[str | None] = mapped_column(String(20))
    denial_note: Mapped[str | None] = mapped_column(Text)
    appeal_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    adjudicated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    transfer_entry_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("journal_entries.id", ondelete="RESTRICT")
    )
    created_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT")
    )

    invoice: Mapped[Invoice] = relationship(lazy="joined")
    policy: Mapped[Policy] = relationship(lazy="joined")
    insurer: Mapped[Insurer] = relationship(lazy="joined")
    patient: Mapped[Patient] = relationship(lazy="joined")
    lines: Mapped[list["ClaimLine"]] = relationship(order_by="ClaimLine.line_no", lazy="selectin")
    events: Mapped[list["ClaimEvent"]] = relationship(order_by="ClaimEvent.id", lazy="selectin")

    @property
    def outstanding(self) -> Decimal:
        """Approved by the insurer but not yet paid. Partial approvals already carry their
        shortfall in adjustment_amount, so: claimed - paid - adjusted."""
        if self.status not in (ClaimStatus.APPROVED, ClaimStatus.PARTIALLY_APPROVED):
            return Decimal("0.00")
        return self.insurer_amount - self.paid_amount - self.adjustment_amount


class ClaimLine(TimestampMixin, Base):
    __tablename__ = "claim_lines"
    __table_args__ = (
        CheckConstraint("billed_amount >= 0 AND insurer_amount >= 0", name="non_negative"),
        CheckConstraint("insurer_amount <= billed_amount", name="insurer_within_billed"),
        UniqueConstraint("claim_id", "line_no", name="uq_claim_lines_claim_line"),
    )

    id: Mapped[IntPK]
    claim_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("claims.id", ondelete="RESTRICT"), index=True
    )
    line_no: Mapped[int] = mapped_column(Integer)
    invoice_line_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("invoice_lines.id", ondelete="RESTRICT")
    )
    service_code: Mapped[str] = mapped_column(String(30), default="", server_default="")
    description: Mapped[str] = mapped_column(String(300))
    service_date: Mapped[date] = mapped_column(Date)
    billed_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    insurer_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))


class ClaimEvent(Base):
    """Append-only timeline of a claim (UPDATE/DELETE rejected by trigger)."""

    __tablename__ = "claim_events"

    id: Mapped[IntPK]
    claim_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("claims.id", ondelete="RESTRICT"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(30))
    from_status: Mapped[str | None] = mapped_column(String(30))
    to_status: Mapped[str | None] = mapped_column(String(30))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    denial_code: Mapped[str | None] = mapped_column(String(20))
    note: Mapped[str] = mapped_column(Text, default="", server_default="")
    actor_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT")
    )
    actor_label: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ClaimAttachment(TimestampMixin, Base):
    __tablename__ = "claim_attachments"
    __table_args__ = (
        CheckConstraint("size_bytes > 0 AND size_bytes <= 5242880", name="valid_size"),
    )

    id: Mapped[IntPK]
    claim_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("claims.id", ondelete="RESTRICT"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    data: Mapped[bytes] = deferred(mapped_column(LargeBinary, nullable=False))
    uploaded_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT")
    )


class Remittance(TimestampMixin, Base):
    __tablename__ = "remittances"
    __table_args__ = (
        CheckConstraint(_in("status", ("imported", "posted")), name="valid_status"),
        CheckConstraint("total_amount >= 0 AND posted_amount >= 0", name="non_negative"),
        UniqueConstraint("insurer_id", "reference", name="uq_remittances_insurer_reference"),
    )

    id: Mapped[IntPK]
    remittance_number: Mapped[str] = mapped_column(String(20), unique=True)
    insurer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("insurers.id", ondelete="RESTRICT"), index=True
    )
    reference: Mapped[str] = mapped_column(String(80))  # payer's EFT / cheque number
    payment_date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(20), default=RemittanceStatus.IMPORTED, index=True)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    posted_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    source_filename: Mapped[str] = mapped_column(String(255), default="", server_default="")
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    imported_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT")
    )

    insurer: Mapped[Insurer] = relationship(lazy="joined")
    lines: Mapped[list["RemittanceLine"]] = relationship(
        order_by="RemittanceLine.line_no", lazy="selectin"
    )


class RemittanceLine(TimestampMixin, Base):
    __tablename__ = "remittance_lines"
    __table_args__ = (
        CheckConstraint("paid_amount >= 0", name="non_negative"),
        CheckConstraint(
            _in("match_status", tuple(m.value for m in MatchStatus)), name="valid_match_status"
        ),
        UniqueConstraint("remittance_id", "line_no", name="uq_remittance_lines_remit_line"),
    )

    id: Mapped[IntPK]
    remittance_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("remittances.id", ondelete="RESTRICT"), index=True
    )
    line_no: Mapped[int] = mapped_column(Integer)
    claim_number: Mapped[str] = mapped_column(String(40))
    claim_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("claims.id", ondelete="RESTRICT"), index=True
    )
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    expected_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    match_status: Mapped[str] = mapped_column(String(20), index=True)
    message: Mapped[str] = mapped_column(Text, default="", server_default="")
    remark: Mapped[str] = mapped_column(String(255), default="", server_default="")
    payment_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("payments.id", ondelete="RESTRICT")
    )
