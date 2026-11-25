"""Queries for insurers, policies, claims and remittances."""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from sqlalchemy import case, extract, func, or_, select
from sqlalchemy.orm import Session

from app.core.pagination import PageParams
from app.models.insurance import (
    Claim,
    ClaimAttachment,
    ClaimStatus,
    DenialCode,
    Insurer,
    Policy,
    Remittance,
)
from app.models.patients import Patient
from app.repositories.billing import _page

# ------------------------------------------------------------------ insurers & policies


def get_insurer(session: Session, insurer_id: int) -> Insurer | None:
    return session.get(Insurer, insurer_id)


def get_insurer_by_code(session: Session, code: str) -> Insurer | None:
    return session.scalars(select(Insurer).where(Insurer.code == code)).first()


def list_insurers(session: Session, *, active_only: bool) -> Sequence[Insurer]:
    stmt = select(Insurer)
    if active_only:
        stmt = stmt.where(Insurer.is_active.is_(True))
    return session.scalars(stmt.order_by(Insurer.name)).all()


def get_policy(session: Session, policy_id: int) -> Policy | None:
    return session.get(Policy, policy_id)


def policy_number_taken(session: Session, insurer_id: int, number: str) -> bool:
    stmt = select(func.count(Policy.id)).where(
        Policy.insurer_id == insurer_id, Policy.policy_number == number
    )
    return bool(session.scalar(stmt))


def list_policies(
    session: Session,
    params: PageParams,
    *,
    patient_id: int | None,
    insurer_id: int | None,
    active_only: bool,
) -> tuple[Sequence[Policy], int]:
    stmt = select(Policy)
    if patient_id is not None:
        stmt = stmt.where(Policy.patient_id == patient_id)
    if insurer_id is not None:
        stmt = stmt.where(Policy.insurer_id == insurer_id)
    if active_only:
        stmt = stmt.where(Policy.is_active.is_(True))
    sorts = {"effective_from": Policy.effective_from, "policy_number": Policy.policy_number}
    return _page(session, stmt, params, sorts, "-effective_from", Policy.id.desc())


def denial_codes(session: Session) -> Sequence[DenialCode]:
    return session.scalars(select(DenialCode).order_by(DenialCode.code)).all()


def get_denial_code(session: Session, code: str) -> DenialCode | None:
    return session.scalars(select(DenialCode).where(DenialCode.code == code)).first()


# ------------------------------------------------------------------ benefit-year usage


def benefit_usage(
    session: Session, policy_id: int, year: int, *, exclude_claim_id: int | None = None
) -> tuple[Decimal, Decimal]:
    """(deductible already applied, insurer amount already committed) for the policy in a
    calendar year. Pending claims count their claimed amount, adjudicated ones the approved
    amount; cancelled, denied and closed claims count nothing towards the limit."""
    committed = case(
        (
            Claim.status.in_(["draft", "submitted", "under_review", "appealed"]),
            Claim.insurer_amount,
        ),
        (Claim.status.in_(["approved", "partially_approved", "paid"]), Claim.approved_amount),
        else_=0,
    )
    deductible = case((Claim.status == ClaimStatus.CANCELLED, 0), else_=Claim.deductible_amount)
    stmt = select(
        func.coalesce(func.sum(deductible), 0), func.coalesce(func.sum(committed), 0)
    ).where(Claim.policy_id == policy_id, extract("year", Claim.service_date) == year)
    if exclude_claim_id is not None:
        stmt = stmt.where(Claim.id != exclude_claim_id)
    row = session.execute(stmt).one()
    return Decimal(row[0]), Decimal(row[1])


# ------------------------------------------------------------------ claims


def get_claim(session: Session, claim_id: int, *, lock: bool = False) -> Claim | None:
    if lock:
        stmt = select(Claim).where(Claim.id == claim_id).with_for_update(of=Claim)
        return session.scalars(stmt).unique().first()
    return session.get(Claim, claim_id)


def get_claim_by_number(session: Session, number: str) -> Claim | None:
    return session.scalars(select(Claim).where(Claim.claim_number == number)).unique().first()


def claims_in_status(session: Session, statuses: Sequence[str], *, limit: int) -> Sequence[Claim]:
    stmt = select(Claim).where(Claim.status.in_(statuses)).order_by(Claim.id).limit(limit)
    return session.scalars(stmt).unique().all()


def list_claims(
    session: Session,
    params: PageParams,
    *,
    status: str | None,
    insurer_id: int | None,
    patient_id: int | None,
    invoice_id: int | None,
    search: str | None,
    date_from: date | None,
    date_to: date | None,
) -> tuple[Sequence[Claim], int]:
    stmt = select(Claim).join(Patient, Patient.id == Claim.patient_id)
    if status:
        stmt = stmt.where(Claim.status == status)
    if insurer_id is not None:
        stmt = stmt.where(Claim.insurer_id == insurer_id)
    if patient_id is not None:
        stmt = stmt.where(Claim.patient_id == patient_id)
    if invoice_id is not None:
        stmt = stmt.where(Claim.invoice_id == invoice_id)
    if date_from:
        stmt = stmt.where(Claim.service_date >= date_from)
    if date_to:
        stmt = stmt.where(Claim.service_date <= date_to)
    if search:
        like = f"%{search.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Claim.claim_number).like(like),
                func.lower(Patient.mrn).like(like),
                func.lower(Patient.first_name + " " + Patient.last_name).like(like),
            )
        )
    sorts = {
        "claim_number": Claim.claim_number,
        "service_date": Claim.service_date,
        "billed_amount": Claim.billed_amount,
        "insurer_amount": Claim.insurer_amount,
        "created_at": Claim.created_at,
    }
    return _page(session, stmt, params, sorts, "-created_at", Claim.id.desc())


def claim_status_counts(session: Session) -> dict[str, int]:
    rows = session.execute(select(Claim.status, func.count(Claim.id)).group_by(Claim.status)).all()
    return {str(s): int(n) for s, n in rows}


def attachments(session: Session, claim_id: int) -> Sequence[ClaimAttachment]:
    stmt = select(ClaimAttachment).where(ClaimAttachment.claim_id == claim_id)
    return session.scalars(stmt.order_by(ClaimAttachment.id)).all()


def get_attachment(session: Session, attachment_id: int) -> ClaimAttachment | None:
    return session.get(ClaimAttachment, attachment_id)


# ------------------------------------------------------------------ remittances


def get_remittance(
    session: Session, remittance_id: int, *, lock: bool = False
) -> Remittance | None:
    if lock:
        stmt = (
            select(Remittance).where(Remittance.id == remittance_id).with_for_update(of=Remittance)
        )
        return session.scalars(stmt).unique().first()
    return session.get(Remittance, remittance_id)


def remittance_reference_taken(session: Session, insurer_id: int, reference: str) -> bool:
    stmt = select(func.count(Remittance.id)).where(
        Remittance.insurer_id == insurer_id, Remittance.reference == reference
    )
    return bool(session.scalar(stmt))


def list_remittances(
    session: Session, params: PageParams, *, insurer_id: int | None, status: str | None
) -> tuple[Sequence[Remittance], int]:
    stmt = select(Remittance)
    if insurer_id is not None:
        stmt = stmt.where(Remittance.insurer_id == insurer_id)
    if status:
        stmt = stmt.where(Remittance.status == status)
    sorts = {
        "payment_date": Remittance.payment_date,
        "created_at": Remittance.created_at,
        "total_amount": Remittance.total_amount,
    }
    return _page(session, stmt, params, sorts, "-created_at", Remittance.id.desc())
