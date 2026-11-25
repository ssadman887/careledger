"""Insurer and policy registry."""

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.models.insurance import Insurer, Policy
from app.repositories import insurance as repo
from app.services import audit
from app.services.audit import Actor
from app.services.patients import get_patient

ONE = Decimal("1")


def _check_rates(approval: Decimal, partial: Decimal, denial: Decimal) -> None:
    if min(approval, partial, denial) < 0 or approval + partial + denial != ONE:
        raise ValidationFailed(
            "Approval, partial and denial rates must be >= 0 and sum to 1", code="invalid_rates"
        )


def get_insurer(session: Session, insurer_id: int) -> Insurer:
    insurer = repo.get_insurer(session, insurer_id)
    if insurer is None:
        raise NotFound("Insurer not found")
    return insurer


def create_insurer(
    session: Session,
    actor: Actor,
    *,
    code: str,
    name: str,
    payer_id: str,
    contact_email: str,
    approval_rate: Decimal,
    partial_rate: Decimal,
    denial_rate: Decimal,
) -> Insurer:
    if repo.get_insurer_by_code(session, code) is not None:
        raise Conflict(f"Insurer {code} already exists", code="insurer_exists")
    _check_rates(approval_rate, partial_rate, denial_rate)
    insurer = Insurer(
        code=code,
        name=name,
        payer_id=payer_id,
        contact_email=contact_email,
        approval_rate=approval_rate,
        partial_rate=partial_rate,
        denial_rate=denial_rate,
    )
    session.add(insurer)
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="insurer",
        entity_id=insurer.id,
        action="create",
        after=audit.snapshot(insurer),
    )
    return insurer


def update_insurer(
    session: Session,
    actor: Actor,
    insurer_id: int,
    *,
    name: str | None,
    contact_email: str | None,
    is_active: bool | None,
    rates: tuple[Decimal, Decimal, Decimal] | None,
) -> Insurer:
    insurer = get_insurer(session, insurer_id)
    before = audit.snapshot(insurer)
    if name is not None:
        insurer.name = name
    if contact_email is not None:
        insurer.contact_email = contact_email
    if rates is not None:
        _check_rates(*rates)
        insurer.approval_rate, insurer.partial_rate, insurer.denial_rate = rates
    if is_active is not None:
        insurer.is_active = is_active
    session.flush()
    action = "status_change" if before["is_active"] != insurer.is_active else "update"
    audit.record(
        session,
        actor,
        entity_type="insurer",
        entity_id=insurer.id,
        action=action,
        before=before,
        after=audit.snapshot(insurer),
    )
    return insurer


def get_policy(session: Session, policy_id: int) -> Policy:
    policy = repo.get_policy(session, policy_id)
    if policy is None:
        raise NotFound("Policy not found")
    return policy


def create_policy(
    session: Session,
    actor: Actor,
    *,
    patient_id: int,
    insurer_id: int,
    policy_number: str,
    plan_name: str,
    coverage_percent: Decimal,
    copay: Decimal,
    deductible: Decimal,
    annual_limit: Decimal,
    effective_from: date,
    effective_to: date | None,
) -> Policy:
    get_patient(session, patient_id)
    insurer = get_insurer(session, insurer_id)
    if not insurer.is_active:
        raise ValidationFailed("Insurer is inactive", code="insurer_inactive")
    if repo.policy_number_taken(session, insurer_id, policy_number):
        raise Conflict("Policy number already registered with this insurer", code="policy_exists")
    if effective_to is not None and effective_to < effective_from:
        raise ValidationFailed("Policy end date is before its start", code="invalid_range")
    if not (Decimal("0") <= coverage_percent <= Decimal("100")):
        raise ValidationFailed("Coverage percent must be 0-100", code="invalid_coverage")
    if min(copay, deductible, annual_limit) < 0:
        raise ValidationFailed("Policy amounts cannot be negative", code="invalid_coverage")
    policy = Policy(
        patient_id=patient_id,
        insurer_id=insurer_id,
        policy_number=policy_number,
        plan_name=plan_name,
        coverage_percent=coverage_percent,
        copay=copay,
        deductible=deductible,
        annual_limit=annual_limit,
        effective_from=effective_from,
        effective_to=effective_to,
        is_active=True,
    )
    session.add(policy)
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="policy",
        entity_id=policy.id,
        action="create",
        after=audit.snapshot(policy),
    )
    return policy


def set_policy_active(session: Session, actor: Actor, policy_id: int, is_active: bool) -> Policy:
    policy = get_policy(session, policy_id)
    before = audit.snapshot(policy)
    policy.is_active = is_active
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="policy",
        entity_id=policy.id,
        action="status_change",
        before=before,
        after=audit.snapshot(policy),
    )
    return policy


def policy_covers(policy: Policy, on: date) -> bool:
    return (
        policy.is_active
        and policy.insurer.is_active
        and policy.effective_from <= on
        and (policy.effective_to is None or policy.effective_to >= on)
    )
