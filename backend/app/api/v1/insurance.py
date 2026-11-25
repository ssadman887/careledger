from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.v1.insurance_presenters import policy_out
from app.core.deps import DbSession, read_roles, require_roles
from app.core.errors import ErrorEnvelope
from app.core.pagination import Page, PageParams, page_params
from app.models.identity import RoleName
from app.repositories import insurance as repo
from app.schemas.insurance import (
    DenialCodeOut,
    InsurerCreate,
    InsurerOut,
    InsurerUpdate,
    PolicyCreate,
    PolicyOut,
    PolicyStatusIn,
)
from app.services import insurance as insurance_service
from app.services.audit import Actor

router = APIRouter(
    tags=["insurance"],
    responses={
        401: {"model": ErrorEnvelope},
        403: {"model": ErrorEnvelope},
        404: {"model": ErrorEnvelope},
        409: {"model": ErrorEnvelope},
        422: {"model": ErrorEnvelope},
    },
)

R = RoleName
InsuranceRead = Annotated[
    Actor,
    Depends(
        read_roles(R.INSURANCE_OFFICER, R.BILLING_CLERK, R.FINANCE_MANAGER, R.ACCOUNTANT, R.ADMIN)
    ),
]
InsurerWrite = Annotated[Actor, Depends(require_roles(R.INSURANCE_OFFICER, R.ADMIN))]
PolicyWrite = Annotated[Actor, Depends(require_roles(R.INSURANCE_OFFICER, R.BILLING_CLERK))]


@router.get("/insurers", response_model=list[InsurerOut])
def list_insurers(_: InsuranceRead, db: DbSession, active_only: bool = False) -> list[InsurerOut]:
    return [InsurerOut.model_validate(i) for i in repo.list_insurers(db, active_only=active_only)]


@router.post("/insurers", response_model=InsurerOut, status_code=status.HTTP_201_CREATED)
def create_insurer(body: InsurerCreate, actor: InsurerWrite, db: DbSession) -> InsurerOut:
    insurer = insurance_service.create_insurer(
        db,
        actor,
        code=body.code,
        name=body.name,
        payer_id=body.payer_id,
        contact_email=body.contact_email,
        approval_rate=body.approval_rate,
        partial_rate=body.partial_rate,
        denial_rate=body.denial_rate,
    )
    return InsurerOut.model_validate(insurer)


@router.patch("/insurers/{insurer_id}", response_model=InsurerOut)
def update_insurer(
    insurer_id: int, body: InsurerUpdate, actor: InsurerWrite, db: DbSession
) -> InsurerOut:
    rates = None
    if (
        body.approval_rate is not None
        and body.partial_rate is not None
        and body.denial_rate is not None
    ):
        rates = (body.approval_rate, body.partial_rate, body.denial_rate)
    insurer = insurance_service.update_insurer(
        db,
        actor,
        insurer_id,
        name=body.name,
        contact_email=body.contact_email,
        is_active=body.is_active,
        rates=rates,
    )
    return InsurerOut.model_validate(insurer)


@router.get("/policies", response_model=Page[PolicyOut])
def list_policies(
    actor: InsuranceRead,
    db: DbSession,
    params: Annotated[PageParams, Depends(page_params)],
    patient_id: int | None = None,
    insurer_id: int | None = None,
    active_only: bool = False,
) -> Page[PolicyOut]:
    rows, total = repo.list_policies(
        db, params, patient_id=patient_id, insurer_id=insurer_id, active_only=active_only
    )
    return Page(
        items=[policy_out(p, actor) for p in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.post("/policies", response_model=PolicyOut, status_code=status.HTTP_201_CREATED)
def create_policy(body: PolicyCreate, actor: PolicyWrite, db: DbSession) -> PolicyOut:
    policy = insurance_service.create_policy(
        db,
        actor,
        patient_id=body.patient_id,
        insurer_id=body.insurer_id,
        policy_number=body.policy_number,
        plan_name=body.plan_name,
        coverage_percent=body.coverage_percent,
        copay=body.copay,
        deductible=body.deductible,
        annual_limit=body.annual_limit,
        effective_from=body.effective_from,
        effective_to=body.effective_to,
    )
    return policy_out(policy, actor)


@router.post("/policies/{policy_id}/status", response_model=PolicyOut)
def set_policy_status(
    policy_id: int, body: PolicyStatusIn, actor: PolicyWrite, db: DbSession
) -> PolicyOut:
    return policy_out(
        insurance_service.set_policy_active(db, actor, policy_id, body.is_active), actor
    )


@router.get("/denial-codes", response_model=list[DenialCodeOut])
def list_denial_codes(_: InsuranceRead, db: DbSession) -> list[DenialCodeOut]:
    return [DenialCodeOut.model_validate(d) for d in repo.denial_codes(db)]
