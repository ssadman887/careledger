"""Patients and visits (synthetic, minimal; not a clinical record)."""

from datetime import date

from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation, NotFound, ValidationFailed
from app.models.org import Department
from app.models.patients import Patient, Visit, VisitStatus, VisitType
from app.repositories import billing as repo
from app.services import audit
from app.services.audit import Actor

SEXES = {"female", "male", "other", "unknown"}


def get_patient(session: Session, patient_id: int) -> Patient:
    patient = repo.get_patient(session, patient_id)
    if patient is None or patient.deleted_at is not None:
        raise NotFound("Patient not found")
    return patient


def create_patient(
    session: Session,
    actor: Actor,
    *,
    first_name: str,
    last_name: str,
    date_of_birth: date,
    sex: str,
    phone: str,
    email: str,
    today: date,
) -> Patient:
    if sex not in SEXES:
        raise ValidationFailed("Invalid sex", code="invalid_sex")
    if date_of_birth > today:
        raise ValidationFailed("Date of birth cannot be in the future", code="invalid_dob")
    patient = Patient(
        mrn=repo.next_number(session, "patient_mrn_seq", "MRN"),
        first_name=first_name,
        last_name=last_name,
        date_of_birth=date_of_birth,
        sex=sex,
        phone=phone,
        email=email,
    )
    session.add(patient)
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="patient",
        entity_id=patient.id,
        action="create",
        after=audit.snapshot(patient),
    )
    return patient


def update_patient(
    session: Session,
    actor: Actor,
    patient_id: int,
    *,
    first_name: str | None,
    last_name: str | None,
    phone: str | None,
    email: str | None,
) -> Patient:
    patient = get_patient(session, patient_id)
    before = audit.snapshot(patient)
    for field, value in (
        ("first_name", first_name),
        ("last_name", last_name),
        ("phone", phone),
        ("email", email),
    ):
        if value is not None:
            setattr(patient, field, value)
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="patient",
        entity_id=patient.id,
        action="update",
        before=before,
        after=audit.snapshot(patient),
    )
    return patient


def get_visit(session: Session, visit_id: int) -> Visit:
    visit = repo.get_visit(session, visit_id)
    if visit is None:
        raise NotFound("Visit not found")
    return visit


def create_visit(
    session: Session,
    actor: Actor,
    *,
    patient_id: int,
    department_id: int,
    visit_type: str,
    admit_date: date,
    discharge_date: date | None,
    attending_physician: str,
) -> Visit:
    get_patient(session, patient_id)
    if session.get(Department, department_id) is None:
        raise NotFound("Department not found", code="department_not_found")
    if visit_type not in {t.value for t in VisitType}:
        raise ValidationFailed("Invalid visit type", code="invalid_visit_type")
    if discharge_date is not None and discharge_date < admit_date:
        raise ValidationFailed("Discharge date is before admission", code="invalid_dates")
    visit = Visit(
        visit_number=repo.next_number(session, "visit_number_seq", "V"),
        patient_id=patient_id,
        department_id=department_id,
        visit_type=visit_type,
        admit_date=admit_date,
        discharge_date=discharge_date,
        attending_physician=attending_physician,
        status=VisitStatus.CLOSED if discharge_date else VisitStatus.OPEN,
    )
    session.add(visit)
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="visit",
        entity_id=visit.id,
        action="create",
        after=audit.snapshot(visit),
    )
    return visit


def set_visit_status(
    session: Session, actor: Actor, visit_id: int, status: str, discharge_date: date | None
) -> Visit:
    visit = get_visit(session, visit_id)
    if status not in {s.value for s in VisitStatus}:
        raise ValidationFailed("Invalid visit status", code="invalid_status")
    if visit.status == VisitStatus.CANCELLED:
        raise BusinessRuleViolation("Cancelled visits cannot change", code="visit_cancelled")
    before = audit.snapshot(visit)
    if status == VisitStatus.CLOSED:
        end = discharge_date or visit.discharge_date or visit.admit_date
        if end < visit.admit_date:
            raise ValidationFailed("Discharge date is before admission", code="invalid_dates")
        visit.discharge_date = end
    visit.status = status
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="visit",
        entity_id=visit.id,
        action="status_change",
        before=before,
        after=audit.snapshot(visit),
    )
    return visit
