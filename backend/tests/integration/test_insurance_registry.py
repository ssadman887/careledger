from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.models.insurance import Insurer
from app.models.patients import Patient
from app.services import insurance
from app.services.audit import SYSTEM_ACTOR

D = Decimal


def _policy_args(db: Session, **over):  # type: ignore[no-untyped-def]
    patient = db.scalars(select(Patient)).first()
    insurer = db.scalars(select(Insurer).where(Insurer.code == "SUN")).one()
    args = {
        "patient_id": patient.id,
        "insurer_id": insurer.id,
        "policy_number": "REG-1",  # type: ignore[union-attr]
        "plan_name": "Plan",
        "coverage_percent": D("80"),
        "copay": D("0"),
        "deductible": D("0"),
        "annual_limit": D("1000"),
        "effective_from": date(2026, 1, 1),
        "effective_to": None,
    }
    args.update(over)
    return args


def test_update_insurer_rates_and_status(client: TestClient, login) -> None:  # type: ignore[no-untyped-def]
    officer = login("insurance")
    insurers = client.get("/api/v1/insurers", headers=officer).json()
    sun = next(i for i in insurers if i["code"] == "SUN")
    resp = client.patch(
        f"/api/v1/insurers/{sun['id']}",
        headers=officer,
        json={
            "name": "Sunhaven Assurance Co",
            "contact_email": "edi@sun.example",
            "approval_rate": "0.5",
            "partial_rate": "0.3",
            "denial_rate": "0.2",
        },
    )
    assert resp.status_code == 200
    assert (
        D(resp.json()["approval_rate"]) == D("0.5")
        and resp.json()["name"] == "Sunhaven Assurance Co"
    )
    partial = client.patch(
        f"/api/v1/insurers/{sun['id']}", headers=officer, json={"approval_rate": "0.5"}
    )
    assert partial.status_code == 422
    bad_sum = client.patch(
        f"/api/v1/insurers/{sun['id']}",
        headers=officer,
        json={"approval_rate": "0.5", "partial_rate": "0.5", "denial_rate": "0.5"},
    )
    assert bad_sum.json()["error"]["code"] == "invalid_rates"
    off = client.patch(f"/api/v1/insurers/{sun['id']}", headers=officer, json={"is_active": False})
    assert off.json()["is_active"] is False
    active = client.get("/api/v1/insurers", params={"active_only": True}, headers=officer).json()
    assert all(i["code"] != "SUN" for i in active)


def test_policy_validation(db: Session) -> None:
    with pytest.raises(ValidationFailed):
        insurance.create_policy(db, SYSTEM_ACTOR, **_policy_args(db, effective_to=date(2025, 1, 1)))
    with pytest.raises(ValidationFailed):
        insurance.create_policy(db, SYSTEM_ACTOR, **_policy_args(db, coverage_percent=D("120")))
    with pytest.raises(ValidationFailed):
        insurance.create_policy(db, SYSTEM_ACTOR, **_policy_args(db, copay=D("-1")))
    insurance.create_policy(db, SYSTEM_ACTOR, **_policy_args(db))
    with pytest.raises(Conflict):
        insurance.create_policy(db, SYSTEM_ACTOR, **_policy_args(db))
    sun = db.scalars(select(Insurer).where(Insurer.code == "SUN")).one()
    insurance.update_insurer(
        db, SYSTEM_ACTOR, sun.id, name=None, contact_email=None, is_active=False, rates=None
    )
    with pytest.raises(ValidationFailed):
        insurance.create_policy(db, SYSTEM_ACTOR, **_policy_args(db, policy_number="REG-2"))
    with pytest.raises(NotFound):
        insurance.get_policy(db, 999_999)
    with pytest.raises(NotFound):
        insurance.get_insurer(db, 999_999)
    with pytest.raises(Conflict):
        insurance.create_insurer(
            db,
            SYSTEM_ACTOR,
            code="SUN",
            name="dup",
            payer_id="",
            contact_email="",
            approval_rate=D("1"),
            partial_rate=D("0"),
            denial_rate=D("0"),
        )
