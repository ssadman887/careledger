from decimal import Decimal

import pytest
from pydantic import BaseModel, ValidationError

from app.core.money import Money, quantize


class Item(BaseModel):
    amount: Money


def test_parses_strings_and_ints_to_decimal() -> None:
    assert Item(amount="12.5").amount == Decimal("12.50")  # type: ignore[arg-type]
    assert Item(amount=7).amount == Decimal("7.00")  # type: ignore[arg-type]


def test_rejects_floats() -> None:
    with pytest.raises(ValidationError):
        Item(amount=1.1)  # type: ignore[arg-type]


def test_rejects_more_than_two_decimals() -> None:
    with pytest.raises(ValidationError):
        Item(amount="1.005")  # type: ignore[arg-type]


def test_rejects_non_numbers() -> None:
    with pytest.raises(ValidationError):
        Item(amount="abc")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        Item(amount="NaN")  # type: ignore[arg-type]


def test_serializes_as_string_in_json() -> None:
    assert Item(amount=Decimal("3")).model_dump_json() == '{"amount":"3.00"}'


def test_json_schema_is_string() -> None:
    assert Item.model_json_schema()["properties"]["amount"]["type"] == "string"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0.005", "0.01"),
        ("0.004", "0.00"),
        ("-0.005", "-0.01"),
        ("2.675", "2.68"),
    ],
)
def test_quantize_rounds_half_up(raw: str, expected: str) -> None:
    assert quantize(Decimal(raw)) == Decimal(expected)
