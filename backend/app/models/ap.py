"""Accounts payable: vendors, purchase orders, vendor bills (three-way match), vendor payments."""

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


class POStatus(StrEnum):
    DRAFT = "draft"
    ISSUED = "issued"
    RECEIVED = "received"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class BillStatus(StrEnum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    REJECTED = "rejected"
    VOID = "void"


class MatchResult(StrEnum):
    NO_PO = "no_po"  # two-way: no purchase order to match
    MATCHED = "matched"  # PO received and bill within PO amount
    NOT_RECEIVED = "not_received"  # goods/services not yet received
    VARIANCE = "variance"  # bill amount differs from PO


class Vendor(TimestampMixin, Base):
    __tablename__ = "vendors"
    __table_args__ = (CheckConstraint("payment_terms_days BETWEEN 0 AND 180", name="valid_terms"),)

    id: Mapped[IntPK]
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str] = mapped_column(String(255), default="", server_default="")
    tax_id: Mapped[str] = mapped_column(String(40), default="", server_default="")
    bank_reference: Mapped[str] = mapped_column(String(80), default="", server_default="")
    payment_terms_days: Mapped[int] = mapped_column(Integer, default=30, server_default="30")
    default_expense_account_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="RESTRICT")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class PurchaseOrder(TimestampMixin, Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','issued','received','closed','cancelled')", name="valid_status"
        ),
        CheckConstraint("total >= 0", name="non_negative_total"),
    )

    id: Mapped[IntPK]
    po_number: Mapped[str] = mapped_column(String(20), unique=True)
    vendor_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vendors.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), default=POStatus.DRAFT, index=True)
    order_date: Mapped[date] = mapped_column(Date, index=True)
    expected_date: Mapped[date | None] = mapped_column(Date)
    received_on: Mapped[date | None] = mapped_column(Date)
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT")
    )

    vendor: Mapped[Vendor] = relationship(lazy="joined")
    lines: Mapped[list["PurchaseOrderLine"]] = relationship(
        order_by="PurchaseOrderLine.line_no", lazy="selectin", cascade="all, delete-orphan"
    )


class PurchaseOrderLine(TimestampMixin, Base):
    __tablename__ = "purchase_order_lines"
    __table_args__ = (
        CheckConstraint("quantity > 0 AND unit_price >= 0 AND amount >= 0", name="valid_amounts"),
        CheckConstraint("received_quantity >= 0", name="non_negative_received"),
        UniqueConstraint("purchase_order_id", "line_no", name="uq_po_lines_po_line"),
    )

    id: Mapped[IntPK]
    purchase_order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("purchase_orders.id", ondelete="CASCADE"), index=True
    )
    line_no: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String(300))
    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="RESTRICT")
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    received_quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))


class VendorBill(TimestampMixin, Base):
    __tablename__ = "vendor_bills"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','pending_approval','approved','partially_paid','paid',"
            "'rejected','void')",
            name="valid_status",
        ),
        CheckConstraint(
            "match_status IN ('no_po','matched','not_received','variance')", name="valid_match"
        ),
        CheckConstraint(
            "total >= 0 AND amount_paid >= 0 AND amount_paid <= total", name="paid_within_total"
        ),
        UniqueConstraint(
            "vendor_id", "vendor_invoice_number", name="uq_vendor_bills_vendor_invoice"
        ),
        Index("ix_vendor_bills_status_due", "status", "due_date"),
    )

    id: Mapped[IntPK]
    bill_number: Mapped[str] = mapped_column(String(20), unique=True)
    vendor_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vendors.id", ondelete="RESTRICT"), index=True
    )
    vendor_invoice_number: Mapped[str] = mapped_column(String(60))
    purchase_order_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("purchase_orders.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), default=BillStatus.DRAFT, index=True)
    match_status: Mapped[str] = mapped_column(String(20), default=MatchResult.NO_PO)
    match_note: Mapped[str] = mapped_column(String(300), default="", server_default="")
    bill_date: Mapped[date] = mapped_column(Date, index=True)
    due_date: Mapped[date] = mapped_column(Date, index=True)
    scheduled_payment_date: Mapped[date | None] = mapped_column(Date, index=True)
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    amount_paid: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    approval_entry_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("journal_entries.id", ondelete="RESTRICT")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT")
    )

    vendor: Mapped[Vendor] = relationship(lazy="joined")
    purchase_order: Mapped[PurchaseOrder | None] = relationship(lazy="joined")
    lines: Mapped[list["VendorBillLine"]] = relationship(
        order_by="VendorBillLine.line_no", lazy="selectin", cascade="all, delete-orphan"
    )

    @property
    def balance_due(self) -> Decimal:
        return self.total - self.amount_paid


class VendorBillLine(TimestampMixin, Base):
    __tablename__ = "vendor_bill_lines"
    __table_args__ = (
        CheckConstraint("quantity > 0 AND unit_price >= 0 AND amount >= 0", name="valid_amounts"),
        UniqueConstraint("vendor_bill_id", "line_no", name="uq_bill_lines_bill_line"),
    )

    id: Mapped[IntPK]
    vendor_bill_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vendor_bills.id", ondelete="CASCADE"), index=True
    )
    line_no: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String(300))
    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="RESTRICT")
    )
    department_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("departments.id", ondelete="RESTRICT")
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))


class VendorPayment(TimestampMixin, Base):
    __tablename__ = "vendor_payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="positive_amount"),
        CheckConstraint("method IN ('bank_transfer','cheque')", name="valid_method"),
    )

    id: Mapped[IntPK]
    payment_number: Mapped[str] = mapped_column(String(20), unique=True)
    vendor_bill_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vendor_bills.id", ondelete="RESTRICT"), index=True
    )
    vendor_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vendors.id", ondelete="RESTRICT"), index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    paid_on: Mapped[date] = mapped_column(Date, index=True)
    method: Mapped[str] = mapped_column(String(20))
    reference: Mapped[str] = mapped_column(String(80), default="", server_default="")
    journal_entry_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("journal_entries.id", ondelete="RESTRICT")
    )
    created_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT")
    )

    vendor: Mapped[Vendor] = relationship(lazy="joined")
    bill: Mapped[VendorBill] = relationship(lazy="joined")
