from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.core.money import Money
from app.models.ledger import AccountType, EntryStatus, PeriodStatus
from app.schemas.common import OrmModel

CODE_PATTERN = r"^[A-Z0-9][A-Z0-9-]{0,19}$"


# ------------------------------------------------------------------ org


class DepartmentOut(OrmModel):
    id: int
    code: str
    name: str
    is_active: bool
    revenue_account_id: int | None


class DepartmentCreate(BaseModel):
    code: str = Field(pattern=CODE_PATTERN)
    name: str = Field(min_length=1, max_length=120)
    revenue_account_id: int | None = None


class CostCenterOut(OrmModel):
    id: int
    code: str
    name: str
    department_id: int | None
    is_active: bool


class CostCenterCreate(BaseModel):
    code: str = Field(pattern=CODE_PATTERN)
    name: str = Field(min_length=1, max_length=120)
    department_id: int | None = None


# ------------------------------------------------------------------ accounts


class AccountOut(OrmModel):
    id: int
    code: str
    name: str
    type: AccountType
    parent_id: int | None
    cost_center_id: int | None
    is_header: bool
    is_active: bool
    description: str
    normal_balance: Literal["debit", "credit"]


class AccountCreate(BaseModel):
    code: str = Field(pattern=CODE_PATTERN)
    name: str = Field(min_length=1, max_length=160)
    type: AccountType
    parent_id: int | None = None
    cost_center_id: int | None = None
    is_header: bool = False
    description: str = Field(default="", max_length=2000)


class AccountUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    parent_id: int | None = None
    clear_parent: bool = False
    cost_center_id: int | None = None
    clear_cost_center: bool = False
    is_active: bool | None = None
    description: str | None = Field(default=None, max_length=2000)


# ------------------------------------------------------------------ periods


class FiscalPeriodOut(OrmModel):
    id: int
    name: str
    start_date: date
    end_date: date
    status: PeriodStatus
    closed_at: datetime | None
    closed_by_id: int | None


class FiscalPeriodCreate(BaseModel):
    name: str = Field(min_length=1, max_length=20)
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def _range(self) -> "FiscalPeriodCreate":
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class CloseCheckOut(BaseModel):
    period_id: int
    can_close: bool
    total_debits: Money
    total_credits: Money
    trial_balance_balanced: bool
    pending_entries: int
    earlier_open_periods: list[str]
    problems: list[str]


# ------------------------------------------------------------------ journal


class JournalLineIn(BaseModel):
    account_id: int
    debit: Money = Field(default=Decimal("0.00"), ge=0)
    credit: Money = Field(default=Decimal("0.00"), ge=0)
    description: str = Field(default="", max_length=500)
    department_id: int | None = None
    cost_center_id: int | None = None


class JournalEntryCreate(BaseModel):
    entry_date: date
    memo: str = Field(min_length=1, max_length=2000)
    lines: list[JournalLineIn] = Field(min_length=2, max_length=200)


class ReasonIn(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class ReverseIn(ReasonIn):
    reversal_date: date | None = None


class JournalLineOut(OrmModel):
    line_no: int
    account_id: int
    account_code: str
    account_name: str
    debit: Money
    credit: Money
    description: str
    department_id: int | None
    cost_center_id: int | None


class JournalEntryOut(BaseModel):
    id: int
    entry_number: str
    entry_date: date
    memo: str
    source_type: str
    source_id: str | None
    status: EntryStatus
    total: Money
    reversal_of_id: int | None
    reversed_by_id: int | None
    reversal_reason: str | None
    created_by_id: int | None
    approved_by_id: int | None
    posted_at: datetime | None
    rejection_reason: str | None
    created_at: datetime
    lines: list[JournalLineOut]


# ------------------------------------------------------------------ reports


class TrialBalanceRowOut(OrmModel):
    account_id: int
    code: str
    name: str
    type: AccountType
    debit: Money
    credit: Money
    balance_debit: Money
    balance_credit: Money


class TrialBalanceOut(OrmModel):
    date_from: date | None
    date_to: date | None
    rows: list[TrialBalanceRowOut]
    total_debit: Money
    total_credit: Money
    total_balance_debit: Money
    total_balance_credit: Money
    balanced: bool


class StatementLineOut(OrmModel):
    account_id: int
    code: str
    name: str
    amount: Money


class StatementSectionOut(OrmModel):
    title: str
    lines: list[StatementLineOut]
    total: Money


class IncomeStatementOut(OrmModel):
    date_from: date | None
    date_to: date | None
    revenue: StatementSectionOut
    expenses: StatementSectionOut
    net_income: Money


class BalanceSheetOut(OrmModel):
    as_of: date
    assets: StatementSectionOut
    liabilities: StatementSectionOut
    equity: StatementSectionOut
    total_assets: Money
    total_liabilities_and_equity: Money
    balanced: bool


class LedgerRowOut(OrmModel):
    entry_id: int
    entry_number: str
    entry_date: date
    memo: str
    source_type: str
    line_description: str
    debit: Money
    credit: Money
    running_balance: Money


class AccountLedgerOut(OrmModel):
    account_id: int
    code: str
    name: str
    normal_balance: Literal["debit", "credit"]
    date_from: date | None
    date_to: date | None
    opening_balance: Money
    closing_balance: Money
    rows: list[LedgerRowOut]
    total: int
    page: int
    page_size: int
