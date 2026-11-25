"""Pure invoice arithmetic (Decimal only). Rounding rule: ROUND_HALF_UP to cents at each step:

    gross    = round(quantity × unit_price)
    discount = round(gross × discount_percent / 100)   (or a fixed amount ≤ gross)
    tax      = round((gross − discount) × tax_rate)
    total    = gross − discount + tax

Invoice totals are sums of the already-rounded line values, so they always tie out exactly.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from app.core.errors import ValidationFailed
from app.core.money import quantize

ZERO = Decimal("0.00")
HUNDRED = Decimal("100")


@dataclass(frozen=True)
class LineAmounts:
    gross: Decimal
    discount: Decimal
    tax: Decimal
    total: Decimal


@dataclass(frozen=True)
class InvoiceTotals:
    subtotal: Decimal
    discount_total: Decimal
    tax_total: Decimal
    total: Decimal


def line_amounts(
    quantity: Decimal,
    unit_price: Decimal,
    tax_rate: Decimal,
    *,
    discount_percent: Decimal | None = None,
    discount_amount: Decimal | None = None,
) -> LineAmounts:
    if quantity <= 0:
        raise ValidationFailed("Quantity must be positive", code="invalid_quantity")
    if unit_price < 0:
        raise ValidationFailed("Unit price cannot be negative", code="invalid_price")
    if not (Decimal("0") <= tax_rate < Decimal("1")):
        raise ValidationFailed("Tax rate must be between 0 and 1", code="invalid_tax_rate")
    if discount_percent is not None and discount_amount is not None:
        raise ValidationFailed(
            "Give a discount percent or an amount, not both", code="invalid_discount"
        )
    gross = quantize(quantity * unit_price)
    if discount_percent is not None:
        if not (Decimal("0") <= discount_percent <= HUNDRED):
            raise ValidationFailed("Discount percent must be 0–100", code="invalid_discount")
        discount = quantize(gross * discount_percent / HUNDRED)
    else:
        discount = quantize(discount_amount or ZERO)
        if discount < 0 or discount > gross:
            raise ValidationFailed(
                "Discount must be between 0 and the line amount", code="invalid_discount"
            )
    tax = quantize((gross - discount) * tax_rate)
    return LineAmounts(gross, discount, tax, gross - discount + tax)


def invoice_totals(lines: Iterable[LineAmounts]) -> InvoiceTotals:
    items = list(lines)
    subtotal = sum((ln.gross for ln in items), ZERO)
    discount = sum((ln.discount for ln in items), ZERO)
    tax = sum((ln.tax for ln in items), ZERO)
    return InvoiceTotals(subtotal, discount, tax, subtotal - discount + tax)
