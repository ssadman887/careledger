"""Phase 6: dashboards (SQL aggregates), exports, notifications, global search, audit viewer."""

import csv
import io
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.core.pagination import PageParams
from app.models.audit import AuditLog
from app.models.notifications import Notification
from app.models.patients import Patient
from app.services import dashboard, exports, ledger, notifications, reports, search
from app.services.audit import SYSTEM_ACTOR
from app.services.ledger import LineInput
from tests.conftest import check_deferred
from tests.integration import test_phase5 as p5
from tests.integration.test_phase4 import account_balance, issue

D = Decimal
staff = p5.staff  # re-used fixture
calculated_run, posted_payroll = p5.calculated_run, p5.posted_payroll
AS_OF = date(2026, 11, 25)


@pytest.fixture
def svc(db: Session):  # type: ignore[no-untyped-def]
    from app.models.catalog import Service

    ids = {s.code: s.id for s in db.scalars(select(Service)).all()}
    return lambda code: ids[code]


@pytest.fixture
def patient(db: Session) -> Patient:
    return db.scalars(select(Patient).order_by(Patient.id)).first()  # type: ignore[return-value]


def kpis(section: dashboard.Section) -> dict[str, str]:
    return {k.key: k.value for k in section.kpis}


def notes_for(db: Session, username: str) -> list[Notification]:
    from app.models.identity import User

    uid = db.scalars(select(User.id).where(User.username == username)).one()
    return list(db.scalars(select(Notification).where(Notification.user_id == uid)).all())


# ------------------------------------------------------------------ dashboards


def test_sections_follow_roles(db: Session, actor_for) -> None:  # type: ignore[no-untyped-def]
    ids = {
        u: [s.id for s in dashboard.build(db, actor_for(u), AS_OF).sections]
        for u in ("billing", "insurance", "accountant", "finance", "admin", "auditor")
    }
    assert ids == {
        "billing": ["revenue"],
        "insurance": ["insurance"],
        "accountant": ["finance"],
        "finance": ["finance", "revenue", "insurance"],
        "admin": ["administration"],
        "auditor": ["finance", "revenue", "insurance", "administration"],
    }


def test_finance_kpis_reconcile_with_the_ledger(
    db: Session, actor_for, patient, svc, staff
) -> None:  # type: ignore[no-untyped-def]
    issue(db, actor_for("billing"), patient, svc, date(2026, 11, 10))  # 120.00 revenue + AR
    posted_payroll(db, actor_for)  # September salaries
    check_deferred(db)
    section = dashboard.finance_section(db, actor_for("finance"), AS_OF)
    k = kpis(section)
    cash = account_balance(db, "1010") + account_balance(db, "1020") + account_balance(db, "1030")
    assert D(k["cash"]) == cash
    assert D(k["ar"]) == account_balance(db, "1100") + account_balance(db, "1110")
    statement = reports.income_statement(db, date(2026, 1, 1), AS_OF)
    assert D(k["revenue_ytd"]) == statement.revenue.total
    assert D(k["expenses_ytd"]) == statement.expenses.total
    assert D(k["net_income_ytd"]) == statement.net_income
    trend = next(c for c in section.charts if c.id == "pl_trend")
    assert len(trend.rows) == 12 and trend.rows[-1].label == "Nov 2026"
    assert sum(D(r.values["revenue"]) for r in trend.rows) == statement.revenue.total
    sep = next(r for r in trend.rows if r.label == "Sep 2026")
    assert D(sep.values["expenses"]) > 0
    by_dept = next(c for c in section.charts if c.id == "revenue_by_department")
    assert sum(D(r.values["revenue"]) for r in by_dept.rows) == statement.revenue.total


def test_revenue_section_counts_invoices_and_overdue(db: Session, actor_for, patient, svc) -> None:  # type: ignore[no-untyped-def]
    clerk = actor_for("billing")
    issue(db, clerk, patient, svc, date(2026, 11, 3))
    issue(db, clerk, patient, svc, date(2026, 8, 1))  # due long before AS_OF
    k = kpis(dashboard.revenue_section(db, AS_OF))
    assert k["invoices_mtd"] == "120.00"
    assert D(k["patient_ar"]) == D("240.00")
    assert D(k["overdue"]) == D("120.00")


