"""Coverage math edge cases: copay, deductible, coinsurance, annual limit, rounding, caps."""

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.core.errors import ValidationFailed
from app.services.coverage import CoverageTerms, allocate, cap_insurer, compute_coverage

D = Decimal


def terms(
    pct: str = "80", copay: str = "0", deductible: str = "0", limit: str = "100000"
) -> CoverageTerms:
    return CoverageTerms(D(pct), D(copay), D(deductible), D(limit))


def cov(billed: str, t: CoverageTerms, met: str = "0", used: str = "0"):  # type: ignore[no-untyped-def]
    return compute_coverage(D(billed), t, deductible_met=D(met), insurer_used=D(used))


def test_plain_coinsurance() -> None:
    r = cov("1000.00", terms("80"))
    assert (r.insurer, r.patient, r.coinsurance) == (D("800.00"), D("200.00"), D("200.00"))


def test_copay_then_deductible_then_coinsurance() -> None:
    r = cov("1000.00", terms("80", copay="50", deductible="500"))
    # 1000 - 50 copay = 950; 500 deductible -> 450; 80% = 360 insurer, 90 coinsurance
    assert (r.copay, r.deductible, r.insurer, r.coinsurance) == (
        D("50.00"),
        D("500.00"),
        D("360.00"),
        D("90.00"),
    )
    assert r.patient == D("640.00")


def test_copay_larger_than_bill_is_all_patient() -> None:
    r = cov("30.00", terms("90", copay="50"))
    assert (r.copay, r.insurer, r.patient) == (D("30.00"), D("0.00"), D("30.00"))


@pytest.mark.parametrize(
    ("met", "expected_deductible", "expected_insurer"),
    [
        ("0", "500.00", "400.00"),
        ("300", "200.00", "640.00"),
        ("500", "0.00", "800.00"),
        ("900", "0.00", "800.00"),
    ],
)
def test_deductible_partially_and_fully_met(
    met: str, expected_deductible: str, expected_insurer: str
) -> None:
    r = cov("1000.00", terms("80", deductible="500"), met=met)
    assert r.deductible == D(expected_deductible)
    assert r.insurer == D(expected_insurer)


def test_deductible_larger_than_bill() -> None:
    r = cov("120.00", terms("80", deductible="500"))
    assert (r.deductible, r.insurer, r.patient) == (D("120.00"), D("0.00"), D("120.00"))


@pytest.mark.parametrize(
    ("used", "expected_insurer", "over"),
    [
        ("0", "800.00", "0.00"),
        ("99500", "500.00", "300.00"),
        ("100000", "0.00", "800.00"),
        ("150000", "0.00", "800.00"),
    ],
)
def test_annual_limit(used: str, expected_insurer: str, over: str) -> None:
    r = cov("1000.00", terms("80", limit="100000"), used=used)
    assert r.insurer == D(expected_insurer)
    assert r.over_limit == D(over)
    assert r.insurer + r.patient == D("1000.00")


def test_zero_limit_and_zero_and_full_coverage() -> None:
    assert cov("100.00", terms("80", limit="0")).insurer == D("0.00")
    assert cov("100.00", terms("0")).insurer == D("0.00")
    assert cov("100.00", terms("100")).patient == D("0.00")


def test_share_rounds_half_up() -> None:
    # 0.05 x 33.33% ... use 1.11 x 50% = 0.555 -> 0.56 insurer
    r = cov("1.11", terms("50"))
    assert (r.insurer, r.patient) == (D("0.56"), D("0.55"))


def test_invalid_terms_rejected() -> None:
    with pytest.raises(ValidationFailed):
        cov("10.00", terms("101"))
    with pytest.raises(ValidationFailed):
        cov("10.00", terms(copay="-1"))
    with pytest.raises(ValidationFailed):
        cov("-1.00", terms())


def test_cap_insurer_moves_excess_to_patient() -> None:
    r = cap_insurer(cov("1000.00", terms("80")), D("300.00"))
    assert (r.insurer, r.patient) == (D("300.00"), D("700.00"))
    same = cov("1000.00", terms("80"))
    assert cap_insurer(same, D("900.00")) == same


def test_allocate_sums_exactly() -> None:
    parts = allocate(D("100.00"), [D("1"), D("1"), D("1")])
    assert sum(parts) == D("100.00")
    assert sorted(parts) == [D("33.33"), D("33.33"), D("33.34")]
    assert allocate(D("10.00"), [D("0"), D("0")]) == [D("10.00"), D("0.00")]
    assert allocate(D("5.00"), []) == []


money = st.integers(min_value=0, max_value=10_000_000).map(lambda c: D(c) / 100)


@given(
    billed=money,
    pct=st.integers(0, 100),
    copay=money,
    deductible=money,
    limit=money,
    met=money,
    used=money,
)
def test_split_always_sums_to_billed_and_is_non_negative(
    billed: Decimal,
    pct: int,
    copay: Decimal,
    deductible: Decimal,
    limit: Decimal,
    met: Decimal,
    used: Decimal,
) -> None:
    r = compute_coverage(
        billed,
        CoverageTerms(D(pct), copay, deductible, limit),
        deductible_met=met,
        insurer_used=used,
    )
    assert r.insurer + r.patient == billed
    assert min(r.insurer, r.patient, r.copay, r.deductible, r.coinsurance, r.over_limit) >= 0
    assert r.insurer <= max(limit - used, D("0"))


@given(total=money, weights=st.lists(money, min_size=1, max_size=8))
def test_allocate_property(total: Decimal, weights: list[Decimal]) -> None:
    parts = allocate(total, weights)
    assert sum(parts) == total
    assert all(p >= 0 for p in parts)
