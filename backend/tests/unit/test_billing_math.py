from decimal import Decimal

import pytest

from app.core.errors import ValidationFailed
from app.services.billing_math import invoice_totals, line_amounts

D = Decimal


def test_simple_line() -> None:
    a = line_amounts(D("2"), D("95.00"), D("0"))
    assert (a.gross, a.discount, a.tax, a.total) == (D("190.00"), D("0.00"), D("0.00"), D("190.00"))


def test_percent_discount_then_tax_on_net_with_half_up_rounding() -> None:
    # gross 3 x 18.35 = 55.05; 10% = 5.505 -> 5.51 (half up); net 49.54; 5% tax = 2.477 -> 2.48
    a = line_amounts(D("3"), D("18.35"), D("0.05"), discount_percent=D("10"))
    assert a.gross == D("55.05")
    assert a.discount == D("5.51")
    assert a.tax == D("2.48")
    assert a.total == D("52.02")


def test_fractional_quantity_rounds_gross() -> None:
    assert line_amounts(D("1.5"), D("33.33"), D("0")).gross == D("50.00")  # 49.995 -> 50.00


def test_fixed_discount_bounds() -> None:
    assert line_amounts(D("1"), D("100"), D("0"), discount_amount=D("100")).total == D("0.00")
    with pytest.raises(ValidationFailed):
        line_amounts(D("1"), D("100"), D("0"), discount_amount=D("100.01"))


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"quantity": D("0")}, "invalid_quantity"),
        ({"unit_price": D("-1")}, "invalid_price"),
        ({"tax_rate": D("1")}, "invalid_tax_rate"),
        ({"discount_percent": D("101")}, "invalid_discount"),
        ({"discount_percent": D("5"), "discount_amount": D("1")}, "invalid_discount"),
    ],
)
def test_invalid_inputs(kwargs: dict[str, Decimal], code: str) -> None:
    args = {"quantity": D("1"), "unit_price": D("10"), "tax_rate": D("0")}
    extra = {k: v for k, v in kwargs.items() if k not in args}
    args.update({k: v for k, v in kwargs.items() if k in args})
    with pytest.raises(ValidationFailed) as exc:
        line_amounts(args["quantity"], args["unit_price"], args["tax_rate"], **extra)
    assert exc.value.code == code


def test_invoice_totals_sum_rounded_lines_exactly() -> None:
    lines = [line_amounts(D("1"), D("0.10"), D("0.05")) for _ in range(3)]  # tax 0.005 -> 0.01 each
    totals = invoice_totals(lines)
    assert totals.subtotal == D("0.30")
    assert totals.tax_total == D("0.03")
    assert totals.total == totals.subtotal - totals.discount_total + totals.tax_total
