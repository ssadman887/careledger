"""Denial codes, fictional insurers, policies, and sample claims in every state with a
reconciled remittance. Deterministic and idempotent."""

import random
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation
from app.models.billing import Invoice
from app.models.identity import User
from app.models.insurance import Claim, DenialCode, Insurer, Policy
from app.models.patients import Patient
from app.services import claims, insurance, mock_insurer, remittances
from app.services.audit import SYSTEM_ACTOR, Actor
from app.services.auth import actor_for

SEED = 20260103
D = Decimal

DENIAL_CODES: tuple[tuple[str, str, bool], ...] = (
    ("CO-16", "Claim lacks information needed for adjudication", False),
    ("CO-27", "Expenses incurred after coverage terminated", True),
    ("CO-29", "Time limit for filing has expired", False),
    ("CO-50", "Not deemed a medical necessity by the payer", False),
    ("CO-97", "Payment included in another service already adjudicated", False),
    ("PR-204", "Service not covered under the patient's plan", True),
)

# Fictional payers. (code, name, payer id, approval, partial, denial)
INSURERS: tuple[tuple[str, str, str, str, str, str], ...] = (
    ("CRS", "Crestline Health Plan", "PAYER-1001", "0.70", "0.20", "0.10"),
    ("MER", "Meridian Care Mutual", "PAYER-1002", "0.60", "0.25", "0.15"),
    ("SUN", "Sunhaven Assurance", "PAYER-1003", "0.80", "0.15", "0.05"),
    ("SHP", "State Health Program", "PAYER-1004", "0.75", "0.10", "0.15"),
)

PLANS = (
    ("Gold PPO", D("90"), D("25.00"), D("250.00"), D("250000.00")),
    ("Silver PPO", D("80"), D("40.00"), D("500.00"), D("100000.00")),
    ("Bronze HMO", D("70"), D("50.00"), D("1000.00"), D("50000.00")),
)


def seed_denial_codes(session: Session) -> None:
    existing = set(session.scalars(select(DenialCode.code)).all())
    for code, description, patient in DENIAL_CODES:
        if code not in existing:
            session.add(
                DenialCode(code=code, description=description, patient_responsibility=patient)
            )
    session.flush()


def seed_insurers(session: Session) -> list[Insurer]:
    existing = {i.code for i in session.scalars(select(Insurer)).all()}
    for code, name, payer, a, p, d in INSURERS:
        if code not in existing:
            insurance.create_insurer(
                session,
                SYSTEM_ACTOR,
                code=code,
                name=name,
                payer_id=payer,
                contact_email=f"claims@{code.lower()}.example",
                approval_rate=D(a),
                partial_rate=D(p),
                denial_rate=D(d),
            )
    return list(session.scalars(select(Insurer).order_by(Insurer.code)).all())


def seed_policies(session: Session) -> None:
    if session.scalar(select(func.count(Policy.id))):
        return
    rng = random.Random(SEED)
    insurers = list(session.scalars(select(Insurer).order_by(Insurer.code)).all())
    people = list(session.scalars(select(Patient).order_by(Patient.id)).all())
    for i, patient in enumerate(people):
        if i % 10 in (3, 7, 9):
            continue  # ~30% self-pay
        insurer = insurers[i % len(insurers)]
        plan, pct, copay, deductible, limit = PLANS[rng.randrange(len(PLANS))]
        insurance.create_policy(
            session,
            SYSTEM_ACTOR,
            patient_id=patient.id,
            insurer_id=insurer.id,
            policy_number=f"{insurer.code}-{rng.randint(1000000, 9999999)}",
            plan_name=plan,
            coverage_percent=pct,
            copay=copay,
            deductible=deductible,
            annual_limit=limit,
            effective_from=date(2026, 1, 1),
            effective_to=date(2026, 12, 31),
        )


def seed_insurance_registry(session: Session) -> None:
    seed_denial_codes(session)
    seed_insurers(session)
    seed_policies(session)


def _user(session: Session, username: str) -> Actor:
    return actor_for(session.scalars(select(User).where(User.username == username)).one())


