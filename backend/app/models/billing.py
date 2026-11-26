"""Patient billing: invoices, invoice lines, payments, refunds.

Financial records are never deleted (status fields only). Invoice lines are frozen once the
invoice leaves draft (DB trigger in migration 0007).
"""

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
from app.models.patients import Patient, Visit


class InvoiceStatus(StrEnum):
    DRAFT = "draft"
    ISSUED = "issued"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    VOID = "void"


class PaymentMethod(StrEnum):
    CASH = "cash"
    CARD = "card"
    BANK_TRANSFER = "bank_transfer"
    DEPOSIT = "deposit"  # applying a patient's unapplied deposit to an invoice
    INSURANCE = "insurance"  # insurer remittances (Phase 3)


class PaymentKind(StrEnum):
    INVOICE = "invoice"  # settles an invoice
    DEPOSIT = "deposit"  # unapplied money received in advance


class RefundStatus(StrEnum):
    PENDING_APPROVAL = "pending_approval"
    COMPLETED = "completed"
    REJECTED = "rejected"


class Invoice(TimestampMixin, Base):
    __tablename__ = "invoices"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','issued','partially_paid','paid','void')", name="valid_status"
        ),
        CheckConstraint(
            "subtotal >= 0 AND discount_total >= 0 AND tax_total >= 0 AND total >= 0",
            name="non_negative_totals",
        ),
        CheckConstraint("total = subtotal - discount_total + tax_total", name="total_formula"),
        CheckConstraint(
            "amount_paid >= 0 AND adjusted_amount >= 0 AND amount_paid + adjusted_amount <= total",
            name="settled_within_total",
        ),
        CheckConstraint(
            "insurance_pending >= 0 AND insurance_pending <= total - amount_paid - adjusted_amount",
            name="insurance_within_balance",
        ),
        Index("ix_invoices_status_date", "status", "invoice_date"),
        # Overdue balances, dunning and the revenue dashboard filter open invoices by due date.
        Index("ix_invoices_status_due", "status", "due_date"),
    )

    id: Mapped[IntPK]
    invoice_number: Mapped[str] = mapped_column(String(20), unique=True)
    patient_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("patients.id", ondelete="RESTRICT"), index=True
    )
    visit_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("visits.id", ondelete="RESTRICT"), index=True
    )
    price_list_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("price_lists.id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(String(20), default=InvoiceStatus.DRAFT, index=True)
    invoice_date: Mapped[date | None] = mapped_column(Date, index=True)
    due_date: Mapped[date | None] = mapped_column(Date, index=True)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    discount_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    tax_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    amount_paid: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    # Written down without cash: contractual adjustments (Phase 3), write-offs (Phase 4).
    adjusted_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0"), server_default="0"
    )
    # Part of the balance currently expected from an insurer (sits in AR - Insurers).
    insurance_pending: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0"), server_default="0"
    )
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    issue_entry_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("journal_entries.id", ondelete="RESTRICT")
    )
    void_entry_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("journal_entries.id", ondelete="RESTRICT")
    )
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    void_reason: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT")
    )

    patient: Mapped[Patient] = relationship(lazy="joined")
    visit: Mapped[Visit | None] = relationship(lazy="joined")
    lines: Mapped[list["InvoiceLine"]] = relationship(
        back_populates="invoice",
        order_by="InvoiceLine.line_no",
        lazy="selectin",
        cascade="all, delete-orphan",
    )

    @property
    def balance_due(self) -> Decimal:
        """Everything still owed on the invoice, by patient and insurer together."""
        return self.total - self.amount_paid - self.adjusted_amount

    @property
    def patient_due(self) -> Decimal:
        """What the patient owes now (excludes amounts pending with an insurer)."""
        return self.balance_due - self.insurance_pending


class InvoiceLine(TimestampMixin, Base):
    __tablename__ = "invoice_lines"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="positive_quantity"),
        CheckConstraint("unit_price >= 0", name="non_negative_price"),
        CheckConstraint(
            "discount_amount >= 0 AND discount_amount <= gross_amount", name="valid_discount"
        ),
        CheckConstraint("tax_rate >= 0 AND tax_rate < 1", name="valid_tax_rate"),
        CheckConstraint(
            "line_total = gross_amount - discount_amount + tax_amount", name="total_formula"
        ),
        UniqueConstraint("invoice_id", "line_no", name="uq_invoice_lines_invoice_line"),
    )

    id: Mapped[IntPK]
    invoice_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("invoices.id", ondelete="CASCADE"), index=True
    )
    line_no: Mapped[int] = mapped_column(Integer)
    service_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("services.id", ondelete="RESTRICT"), index=True
    )
    description: Mapped[str] = mapped_column(String(300))
    department_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("departments.id", ondelete="RESTRICT"), index=True
    )
    service_date: Mapped[date] = mapped_column(Date)
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0"))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2))

    invoice: Mapped[Invoice] = relationship(back_populates="lines")


class Payment(TimestampMixin, Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="positive_amount"),
        CheckConstraint(
            "refunded_amount >= 0 AND refunded_amount <= amount", name="refund_within_amount"
        ),
        CheckConstraint(
            "method IN ('cash','card','bank_transfer','deposit','insurance')", name="valid_method"
        ),
        CheckConstraint("kind IN ('invoice','deposit')", name="valid_kind"),
        CheckConstraint(
            "(kind = 'invoice') = (invoice_id IS NOT NULL)", name="kind_matches_invoice"
        ),
        CheckConstraint(
            "NOT (kind = 'deposit' AND method = 'deposit')", name="deposit_not_from_deposit"
        ),
        Index("ix_payments_method_date", "method", "received_on"),
    )

    id: Mapped[IntPK]
    payment_number: Mapped[str] = mapped_column(String(20), unique=True)
    kind: Mapped[str] = mapped_column(String(10))
    patient_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("patients.id", ondelete="RESTRICT"), index=True
    )
    invoice_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("invoices.id", ondelete="RESTRICT"), index=True
    )
    method: Mapped[str] = mapped_column(String(20))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    refunded_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    received_on: Mapped[date] = mapped_column(Date, index=True)
    # Card: last 4 digits only (never a full PAN). Bank transfer: the bank's reference.
    reference: Mapped[str] = mapped_column(String(100), default="", server_default="")
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    journal_entry_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("journal_entries.id", ondelete="RESTRICT")
    )
    created_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT")
    )

    patient: Mapped[Patient] = relationship(lazy="joined")
    invoice: Mapped[Invoice | None] = relationship(lazy="joined")


class Refund(TimestampMixin, Base):
    __tablename__ = "refunds"
    __table_args__ = (
        CheckConstraint("amount > 0", name="positive_amount"),
        CheckConstraint(
            "status IN ('pending_approval','completed','rejected')", name="valid_status"
        ),
    )

    id: Mapped[IntPK]
    refund_number: Mapped[str] = mapped_column(String(20), unique=True)
    payment_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("payments.id", ondelete="RESTRICT"), index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), index=True)
    refunded_on: Mapped[date | None] = mapped_column(Date)
    journal_entry_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("journal_entries.id", ondelete="RESTRICT")
    )
    requested_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT")
    )
    decided_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT")
    )
    decision_note: Mapped[str | None] = mapped_column(Text)

    payment: Mapped[Payment] = relationship(lazy="joined")
