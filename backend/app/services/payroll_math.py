"""Payroll arithmetic. Pure functions on Decimal; no database access.

Rules (docs/ARCHITECTURE.md, "Payroll"):
  1. Proration: an employee hired or terminated during the month is paid for the calendar days
     employed (both ends inclusive). Each pay component is prorated separately:
     component x days_worked / days_in_month, rounded half-up to cents.
  2. Gross = basic + housing + transport + other allowance (all prorated).
  3. Pension (employee contribution) = round(prorated basic x pension_rate).
  4. Taxable = gross - pension.
  5. Income tax: taxable is annualised (x 12), progressive slabs are applied to the annual
     amount, and the annual tax is divided by 12 and rounded half-up.
  6. Other deduction (fixed monthly amount, prorated) is capped so net pay is never negative.
  7. Net = gross - pension - income tax - other deduction.
Every intermediate is a Decimal rounded to cents, so totals equal the sum of payslips exactly.
"""

import calendar
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.core.money import quantize

ZERO = Decimal("0.00")
MONTHS = Decimal(12)


@dataclass(frozen=True)
class Slab:
    lower: Decimal
    upper: Decimal | None  # None = no upper limit
    rate: Decimal


@dataclass(frozen=True)
class SalaryStructure:
    basic: Decimal
    housing: Decimal = ZERO
    transport: Decimal = ZERO
    other_allowance: Decimal = ZERO
    pension_rate: Decimal = ZERO
    other_deduction: Decimal = ZERO


@dataclass(frozen=True)
class PayResult:
    days_in_month: int
    days_worked: int
    basic: Decimal
    housing: Decimal
    transport: Decimal
    other_allowance: Decimal
    gross: Decimal
    pension: Decimal
    taxable: Decimal
    income_tax: Decimal
    other_deduction: Decimal
    net: Decimal


def month_bounds(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def days_employed(
    year: int, month: int, hire_date: date, termination_date: date | None
) -> tuple[int, int]:
    """(days worked, days in month). Days worked is 0 if not employed at all that month."""
    first, last = month_bounds(year, month)
    start = max(first, hire_date)
    end = min(last, termination_date) if termination_date else last
    worked = (end - start).days + 1 if end >= start else 0
    return worked, last.day


def prorate(amount: Decimal, days_worked: int, days_in_month: int) -> Decimal:
    if days_worked >= days_in_month:
        return quantize(amount)
    return quantize(amount * days_worked / days_in_month)


def annual_tax(annual_income: Decimal, slabs: Sequence[Slab]) -> Decimal:
    """Progressive tax: each slab's rate applies to the part of income inside [lower, upper)."""
    tax = Decimal(0)
    for slab in sorted(slabs, key=lambda s: s.lower):
        if annual_income <= slab.lower:
            break
        top = annual_income if slab.upper is None else min(annual_income, slab.upper)
        tax += (top - slab.lower) * slab.rate
    return tax


def monthly_tax(taxable: Decimal, slabs: Sequence[Slab]) -> Decimal:
    if taxable <= 0:
        return ZERO
    return quantize(annual_tax(taxable * MONTHS, slabs) / MONTHS)


def validate_slabs(slabs: Sequence[Slab]) -> None:
    """Slabs must start at 0, be contiguous, have rates in [0, 1) and only the last open-ended."""
    if not slabs:
        raise ValueError("At least one tax slab is required")
    ordered = sorted(slabs, key=lambda s: s.lower)
    if ordered[0].lower != 0:
        raise ValueError("The first slab must start at 0")
    for i, slab in enumerate(ordered):
        if not (0 <= slab.rate < 1):
            raise ValueError("Rates must be between 0 and 1")
        last = i == len(ordered) - 1
        if slab.upper is None and not last:
            raise ValueError("Only the last slab can be open-ended")
        if slab.upper is not None and slab.upper <= slab.lower:
            raise ValueError("Each slab's upper bound must exceed its lower bound")
        if not last and ordered[i + 1].lower != slab.upper:
            raise ValueError("Slabs must be contiguous (each lower = previous upper)")


def calculate(
    structure: SalaryStructure, slabs: Sequence[Slab], *, days_worked: int, days_in_month: int
) -> PayResult:
    if not 1 <= days_worked <= days_in_month:
        raise ValueError("days_worked must be between 1 and days_in_month")
    basic = prorate(structure.basic, days_worked, days_in_month)
    housing = prorate(structure.housing, days_worked, days_in_month)
    transport = prorate(structure.transport, days_worked, days_in_month)
    other_allowance = prorate(structure.other_allowance, days_worked, days_in_month)
    gross = basic + housing + transport + other_allowance
    pension = quantize(basic * structure.pension_rate)
    taxable = gross - pension
    income_tax = monthly_tax(taxable, slabs)
    deduction = min(
        prorate(structure.other_deduction, days_worked, days_in_month), taxable - income_tax
    )
    deduction = max(deduction, ZERO)
    net = gross - pension - income_tax - deduction
    return PayResult(
        days_in_month=days_in_month,
        days_worked=days_worked,
        basic=basic,
        housing=housing,
        transport=transport,
        other_allowance=other_allowance,
        gross=gross,
        pension=pension,
        taxable=taxable,
        income_tax=income_tax,
        other_deduction=deduction,
        net=net,
    )


DEFAULT_SLABS: tuple[Slab, ...] = (
    Slab(Decimal("0.00"), Decimal("12000.00"), Decimal("0.0000")),
    Slab(Decimal("12000.00"), Decimal("40000.00"), Decimal("0.1000")),
    Slab(Decimal("40000.00"), Decimal("80000.00"), Decimal("0.2000")),
    Slab(Decimal("80000.00"), None, Decimal("0.3000")),
)
