"""Payroll arithmetic: tax slabs, proration and rounding (Decimal throughout)."""

from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.services import payroll_math as pm
from app.services.budgets import percent, split_annual

D = Decimal
SLABS = pm.DEFAULT_SLABS  # 0-12k 0%, 12k-40k 10%, 40k-80k 20%, 80k+ 30%


# ------------------------------------------------------------------ tax slabs


@pytest.mark.parametrize(
    ("annual", "tax"),
    [
        (D("0"), D("0")),
        (D("12000"), D("0")),  # top of the 0% band
        (D("12000.01"), D("0.001")),
        (D("40000"), D("2800")),  # 28,000 x 10%
        (D("80000"), D("10800")),  # 2,800 + 40,000 x 20%
        (D("100000"), D("16800")),  # 10,800 + 20,000 x 30%
    ],
)
def test_annual_tax_is_progressive_by_band(annual: Decimal, tax: Decimal) -> None:
    assert pm.annual_tax(annual, SLABS) == tax


def test_monthly_tax_annualises_then_rounds_half_up() -> None:
    # 5,000/month -> 60,000/year -> 2,800 + 20,000 x 20% = 6,800 -> 566.666.. -> 566.67
    assert pm.monthly_tax(D("5000.00"), SLABS) == D("566.67")
    # 1,000/month is inside the 0% band.
    assert pm.monthly_tax(D("1000.00"), SLABS) == D("0.00")
    # Exactly half a cent rounds up: annual tax 0.06 / 12 = 0.005 -> 0.01
    assert pm.monthly_tax(D("1000.05"), SLABS) == D("0.01")
    assert pm.monthly_tax(D("-5"), SLABS) == D("0.00")


def test_slab_validation() -> None:
    pm.validate_slabs(SLABS)
    bad = [
        [],
        [pm.Slab(D("1"), None, D("0.1"))],  # does not start at 0
        [pm.Slab(D("0"), D("100"), D("0")), pm.Slab(D("150"), None, D("0.1"))],  # gap
        [pm.Slab(D("0"), None, D("0")), pm.Slab(D("100"), None, D("0.1"))],  # open middle
        [pm.Slab(D("0"), D("100"), D("1.0"))],  # rate 100%
        [pm.Slab(D("0"), D("0"), D("0.1"))],  # empty band
    ]
    for slabs in bad:
        with pytest.raises(ValueError):
            pm.validate_slabs(slabs)


# ------------------------------------------------------------------ proration


@pytest.mark.parametrize(
    ("hire", "termination", "expected"),
    [
        (date(2020, 1, 1), None, (30, 30)),
        (date(2026, 9, 15), None, (16, 30)),  # 15th..30th inclusive
        (date(2026, 9, 30), None, (1, 30)),
        (date(2020, 1, 1), date(2026, 9, 1), (1, 30)),
        (date(2026, 9, 10), date(2026, 9, 19), (10, 30)),
        (date(2026, 10, 1), None, (0, 30)),  # not yet hired
        (date(2020, 1, 1), date(2026, 8, 31), (0, 30)),  # already left
    ],
)
def test_days_employed(hire: date, termination: date | None, expected: tuple[int, int]) -> None:
    assert pm.days_employed(2026, 9, hire, termination) == expected


def test_february_leap_year_days() -> None:
    assert pm.days_employed(2028, 2, date(2020, 1, 1), None) == (29, 29)
    assert pm.days_employed(2026, 2, date(2020, 1, 1), None) == (28, 28)


def test_prorate_rounds_each_component_half_up() -> None:
    assert pm.prorate(D("3000.00"), 10, 30) == D("1000.00")
    assert pm.prorate(D("1000.00"), 1, 3) == D("333.33")
    assert pm.prorate(D("0.05"), 1, 2) == D("0.03")  # 0.025 -> 0.03 (half-up)
    assert pm.prorate(D("1234.56"), 31, 31) == D("1234.56")


# ------------------------------------------------------------------ full payslip