def test_insurance_and_admin_sections(db: Session, actor_for) -> None:  # type: ignore[no-untyped-def]
    ins = dashboard.insurance_section(db)
    assert kpis(ins)["denial_rate"] == "0.0"  # no adjudicated claims in the test database
    admin = dashboard.administration_section(db, AS_OF)
    assert kpis(admin)["active_users"] == "6"
    by_day = next(c for c in admin.charts if c.id == "audit_by_day")
    assert len(by_day.rows) == 7


def test_dashboard_api(client: TestClient, login) -> None:  # type: ignore[no-untyped-def]
    resp = client.get("/api/v1/dashboard?as_of=2026-11-25", headers=login("finance"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["as_of"] == "2026-11-25"
    finance = body["sections"][0]
    assert finance["id"] == "finance"
    assert all(isinstance(k["value"], str) for k in finance["kpis"])  # money never as floats
    assert client.get("/api/v1/dashboard").status_code == 401


# ------------------------------------------------------------------ exports


def test_safe_cell_neutralises_formulas_but_not_numbers() -> None:
    assert exports.safe_cell("=HYPERLINK(1)") == "'=HYPERLINK(1)"
    assert exports.safe_cell("@SUM(A1)") == "'@SUM(A1)"
    assert exports.safe_cell("+cmd") == "'+cmd"
    assert exports.safe_cell("-123.45") == "-123.45"
    assert exports.safe_cell("Cash") == "Cash"


def test_trial_balance_csv_and_pdf(db: Session) -> None:
    table = exports.trial_balance(reports.trial_balance(db, None, None), AS_OF)
    content, media, name = exports.render(table, "csv")
    assert media.startswith("text/csv") and name == "trial-balance-2026-11-25.csv"
    assert content.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))
    assert rows[0] == ["Code", "Account", "Type", "Debits", "Credits", "Balance Dr", "Balance Cr"]
    assert rows[-1][1] == "Totals" and rows[-1][3] == rows[-1][4]  # balanced
    pdf, media, name = exports.render(table, "pdf")
    assert pdf.startswith(b"%PDF") and name.endswith(".pdf")


def test_export_endpoints_are_role_checked_and_audited(
    client: TestClient, login, db: Session
) -> None:  # type: ignore[no-untyped-def]
    fin = login("finance")
    for path in (
        "/api/v1/exports/trial-balance?format=csv",
        "/api/v1/exports/income-statement?format=pdf&date_from=2026-01-01&date_to=2026-11-30",
        "/api/v1/exports/balance-sheet?format=csv&as_of=2026-11-30",
        "/api/v1/exports/ar-aging?format=csv&by=insurer",
        "/api/v1/exports/invoices?format=csv&status=issued",
        "/api/v1/exports/audit-log?format=csv&action=create",
    ):
        resp = client.get(path, headers=fin)
        assert resp.status_code == 200, (path, resp.text)
        assert "attachment; filename=" in resp.headers["content-disposition"]
    assert client.get("/api/v1/exports/trial-balance", headers=login("billing")).status_code == 403
    assert client.get("/api/v1/exports/audit-log", headers=login("accountant")).status_code == 403
    assert client.get("/api/v1/exports/trial-balance?format=xlsx", headers=fin).status_code == 422
    logged = db.scalars(select(AuditLog).where(AuditLog.action == "export")).all()
    assert {e.after["format"] for e in logged if e.after} == {"csv", "pdf"}
    assert len(logged) == 6


def test_budget_variance_export(
    client: TestClient, login, db: Session, actor_for, dept, acct
) -> None:  # type: ignore[no-untyped-def]
    from app.services import budgets
    from app.services.budgets import LineSpec

    b = budgets.create_budget(
        db, actor_for("finance"), year=2026, department_id=dept("RAD"), name="Rad",
        alert_threshold_percent=D("90"), lines=[LineSpec(acct("5100"), annual=D("1200.00"))],
    )  # fmt: skip
    resp = client.get(
        f"/api/v1/exports/budgets/{b.id}/variance?format=csv&through_month=6",
        headers=login("finance"),
    )
    rows = list(csv.reader(io.StringIO(resp.content.decode("utf-8-sig"))))
    assert rows[1][:5] == ["5100", "Salaries & Wages", "expense", "1200.00", "600.00"]


