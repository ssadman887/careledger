"""Ledger HTTP API: roles, validation envelope, approvals, reports, chart of accounts, periods."""

import pytest
from fastapi.testclient import TestClient

ENTRY = "/api/v1/journal-entries"


def _lines(acct, amount: str = "250.00", dr: str = "1010", cr: str = "4120"):  # type: ignore[no-untyped-def]
    return [
        {"account_id": acct(dr), "debit": amount, "description": "cash"},
        {"account_id": acct(cr), "credit": amount, "description": "radiology"},
    ]


def _post(client: TestClient, headers, acct, **kw):  # type: ignore[no-untyped-def]
    body = {
        "entry_date": kw.pop("on", "2026-06-10"),
        "memo": kw.pop("memo", "Test entry"),
        "lines": kw.pop("lines", None) or _lines(acct, **kw),
    }
    return client.post(ENTRY, json=body, headers=headers)


def test_accountant_posts_manual_entry(client: TestClient, login, acct) -> None:  # type: ignore[no-untyped-def]
    resp = _post(client, login("accountant"), acct)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "posted"
    assert body["total"] == "250.00"
    assert body["entry_number"].startswith("JE-")
    assert [ln["debit"] for ln in body["lines"]] == ["250.00", "0.00"]
    assert body["lines"][1]["account_code"] == "4120"


def test_unbalanced_entry_returns_envelope(client: TestClient, login, acct) -> None:  # type: ignore[no-untyped-def]
    lines = _lines(acct)
    lines[1]["credit"] = "249.99"
    resp = _post(client, login("accountant"), acct, lines=lines)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "unbalanced_entry"


def test_float_money_rejected(client: TestClient, login, acct) -> None:  # type: ignore[no-untyped-def]
    lines = _lines(acct)
    lines[0]["debit"] = 250.0
    lines[1]["credit"] = 250.0
    resp = _post(client, login("accountant"), acct, lines=lines)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


def test_single_line_rejected(client: TestClient, login, acct) -> None:  # type: ignore[no-untyped-def]
    resp = _post(client, login("accountant"), acct, lines=_lines(acct)[:1])
    assert resp.status_code == 422


@pytest.mark.parametrize("username", ["billing", "insurance", "admin"])
def test_journal_forbidden_for_other_roles(client: TestClient, login, acct, username: str) -> None:  # type: ignore[no-untyped-def]
    headers = login(username)
    assert client.get(ENTRY, headers=headers).status_code == 403
    assert _post(client, headers, acct).status_code == 403


def test_auditor_reads_but_cannot_post(client: TestClient, login, acct) -> None:  # type: ignore[no-untyped-def]
    headers = login("auditor")
    assert client.get(ENTRY, headers=headers).status_code == 200
    assert client.get("/api/v1/reports/trial-balance", headers=headers).status_code == 200
    assert _post(client, headers, acct).status_code == 403


def test_approval_flow_over_threshold(client: TestClient, login, acct) -> None:  # type: ignore[no-untyped-def]
    accountant, finance = login("accountant"), login("finance")
    created = _post(client, accountant, acct, amount="25000.00").json()
    assert created["status"] == "pending_approval"
    entry_id = created["id"]
    # Accountants cannot approve; finance managers can.
    assert client.post(f"{ENTRY}/{entry_id}/approve", headers=accountant).status_code == 403
    pending = client.get(ENTRY, params={"status": "pending_approval"}, headers=finance).json()
    assert any(e["id"] == entry_id for e in pending["items"])
    approved = client.post(f"{ENTRY}/{entry_id}/approve", headers=finance)
    assert approved.status_code == 200
    assert approved.json()["status"] == "posted"
    again = client.post(f"{ENTRY}/{entry_id}/approve", headers=finance)
    assert again.status_code == 409


def test_reverse_via_api(client: TestClient, login, acct) -> None:  # type: ignore[no-untyped-def]
    headers = login("accountant")
    entry = _post(client, headers, acct).json()
    resp = client.post(
        f"{ENTRY}/{entry['id']}/reverse", json={"reason": "Wrong department"}, headers=headers
    )
    assert resp.status_code == 201
    reversal = resp.json()
    assert reversal["reversal_of_id"] == entry["id"]
    assert reversal["lines"][0]["credit"] == "250.00"
    original = client.get(f"{ENTRY}/{entry['id']}", headers=headers).json()
    assert original["reversed_by_id"] == reversal["id"]
    assert (
        client.post(
            f"{ENTRY}/{entry['id']}/reverse", json={"reason": "x"}, headers=headers
        ).status_code
        == 409
    )


