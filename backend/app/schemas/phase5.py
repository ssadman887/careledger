"""Schemas for payroll and budgets."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.core.money import Money, StrictDecimal
from app.models.budgets import AlertLevel, BudgetStatus
from app.models.payroll import EmployeeStatus, PayrollStatus
from app.schemas.common import OrmModel

Rate = Annotated[StrictDecimal, Field(ge=0, le=1, max_digits=5, decimal_places=4)]
PensionRate = Annotated[StrictDecimal, Field(ge=0, le=0.2, max_digits=5, decimal_places=4)]
Percent = Annotated[StrictDecimal, Field(gt=0, le=100, max_digits=5, decimal_places=2)]
NonNegMoney = Annotated[Money, Field(ge=0)]


# ------------------------------------------------------------------ employees


class EmployeeOut(BaseModel):
    id: int
    employee_number: str
    first_name: str
    last_name: str
    full_name: str
    email: str
    department_id: int
    department_name: str
    position: str
    hire_date: date
    termination_date: date | None
    status: EmployeeStatus
    bank_reference: str  # masked for roles that do not run payroll
    basic_salary: Money
    housing_allowance: Money
    transport_allowance: Money
    other_allowance: Money
    monthly_gross: Money
    pension_rate: StrictDecimal
    other_deduction: Money


class EmployeeCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    email: str = Field(default="", max_length=255)
    department_id: int
    position: str = Field(min_length=1, max_length=120)
    hire_date: date
    bank_reference: str = Field(default="", max_length=80)
    basic_salary: NonNegMoney
    housing_allowance: NonNegMoney = Decimal("0")
    transport_allowance: NonNegMoney = Decimal("0")
    other_allowance: NonNegMoney = Decimal("0")
    pension_rate: PensionRate = Decimal("0.05")
    other_deduction: NonNegMoney = Decimal("0")


class EmployeeUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=80)
    last_name: str | None = Field(default=None, min_length=1, max_length=80)
    email: str | None = Field(default=None, max_length=255)
    department_id: int | None = None
    position: str | None = Field(default=None, min_length=1, max_length=120)
    bank_reference: str | None = Field(default=None, max_length=80)
    basic_salary: NonNegMoney | None = None
    housing_allowance: NonNegMoney | None = None
    transport_allowance: NonNegMoney | None = None
    other_allowance: NonNegMoney | None = None
    pension_rate: PensionRate | None = None
    other_deduction: NonNegMoney | None = None


class TerminateIn(BaseModel):
    termination_date: date


# ------------------------------------------------------------------ tax slabs


class TaxSlabIO(BaseModel):
    lower_bound: NonNegMoney
    upper_bound: NonNegMoney | None = None
    rate: Rate


class TaxTableOut(BaseModel):
    year: int
    slabs: list[TaxSlabIO]
    locked: bool
    years: list[int]


class TaxTableIn(BaseModel):
    slabs: list[TaxSlabIO] = Field(min_length=1, max_length=20)


class TaxPreviewIn(BaseModel):
    year: int
    monthly_taxable: NonNegMoney


class TaxPreviewOut(BaseModel):
    annual_taxable: Money
    annual_tax: Money
    monthly_tax: Money
    effective_rate_percent: StrictDecimal


# ------------------------------------------------------------------ runs


class PayslipOut(OrmModel):
    id: int
    payroll_run_id: int
    employee_id: int
    employee_number: str
    employee_name: str
    position: str
    department_id: int
    department_name: str = ""
    days_in_month: int
    days_worked: int
    basic: Money
    housing: Money
    transport: Money
    other_allowance: Money
    gross: Money
    pension: Money
    taxable: Money
    income_tax: Money
    other_deduction: Money
    net: Money


class DepartmentTotalOut(BaseModel):
    department_id: int
    department_name: str
    headcount: int
    gross: Money
    net: Money


class PayrollRunOut(BaseModel):
    id: int
    run_number: str
    year: int
    month: int
    period_start: date
    period_end: date
    pay_date: date
    status: PayrollStatus
    employee_count: int
    gross_total: Money
    pension_total: Money
    tax_total: Money
    other_deduction_total: Money
    net_total: Money
    error: str | None
    calculated_at: datetime | None
    posting_entry_id: int | None
    funding_entry_id: int | None
    payment_entry_id: int | None
    approved_at: datetime | None
    paid_at: datetime | None
    created_by_id: int | None
    approval_id: int | None = None


class PayrollRunDetail(PayrollRunOut):
    payslips: list[PayslipOut]
    departments: list[DepartmentTotalOut]


class PayrollRunCreate(BaseModel):
    year: int = Field(ge=2000, le=2100)
    month: int = Field(ge=1, le=12)
    pay_date: date | None = None
    background: bool = Field(
        default=True, description="Calculate in the background job (poll the run) or inline."
    )


class PayRunIn(BaseModel):
    paid_on: date | None = None


class RunDecisionIn(BaseModel):
    note: str = Field(default="", max_length=2000)


# ------------------------------------------------------------------ budgets


class BudgetLineIn(BaseModel):
    account_id: int
    annual: NonNegMoney | None = None
    monthly: list[NonNegMoney] | None = Field(default=None, min_length=12, max_length=12)


class BudgetCreate(BaseModel):
    year: int = Field(ge=2000, le=2100)
    department_id: int
    name: str = Field(default="", max_length=160)
    alert_threshold_percent: Percent = Decimal("90")
    notes: str = Field(default="", max_length=2000)
    lines: list[BudgetLineIn] = Field(min_length=1, max_length=100)


class BudgetUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=160)
    alert_threshold_percent: Percent | None = None
    notes: str | None = Field(default=None, max_length=2000)
    lines: list[BudgetLineIn] | None = Field(default=None, min_length=1, max_length=100)


class BudgetStatusIn(BaseModel):
    status: Literal["active", "archived"]


class BudgetOut(BaseModel):
    id: int
    year: int
    department_id: int
    department_name: str
    name: str
    status: BudgetStatus
    alert_threshold_percent: StrictDecimal
    notes: str
    annual_total: Money
    accounts: int
    created_at: datetime


class VarianceRowOut(BaseModel):
    account_id: int
    account_code: str
    account_name: str
    account_type: Literal["expense", "revenue"]
    budgeted: bool
    monthly_budget: list[Money]
    monthly_actual: list[Money]
    annual_budget: Money
    budget_ytd: Money
    actual_ytd: Money
    variance_ytd: Money  # positive = favourable
    percent_used: StrictDecimal | None
    status: Literal["ok", "warning", "exceeded", "unbudgeted"]


class VarianceTotals(BaseModel):
    budget_ytd: Money
    actual_ytd: Money
    variance_ytd: Money
    annual_budget: Money


class VarianceOut(BaseModel):
    budget: BudgetOut
    through_month: int
    rows: list[VarianceRowOut]
    expense_totals: VarianceTotals
    revenue_totals: VarianceTotals


class BudgetAlertOut(BaseModel):
    id: int
    budget_id: int
    budget_name: str
    department_name: str
    account_id: int
    account_code: str
    account_name: str
    month: int
    level: AlertLevel
    budget_ytd: Money
    actual_ytd: Money
    percent_used: StrictDecimal
    message: str
    created_at: datetime


class BudgetCheckIn(BaseModel):
    as_of: date | None = None


class BudgetCheckOut(BaseModel):
    created: int
    alerts: list[BudgetAlertOut]
