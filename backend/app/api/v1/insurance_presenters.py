"""Map insurance models to response schemas (presentation only: naming, masking)."""

from collections.abc import Sequence

from app.core.masking import mask
from app.models.identity import RoleName
from app.models.insurance import Claim, ClaimAttachment, Policy, Remittance
from app.schemas.insurance import (
    ClaimAttachmentOut,
    ClaimEventOut,
    ClaimLineOut,
    ClaimOut,
    ClaimSummaryOut,
    PolicyOut,
    RemittanceLineOut,
    RemittanceOut,
    RemittanceSummaryOut,
)
from app.services.audit import Actor
from app.services.claims import TRANSITIONS
from app.services.remittances import summary

# Roles that need full policy numbers (front desk and claims staff).
POLICY_ROLES = frozenset({RoleName.INSURANCE_OFFICER.value, RoleName.BILLING_CLERK.value})


def policy_number(number: str, actor: Actor) -> str:
    return number if actor.roles.intersection(POLICY_ROLES) else mask(number)


def policy_out(p: Policy, actor: Actor) -> PolicyOut:
    return PolicyOut(
        id=p.id,
        policy_number=policy_number(p.policy_number, actor),
        patient_id=p.patient_id,
        patient_name=p.patient.full_name,
        insurer_id=p.insurer_id,
        insurer_name=p.insurer.name,
        plan_name=p.plan_name,
        coverage_percent=p.coverage_percent,
        copay=p.copay,
        deductible=p.deductible,
        annual_limit=p.annual_limit,
        effective_from=p.effective_from,
        effective_to=p.effective_to,
        is_active=p.is_active,
    )


def _summary(c: Claim) -> dict[str, object]:
    return {
        "id": c.id,
        "claim_number": c.claim_number,
        "status": c.status,
        "invoice_id": c.invoice_id,
        "invoice_number": c.invoice.invoice_number,
        "patient_id": c.patient_id,
        "patient_name": c.patient.full_name,
        "patient_mrn": c.patient.mrn,
        "insurer_id": c.insurer_id,
        "insurer_name": c.insurer.name,
        "service_date": c.service_date,
        "billed_amount": c.billed_amount,
        "insurer_amount": c.insurer_amount,
        "patient_amount": c.patient_amount,
        "approved_amount": c.approved_amount,
        "paid_amount": c.paid_amount,
        "outstanding": c.outstanding,
        "denial_code": c.denial_code,
        "created_at": c.created_at,
    }


def claim_summary(c: Claim) -> ClaimSummaryOut:
    return ClaimSummaryOut.model_validate(_summary(c))


def claim_out(
    c: Claim, attachments: Sequence[ClaimAttachment], actor: Actor, denial_description: str | None
) -> ClaimOut:
    return ClaimOut.model_validate(
        {
            **_summary(c),
            "policy_id": c.policy_id,
            "policy_number": policy_number(c.policy.policy_number, actor),
            "plan_name": c.policy.plan_name,
            "copay_amount": c.copay_amount,
            "deductible_amount": c.deductible_amount,
            "coinsurance_amount": c.coinsurance_amount,
            "over_limit_amount": c.over_limit_amount,
            "adjustment_amount": c.adjustment_amount,
            "denial_note": c.denial_note,
            "denial_description": denial_description,
            "appeal_count": c.appeal_count,
            "submitted_at": c.submitted_at,
            "adjudicated_at": c.adjudicated_at,
            "transfer_entry_id": c.transfer_entry_id,
            "allowed_transitions": sorted(TRANSITIONS.get(c.status, frozenset())),
            "lines": [ClaimLineOut.model_validate(ln) for ln in c.lines],
            "events": [ClaimEventOut.model_validate(e) for e in c.events],
            "attachments": [ClaimAttachmentOut.model_validate(a) for a in attachments],
        }
    )


def _remittance(r: Remittance) -> dict[str, object]:
    return {
        "id": r.id,
        "remittance_number": r.remittance_number,
        "insurer_id": r.insurer_id,
        "insurer_name": r.insurer.name,
        "reference": r.reference,
        "payment_date": r.payment_date,
        "status": r.status,
        "total_amount": r.total_amount,
        "posted_amount": r.posted_amount,
        "line_count": len(r.lines),
        "counts": summary(r),
        "created_at": r.created_at,
    }


def remittance_summary(r: Remittance) -> RemittanceSummaryOut:
    return RemittanceSummaryOut.model_validate(_remittance(r))


def remittance_out(r: Remittance) -> RemittanceOut:
    return RemittanceOut.model_validate(
        {
            **_remittance(r),
            "source_filename": r.source_filename,
            "posted_at": r.posted_at,
            "lines": [RemittanceLineOut.model_validate(ln) for ln in r.lines],
        }
    )
