"""Money handling. Decimal only; serialized to JSON as a string with 2 decimal places."""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Annotated, Any

from pydantic import BeforeValidator, PlainSerializer, WithJsonSchema

CENT = Decimal("0.01")
MONEY_PATTERN = r"^-?\d{1,12}(\.\d{1,2})?$"


def quantize(value: Decimal) -> Decimal:
    """Round half-up to cents (the rounding rule used everywhere in CareLedger)."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _parse_money(value: Any) -> Decimal:
    if isinstance(value, float):
        raise ValueError("money must be a string or integer, never a float")
    if isinstance(value, bool):
        raise ValueError("money must be a string or integer")
    try:
        dec = value if isinstance(value, Decimal) else Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("invalid money amount") from exc
    if not dec.is_finite():
        raise ValueError("money must be finite")
    if dec != dec.quantize(CENT):
        raise ValueError("money supports at most 2 decimal places")
    return quantize(dec)


Money = Annotated[
    Decimal,
    BeforeValidator(_parse_money),
    PlainSerializer(lambda d: f"{quantize(d):.2f}", return_type=str, when_used="always"),
    WithJsonSchema({"type": "string", "pattern": MONEY_PATTERN, "examples": ["1250.00"]}),
]