def test_list_filters(client: TestClient, login, acct) -> None:  # type: ignore[no-untyped-def]
    headers = login("accountant")
    _post(client, headers, acct, memo="Needle memo")
    found = client.get(ENTRY, params={"search": "needle"}, headers=headers).json()
    assert found["total"] == 1
    by_account = client.get(
        ENTRY, params={"account_id": acct("4120"), "source_type": "manual"}, headers=headers
    ).json()
    assert by_account["total"] >= 1
    ranged = client.get(
        ENTRY,
        params={"date_from": "2026-06-10", "date_to": "2026-06-10", "sort": "total"},
        headers=headers,
    ).json()
    assert all(e["entry_date"] == "2026-06-10" for e in ranged["items"])


def test_closing_period_then_posting_is_rejected(client: TestClient, login, acct) -> None:  # type: ignore[no-untyped-def]
    accountant = login("accountant")
    periods = client.get("/api/v1/fiscal-periods", headers=accountant).json()
    jan = next(p for p in periods if p["name"] == "2026-01")
    check = client.get(f"/api/v1/fiscal-periods/{jan['id']}/close-check", headers=accountant).json()
    assert check["can_close"] is True and check["trial_balance_balanced"] is True
    closed = client.post(f"/api/v1/fiscal-periods/{jan['id']}/close", headers=accountant)
    assert closed.status_code == 200 and closed.json()["status"] == "closed"

    resp = _post(client, accountant, acct, on="2026-01-15")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "period_closed"

    again = client.post(f"/api/v1/fiscal-periods/{jan['id']}/close", headers=accountant)
    assert again.json()["error"]["code"] == "close_check_failed"


def test_period_roles(client: TestClient, login) -> None:  # type: ignore[no-untyped-def]
    body = {"name": "2030-01", "start_date": "2030-01-01", "end_date": "2030-01-31"}
    assert (
        client.post("/api/v1/fiscal-periods", json=body, headers=login("billing")).status_code
        == 403
    )
    created = client.post("/api/v1/fiscal-periods", json=body, headers=login("accountant"))
    assert created.status_code == 201
    dup = client.post("/api/v1/fiscal-periods", json=body, headers=login("accountant"))
    assert dup.status_code == 409
    bad = {**body, "name": "bad", "start_date": "2031-02-01", "end_date": "2031-01-01"}
    assert (
        client.post("/api/v1/fiscal-periods", json=bad, headers=login("accountant")).status_code
        == 422
    )


def test_reports_endpoints(client: TestClient, login, acct) -> None:  # type: ignore[no-untyped-def]
    headers = login("finance")
    _post(client, login("accountant"), acct, amount="1000.00", on="2026-07-01")
    _post(client, login("accountant"), acct, amount="400.00", on="2026-07-02", dr="5200", cr="1020")

    tb = client.get("/api/v1/reports/trial-balance", headers=headers).json()
    assert tb["balanced"] is True
    assert tb["total_debit"] == tb["total_credit"]

    inc = client.get(
        "/api/v1/reports/income-statement",
        params={"date_from": "2026-07-01", "date_to": "2026-07-31"},
        headers=headers,
    ).json()
    assert inc["revenue"]["total"] == "1000.00"
    assert inc["expenses"]["total"] == "400.00"
    assert inc["net_income"] == "600.00"

    bs = client.get(
        "/api/v1/reports/balance-sheet", params={"as_of": "2026-07-31"}, headers=headers
    ).json()
    assert bs["balanced"] is True

    bad = client.get(
        "/api/v1/reports/income-statement",
        params={"date_from": "2026-08-01", "date_to": "2026-07-01"},
        headers=headers,
    )
    assert bad.status_code == 422
    assert client.get("/api/v1/reports/trial-balance", headers=login("billing")).status_code == 403