@pytest.fixture
def dept(db: Session):  # type: ignore[no-untyped-def]
    from app.models.org import Department

    ids = {d.code: d.id for d in db.scalars(select(Department)).all()}
    return lambda code: ids[code]


# ------------------------------------------------------------------ notifications


def manual_entry_over_threshold(db: Session, actor_for, acct):  # type: ignore[no-untyped-def]
    return ledger.create_manual_entry(
        db,
        actor_for("accountant"),
        entry_date=date(2026, 11, 2),
        memo="Large accrual",
        lines=[
            LineInput(acct("5900"), debit=D("25000.00")),
            LineInput(acct("2400"), credit=D("25000.00")),
        ],
        approval_threshold=D("10000.00"),
    )


def test_approval_request_and_decision_notify_the_right_people(
    db: Session, actor_for, acct
) -> None:  # type: ignore[no-untyped-def]
    from app.models.approvals import Approval

    entry = manual_entry_over_threshold(db, actor_for, acct)
    requested = notes_for(db, "finance")
    assert [(n.kind, n.level) for n in requested] == [("approval_requested", "action")]
    assert entry.entry_number in requested[0].title
    assert notes_for(db, "accountant") == []  # the requester is not told about their own request
    approval = db.scalars(select(Approval).where(Approval.entity_id == entry.id)).one()
    from app.services import approvals

    approvals.decide(db, actor_for("finance"), approval.id, approve=False, note="Needs support")
    decided = notes_for(db, "accountant")
    assert [(n.kind, n.level, n.link) for n in decided] == [
        ("approval_rejected", "warning", f"/journal/{entry.id}")
    ]
    assert decided[0].body == "Needs support"


def test_budget_alerts_and_payroll_job_notify(db: Session, actor_for, staff, dept, acct) -> None:  # type: ignore[no-untyped-def]
    from app.services import budgets, payroll
    from app.services.budgets import LineSpec

    accountant = actor_for("accountant")
    run = payroll.create_run(db, accountant, year=2026, month=9, pay_date=None)
    payroll.calculate_run(db, SYSTEM_ACTOR, run.id)  # as the background job
    assert [n.kind for n in notes_for(db, "accountant")] == ["payroll_calculated"]
    other = payroll.create_run(db, accountant, year=2026, month=10, pay_date=None)
    payroll.mark_failed(db, SYSTEM_ACTOR, other.id, "boom")
    assert [n.kind for n in notes_for(db, "accountant")][-1] == "payroll_failed"

    b = budgets.create_budget(
        db, actor_for("finance"), year=2026, department_id=dept("SURG"), name="S",
        alert_threshold_percent=D("90"), lines=[LineSpec(acct("5100"), monthly=[D("1.00")] * 12)],
    )  # fmt: skip
    budgets.set_status(db, actor_for("finance"), b.id, "active")
    payroll.submit_run(db, accountant, run.id)
    from tests.integration import test_phase5 as p5

    p5.approve(db, actor_for, run.id)
    budgets.check_alerts(db, SYSTEM_ACTOR, as_of=date(2026, 9, 30))
    kinds = [n.kind for n in notes_for(db, "finance")]
    assert "budget_alert" in kinds and "approval_requested" in kinds


def test_notification_api_is_per_user(
    client: TestClient, login, db: Session, actor_for, acct
) -> None:  # type: ignore[no-untyped-def]
    manual_entry_over_threshold(db, actor_for, acct)
    fin, acc = login("finance"), login("accountant")
    assert client.get("/api/v1/notifications/unread-count", headers=fin).json() == {"unread": 1}
    listed = client.get("/api/v1/notifications?unread_only=true", headers=fin).json()
    note_id = listed["items"][0]["id"]
    assert listed["items"][0]["link"] == "/approvals?tab=to_decide"
    assert client.post(f"/api/v1/notifications/{note_id}/read", headers=acc).status_code == 404
    read = client.post(f"/api/v1/notifications/{note_id}/read", headers=fin).json()
    assert read["read_at"] is not None
    assert client.get("/api/v1/notifications/unread-count", headers=fin).json() == {"unread": 0}
    manual_entry_over_threshold(db, actor_for, acct)
    assert client.post("/api/v1/notifications/read-all", headers=fin).json() == {"marked": 1}
    assert client.get("/api/v1/notifications", headers=fin).json()["total"] == 2


