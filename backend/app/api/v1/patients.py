from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.v1.billing_presenters import visit_out
from app.core.deps import DbSession, read_roles, require_roles
from app.core.errors import ErrorEnvelope
from app.core.pagination import Page, PageParams, page_params
from app.models.identity import RoleName
from app.models.patients import VisitStatus
from app.repositories import billing as repo
from app.schemas.billing import (
    PatientCreate,
    PatientDetailOut,
    PatientOut,
    PatientUpdate,
    VisitCreate,
    VisitOut,
    VisitStatusIn,
)
from app.services import patients as patients_service
from app.services.audit import Actor

router = APIRouter(
    tags=["patients"],
    responses={
        401: {"model": ErrorEnvelope},
        403: {"model": ErrorEnvelope},
        404: {"model": ErrorEnvelope},
        422: {"model": ErrorEnvelope},
    },
)

R = RoleName
PatientRead = Annotated[
    Actor,
    Depends(read_roles(R.BILLING_CLERK, R.INSURANCE_OFFICER, R.FINANCE_MANAGER, R.ACCOUNTANT)),
]
PatientWrite = Annotated[Actor, Depends(require_roles(R.BILLING_CLERK))]


def _detail(db: DbSession, patient_id: int) -> PatientDetailOut:
    patient = patients_service.get_patient(db, patient_id)
    return PatientDetailOut.model_validate(
        {
            **PatientOut.model_validate(patient).model_dump(),
            "deposit_balance": repo.deposit_balance(db, patient.id),
        }
    )


@router.get("/patients", response_model=Page[PatientOut])
def list_patients(
    _: PatientRead,
    db: DbSession,
    params: Annotated[PageParams, Depends(page_params)],
    search: Annotated[str | None, Query(max_length=100, description="MRN or name")] = None,
) -> Page[PatientOut]:
    rows, total = repo.list_patients(db, params, search=search)
    return Page(
        items=[PatientOut.model_validate(p) for p in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.post("/patients", response_model=PatientDetailOut, status_code=status.HTTP_201_CREATED)
def create_patient(body: PatientCreate, actor: PatientWrite, db: DbSession) -> PatientDetailOut:
    patient = patients_service.create_patient(
        db,
        actor,
        first_name=body.first_name,
        last_name=body.last_name,
        date_of_birth=body.date_of_birth,
        sex=body.sex,
        phone=body.phone,
        email=body.email,
        today=datetime.now(UTC).date(),
    )
    return _detail(db, patient.id)


@router.get("/patients/{patient_id}", response_model=PatientDetailOut)
def get_patient(patient_id: int, _: PatientRead, db: DbSession) -> PatientDetailOut:
    return _detail(db, patient_id)


@router.patch("/patients/{patient_id}", response_model=PatientDetailOut)
def update_patient(
    patient_id: int, body: PatientUpdate, actor: PatientWrite, db: DbSession
) -> PatientDetailOut:
    patients_service.update_patient(
        db,
        actor,
        patient_id,
        first_name=body.first_name,
        last_name=body.last_name,
        phone=body.phone,
        email=body.email,
    )
    return _detail(db, patient_id)


@router.get("/visits", response_model=Page[VisitOut])
def list_visits(
    _: PatientRead,
    db: DbSession,
    params: Annotated[PageParams, Depends(page_params)],
    patient_id: int | None = None,
    status: VisitStatus | None = None,
    department_id: int | None = None,
) -> Page[VisitOut]:
    rows, total = repo.list_visits(
        db,
        params,
        patient_id=patient_id,
        status=status.value if status else None,
        department_id=department_id,
    )
    return Page(
        items=[visit_out(v) for v in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.post("/visits", response_model=VisitOut, status_code=201)
def create_visit(body: VisitCreate, actor: PatientWrite, db: DbSession) -> VisitOut:
    visit = patients_service.create_visit(
        db,
        actor,
        patient_id=body.patient_id,
        department_id=body.department_id,
        visit_type=body.visit_type.value,
        admit_date=body.admit_date,
        discharge_date=body.discharge_date,
        attending_physician=body.attending_physician,
    )
    return visit_out(visit)


@router.get("/visits/{visit_id}", response_model=VisitOut)
def get_visit(visit_id: int, _: PatientRead, db: DbSession) -> VisitOut:
    return visit_out(patients_service.get_visit(db, visit_id))


@router.post("/visits/{visit_id}/status", response_model=VisitOut)
def set_visit_status(
    visit_id: int, body: VisitStatusIn, actor: PatientWrite, db: DbSession
) -> VisitOut:
    visit = patients_service.set_visit_status(
        db, actor, visit_id, body.status.value, body.discharge_date
    )
    return visit_out(visit)
