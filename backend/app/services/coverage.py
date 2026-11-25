"""Coverage calculation: how a bill splits between insurer and patient (pure, Decimal only).

Order of application (benefit year = calendar year):
  1. copay       patient pays min(copay, billed) per claim
  2. deductible  patient pays min(remaining, deductible not yet met this year)
  3. coinsurance insurer pays round(after_deductible x coverage%), patient the rest
  4. limit       insurer share is capped at the annual limit still available; the excess
                 becomes patient responsibility
All rounding is ROUND_HALF_UP to cents. insurer + patient == billed, always.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.core.errors import ValidationFailed
from app.core.money import quantize

ZERO = Decimal("0.00")
HUNDRED = Decimal("100")


@dataclass(frozen=True)
class CoverageTerms:
    coverage_percent: Decimal
    copay: Decimal
    deductible: Decimal
    annual_limit: Decimal


@dataclass(frozen=True)
class CoverageResult:
    billed: Decimal
    copay: Decimal
    deductible: Decimal
    coinsurance: Decimal
    over_limit: Decimal
    insurer: Decimal
    patient: Decimal


def compute_coverage(
    billed: Decimal, terms: CoverageTerms, *, deductible_met: Decimal, insurer_used: Decimal
) -> CoverageResult:
    if billed < 0:
        raise ValidationFailed("Billed amount cannot be negative", code="invalid_amount")
    if not (Decimal("0") <= terms.coverage_percent <= HUNDRED):
        raise ValidationFailed("Coverage percent must be 0-100", code="invalid_coverage")
    for value in (terms.copay, terms.deductible, terms.annual_limit, deductible_met, insurer_used):
        if value < 0:
            raise ValidationFailed("Coverage amounts cannot be negative", code="invalid_coverage")

    copay = min(terms.copay, billed)
    remaining = billed - copay
    deductible = min(remaining, max(terms.deductible - deductible_met, ZERO))
    after_deductible = remaining - deductible
    insurer = quantize(after_deductible * terms.coverage_percent / HUNDRED)
    coinsurance = after_deductible - insurer
    limit_left = max(terms.annual_limit - insurer_used, ZERO)
    over_limit = max(insurer - limit_left, ZERO)
    insurer -= over_limit
    patient = copay + deductible + coinsurance + over_limit
    assert insurer + patient == billed
    return CoverageResult(billed, copay, deductible, coinsurance, over_limit, insurer, patient)


def cap_insurer(result: CoverageResult, collectible: Decimal) -> CoverageResult:
    """If the patient has already paid part of the bill, the insurer can only be asked for what
    is still collectible; the remainder stays patient responsibility (already settled)."""
    if result.insurer <= collectible:
        return result
    excess = result.insurer - max(collectible, ZERO)
    return CoverageResult(
        result.billed,
        result.copay,
        result.deductible,
        result.coinsurance,
        result.over_limit + excess,
        result.insurer - excess,
        result.patient + excess,
    )


def allocate(total: Decimal, weights: Sequence[Decimal]) -> list[Decimal]:
    """Split `total` across lines proportionally to `weights` (largest remainder, to the cent),
    so the parts always sum exactly to `total`."""
    weight_sum = sum(weights, ZERO)
    if not weights:
        return []
    if weight_sum <= 0:
        return [total if i == 0 else ZERO for i in range(len(weights))]
    raw = [total * w / weight_sum for w in weights]
    floors = [r.quantize(Decimal("0.01"), rounding="ROUND_DOWN") for r in raw]
    leftover_cents = int(((total - sum(floors, ZERO)) * 100).to_integral_value())
    order = sorted(range(len(raw)), key=lambda i: (raw[i] - floors[i], -i), reverse=True)
    for i in order[:leftover_cents]:
        floors[i] += Decimal("0.01")
    return floors