def test_notifications_cannot_be_deleted(db: Session, actor_for, acct) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy.exc import DBAPIError

    manual_entry_over_threshold(db, actor_for, acct)
    db.flush()
    with pytest.raises(DBAPIError), db.begin_nested():
        db.execute(text("DELETE FROM notifications"))
    with pytest.raises(NotFound):
        notifications.mark_read(db, 999, 1)


# ------------------------------------------------------------------ search


def test_search_is_filtered_by_role(db: Session, actor_for, patient, svc, acct) -> None:  # type: ignore[no-untyped-def]
    inv = issue(db, actor_for("billing"), patient, svc, date(2026, 11, 3))
    manual_entry_over_threshold(db, actor_for, acct)

    def groups(user: str, q: str) -> dict[str, list[str]]:
        return {g.type: [h.title for h in g.hits] for g in search.search(db, actor_for(user), q)}

    assert inv.invoice_number in groups("billing", inv.invoice_number)["invoice"]
    assert "journal_entry" not in groups("billing", "accrual")
    assert groups("accountant", "accrual")["journal_entry"]
    assert groups("finance", patient.mrn)["patient"] == [patient.full_name]
    assert "patient" not in groups("accountant", patient.mrn)
    assert groups("admin", "auditor")["user"]
    assert "user" not in groups("finance", "auditor")
    assert search.search(db, actor_for("finance"), "a") == []  # too short
    assert groups("finance", "100%") == {}  # % is literal, not a wildcard


def test_search_api(client: TestClient, login) -> None:  # type: ignore[no-untyped-def]
    body = client.get("/api/v1/search?q=bank", headers=login("accountant")).json()
    assert body["query"] == "bank"
    accounts = next(g for g in body["groups"] if g["type"] == "account")
    assert {h["title"] for h in accounts["hits"]} >= {
        "1020 Bank - Operating",
        "1030 Bank - Payroll",
    }


# ------------------------------------------------------------------ audit viewer


def test_audit_facets_and_actor_filter(
    client: TestClient, login, db: Session, actor_for, acct
) -> None:  # type: ignore[no-untyped-def]
    manual_entry_over_threshold(db, actor_for, acct)
    admin = login("admin")
    facets = client.get("/api/v1/audit-log/facets", headers=admin).json()
    assert "journal_entry" in facets["entity_types"] and "create" in facets["actions"]
    rows = client.get(
        "/api/v1/audit-log?actor_label=ACCOUNTANT&page_size=100", headers=admin
    ).json()
    assert rows["total"] >= 1
    assert all("accountant" in r["actor_label"].lower() for r in rows["items"])
    assert client.get("/api/v1/audit-log/facets", headers=login("billing")).status_code == 403


def test_audit_log_export_respects_filters(db: Session, actor_for, acct) -> None:  # type: ignore[no-untyped-def]
    from app.repositories import audit as audit_repo

    manual_entry_over_threshold(db, actor_for, acct)
    rows, total = audit_repo.list_entries(
        db, PageParams(1, 100, None), entity_type="approval", entity_id=None, actor_id=None,
        action=None, date_from=None, date_to=None,
    )  # fmt: skip
    table = exports.audit_log(rows, "Filters: entity_type=approval")
    assert {r["entity_type"] for r in table.rows} == {"approval"} and total == len(rows)


def test_cors_exposes_export_file_names(client: TestClient, login) -> None:  # type: ignore[no-untyped-def]
    from app.core.config import get_settings

    origin = get_settings().cors_origins[0]
    resp = client.get(
        "/api/v1/exports/balance-sheet?as_of=2026-11-30",
        headers={**login("accountant"), "Origin": origin},
    )
    assert "content-disposition" in resp.headers["access-control-expose-headers"].lower()
