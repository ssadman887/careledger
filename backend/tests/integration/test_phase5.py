"""Phase 5: employees, payroll runs (calculation, approval, posting, payment), budgets, alerts."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation, Conflict, PermissionDenied, ValidationFailed
from app.models.approvals import Approval, ApprovalKind
from app.models.ledger import FiscalPeriod
from app.models.org import Department
from app.models.payroll import PayrollStatus
from app.services import approvals, budgets, payroll, periods
from app.services import payroll_math as pm
from app.services.audit import SYSTEM_ACTOR
from app.services.budgets import LineSpec
from app.services.payroll import EmployeeInput
from tests.conftest import check_deferred
from tests.integration.test_billing import entry_lines
from tests.integration.test_phase4 import account_balance

D = Decimal
YEAR, MONTH = 2026, 9


@pytest.fixture
def dept(db: Session):  # type: ignore[no-untyped-def]
    ids = {d.code: d.id for d in db.scalars(select(Department)).all()}
    return lambda code: ids[code]


@pytest.fixture
def staff(db: Session, actor_for, dept):  # type: ignore[no-untyped-def]
    """Three employees: two full-month (EMER, SURG) and one hired mid-September (EMER)."""
    accountant = actor_for("accountant")
    rows = [
        ("Ada", "Full", "EMER", date(2020, 1, 1), "4000.00", "600.00", "150.00", "45.00"),
        ("Ben", "Surgeon", "SURG", date(2019, 5, 1), "12000.00", "1800.00", "300.00", "0.00"),
        ("Cyd", "New", "EMER", date(2026, 9, 15), "3000.00", "450.00", "150.00", "0.00"),
    ]
    out = []
    for first, last, code, hired, basic, housing, transport, other in rows:
        out.append(
            payroll.create_employee(
                db,
                accountant,
                EmployeeInput(
                    first_name=first,
                    last_name=last,
                    department_id=dept(code),
                    position="Clinician",
                    hire_date=hired,
                    basic_salary=D(basic),
                    housing_allowance=D(housing),
                    transport_allowance=D(transport),
                    pension_rate=D("0.05"),
                    other_deduction=D(other),
                    bank_reference="GB00-TEST-123456",
                ),
            )
        )
    return out


def calculated_run(db: Session, actor_for, month: int = MONTH):  # type: ignore[no-untyped-def]
    accountant = actor_for("accountant")
    run = payroll.create_run(db, accountant, year=YEAR, month=month, pay_date=None)
    return payroll.calculate_run(db, accountant, run.id)


def approve(db: Session, actor_for, run_id: int):  # type: ignore[no-untyped-def]
    approval = db.scalars(
        select(Approval).where(
            Approval.kind == ApprovalKind.PAYROLL_RUN, Approval.entity_id == run_id
        )
    ).one()
    return approvals.decide(db, actor_for("finance"), approval.id, approve=True, note="ok")


# ------------------------------------------------------------------ calculation


def test_run_totals_equal_sum_of_payslips_and_prorate(db: Session, actor_for, staff) -> None:  # type: ignore[no-untyped-def]
    run = calculated_run(db, actor_for)
    assert run.status == PayrollStatus.CALCULATED
    assert run.employee_count == 3
    slips = {s.employee_name: s for s in run.payslips}
    assert slips["Cyd New"].days_worked == 16 and slips["Cyd New"].days_in_month == 30
    assert slips["Cyd New"].basic == D("1600.00")  # 3000 x 16/30
    # 4750 gross - 200 pension - 476.67 tax (54,600/yr) - 45 other = 4028.33
    assert slips["Ada Full"].net == D("4028.33")
    for field in ("gross", "pension", "income_tax", "other_deduction", "net"):
        total = sum((getattr(s, field) for s in run.payslips), D("0"))
        run_field = {"income_tax": "tax_total", "gross": "gross_total", "pension": "pension_total",
                     "other_deduction": "other_deduction_total", "net": "net_total"}[field]  # fmt: skip
        assert getattr(run, run_field) == total
    check_deferred(db)


def test_terminated_employee_is_prorated_and_later_excluded(db: Session, actor_for, staff) -> None:  # type: ignore[no-untyped-def]
    accountant = actor_for("accountant")
    payroll.terminate_employee(db, accountant, staff[0].id, date(2026, 9, 10))
    run = calculated_run(db, actor_for)
    ada = next(s for s in run.payslips if s.employee_id == staff[0].id)
    assert ada.days_worked == 10
    october = calculated_run(db, actor_for, month=10)
    assert staff[0].id not in {s.employee_id for s in october.payslips}
    with pytest.raises(Conflict):
        payroll.terminate_employee(db, accountant, staff[0].id, date(2026, 9, 11))


def test_one_run_per_month_and_recalculation(db: Session, actor_for, staff) -> None:  # type: ignore[no-untyped-def]
    run = calculated_run(db, actor_for)
    with pytest.raises(Conflict):
        payroll.create_run(db, actor_for("accountant"), year=YEAR, month=MONTH, pay_date=None)
    payroll.update_employee(
        db, actor_for("accountant"), staff[1].id, {"basic_salary": D("13000.00")}
    )
    before = run.gross_total
    run = payroll.calculate_run(db, actor_for("accountant"), run.id)
    assert run.gross_total == before + D("1000.00")
    assert len(run.payslips) == 3


def test_run_needs_slabs_employees_and_open_period(db: Session, actor_for) -> None:  # type: ignore[no-untyped-def]
    accountant = actor_for("accountant")
    run = payroll.create_run(db, accountant, year=YEAR, month=MONTH, pay_date=None)
    with pytest.raises(BusinessRuleViolation, match="No employees"):
        payroll.calculate_run(db, accountant, run.id)
    with pytest.raises(ValidationFailed):
        payroll.create_run(db, accountant, year=YEAR, month=13, pay_date=None)
    with pytest.raises(ValidationFailed):
        payroll.create_run(db, accountant, year=YEAR, month=8, pay_date=date(2026, 8, 1))
    # Closed period: January is closed here.
    jan = db.scalars(select(FiscalPeriod).where(FiscalPeriod.start_date == date(2026, 1, 1))).one()
    periods.close_period(db, actor_for("finance"), jan.id)
    with pytest.raises(BusinessRuleViolation):
        payroll.create_run(db, accountant, year=YEAR, month=1, pay_date=None)


def test_no_slabs_for_year_fails_the_calculation(db: Session, actor_for, staff) -> None:  # type: ignore[no-untyped-def]
    db.execute(text("DELETE FROM tax_slabs WHERE year = 2026"))
    with pytest.raises(BusinessRuleViolation, match="tax slabs"):
        calculated_run(db, actor_for)


# ------------------------------------------------------------------ approval, posting, payment


def test_submit_approve_posts_balanced_entry_by_department(
    db: Session, actor_for, staff, dept
) -> None:  # type: ignore[no-untyped-def]
    run = calculated_run(db, actor_for)
    payroll.submit_run(db, actor_for("accountant"), run.id)
    assert run.status == PayrollStatus.PENDING_APPROVAL
    # The preparer cannot approve their own run, auditors never can.
    approval = db.scalars(
        select(Approval).where(Approval.entity_id == run.id, Approval.kind == "payroll_run")
    ).one()
    with pytest.raises(PermissionDenied):
        approvals.decide(db, actor_for("accountant"), approval.id, approve=True, note="")
    approve(db, actor_for, run.id)
    assert run.status == PayrollStatus.POSTED
    lines = entry_lines(db, run.posting_entry_id)
    assert lines["5100"] == (run.gross_total, D("0"))
    assert lines["2110"] == (D("0"), run.tax_total)
    assert lines["2120"] == (D("0"), run.pension_total + run.other_deduction_total)
    assert lines["2100"] == (D("0"), run.net_total)
    by_dept = dict(
        db.execute(
            text(
                "SELECT d.code, sum(l.debit) FROM journal_lines l JOIN departments d "
                "ON d.id = l.department_id WHERE l.entry_id = :e GROUP BY d.code"
            ),
            {"e": run.posting_entry_id},
        ).all()
    )
    emer = sum((s.gross for s in run.payslips if s.department_id == dept("EMER")), D("0"))
    assert by_dept == {"EMER": emer, "SURG": run.gross_total - emer}
    check_deferred(db)


def test_pay_clears_salaries_payable_through_payroll_bank(db: Session, actor_for, staff) -> None:  # type: ignore[no-untyped-def]
    bank_before = account_balance(db, "1020")
    run = calculated_run(db, actor_for)
    payroll.submit_run(db, actor_for("accountant"), run.id)
    approve(db, actor_for, run.id)
    payroll.pay_run(db, actor_for("accountant"), run.id, paid_on=None)
    assert run.status == PayrollStatus.PAID
    assert account_balance(db, "2100") == 0
    assert account_balance(db, "1030") == 0
    assert account_balance(db, "1020") == bank_before - run.net_total
    with pytest.raises(Conflict):
        payroll.pay_run(db, actor_for("accountant"), run.id, paid_on=None)
    check_deferred(db)


def test_reject_returns_to_calculated_and_resubmit_reopens_request(
    db: Session, actor_for, staff
) -> None:  # type: ignore[no-untyped-def]
    accountant, finance = actor_for("accountant"), actor_for("finance")
    run = calculated_run(db, actor_for)
    payroll.submit_run(db, accountant, run.id)
    approval = db.scalars(
        select(Approval).where(Approval.entity_id == run.id, Approval.kind == "payroll_run")
    ).one()
    with pytest.raises(ValidationFailed):
        approvals.decide(db, finance, approval.id, approve=False, note=" ")
    approvals.decide(db, finance, approval.id, approve=False, note="Overtime missing")
    assert run.status == PayrollStatus.CALCULATED
    assert run.error == "Rejected: Overtime missing"
    payroll.calculate_run(db, accountant, run.id)
    payroll.submit_run(db, accountant, run.id)
    db.refresh(approval)
    assert approval.status == "pending"
    assert any("Overtime missing" in c.body for c in approval.comments)
    approvals.decide(db, finance, approval.id, approve=True, note="")
    assert run.status == PayrollStatus.POSTED
    with pytest.raises(Conflict):
        payroll.calculate_run(db, accountant, run.id)


def test_posted_run_is_frozen_in_the_database(db: Session, actor_for, staff) -> None:  # type: ignore[no-untyped-def]
    run = calculated_run(db, actor_for)
    payroll.submit_run(db, actor_for("accountant"), run.id)
    approve(db, actor_for, run.id)
    db.flush()
    for sql in (
        "UPDATE payroll_runs SET net_total = net_total + 1, gross_total = gross_total + 1 WHERE id = :r",
        "UPDATE payroll_runs SET status = 'calculated' WHERE id = :r",
        "DELETE FROM payslips WHERE payroll_run_id = :r",
        "UPDATE payslips SET employee_name = 'x' WHERE payroll_run_id = :r",
        "DELETE FROM payroll_runs WHERE id = :r",
    ):
        with pytest.raises(DBAPIError, match="P0001|cannot|not allowed"), db.begin_nested():
            db.execute(text(sql), {"r": run.id})


def test_inactive_policy_posts_on_submit(db: Session, actor_for, staff) -> None:  # type: ignore[no-untyped-def]
    approvals.update_policy(
        db,
        actor_for("finance"),
        "payroll_run",
        threshold_amount=None,
        approver_role=None,
        is_active=False,
    )
    run = calculated_run(db, actor_for)
    payroll.submit_run(db, actor_for("accountant"), run.id)
    assert run.status == PayrollStatus.POSTED


def test_background_job_marks_failures(db: Session, actor_for) -> None:  # type: ignore[no-untyped-def]
    run = payroll.create_run(db, actor_for("accountant"), year=YEAR, month=MONTH, pay_date=None)
    payroll.mark_failed(db, SYSTEM_ACTOR, run.id, "BusinessRuleViolation: No employees")
    assert run.status == PayrollStatus.FAILED
    assert "No employees" in (run.error or "")


# ------------------------------------------------------------------ tax slabs


def test_replace_slabs_validates_and_locks_after_submission(db: Session, actor_for, staff) -> None:  # type: ignore[no-untyped-def]
    finance = actor_for("finance")
    new = [pm.Slab(D("0"), D("10000"), D("0")), pm.Slab(D("10000"), None, D("0.15"))]
    payroll.replace_slabs(db, finance, 2026, new)
    assert payroll.slabs(db, 2026) == new
    with pytest.raises(ValidationFailed):
        payroll.replace_slabs(db, finance, 2026, [pm.Slab(D("5"), None, D("0.1"))])
    run = calculated_run(db, actor_for)
    payroll.submit_run(db, actor_for("accountant"), run.id)
    with pytest.raises(BusinessRuleViolation, match="locked"):
        payroll.replace_slabs(db, finance, 2026, list(pm.DEFAULT_SLABS))


# ------------------------------------------------------------------ API


def test_payroll_api_flow_with_masking_pdf_and_idempotent_pay(
    client: TestClient, login, dept
) -> None:  # type: ignore[no-untyped-def]
    acc, fin, aud = login("accountant"), login("finance"), login("auditor")
    body = {
        "first_name": "Api",
        "last_name": "Tester",
        "department_id": dept("LAB"),
        "position": "Scientist",
        "hire_date": "2024-01-01",
        "basic_salary": "4100.00",
        "housing_allowance": "550.00",
        "bank_reference": "GB00-API-778899",
    }
    created = client.post("/api/v1/payroll/employees", json=body, headers=acc)
    assert created.status_code == 201, created.text
    emp = created.json()
    assert emp["employee_number"].startswith("EMP-") and emp["monthly_gross"] == "4650.00"
    assert (
        client.post(
            "/api/v1/payroll/employees", json={**body, "basic_salary": 4100.5}, headers=acc
        ).status_code
        == 422
    )
    assert client.post("/api/v1/payroll/employees", json=body, headers=fin).status_code == 403
    masked = client.get(f"/api/v1/payroll/employees/{emp['id']}", headers=aud).json()
    assert masked["bank_reference"].endswith("8899") and "API" not in masked["bank_reference"]
    assert client.get("/api/v1/payroll/employees", headers=login("billing")).status_code == 403

    run = client.post(
        "/api/v1/payroll/runs", json={"year": 2026, "month": 9, "background": False}, headers=acc
    )
    assert run.status_code == 201, run.text
    run_id = run.json()["id"]
    assert run.json()["status"] == "calculated"
    assert run.json()["departments"][0]["department_name"] == "Laboratory"
    sub = client.post(f"/api/v1/payroll/runs/{run_id}/submit", headers=acc).json()
    assert sub["status"] == "pending_approval" and sub["approval_id"]
    assert (
        client.post(f"/api/v1/payroll/runs/{run_id}/approve", json={}, headers=acc).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/payroll/runs/{run_id}/reject", json={"note": ""}, headers=fin
        ).status_code
        == 422
    )
    approved = client.post(
        f"/api/v1/payroll/runs/{run_id}/approve", json={"note": "ok"}, headers=fin
    )
    assert approved.json()["status"] == "posted" and approved.json()["posting_entry_id"]

    key = {**acc, "Idempotency-Key": "payroll-pay-test-1"}
    first = client.post(f"/api/v1/payroll/runs/{run_id}/pay", json={}, headers=key)
    again = client.post(f"/api/v1/payroll/runs/{run_id}/pay", json={}, headers=key)
    assert first.status_code == 200 and first.json()["status"] == "paid"
    assert again.json() == first.json()

    slip_id = first.json()["payslips"][0]["id"]
    pdf = client.get(f"/api/v1/payroll/payslips/{slip_id}/pdf", headers=aud)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    history = client.get(f"/api/v1/payroll/employees/{emp['id']}/payslips", headers=acc).json()
    assert [h["payroll_run_id"] for h in history] == [run_id]
    listed = client.get("/api/v1/payroll/runs?year=2026", headers=aud).json()
    assert listed["total"] == 1


def test_background_run_is_dispatched_after_commit(
    client: TestClient, login, dept, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    calls: list[int] = []
    monkeypatch.setattr("app.api.v1.payroll._dispatch", lambda run_id: calls.append(run_id))
    resp = client.post(
        "/api/v1/payroll/runs", json={"year": 2026, "month": 10}, headers=login("accountant")
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "queued"
    assert calls == [resp.json()["id"]]


def test_dispatch_falls_back_to_in_process_when_broker_is_down(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.jobs import worker

    ran: list[int] = []

    def broken(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise ConnectionError("broker down")

    monkeypatch.setattr(worker.calculate_payroll, "apply_async", broken)
    monkeypatch.setattr(worker, "process_payroll_run", lambda run_id: ran.append(run_id) or "ok")
    worker.dispatch_payroll_run(42)
    assert ran == [42]


def test_tax_api(client: TestClient, login) -> None:  # type: ignore[no-untyped-def]
    acc, fin = login("accountant"), login("finance")
    table = client.get("/api/v1/payroll/tax-slabs/2026", headers=acc).json()
    assert [s["rate"] for s in table["slabs"]] == ["0.0000", "0.1000", "0.2000", "0.3000"]
    assert table["locked"] is False and 2026 in table["years"]
    preview = client.post(
        "/api/v1/payroll/tax-preview",
        json={"year": 2026, "monthly_taxable": "5000.00"},
        headers=acc,
    ).json()
    assert preview == {
        "annual_taxable": "60000.00",
        "annual_tax": "6800.00",
        "monthly_tax": "566.67",
        "effective_rate_percent": "11.33",
    }
    bad = client.put(
        "/api/v1/payroll/tax-slabs/2027",
        json={"slabs": [{"lower_bound": "100.00", "rate": "0.1"}]},
        headers=fin,
    )
    assert bad.status_code == 422
    ok = client.put(
        "/api/v1/payroll/tax-slabs/2027",
        json={"slabs": [{"lower_bound": "0.00", "upper_bound": "20000.00", "rate": "0"},
                        {"lower_bound": "20000.00", "rate": "0.25"}]},
        headers=fin,
    )  # fmt: skip
    assert ok.status_code == 200 and len(ok.json()["slabs"]) == 2
    assert (
        client.put(
            "/api/v1/payroll/tax-slabs/2027", json={"slabs": []}, headers=login("auditor")
        ).status_code
        == 403
    )


# ------------------------------------------------------------------ budgets


def posted_payroll(db: Session, actor_for) -> object:  # type: ignore[no-untyped-def]
    run = calculated_run(db, actor_for)
    payroll.submit_run(db, actor_for("accountant"), run.id)
    approve(db, actor_for, run.id)
    return run


def test_budget_variance_uses_department_ledger_lines(
    db: Session, actor_for, staff, dept, acct
) -> None:  # type: ignore[no-untyped-def]
    finance = actor_for("finance")
    run = posted_payroll(db, actor_for)
    emer_gross = sum((s.gross for s in run.payslips if s.department_id == dept("EMER")), D("0"))  # type: ignore[attr-defined]
    budget = budgets.create_budget(
        db,
        finance,
        year=2026,
        department_id=dept("EMER"),
        name="",
        alert_threshold_percent=D("90"),
        lines=[
            LineSpec(acct("5100"), monthly=[D("0")] * 8 + [D("4000.00")] * 4),
            LineSpec(acct("5200"), annual=D("1000.00")),
            LineSpec(acct("4110"), annual=D("12000.00")),
        ],
    )
    assert budget.name == "Emergency 2026"
    report = budgets.variance(db, budget.id, through_month=9)
    rows = {r.account.code: r for r in report.rows}
    salaries = rows["5100"]
    assert salaries.actual[8] == emer_gross and sum(salaries.actual) == emer_gross
    assert salaries.budget_ytd(9) == D("4000.00")
    assert salaries.variance_ytd(9) == D("4000.00") - emer_gross  # negative = overspent
    assert rows["5200"].annual_budget == D("1000.00")
    assert rows["4110"].budget_ytd(9) == D("9000.00")
    assert rows["4110"].variance_ytd(9) == -D("9000.00")  # no revenue: unfavourable
    assert list(rows) == ["5100", "5200", "4110"]  # expenses first, then revenue


def test_budget_variance_nets_reversals(db: Session, actor_for, staff, dept, acct) -> None:  # type: ignore[no-untyped-def]
    from app.services import ledger

    run = posted_payroll(db, actor_for)
    budget = budgets.create_budget(
        db, actor_for("finance"), year=2026, department_id=dept("SURG"), name="S",
        alert_threshold_percent=D("90"), lines=[LineSpec(acct("5100"), annual=D("120000.00"))],
    )  # fmt: skip
    ledger.reverse_entry(db, actor_for("finance"), run.posting_entry_id, "test reversal")  # type: ignore[attr-defined]
    report = budgets.variance(db, budget.id, through_month=12)
    assert report.rows[0].actual_ytd(12) == 0


def test_budget_rules(db: Session, actor_for, dept, acct) -> None:  # type: ignore[no-untyped-def]
    finance = actor_for("finance")
    args = {
        "year": 2026,
        "department_id": dept("LAB"),
        "name": "Lab",
        "alert_threshold_percent": D("90"),
    }
    with pytest.raises(ValidationFailed):
        budgets.create_budget(db, finance, **args, lines=[LineSpec(acct("1020"), annual=D("1"))])
    with pytest.raises(ValidationFailed):
        budgets.create_budget(db, finance, **args, lines=[LineSpec(acct("5100"))])
    with pytest.raises(ValidationFailed):
        budgets.create_budget(
            db, finance, **args, lines=[LineSpec(acct("5100"), monthly=[D("1")] * 11)]
        )
    with pytest.raises(ValidationFailed):
        budgets.create_budget(
            db, finance, **args,
            lines=[LineSpec(acct("5100"), annual=D("1")), LineSpec(acct("5100"), annual=D("2"))],
        )  # fmt: skip
    with pytest.raises(ValidationFailed):
        budgets.create_budget(
            db,
            finance,
            **{**args, "alert_threshold_percent": D("0")},
            lines=[LineSpec(acct("5100"), annual=D("1"))],
        )
    budget = budgets.create_budget(
        db, finance, **args, lines=[LineSpec(acct("5100"), annual=D("1200.00"))]
    )
    with pytest.raises(Conflict):
        budgets.create_budget(db, finance, **args, lines=[LineSpec(acct("5100"), annual=D("1"))])
    budgets.update_budget(
        db, finance, budget.id, name=None, alert_threshold_percent=None, notes="v2",
        lines=[LineSpec(acct("5100"), annual=D("2400.00"))],
    )  # fmt: skip
    assert sum(ln.amount for ln in budget.lines) == D("2400.00")
    budgets.set_status(db, finance, budget.id, "active")
    with pytest.raises(BusinessRuleViolation):
        budgets.update_budget(
            db, finance, budget.id, name=None, alert_threshold_percent=None, notes=None,
            lines=[LineSpec(acct("5100"), annual=D("1"))],
        )  # fmt: skip
    budgets.update_budget(
        db, finance, budget.id, name=None, alert_threshold_percent=D("80"), notes=None, lines=None
    )
    with pytest.raises(Conflict):
        budgets.set_status(db, finance, budget.id, "draft")
    budgets.set_status(db, finance, budget.id, "archived")
    with pytest.raises(Conflict):
        budgets.update_budget(
            db, finance, budget.id, name="x", alert_threshold_percent=None, notes=None, lines=None
        )


def test_alerts_warning_and_exceeded_raised_once(db: Session, actor_for, staff, dept, acct) -> None:  # type: ignore[no-untyped-def]
    finance = actor_for("finance")
    run = posted_payroll(db, actor_for)
    gross = {code: sum((s.gross for s in run.payslips if s.department_id == dept(code)), D("0"))  # type: ignore[attr-defined]
             for code in ("EMER", "SURG")}  # fmt: skip
    # EMER budget below actual (exceeded); SURG budget so actual is ~95% (warning at 90%).
    emer = budgets.create_budget(
        db, finance, year=2026, department_id=dept("EMER"), name="E", alert_threshold_percent=D("90"),
        lines=[LineSpec(acct("5100"), monthly=[D("0")] * 8 + [gross["EMER"] - D("100.00")] * 4)],
    )  # fmt: skip
    surg_budget = (gross["SURG"] / D("0.95")).quantize(D("0.01"))
    surg = budgets.create_budget(
        db, finance, year=2026, department_id=dept("SURG"), name="S", alert_threshold_percent=D("90"),
        lines=[LineSpec(acct("5100"), monthly=[D("0")] * 8 + [surg_budget] * 4)],
    )  # fmt: skip
    draft_only = budgets.check_alerts(db, SYSTEM_ACTOR, as_of=date(2026, 9, 30))
    assert draft_only == []  # drafts are not monitored
    budgets.set_status(db, finance, emer.id, "active")
    budgets.set_status(db, finance, surg.id, "active")
    created = budgets.check_alerts(db, SYSTEM_ACTOR, as_of=date(2026, 9, 30))
    levels = {a.budget_id: a.level for a in created}
    assert levels == {emer.id: "exceeded", surg.id: "warning"}
    assert next(a for a in created if a.budget_id == surg.id).percent_used == D("95.00")
    assert budgets.check_alerts(db, SYSTEM_ACTOR, as_of=date(2026, 9, 30)) == []  # once only
    alert_id = created[0].id
    db.flush()
    with pytest.raises(DBAPIError), db.begin_nested():
        db.execute(text("UPDATE budget_alerts SET message = 'x' WHERE id = :i"), {"i": alert_id})


def test_budget_api(client: TestClient, login, dept, acct) -> None:  # type: ignore[no-untyped-def]
    fin, acc, aud = login("finance"), login("accountant"), login("auditor")
    body = {
        "year": 2026,
        "department_id": dept("RAD"),
        "lines": [
            {"account_id": acct("5100"), "annual": "120000.00"},
            {"account_id": acct("4120"), "monthly": ["1000.00"] * 12},
        ],
    }
    assert client.post("/api/v1/budgets", json=body, headers=acc).status_code == 403
    created = client.post("/api/v1/budgets", json=body, headers=fin)
    assert created.status_code == 201, created.text
    b = created.json()
    assert b["annual_total"] == "132000.00" and b["accounts"] == 2 and b["status"] == "draft"
    assert b["alert_threshold_percent"] == "90.00"
    bad = {
        **body,
        "department_id": dept("LAB"),
        "lines": [{"account_id": acct("5100"), "annual": 10.5}],
    }
    assert client.post("/api/v1/budgets", json=bad, headers=fin).status_code == 422
    active = client.post(
        f"/api/v1/budgets/{b['id']}/status", json={"status": "active"}, headers=fin
    )
    assert active.json()["status"] == "active"
    var = client.get(f"/api/v1/budgets/{b['id']}/variance?through_month=6", headers=aud)
    assert var.status_code == 200
    data = var.json()
    assert data["through_month"] == 6
    salaries = next(r for r in data["rows"] if r["account_code"] == "5100")
    assert salaries["budget_ytd"] == "60000.00" and salaries["status"] == "ok"
    assert data["revenue_totals"]["budget_ytd"] == "6000.00"
    assert client.get("/api/v1/budgets?year=2026", headers=acc).json()["total"] == 1
    check = client.post("/api/v1/budgets/alerts/check", json={"as_of": "2026-06-30"}, headers=fin)
    assert check.status_code == 200 and check.json()["created"] == 0
    assert client.get("/api/v1/budgets/alerts", headers=aud).json()["total"] == 0
    patched = client.patch(
        f"/api/v1/budgets/{b['id']}", json={"alert_threshold_percent": "85.00"}, headers=fin
    )
    assert patched.json()["alert_threshold_percent"] == "85.00"
    locked = client.patch(f"/api/v1/budgets/{b['id']}", json={"lines": body["lines"]}, headers=fin)
    assert locked.status_code == 422 and locked.json()["error"]["code"] == "budget_locked"
