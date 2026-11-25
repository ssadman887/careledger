"""Schemas for approvals, accounts receivable and accounts payable."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.core.money import Money, StrictDecimal
from app.models.ap import BillStatus, MatchResult, POStatus
from app.models.approvals import ApprovalKind, ApprovalStatus
from app.models.ar import WriteOffStatus
from app.schemas.common import OrmModel

Quantity = Annotated[StrictDecimal, Field(gt=0, max_digits=10, decimal_places=2)]


# ------------------------------------------------------------------ approvals


class ApprovalCommentOut(OrmModel):
    id: int
    author_label: str
    body: str
    created_at: datetime


class ApprovalOut(OrmModel):
    id: int
    kind: ApprovalKind
    entity_type: str
    entity_id: int
    reference: str
    summary: str
    amount: Money
    threshold: Money
    approver_role: str
    status: ApprovalStatus
    requested_by_id: int | None
    requested_by_label: str
    decided_by_label: str | None
    decided_at: datetime | None
    decision_note: str | None
    created_at: datetime
    comments: list[ApprovalCommentOut]
    can_decide: bool = False


class DecisionIn(BaseModel):
    approve: bool
    note: str = Field(default="", max_length=2000)


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


class ApprovalPolicyOut(OrmModel):
    kind: ApprovalKind
    threshold: Money
    approver_role: str
    description: str
    is_active: bool


class ApprovalPolicyUpdate(BaseModel):
    threshold: Money | None = Field(default=None, ge=0)
    approver_role: str | None = Field(default=None, max_length=50)
    is_active: bool | None = None


class PendingCountOut(BaseModel):
    pending: int


# ------------------------------------------------------------------ AR


class AgingRowOut(BaseModel):
    party_id: int
    name: str
    code: str
    buckets: dict[str, Money]
    total: Money


class AgingReportOut(BaseModel):
    as_of: date
    by: Literal["patient", "insurer"]
    buckets: list[str]
    rows: list[AgingRowOut]
    totals: dict[str, Money]
    total: Money


class DunningNoticeOut(OrmModel):
    id: int
    invoice_id: int
    invoice_number: str
    patient_id: int
    patient_name: str
    level: int
    days_overdue: int
    amount_due: Money
    channel: str
    message: str
    sent_at: datetime


class DunningRunIn(BaseModel):
    as_of: date | None = None


class DunningRunOut(BaseModel):
    created: int
    notices: list[DunningNoticeOut]


class WriteOffIn(BaseModel):
    invoice_id: int
    amount: Money = Field(gt=0)
    reason: str = Field(min_length=1, max_length=2000)


class WriteOffOut(BaseModel):
    id: int
    write_off_number: str
    invoice_id: int
    invoice_number: str
    patient_name: str
    amount: Money
    reason: str
    status: WriteOffStatus
    posted_on: date | None
    journal_entry_id: int | None
    created_at: datetime


# ------------------------------------------------------------------ AP


class VendorOut(BaseModel):
    id: int
    code: str
    name: str
    email: str
    tax_id: str
    bank_reference: str
    payment_terms_days: int
    default_expense_account_id: int | None
    is_active: bool


class VendorCreate(BaseModel):
    code: str = Field(pattern=r"^[A-Z0-9][A-Z0-9-]{0,19}$")
    name: str = Field(min_length=1, max_length=160)
    email: str = Field(default="", max_length=255)
    tax_id: str = Field(default="", max_length=40)
    bank_reference: str = Field(default="", max_length=80)
    payment_terms_days: int = Field(default=30, ge=0, le=180)
    default_expense_account_id: int | None = None


class VendorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    email: str | None = Field(default=None, max_length=255)
    bank_reference: str | None = Field(default=None, max_length=80)
    payment_terms_days: int | None = Field(default=None, ge=0, le=180)
    is_active: bool | None = None


class APLineIn(BaseModel):
    description: str = Field(min_length=1, max_length=300)
    account_id: int
    quantity: Quantity = Decimal("1")
    unit_price: Money = Field(ge=0)
    department_id: int | None = None


class APLineOut(OrmModel):
    line_no: int
    description: str
    account_id: int
    quantity: Decimal
    unit_price: Money
    amount: Money


class POLineOut(APLineOut):
    received_quantity: Decimal


class PurchaseOrderCreate(BaseModel):
    vendor_id: int
    order_date: date
    expected_date: date | None = None
    notes: str = Field(default="", max_length=2000)
    lines: list[APLineIn] = Field(min_length=1, max_length=100)


class PurchaseOrderOut(BaseModel):
    id: int
    po_number: str
    vendor_id: int
    vendor_name: str
    status: POStatus
    order_date: date
    expected_date: date | None
    received_on: date | None
    total: Money
    billed: Money
    notes: str
    lines: list[POLineOut]


class BillCreate(BaseModel):
    vendor_id: int
    vendor_invoice_number: str = Field(min_length=1, max_length=60)
    bill_date: date
    due_date: date | None = None
    purchase_order_id: int | None = None
    notes: str = Field(default="", max_length=2000)
    lines: list[APLineIn] | None = Field(
        default=None, max_length=100, description="Omit to copy the purchase order's lines"
    )


class ScheduleIn(BaseModel):
    pay_on: date


class VendorPaymentIn(BaseModel):
    amount: Money | None = Field(default=None, gt=0, description="Defaults to the full balance")
    paid_on: date | None = None
    method: Literal["bank_transfer", "cheque"] = "bank_transfer"
    reference: str = Field(default="", max_length=80)


class ReasonIn(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class PaymentRunIn(BaseModel):
    as_of: date | None = None


class VendorPaymentOut(BaseModel):
    id: int
    payment_number: str
    vendor_bill_id: int
    bill_number: str
    vendor_id: int
    vendor_name: str
    amount: Money
    paid_on: date
    method: str
    reference: str
    journal_entry_id: int | None


class VendorBillOut(BaseModel):
    id: int
    bill_number: str
    vendor_id: int
    vendor_name: str
    vendor_invoice_number: str
    purchase_order_id: int | None
    po_number: str | None
    status: BillStatus
    match_status: MatchResult
    match_note: str
    bill_date: date
    due_date: date
    scheduled_payment_date: date | None
    total: Money
    amount_paid: Money
    balance_due: Money
    notes: str
    approval_entry_id: int | None
    lines: list[APLineOut]


class PaymentRunOut(BaseModel):
    paid: int
    payments: list[VendorPaymentOut]
