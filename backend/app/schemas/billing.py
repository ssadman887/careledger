from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, model_validator

from app.core.money import Money, StrictDecimal
from app.models.billing import InvoiceStatus, PaymentKind, PaymentMethod, RefundStatus
from app.models.patients import VisitStatus, VisitType
from app.schemas.common import OrmModel

Rate = Annotated[
    StrictDecimal,
    Field(ge=0, lt=1, max_digits=5, decimal_places=4, description="Fraction, e.g. 0.0500 = 5%"),
]
Quantity = Annotated[StrictDecimal, Field(gt=0, max_digits=10, decimal_places=2)]
Percent = Annotated[StrictDecimal, Field(ge=0, le=100, max_digits=5, decimal_places=2)]
CODE = r"^[A-Z0-9][A-Z0-9-]{0,29}$"


# ------------------------------------------------------------------ patients & visits


class PatientOut(OrmModel):
    id: int
    mrn: str
    first_name: str
    last_name: str
    full_name: str
    date_of_birth: date
    sex: str
    phone: str
    email: str
    created_at: datetime


class PatientDetailOut(PatientOut):
    deposit_balance: Money


class PatientCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    date_of_birth: date
    sex: str = Field(default="unknown", pattern=r"^(female|male|other|unknown)$")
    phone: str = Field(default="", max_length=40)
    email: str = Field(default="", max_length=255)


class PatientUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=80)
    last_name: str | None = Field(default=None, min_length=1, max_length=80)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=255)


class VisitOut(OrmModel):
    id: int
    visit_number: str
    patient_id: int
    patient_name: str
    department_id: int
    department_name: str
    visit_type: VisitType
    admit_date: date
    discharge_date: date | None
    attending_physician: str
    status: VisitStatus


class VisitCreate(BaseModel):
    patient_id: int
    department_id: int
    visit_type: VisitType
    admit_date: date
    discharge_date: date | None = None
    attending_physician: str = Field(default="", max_length=120)


class VisitStatusIn(BaseModel):
    status: VisitStatus
    discharge_date: date | None = None


# ------------------------------------------------------------------ catalog


class ServiceOut(OrmModel):
    id: int
    code: str
    name: str
    department_id: int
    tax_rate: Decimal
    is_active: bool
    current_price: Money | None = None


class ServiceCreate(BaseModel):
    code: str = Field(pattern=CODE)
    name: str = Field(min_length=1, max_length=200)
    department_id: int
    tax_rate: Rate = Decimal("0")


class ServiceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    tax_rate: Rate | None = None
    is_active: bool | None = None


class PriceListOut(OrmModel):
    id: int
    code: str
    name: str
    is_default: bool
    is_active: bool


class PriceListCreate(BaseModel):
    code: str = Field(pattern=CODE)
    name: str = Field(min_length=1, max_length=120)
    is_default: bool = False


class PriceItemOut(OrmModel):
    id: int
    price_list_id: int
    service_id: int
    unit_price: Money
    effective_from: date
    effective_to: date | None


class PriceItemCreate(BaseModel):
    service_id: int
    unit_price: Money = Field(ge=0)
    effective_from: date


# ------------------------------------------------------------------ invoices


class InvoiceLineIn(BaseModel):
    service_id: int | None = None
    description: str | None = Field(default=None, max_length=300)
    department_id: int | None = None
    unit_price: Money | None = Field(default=None, ge=0)
    quantity: Quantity = Decimal("1")
    service_date: date | None = None
    discount_percent: Percent | None = None
    discount_amount: Money | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _one_discount(self) -> "InvoiceLineIn":
        if self.discount_percent is not None and self.discount_amount is not None:
            raise ValueError("give discount_percent or discount_amount, not both")
        return self


class InvoiceCreate(BaseModel):
    patient_id: int
    visit_id: int | None = None
    price_list_id: int | None = None
    notes: str = Field(default="", max_length=2000)
    lines: list[InvoiceLineIn] = Field(default_factory=list, max_length=200)


class InvoiceUpdate(BaseModel):
    notes: str | None = Field(default=None, max_length=2000)
    lines: list[InvoiceLineIn] | None = Field(default=None, max_length=200)


class InvoiceIssueIn(BaseModel):
    invoice_date: date | None = None


class ReasonIn(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class InvoiceLineOut(OrmModel):
    line_no: int
    service_id: int | None
    description: str
    department_id: int
    service_date: date
    quantity: Decimal
    unit_price: Money
    gross_amount: Money
    discount_amount: Money
    tax_rate: Decimal
    tax_amount: Money
    line_total: Money


class InvoiceSummaryOut(OrmModel):
    id: int
    invoice_number: str
    patient_id: int
    patient_name: str
    patient_mrn: str
    visit_id: int | None
    status: InvoiceStatus
    invoice_date: date | None
    due_date: date | None
    total: Money
    amount_paid: Money
    balance_due: Money
    created_at: datetime


class InvoiceOut(InvoiceSummaryOut):
    visit_number: str | None
    price_list_id: int
    subtotal: Money
    discount_total: Money
    tax_total: Money
    notes: str
    issue_entry_id: int | None
    void_entry_id: int | None
    issued_at: datetime | None
    voided_at: datetime | None
    void_reason: str | None
    lines: list[InvoiceLineOut]


# ------------------------------------------------------------------ payments & refunds


class PaymentIn(BaseModel):
    """Patient payment against an invoice, or a deposit on account when invoice_id is omitted."""

    invoice_id: int | None = None
    patient_id: int | None = None
    method: PaymentMethod
    amount: Money = Field(gt=0)
    received_on: date | None = None
    reference: str = Field(
        default="",
        max_length=100,
        description="Card: last 4 digits only. Bank transfer: bank reference.",
    )
    notes: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def _target(self) -> "PaymentIn":
        if (self.invoice_id is None) == (self.patient_id is None):
            raise ValueError("give invoice_id (invoice payment) or patient_id (deposit), not both")
        return self


class ApplyDepositIn(BaseModel):
    amount: Money = Field(gt=0)
    applied_on: date | None = None


class RefundIn(BaseModel):
    amount: Money = Field(gt=0)
    reason: str = Field(min_length=1, max_length=2000)


class DecisionIn(BaseModel):
    note: str = Field(default="", max_length=2000)


class PaymentOut(OrmModel):
    id: int
    payment_number: str
    kind: PaymentKind
    patient_id: int
    patient_name: str
    patient_mrn: str
    invoice_id: int | None
    invoice_number: str | None
    method: PaymentMethod
    amount: Money
    refunded_amount: Money
    received_on: date
    reference: str
    notes: str
    journal_entry_id: int | None
    created_at: datetime


class RefundOut(OrmModel):
    id: int
    refund_number: str
    payment_id: int
    payment_number: str
    patient_name: str
    amount: Money
    reason: str
    status: RefundStatus
    refunded_on: date | None
    journal_entry_id: int | None
    requested_by_id: int | None
    decided_by_id: int | None
    decision_note: str | None
    created_at: datetime


class PaymentDetailOut(PaymentOut):
    refunds: list[RefundOut]
