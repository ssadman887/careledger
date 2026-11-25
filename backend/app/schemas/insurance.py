from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from app.core.money import Money, StrictDecimal
from app.models.insurance import ClaimStatus, MatchStatus, RemittanceStatus
from app.schemas.common import OrmModel

Rate = Annotated[StrictDecimal, Field(ge=0, le=1, max_digits=5, decimal_places=4)]
Percent = Annotated[StrictDecimal, Field(ge=0, le=100, max_digits=5, decimal_places=2)]
CODE = r"^[A-Z0-9][A-Z0-9-]{0,19}$"


# ------------------------------------------------------------------ insurers & policies


class InsurerOut(OrmModel):
    id: int
    code: str
    name: str
    payer_id: str
    contact_email: str
    is_active: bool
    approval_rate: Decimal
    partial_rate: Decimal
    denial_rate: Decimal


class InsurerCreate(BaseModel):
    code: str = Field(pattern=CODE)
    name: str = Field(min_length=1, max_length=160)
    payer_id: str = Field(default="", max_length=40)
    contact_email: str = Field(default="", max_length=255)
    approval_rate: Rate = Decimal("0.7")
    partial_rate: Rate = Decimal("0.2")
    denial_rate: Rate = Decimal("0.1")


class InsurerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    contact_email: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None
    approval_rate: Rate | None = None
    partial_rate: Rate | None = None
    denial_rate: Rate | None = None

    @model_validator(mode="after")
    def _all_rates_or_none(self) -> "InsurerUpdate":
        rates = (self.approval_rate, self.partial_rate, self.denial_rate)
        if any(r is not None for r in rates) and any(r is None for r in rates):
            raise ValueError("give all three rates together")
        return self


class PolicyOut(BaseModel):
    id: int
    policy_number: str
    patient_id: int
    patient_name: str
    insurer_id: int
    insurer_name: str
    plan_name: str
    coverage_percent: Decimal
    copay: Money
    deductible: Money
    annual_limit: Money
    effective_from: date
    effective_to: date | None
    is_active: bool


class PolicyCreate(BaseModel):
    patient_id: int
    insurer_id: int
    policy_number: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9-]+$")
    plan_name: str = Field(min_length=1, max_length=120)
    coverage_percent: Percent
    copay: Money = Field(default=Decimal("0.00"), ge=0)
    deductible: Money = Field(default=Decimal("0.00"), ge=0)
    annual_limit: Money = Field(ge=0)
    effective_from: date
    effective_to: date | None = None


class PolicyStatusIn(BaseModel):
    is_active: bool


class DenialCodeOut(OrmModel):
    code: str
    description: str
    patient_responsibility: bool


# ------------------------------------------------------------------ claims


class CoveragePreviewOut(BaseModel):
    policy_id: int
    invoice_id: int
    billed: Money
    collectible: Money
    deductible_met_before: Money
    insurer_used_before: Money
    copay: Money
    deductible: Money
    coinsurance: Money
    over_limit: Money
    insurer_amount: Money
    patient_amount: Money


class ClaimCreate(BaseModel):
    invoice_id: int
    policy_id: int


class NoteIn(BaseModel):
    note: str = Field(default="", max_length=2000)


class RequiredNoteIn(BaseModel):
    note: str = Field(min_length=1, max_length=2000)


class AdjudicateIn(BaseModel):
    """Leave `outcome` empty to let the mock insurer decide (deterministic per claim)."""

    outcome: Literal["approve", "partial", "deny"] | None = None
    approved_amount: Money | None = Field(default=None, gt=0)
    denial_code: str | None = Field(default=None, max_length=20)


class ClaimLineOut(OrmModel):
    line_no: int
    service_code: str
    description: str
    service_date: date
    billed_amount: Money
    insurer_amount: Money


class ClaimEventOut(OrmModel):
    id: int
    event_type: str
    from_status: str | None
    to_status: str | None
    amount: Money | None
    denial_code: str | None
    note: str
    actor_label: str
    created_at: datetime


class ClaimAttachmentOut(OrmModel):
    id: int
    filename: str
    content_type: str
    size_bytes: int
    created_at: datetime


class ClaimSummaryOut(BaseModel):
    id: int
    claim_number: str
    status: ClaimStatus
    invoice_id: int
    invoice_number: str
    patient_id: int
    patient_name: str
    patient_mrn: str
    insurer_id: int
    insurer_name: str
    service_date: date
    billed_amount: Money
    insurer_amount: Money
    patient_amount: Money
    approved_amount: Money
    paid_amount: Money
    outstanding: Money
    denial_code: str | None
    created_at: datetime


class ClaimOut(ClaimSummaryOut):
    policy_id: int
    policy_number: str
    plan_name: str
    copay_amount: Money
    deductible_amount: Money
    coinsurance_amount: Money
    over_limit_amount: Money
    adjustment_amount: Money
    denial_note: str | None
    denial_description: str | None
    appeal_count: int
    submitted_at: datetime | None
    adjudicated_at: datetime | None
    transfer_entry_id: int | None
    allowed_transitions: list[str]
    lines: list[ClaimLineOut]
    events: list[ClaimEventOut]
    attachments: list[ClaimAttachmentOut]


class ClaimCountsOut(BaseModel):
    counts: dict[str, int]


class BatchResultOut(BaseModel):
    processed: int
    claims: list[ClaimSummaryOut]


# ------------------------------------------------------------------ remittances


class RemittanceLineOut(OrmModel):
    line_no: int
    claim_number: str
    claim_id: int | None
    paid_amount: Money
    expected_amount: Money | None
    match_status: MatchStatus
    message: str
    remark: str
    payment_id: int | None


class RemittanceSummaryOut(BaseModel):
    id: int
    remittance_number: str
    insurer_id: int
    insurer_name: str
    reference: str
    payment_date: date
    status: RemittanceStatus
    total_amount: Money
    posted_amount: Money
    line_count: int
    counts: dict[str, int]
    created_at: datetime


class RemittanceOut(RemittanceSummaryOut):
    source_filename: str
    posted_at: datetime | None
    lines: list[RemittanceLineOut]
