from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["database"] == "ok"
    assert "X-Request-ID" in resp.headers


def test_login_with_username_and_email(client: TestClient, demo_password: str) -> None:
    for login in ("billing", "BILLING@careledger.example"):
        resp = client.post("/api/v1/auth/login", json={"login": login, "password": demo_password})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["token_type"] == "bearer"
        assert body["access_token"] and body["refresh_token"]


def test_all_demo_users_share_the_demo_password(client: TestClient, demo_password: str) -> None:
    for username in ("admin", "billing", "insurance", "accountant", "finance", "auditor"):
        resp = client.post(
            "/api/v1/auth/login", json={"login": username, "password": demo_password}
        )
        assert resp.status_code == 200, username


def test_bad_password_returns_error_envelope(client: TestClient) -> None:
    resp = client.post("/api/v1/auth/login", json={"login": "admin", "password": "nope"})
    assert resp.status_code == 401
    assert resp.json() == {
        "error": {"code": "invalid_credentials", "message": "Invalid credentials", "details": None}
    }


def test_me_requires_token(client: TestClient, login) -> None:  # type: ignore[no-untyped-def]
    assert client.get("/api/v1/auth/me").json()["error"]["code"] == "unauthenticated"
    resp = client.get("/api/v1/auth/me", headers=login("accountant"))
    assert resp.status_code == 200
    assert resp.json()["roles"] == ["accountant"]


def test_invalid_bearer_token(client: TestClient) -> None:
    resp = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer garbage"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "invalid_token"


def test_refresh_rotates_and_old_token_is_single_use(
    client: TestClient, demo_password: str
) -> None:
    tokens = client.post(
        "/api/v1/auth/login", json={"login": "finance", "password": demo_password}
    ).json()
    first = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert first.status_code == 200
    assert first.json()["refresh_token"] != tokens["refresh_token"]
    reuse = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert reuse.status_code == 401


def test_refresh_rejects_access_token(client: TestClient, demo_password: str) -> None:
    tokens = client.post(
        "/api/v1/auth/login", json={"login": "finance", "password": demo_password}
    ).json()
    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["access_token"]})
    assert resp.status_code == 401


def test_logout_revokes_refresh_token(client: TestClient, demo_password: str) -> None:
    tokens = client.post(
        "/api/v1/auth/login", json={"login": "auditor", "password": demo_password}
    ).json()
    assert (
        client.post(
            "/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]}
        ).status_code
        == 200
    )
    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert resp.status_code == 401


def test_validation_error_envelope(client: TestClient) -> None:
    resp = client.post("/api/v1/auth/login", json={"login": ""})
    assert resp.status_code == 422
    err = resp.json()["error"]
    assert err["code"] == "validation_error"
    assert isinstance(err["details"], list)


def test_unknown_route_uses_envelope(client: TestClient) -> None:
    resp = client.get("/api/v1/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"