def seed_claims_activity(session: Session) -> None:
    """Claims in every state (draft .. paid, denied, appealed, closed) and one remittance with a
    matched line, a short-paid line and an unmatched line."""
    if session.scalar(select(func.count(Claim.id))):
        return
    officer, clerk = _user(session, "insurance"), _user(session, "billing")
    covered = {p.patient_id: p for p in session.scalars(select(Policy)).all()}
    invoices = [
        inv
        for inv in session.scalars(
            select(Invoice)
            .where(Invoice.status.in_(["issued", "partially_paid"]))
            .order_by(Invoice.invoice_date, Invoice.id)
        ).all()
        if inv.patient_id in covered and inv.patient_due > 0
    ]
    # Scripted plan per claim: the final state each one should reach.
    # Scripted final states, assigned in order to invoices that actually have something to claim.
    plan = [
        "paid",
        "partial",
        "denied",
        "appealed",
        "approved",
        "paid_short",
        "closed",
        "submitted",
        "under_review",
        "draft",
        "cancelled",
        "paid",
        "approved",
        "partial",
    ]
    created: dict[str, list[Claim]] = {}
    for inv in invoices:
        if not plan:
            break
        target = plan[0]
        actor = clerk if target in ("draft", "cancelled") else officer
        try:
            claim = claims.create_claim(
                session, actor, invoice_id=inv.id, policy_id=covered[inv.patient_id].id
            )
        except BusinessRuleViolation:
            continue  # nothing to claim after copay/deductible
        plan.pop(0)
        created.setdefault(target, []).append(claim)
        if target == "draft":
            continue
        if target == "cancelled":
            claims.cancel_claim(session, clerk, claim.id, "Patient chose to self-pay")
            continue
        on = inv.invoice_date or date(2026, 11, 1)
        claims.submit_claim(session, officer, claim.id, on=on)
        if target == "submitted":
            continue
        if target == "under_review":
            claims.start_review(session, officer, claims.get_claim(session, claim.id))
            continue
        if target in ("paid", "paid_short", "approved"):
            mock_insurer.adjudicate(session, officer, claim.id, outcome="approve", on=on)
        elif target == "partial":
            mock_insurer.adjudicate(session, officer, claim.id, outcome="partial", on=on)
        else:
            mock_insurer.adjudicate(
                session,
                officer,
                claim.id,
                outcome="deny",
                denial_code="CO-16" if target == "appealed" else "PR-204",
                on=on,
            )
            if target == "appealed":
                claims.appeal_claim(
                    session,
                    officer,
                    claim.id,
                    "Operative report and itemised bill attached; please re-review.",
                )
            elif target == "closed":
                claims.close_claim(
                    session,
                    officer,
                    claim.id,
                    "Service excluded by plan; billed to patient.",
                    on=on,
                )

    lines = ["claim_number,paid_amount,remark"]
    for claim in created.get("paid", []):
        lines.append(f"{claim.claim_number},{claim.approved_amount:.2f},Paid per contract")
    for claim in created.get("paid_short", []):
        short = (claim.approved_amount * D("0.85")).quantize(D("0.01"))
        lines.append(f"{claim.claim_number},{short:.2f},Reduced per fee schedule")
    lines.append("CLM-999999,125.00,Unknown claim reference")
    if len(lines) > 2:
        crs = session.scalars(select(Insurer).where(Insurer.code == "CRS")).one()
        by_insurer: dict[int, list[str]] = {}
        for row in lines[1:-1]:
            number = row.split(",")[0]
            c = session.scalars(select(Claim).where(Claim.claim_number == number)).one()
            by_insurer.setdefault(c.insurer_id, []).append(row)
        for n, (insurer_id, rows) in enumerate(sorted(by_insurer.items()), start=1):
            if insurer_id == crs.id or n == 1:
                rows = [*rows, lines[-1]]
            remittance = remittances.import_remittance(
                session,
                officer,
                insurer_id=insurer_id,
                reference=f"EFT-2026-11-{n:04d}",
                payment_date=date(2026, 11, 20),
                filename=f"era_{n}.csv",
                csv_text="\n".join([lines[0], *rows]) + "\n",
            )
            remittances.post_remittance(session, officer, remittance.id)


def seed_insurance(session: Session) -> None:
    seed_insurance_registry(session)
    seed_claims_activity(session)
