import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.models.audit import AuditLog

NEW_USER = {
    "email": "new.clerk@careledger.example",
    "username": "newclerk",
    "full_name": "New Clerk",
    "password": "another-password",
    "roles": ["billing_clerk"],
}


@pytest.mark.parametrize("username", ["billing", "insurance", "accountant", "finance"])
def test_non_admins_cannot_list_users(client: TestClient, login, username: str) -> None:  # type: ignore[no-untyped-def]
    resp = client.get("/api/v1/users", headers=login(username))
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden"


def test_unauthenticated_gets_401(client: TestClient) -> None:
    assert client.get("/api/v1/users").status_code == 401


def test_auditor_can_read_but_not_write(client: TestClient, login) -> None:  # type: ignore[no-untyped-def]
    headers = login("auditor")
    resp = client.get("/api/v1/users", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["total"] >= 6
    assert client.post("/api/v1/users", json=NEW_USER, headers=headers).status_code == 403


def test_admin_creates_user_and_it_is_audited(client: TestClient, login, db: Session) -> None:  # type: ignore[no-untyped-def]
    resp = client.post("/api/v1/users", json=NEW_USER, headers=login("admin"))
    assert resp.status_code == 201, resp.text
    user = resp.json()
    assert user["roles"] == ["billing_clerk"]
    assert "password_hash" not in user

    entry = db.scalars(
        select(AuditLog).where(
            AuditLog.entity_type == "user",
            AuditLog.entity_id == str(user["id"]),
            AuditLog.action == "create",
        )
    ).one()
    assert entry.actor_label == "admin@careledger.example"
    assert entry.after is not None and "password_hash" not in entry.after
    assert entry.after["roles"] == ["billing_clerk"]

    # The new user can log in with their own password.
    login_resp = client.post(
        "/api/v1/auth/login", json={"login": "newclerk", "password": "another-password"}
    )
    assert login_resp.status_code == 200


def test_duplicate_user_conflicts(client: TestClient, login) -> None:  # type: ignore[no-untyped-def]
    headers = login("admin")
    assert client.post("/api/v1/users", json=NEW_USER, headers=headers).status_code == 201
    dup = client.post("/api/v1/users", json=NEW_USER, headers=headers)
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "user_exists"


def test_unknown_role_rejected(client: TestClient, login) -> None:  # type: ignore[no-untyped-def]
    resp = client.post(
        "/api/v1/users", json={**NEW_USER, "roles": ["superuser"]}, headers=login("admin")
    )
    assert resp.status_code == 422


def test_deactivation_is_status_change_and_blocks_login(
    client: TestClient,
    login,
    db: Session,
    demo_password: str,  # type: ignore[no-untyped-def]
) -> None:
    headers = login("admin")
    users = client.get("/api/v1/users", params={"search": "billing"}, headers=headers).json()
    billing_id = users["items"][0]["id"]
    resp = client.patch(f"/api/v1/users/{billing_id}", json={"is_active": False}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False
    entry = db.scalars(
        select(AuditLog).where(
            AuditLog.entity_id == str(billing_id), AuditLog.action == "status_change"
        )
    ).one()
    assert entry.before is not None and entry.before["is_active"] is True
    assert (
        client.post(
            "/api/v1/auth/login", json={"login": "billing", "password": demo_password}
        ).status_code
        == 401
    )


def test_admin_cannot_lock_themselves_out(client: TestClient, login) -> None:  # type: ignore[no-untyped-def]
    headers = login("admin")
    me = client.get("/api/v1/auth/me", headers=headers).json()
    resp = client.patch(f"/api/v1/users/{me['id']}", json={"is_active": False}, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "self_lockout"


def test_list_users_pagination_and_sort(client: TestClient, login) -> None:  # type: ignore[no-untyped-def]
    resp = client.get(
        "/api/v1/users",
        params={"page_size": 2, "page": 2, "sort": "-username"},
        headers=login("admin"),
    )
    body = resp.json()
    assert body["page"] == 2 and body["page_size"] == 2
    assert len(body["items"]) == 2
    assert (
        client.get("/api/v1/users", params={"page_size": 500}, headers=login("admin")).status_code
        == 422
    )


def test_audit_log_is_readable_by_auditor_not_clerk(client: TestClient, login) -> None:  # type: ignore[no-untyped-def]
    resp = client.get("/api/v1/audit-log", params={"entity_type": "user"}, headers=login("auditor"))
    assert resp.status_code == 200
    assert all(item["entity_type"] == "user" for item in resp.json()["items"])
    assert client.get("/api/v1/audit-log", headers=login("billing")).status_code == 403


def test_audit_log_rejects_update_and_delete_at_db_level(
    client: TestClient, login, db: Session
) -> None:  # type: ignore[no-untyped-def]
    login("admin")  # writes a login audit row
    db.flush()
    entry_id = db.scalars(select(AuditLog.id).order_by(AuditLog.id.desc())).first()
    for stmt in (
        "UPDATE audit_log SET action = 'tampered' WHERE id = :id",
        "DELETE FROM audit_log WHERE id = :id",
    ):
        nested = db.begin_nested()
        with pytest.raises(DBAPIError, match="append-only"):
            db.execute(text(stmt), {"id": entry_id})
        nested.rollback()
