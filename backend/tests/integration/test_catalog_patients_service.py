from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation, Conflict, NotFound, ValidationFailed
from app.models.catalog import Service
from app.models.org import Department
from app.models.patients import Patient, VisitStatus
from app.services import catalog, patients
from app.services.audit import SYSTEM_ACTOR

D = Decimal
TODAY = date(2026, 11, 25)


@pytest.fixture
def dept(db: Session) -> Department:
    return db.scalars(select(Department).where(Department.code == "OPD")).one()


def test_service_create_update_and_validation(db: Session, dept: Department) -> None:
    s = catalog.create_service(
        db, SYSTEM_ACTOR, code="T-1", name="Test", department_id=dept.id, tax_rate=D("0")
    )
    with pytest.raises(Conflict):
        catalog.create_service(
            db, SYSTEM_ACTOR, code="T-1", name="Dup", department_id=dept.id, tax_rate=D("0")
        )
    with pytest.raises(NotFound):
        catalog.create_service(
            db, SYSTEM_ACTOR, code="T-2", name="x", department_id=999_999, tax_rate=D("0")
        )
    with pytest.raises(ValidationFailed):
        catalog.create_service(
            db, SYSTEM_ACTOR, code="T-3", name="x", department_id=dept.id, tax_rate=D("1.5")
        )
    updated = catalog.update_service(
        db, SYSTEM_ACTOR, s.id, name="Renamed", tax_rate=D("0.05"), is_active=False
    )
    assert (updated.name, updated.tax_rate, updated.is_active) == ("Renamed", D("0.05"), False)
    with pytest.raises(ValidationFailed):
        catalog.update_service(
            db, SYSTEM_ACTOR, s.id, name=None, tax_rate=D("-0.1"), is_active=None
        )
    with pytest.raises(NotFound):
        catalog.get_service(db, 999_999)


def test_default_price_list_switches(db: Session) -> None:
    old = catalog.default_price_list(db)
    new = catalog.create_price_list(db, SYSTEM_ACTOR, code="PL-2027", name="2027", is_default=True)
    assert catalog.default_price_list(db).id == new.id
    assert old.is_default is False
    with pytest.raises(NotFound):
        catalog.get_price_list(db, 999_999)
    service = db.scalars(select(Service)).first()
    assert service is not None
    with pytest.raises(ValidationFailed):
        catalog.set_price(
            db,
            SYSTEM_ACTOR,
            price_list_id=new.id,
            service_id=service.id,
            unit_price=D("-1"),
            effective_from=TODAY,
        )


def test_patient_update_and_validation(db: Session) -> None:
    p = patients.create_patient(
        db,
        SYSTEM_ACTOR,
        first_name="Ann",
        last_name="Lee",
        date_of_birth=date(1980, 1, 1),
        sex="female",
        phone="",
        email="",
        today=TODAY,
    )
    updated = patients.update_patient(
        db,
        SYSTEM_ACTOR,
        p.id,
        first_name="Anna",
        last_name=None,
        phone="555-0199",
        email="anna@example.com",
    )
    assert (updated.first_name, updated.phone) == ("Anna", "555-0199")
    with pytest.raises(ValidationFailed):
        patients.create_patient(
            db,
            SYSTEM_ACTOR,
            first_name="X",
            last_name="Y",
            date_of_birth=date(1980, 1, 1),
            sex="robot",
            phone="",
            email="",
            today=TODAY,
        )
    with pytest.raises(NotFound):
        patients.get_patient(db, 999_999)


def test_visit_rules(db: Session, dept: Department) -> None:
    p = db.scalars(select(Patient)).first()
    assert p is not None
    with pytest.raises(NotFound):
        patients.create_visit(
            db,
            SYSTEM_ACTOR,
            patient_id=p.id,
            department_id=999_999,
            visit_type="outpatient",
            admit_date=TODAY,
            discharge_date=None,
            attending_physician="",
        )
    with pytest.raises(ValidationFailed):
        patients.create_visit(
            db,
            SYSTEM_ACTOR,
            patient_id=p.id,
            department_id=dept.id,
            visit_type="spa",
            admit_date=TODAY,
            discharge_date=None,
            attending_physician="",
        )
    with pytest.raises(ValidationFailed):
        patients.create_visit(
            db,
            SYSTEM_ACTOR,
            patient_id=p.id,
            department_id=dept.id,
            visit_type="outpatient",
            admit_date=TODAY,
            discharge_date=date(2026, 1, 1),
            attending_physician="",
        )
    v = patients.create_visit(
        db,
        SYSTEM_ACTOR,
        patient_id=p.id,
        department_id=dept.id,
        visit_type="outpatient",
        admit_date=TODAY,
        discharge_date=None,
        attending_physician="Dr. Test",
    )
    closed = patients.set_visit_status(db, SYSTEM_ACTOR, v.id, "closed", None)
    assert closed.status == VisitStatus.CLOSED and closed.discharge_date == TODAY
    patients.set_visit_status(db, SYSTEM_ACTOR, v.id, "cancelled", None)
    with pytest.raises(BusinessRuleViolation):
        patients.set_visit_status(db, SYSTEM_ACTOR, v.id, "open", None)
    with pytest.raises(ValidationFailed):
        patients.set_visit_status(db, SYSTEM_ACTOR, v.id, "nope", None)
