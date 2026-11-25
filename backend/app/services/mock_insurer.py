"""Mock insurer: simulates adjudication so the full claim cycle can be demoed.

Each insurer has approval / partial / denial rates. The outcome for a claim is *deterministic*
per (claim number, appeal round), seeded from those values, so demos and tests are repeatable;
an explicit `outcome` overrides it for scripted demos. Partial approvals pay 50-90% of the
claimed amount. Appealed claims are re-adjudicated with a fresh draw.
"""

import hashlib
import random
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.errors import Conflict
from app.core.money import quantize
from app.models.insurance import Claim, ClaimStatus
from app.repositories import insurance as repo
from app.services import claims
from app.services.audit import Actor

MOCK_ACTOR_LABEL = "mock-insurer"
DENIAL_CODES = ("CO-16", "CO-50", "CO-27", "CO-97", "PR-204")


@dataclass(frozen=True)
class Decision:
    outcome: str  # approve | partial | deny
    approved_amount: Decimal | None
    denial_code: str | None
    note: str


def _rng(claim: Claim) -> random.Random:
    digest = hashlib.sha256(f"{claim.claim_number}:{claim.appeal_count}".encode()).hexdigest()
    return random.Random(int(digest[:16], 16))  # noqa: S311 - simulation, not security


def decide(claim: Claim) -> Decision:
    rng = _rng(claim)
    roll = Decimal(str(rng.random()))
    ins = claim.insurer
    if roll < ins.approval_rate:
        return Decision("approve", None, None, "Approved in full")
    if roll < ins.approval_rate + ins.partial_rate:
        pct = Decimal(rng.randint(50, 90)) / 100
        amount = quantize(claim.insurer_amount * pct)
        amount = min(max(amount, Decimal("0.01")), claim.insurer_amount - Decimal("0.01"))
        return Decision("partial", amount, None, f"Approved {int(pct * 100)}% per fee schedule")
    code = DENIAL_CODES[rng.randrange(len(DENIAL_CODES))]
    return Decision("deny", None, code, "Denied on review")


def adjudicate(
    session: Session,
    actor: Actor,
    claim_id: int,
    *,
    outcome: str | None = None,
    approved_amount: Decimal | None = None,
    denial_code: str | None = None,
    on: date | None = None,
) -> Claim:
    """Move a submitted/appealed claim to under_review, then apply a decision."""
    claim = claims.get_claim(session, claim_id, lock=True)
    if claim.status not in (ClaimStatus.SUBMITTED, ClaimStatus.APPEALED):
        raise Conflict(
            f"Claim {claim.claim_number} is {claim.status}; nothing to adjudicate",
            code="invalid_transition",
        )
    claims.start_review(session, actor, claim)
    if outcome is None:
        d = decide(claim)
    else:
        default_partial = quantize(claim.insurer_amount * Decimal("0.7"))
        d = Decision(
            outcome,
            approved_amount
            if approved_amount is not None
            else (default_partial if outcome == "partial" else None),
            denial_code or ("CO-50" if outcome == "deny" else None),
            "Scripted outcome",
        )
    return claims.record_decision(
        session,
        actor,
        claim.id,
        outcome=d.outcome,
        approved_amount=d.approved_amount,
        denial_code=d.denial_code,
        note=d.note,
        on=on,
    )


def run_batch(session: Session, actor: Actor, *, limit: int = 100) -> list[Claim]:
    """Adjudicate every claim waiting with an insurer (submitted or appealed)."""
    pending = repo.claims_in_status(
        session, [ClaimStatus.SUBMITTED, ClaimStatus.APPEALED], limit=limit
    )
    return [adjudicate(session, actor, c.id) for c in pending]