def test_account_ledger_running_balance(client: TestClient, login, acct) -> None:  # type: ignore[no-untyped-def]
    accountant = login("accountant")
    for amount, on in (("100.00", "2026-08-01"), ("50.00", "2026-08-05")):
        _post(client, accountant, acct, amount=amount, on=on)
    _post(client, accountant, acct, amount="30.00", on="2026-08-07", dr="5200", cr="1010")

    resp = client.get(
        f"/api/v1/reports/account-ledger/{acct('1010')}",
        params={"date_from": "2026-08-01", "date_to": "2026-08-31"},
        headers=login("finance"),
    ).json()
    assert resp["normal_balance"] == "debit"
    opening = float(resp["opening_balance"])  # display-only comparison in a test
    assert [r["running_balance"] for r in resp["rows"]] == [
        f"{opening + 100:.2f}",
        f"{opening + 150:.2f}",
        f"{opening + 120:.2f}",
    ]
    assert resp["closing_balance"] == f"{opening + 120:.2f}"

    paged = client.get(
        f"/api/v1/reports/account-ledger/{acct('1010')}",
        params={"date_from": "2026-08-01", "page": 2, "page_size": 2},
        headers=login("finance"),
    ).json()
    assert paged["total"] == 3 and len(paged["rows"]) == 1
    assert paged["rows"][0]["running_balance"] == f"{opening + 120:.2f}"


# ------------------------------------------------------------------ chart of accounts


def test_chart_of_accounts_seeded(client: TestClient, login) -> None:  # type: ignore[no-untyped-def]
    resp = client.get(
        "/api/v1/accounts", params={"page_size": 200}, headers=login("accountant")
    ).json()
    codes = {a["code"] for a in resp["items"]}
    assert {"1100", "1110", "2010", "4110", "4900", "5400"} <= codes
    revenue = client.get(
        "/api/v1/accounts",
        params={"type": "revenue", "postable_only": True},
        headers=login("accountant"),
    ).json()
    assert all(a["type"] == "revenue" and not a["is_header"] for a in revenue["items"])


def test_admin_manages_accounts(client: TestClient, login, acct) -> None:  # type: ignore[no-untyped-def]
    admin = login("admin")
    body = {"code": "5950", "name": "Training", "type": "expense", "parent_id": acct("5000")}
    created = client.post("/api/v1/accounts", json=body, headers=admin)
    assert created.status_code == 201
    assert created.json()["normal_balance"] == "debit"
    assert client.post("/api/v1/accounts", json=body, headers=admin).status_code == 409

    not_header = {**body, "code": "5951", "parent_id": acct("5100")}
    assert (
        client.post("/api/v1/accounts", json=not_header, headers=admin).json()["error"]["code"]
        == "parent_not_header"
    )
    wrong_type = {**body, "code": "5952", "parent_id": acct("1000")}
    assert (
        client.post("/api/v1/accounts", json=wrong_type, headers=admin).json()["error"]["code"]
        == "parent_type_mismatch"
    )

    patched = client.patch(
        f"/api/v1/accounts/{created.json()['id']}",
        json={"name": "Staff training", "is_active": False},
        headers=admin,
    )
    assert patched.status_code == 200
    assert patched.json()["is_active"] is False
    assert (
        client.post(
            "/api/v1/accounts", json={**body, "code": "5953"}, headers=login("billing")
        ).status_code
        == 403
    )


def test_account_with_balance_cannot_be_deactivated(client: TestClient, login, acct) -> None:  # type: ignore[no-untyped-def]
    resp = client.patch(
        f"/api/v1/accounts/{acct('1020')}", json={"is_active": False}, headers=login("admin")
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "non_zero_balance"


def test_departments_and_cost_centers(client: TestClient, login, acct) -> None:  # type: ignore[no-untyped-def]
    depts = client.get("/api/v1/departments", headers=login("billing")).json()
    assert {d["code"] for d in depts} >= {"EMER", "RAD", "LAB"}
    assert all(d["revenue_account_id"] for d in depts if d["code"] != "ADMIN")
    centers = client.get("/api/v1/cost-centers", headers=login("billing")).json()
    assert len(centers) == len(depts)
    created = client.post(
        "/api/v1/departments",
        json={"code": "ONC", "name": "Oncology", "revenue_account_id": acct("4950")},
        headers=login("admin"),
    )
    assert created.status_code == 201
    bad = client.post(
        "/api/v1/departments",
        json={"code": "ONC2", "name": "X", "revenue_account_id": acct("1010")},
        headers=login("admin"),
    )
    assert bad.status_code == 422
