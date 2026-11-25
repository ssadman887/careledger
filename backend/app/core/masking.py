"""Masking of sensitive references for roles that do not need them (spec rule 15)."""

from app.models.identity import RoleName
from app.services.audit import Actor

# Roles that work with payment references day to day.
REFERENCE_ROLES = frozenset({RoleName.BILLING_CLERK.value, RoleName.FINANCE_MANAGER.value})


def mask(value: str, *, keep: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= keep:
        return "*" * len(value)
    return "*" * min(8, len(value) - keep) + value[-keep:]


def payment_reference(method: str, reference: str, actor: Actor) -> str:
    if not reference:
        return ""
    if method == "card":
        return f"**** {reference[-4:]}"  # only the last 4 digits are ever stored
    if actor.roles.intersection(REFERENCE_ROLES):
        return reference
    return mask(reference)