def test_full_month_payslip() -> None:
    r = pm.calculate(
        pm.SalaryStructure(
            basic=D("4000.00"),
            housing=D("600.00"),
            transport=D("150.00"),
            other_allowance=D("50.00"),
            pension_rate=D("0.05"),
            other_deduction=D("45.00"),
        ),
        SLABS,
        days_worked=30,
        days_in_month=30,
    )
    assert r.gross == D("4800.00")
    assert r.pension == D("200.00")
    assert r.taxable == D("4600.00")
    # 55,200/yr -> 2,800 + 15,200 x 20% = 5,840 -> 486.666.. -> 486.67
    assert r.income_tax == D("486.67")
    assert r.other_deduction == D("45.00")
    assert r.net == D("4068.33")


def test_prorated_payslip_matches_hand_calculation() -> None:
    # Hired 15 September: 16 of 30 days.
    r = pm.calculate(
        pm.SalaryStructure(
            basic=D("11500.00"),
            housing=D("1700.00"),
            transport=D("250.00"),
            pension_rate=D("0.05"),
        ),
        SLABS,
        days_worked=16,
        days_in_month=30,
    )
    assert (r.basic, r.housing, r.transport) == (D("6133.33"), D("906.67"), D("133.33"))
    assert r.gross == D("7173.33")
    assert r.pension == D("306.67")
    # annual 82,399.92 -> 10,800 + 2,399.92 x 30% = 11,519.976 -> /12 = 959.998 -> 960.00
    assert r.income_tax == D("960.00")
    assert r.net == D("5906.66")


def test_other_deduction_is_capped_so_net_is_not_negative() -> None:
    r = pm.calculate(
        pm.SalaryStructure(basic=D("100.00"), other_deduction=D("500.00")),
        SLABS,
        days_worked=31,
        days_in_month=31,
    )
    assert r.other_deduction == D("100.00")
    assert r.net == D("0.00")


def test_days_worked_must_be_in_range() -> None:
    with pytest.raises(ValueError):
        pm.calculate(pm.SalaryStructure(basic=D("1")), SLABS, days_worked=0, days_in_month=30)


cents = st.integers(min_value=0, max_value=5_000_000).map(lambda c: D(c) / 100)


@given(
    basic=cents,
    housing=cents,
    transport=cents,
    rate=st.integers(min_value=0, max_value=2000).map(lambda b: D(b) / 10000),
    deduction=cents,
    days=st.integers(min_value=1, max_value=31),
)
def test_payslip_invariants(
    basic: Decimal,
    housing: Decimal,
    transport: Decimal,
    rate: Decimal,
    deduction: Decimal,
    days: int,
) -> None:
    r = pm.calculate(
        pm.SalaryStructure(
            basic=basic,
            housing=housing,
            transport=transport,
            pension_rate=rate,
            other_deduction=deduction,
        ),
        SLABS,
        days_worked=days,
        days_in_month=31,
    )
    for value in (r.gross, r.pension, r.income_tax, r.other_deduction, r.net):
        assert value == value.quantize(D("0.01"))  # always whole cents
        assert value >= 0
    assert r.gross == r.basic + r.housing + r.transport + r.other_allowance
    assert r.net == r.gross - r.pension - r.income_tax - r.other_deduction
    assert r.income_tax <= r.taxable * D("0.30") + D("0.01")  # never above the top rate


@given(a=cents, b=cents)
def test_tax_is_monotonic(a: Decimal, b: Decimal) -> None:
    lo, hi = sorted((a, b))
    assert pm.monthly_tax(lo, SLABS) <= pm.monthly_tax(hi, SLABS)


# ------------------------------------------------------------------ budget math


@given(annual=cents)
def test_split_annual_sums_exactly(annual: Decimal) -> None:
    months = split_annual(annual)
    assert len(months) == 12
    assert sum(months) == annual
    assert all(m >= 0 for m in months)
    assert months[11] >= months[0]  # remainder in December


def test_split_annual_examples() -> None:
    assert split_annual(D("1200.00")) == [D("100.00")] * 12
    months = split_annual(D("1000.00"))
    assert months[:11] == [D("83.33")] * 11
    assert months[11] == D("83.37")


def test_percent_used() -> None:
    assert percent(D("90"), D("100")) == D("90.00")
    assert percent(D("1"), D("3")) == D("33.33")
    assert percent(D("2"), D("3")) == D("66.67")  # half-up
    assert percent(D("5"), D("0")) is None
