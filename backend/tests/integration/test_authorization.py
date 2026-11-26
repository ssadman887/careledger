"""Authorization review, automated: every route is protected and every role rule holds.

The matrix comes from the live route table (app.authz), so a new endpoint without a role
dependency, or a role that can call something it should not, fails here.
"""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.authz import PUBLIC, ROLE_ORDER, markdown, routes
from app.main import app

USERS = {
    "admin": "admin",
    "billing_clerk": "billing",
    "insurance_officer": "insurance",
    "accountant": "accountant",
    "finance_manager": "finance",
    "auditor": "auditor",
}
ROUTES = routes(app)


def _url(path: str) -> str:
    # Any id/kind works: authorization is checked before the record is looked up.
    return re.sub(r"\{[^}]+\}", "1", path)


def test_public_routes_are_exactly_the_allowlist() -> None:
    unauthenticated = {(r.method, r.path) for r in ROUTES if not r.authenticated}
    assert unauthenticated == set(PUBLIC)


@pytest.mark.parametrize(
    "route", [r for r in ROUTES if not r.public], ids=lambda r: f"{r.method} {r.path}"
)
def test_every_protected_route_rejects_anonymous_requests(client: TestClient, route) -> None:  # type: ignore[no-untyped-def]
    resp = client.request(route.method, _url(route.path), json={})
    assert resp.status_code == 401, resp.text


def test_roles_outside_each_rule_are_forbidden(client: TestClient, login) -> None:  # type: ignore[no-untyped-def]
    headers = {role: login(user) for role, user in USERS.items()}
    checked = 0
    for route in ROUTES:
        if route.public or route.roles is None:
            continue
        for role in ROLE_ORDER:
            if role in route.roles:
                continue
            resp = client.request(route.method, _url(route.path), json={}, headers=headers[role])
            assert resp.status_code == 403, (
                f"{role} -> {route.method} {route.path}: {resp.status_code}"
            )
            checked += 1
    assert checked > 300  # the matrix is not trivially empty


# POST endpoints that only compute and change nothing.
READ_ONLY_POSTS = {"/api/v1/payroll/tax-preview"}


def test_auditors_can_read_everything_role_gated_but_write_nothing() -> None:
    for route in ROUTES:
        if route.roles is None:
            continue
        if route.method == "GET" or route.path in READ_ONLY_POSTS:
            assert "auditor" in route.roles, f"auditor cannot read {route.path}"
        else:
            assert "auditor" not in route.roles, f"auditor can write {route.method} {route.path}"


def test_authorization_doc_is_current() -> None:
    doc = Path(__file__).resolve().parents[3] / "docs" / "AUTHORIZATION.md"
    assert doc.read_text(encoding="utf-8") == markdown(app), "run: python -m app.authz"
