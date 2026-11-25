"""Payroll: employees, tax slabs, monthly runs, approval, ledger posting and payment.

Run lifecycle:
  queued -> calculated -> pending_approval -> posted -> paid
             ^    |  (recalculate)     |
             |    v                    | rejected: back to calculated for correction
           failed (background error)   v
Posting on approval (entry dated the last day of the month, department dimension):
  Dr 5100 Salaries & Wages        gross, one line per department
  Cr 2110 Payroll Tax Payable     income tax withheld
  Cr 2120 Other Deductions        employee pension + other deductions
  Cr 2100 Salaries Payable        net pay
Payment on the pay date: Dr 1030 Bank-Payroll / Cr 1020 Bank-Operating (funding transfer),
then Dr 2100 Salaries Payable / Cr 1030 Bank-Payroll (net pay to employees).
The arithmetic lives in payroll_math (pure, unit-tested).
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.errors import (
    BusinessRuleViolation,
    Conflict,
    NotFound,
    PermissionDenied,
    ValidationFailed,
)
from app.core.money import quantize
from app.models.approvals import ApprovalKind
from app.models.org import Department
from app.models.payroll import Employee, EmployeeStatus, PayrollRun, PayrollStatus, Payslip, TaxSlab
from app.repositories import billing as billing_repo
from app.repositories import payroll as repo
from app.services import approvals, audit, ledger, posting
from app.services import payroll_math as pm
from app.services.audit import Actor
from app.services.ledger import EntryDraft, LineInput

ZERO = Decimal("0.00")
SALARIES = "5100"
SALARIES_PAYABLE = "2100"
PAYROLL_TAX = "2110"
OTHER_DEDUCTIONS = "2120"
BANK_PAYROLL = "1030"
RECALCULABLE = (PayrollStatus.QUEUED, PayrollStatus.CALCULATED, PayrollStatus.FAILED)


# --------------------------------------------------------------------------- employees


@dataclass(frozen=True)
class EmployeeInput:
    first_name: str
    last_name: str
    department_id: int
    position: str
    hire_date: date
    basic_salary: Decimal
    housing_allowance: Decimal = ZERO
    transport_allowance: Decimal = ZERO
    other_allowance: Decimal = ZERO
    pension_rate: Decimal = Decimal("0.0500")
    other_deduction: Decimal = ZERO
    email: str = ""
    bank_reference: str = ""


def get_employee(session: Session, employee_id: int) -> Employee:
    employee = repo.get_employee(session, employee_id)
    if employee is None:
        raise NotFound("Employee not found")
    return employee


def _check_pay(values: dict[str, object]) -> None:
    for name in (
        "basic_salary",
        "housing_allowance",
        "transport_allowance",
        "other_allowance",
        "other_deduction",
    ):
        value = values.get(name)
        if value is None:
            continue
        if not isinstance(value, Decimal) or value < 0 or quantize(value) != value:
            raise ValidationFailed(f"{name} must be a non-negative amount", code="invalid_amount")
    rate = values.get("pension_rate")
    if rate is not None and (not isinstance(rate, Decimal) or not (0 <= rate <= Decimal("0.2"))):
        raise ValidationFailed("Pension rate must be between 0 and 0.20", code="invalid_rate")
    dept = values.get("department_id")
    if isinstance(dept, int) and dept <= 0:
        raise ValidationFailed("Invalid department", code="invalid_department")


def _require_department(session: Session, department_id: int) -> None:
    dept = session.get(Department, department_id)
    if dept is None or not dept.is_active:
        raise ValidationFailed("Department must exist and be active", code="invalid_department")


def create_employee(session: Session, actor: Actor, data: EmployeeInput) -> Employee:
    values = dict(data.__dict__)
    _check_pay(values)
    _require_department(session, data.department_id)
    if not data.first_name.strip() or not data.last_name.strip() or not data.position.strip():
        raise ValidationFailed("Name and position are required", code="required")
    employee = Employee(
        employee_number=billing_repo.next_number(session, "employee_number_seq", "EMP"),
        status=EmployeeStatus.ACTIVE,
        **{k: v.strip() if isinstance(v, str) else v for k, v in values.items()},
    )
    session.add(employee)
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="employee",
        entity_id=employee.id,
        action="create",
        after=audit.snapshot(employee),
    )
    return employee


UPDATABLE = frozenset(
    {
        "first_name",
        "last_name",
        "email",
        "department_id",
        "position",
        "bank_reference",
        "basic_salary",
        "housing_allowance",
        "transport_allowance",
        "other_allowance",
        "pension_rate",
        "other_deduction",
    }
)


def update_employee(
    session: Session, actor: Actor, employee_id: int, changes: dict[str, object]
) -> Employee:
    employee = get_employee(session, employee_id)
    unknown = set(changes) - UPDATABLE
    if unknown:
        raise ValidationFailed(f"Cannot update {sorted(unknown)}", code="invalid_field")
    _check_pay(changes)
    dept = changes.get("department_id")
    if isinstance(dept, int):
        _require_department(session, dept)
    before = audit.snapshot(employee)
    for key, value in changes.items():
        setattr(employee, key, value.strip() if isinstance(value, str) else value)
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="employee",
        entity_id=employee.id,
        action="update",
        before=before,
        after=audit.snapshot(employee),
    )
    return employee


def terminate_employee(
    session: Session, actor: Actor, employee_id: int, termination_date: date
) -> Employee:
    """Employees are never deleted; termination stops pay after the given date (prorated)."""
    employee = get_employee(session, employee_id)
    if employee.status == EmployeeStatus.TERMINATED:
        raise Conflict("Employee is already terminated", code="already_terminated")
    if termination_date < employee.hire_date:
        raise ValidationFailed("Termination cannot precede hire date", code="invalid_date")
    before = audit.snapshot(employee)
    employee.termination_date = termination_date
    employee.status = EmployeeStatus.TERMINATED
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="employee",
        entity_id=employee.id,
        action="status_change",
        before=before,
        after=audit.snapshot(employee),
    )
    return employee


# --------------------------------------------------------------------------- tax slabs


def slabs(session: Session, year: int) -> list[pm.Slab]:
    return [
        pm.Slab(s.lower_bound, s.upper_bound, s.rate) for s in repo.slabs_for_year(session, year)
    ]


def replace_slabs(
    session: Session, actor: Actor, year: int, new: Sequence[pm.Slab]
) -> Sequence[TaxSlab]:
    """Replace a year's slabs. Blocked once a run for that year has been posted."""
    try:
        pm.validate_slabs(new)
    except ValueError as exc:
        raise ValidationFailed(str(exc), code="invalid_slabs") from exc
    if repo.year_has_submitted_runs(session, year):
        raise BusinessRuleViolation(
            f"{year} already has submitted or posted payroll runs; slabs are locked",
            code="slabs_locked",
        )
    before = [audit.snapshot(s) for s in repo.slabs_for_year(session, year)]
    repo.delete_slabs(session, year)
    session.flush()
    rows = [
        TaxSlab(year=year, lower_bound=s.lower, upper_bound=s.upper, rate=s.rate)
        for s in sorted(new, key=lambda s: s.lower)
    ]
    session.add_all(rows)
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="tax_slabs",
        entity_id=year,
        action="update",
        before={"slabs": before},
        after={"slabs": [audit.snapshot(s) for s in rows]},
    )
    return rows


def ensure_slabs(session: Session, year: int) -> None:
    """Seed the default slabs for a year if it has none (idempotent)."""
    if not repo.slabs_for_year(session, year):
        session.add_all(
            TaxSlab(year=year, lower_bound=s.lower, upper_bound=s.upper, rate=s.rate)
            for s in pm.DEFAULT_SLABS
        )
        session.flush()


# --------------------------------------------------------------------------- runs


def get_run(session: Session, run_id: int, *, lock: bool = False) -> PayrollRun:
    run = repo.get_run(session, run_id, lock=lock)
    if run is None:
        raise NotFound("Payroll run not found")
    return run


def create_run(
    session: Session, actor: Actor, *, year: int, month: int, pay_date: date | None
) -> PayrollRun:
    """Create the run for a month (status queued). Call calculate_run() or queue the job."""
    if not 1 <= month <= 12 or not 2000 <= year <= 2100:
        raise ValidationFailed("Invalid payroll month", code="invalid_month")
    if repo.run_for_month(session, year, month) is not None:
        raise Conflict(f"A payroll run for {year}-{month:02d} already exists", code="run_exists")
    first, last = pm.month_bounds(year, month)
    ledger.require_open_period(session, last)  # posting would fail later otherwise
    if pay_date is not None and pay_date < last:
        raise ValidationFailed(
            "Pay date cannot be before the end of the month", code="invalid_date"
        )
    run = PayrollRun(
        run_number=f"PR-{year}-{month:02d}",
        year=year,
        month=month,
        period_start=first,
        period_end=last,
        pay_date=pay_date or last,
        status=PayrollStatus.QUEUED,
        created_by_id=actor.id,
    )
    session.add(run)
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="payroll_run",
        entity_id=run.id,
        action="create",
        after=audit.snapshot(run),
    )
    return run


def calculate_run(session: Session, actor: Actor, run_id: int) -> PayrollRun:
    """(Re)compute every payslip for the run from current employee data and tax slabs."""
    run = get_run(session, run_id, lock=True)
    if run.status not in RECALCULABLE:
        raise Conflict(f"A {run.status} run cannot be recalculated", code="invalid_transition")
    tax = slabs(session, run.year)
    if not tax:
        raise BusinessRuleViolation(f"No tax slabs defined for {run.year}", code="no_tax_slabs")
    employees = repo.employed_between(session, run.period_start, run.period_end)
    if not employees:
        raise BusinessRuleViolation("No employees were employed in this month", code="no_employees")
    before = audit.snapshot(run)
    run.payslips.clear()
    session.flush()
    for emp in employees:
        worked, days = pm.days_employed(run.year, run.month, emp.hire_date, emp.termination_date)
        if worked == 0:  # pragma: no cover - excluded by the query
            continue
        r = pm.calculate(
            pm.SalaryStructure(
                basic=emp.basic_salary,
                housing=emp.housing_allowance,
                transport=emp.transport_allowance,
                other_allowance=emp.other_allowance,
                pension_rate=emp.pension_rate,
                other_deduction=emp.other_deduction,
            ),
            tax,
            days_worked=worked,
            days_in_month=days,
        )
        run.payslips.append(
            Payslip(
                employee_id=emp.id,
                employee_number=emp.employee_number,
                employee_name=emp.full_name,
                position=emp.position,
                department_id=emp.department_id,
                days_in_month=r.days_in_month,
                days_worked=r.days_worked,
                basic=r.basic,
                housing=r.housing,
                transport=r.transport,
                other_allowance=r.other_allowance,
                gross=r.gross,
                pension=r.pension,
                taxable=r.taxable,
                income_tax=r.income_tax,
                other_deduction=r.other_deduction,
                net=r.net,
            )
        )
    slips = run.payslips
    run.employee_count = len(slips)
    run.gross_total = sum((p.gross for p in slips), ZERO)
    run.pension_total = sum((p.pension for p in slips), ZERO)
    run.tax_total = sum((p.income_tax for p in slips), ZERO)
    run.other_deduction_total = sum((p.other_deduction for p in slips), ZERO)
    run.net_total = sum((p.net for p in slips), ZERO)
    run.status = PayrollStatus.CALCULATED
    run.error = None
    run.calculated_at = datetime.now(UTC)
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="payroll_run",
        entity_id=run.id,
        action="calculate",
        before=before,
        after=audit.snapshot(run),
    )
    return run


def mark_failed(session: Session, actor: Actor, run_id: int, error: str) -> PayrollRun:
    run = get_run(session, run_id, lock=True)
    if run.status not in RECALCULABLE:
        return run
    before = audit.snapshot(run)
    run.status = PayrollStatus.FAILED
    run.error = error[:1000]
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="payroll_run",
        entity_id=run.id,
        action="status_change",
        before=before,
        after=audit.snapshot(run),
    )
    return run


def _post(session: Session, actor: Actor, run: PayrollRun) -> None:
    memo = f"Payroll {run.run_number} ({run.employee_count} employees)"
    by_dept: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for slip in run.payslips:
        by_dept[slip.department_id] += slip.gross
    salaries = posting.account_id(session, SALARIES)
    lines = [
        LineInput(
            salaries, debit=amount, description=f"Gross pay {run.run_number}", department_id=d
        )
        for d, amount in sorted(by_dept.items())
        if amount > 0
    ]
    credits = (
        (PAYROLL_TAX, run.tax_total, "Income tax withheld"),
        (
            OTHER_DEDUCTIONS,
            run.pension_total + run.other_deduction_total,
            "Pension and other deductions",
        ),
        (SALARIES_PAYABLE, run.net_total, "Net pay payable"),
    )
    lines += [
        LineInput(posting.account_id(session, code), credit=amount, description=desc)
        for code, amount, desc in credits
        if amount > 0
    ]
    entry = ledger.post_entry(
        session,
        actor,
        EntryDraft(
            entry_date=run.period_end,
            memo=memo,
            source_type="payroll_run",
            source_id=str(run.id),
            lines=lines,
        ),
    )
    run.posting_entry_id = entry.id
    run.status = PayrollStatus.POSTED
    run.approved_by_id = actor.id
    run.approved_at = datetime.now(UTC)
    session.flush()


def submit_run(session: Session, actor: Actor, run_id: int) -> PayrollRun:
    run = get_run(session, run_id, lock=True)
    if run.status != PayrollStatus.CALCULATED:
        raise Conflict("Only calculated runs can be submitted", code="invalid_transition")
    if run.gross_total <= 0:
        raise BusinessRuleViolation("Run has no pay to post", code="empty_run")
    before = audit.snapshot(run)
    if approvals.needs_approval(session, ApprovalKind.PAYROLL_RUN, run.gross_total):
        run.status = PayrollStatus.PENDING_APPROVAL
        session.flush()
        approvals.request(
            session,
            actor,
            kind=ApprovalKind.PAYROLL_RUN,
            entity_type="payroll_run",
            entity_id=run.id,
            reference=run.run_number,
            summary=f"Payroll {run.year}-{run.month:02d}: {run.employee_count} employees, "
            f"gross {run.gross_total:.2f}, net {run.net_total:.2f}",
            amount=run.gross_total,
        )
    else:
        _post(session, actor, run)
    audit.record(
        session,
        actor,
        entity_type="payroll_run",
        entity_id=run.id,
        action="status_change",
        before=before,
        after=audit.snapshot(run),
    )
    return run


def _pending_run(session: Session, actor: Actor, run_id: int) -> PayrollRun:
    run = get_run(session, run_id, lock=True)
    if run.status != PayrollStatus.PENDING_APPROVAL:
        raise Conflict("Run is not awaiting approval", code="not_pending")
    if run.created_by_id is not None and run.created_by_id == actor.id:
        raise PermissionDenied(
            "You cannot approve a payroll run you prepared", code="self_approval"
        )
    return run


def approve_run(session: Session, actor: Actor, run_id: int, note: str) -> PayrollRun:
    run = _pending_run(session, actor, run_id)
    before = audit.snapshot(run)
    _post(session, actor, run)
    audit.record(
        session,
        actor,
        entity_type="payroll_run",
        entity_id=run.id,
        action="status_change",
        before=before,
        after=audit.snapshot(run),
    )
    approvals.record_decision(
        session, actor, kind=ApprovalKind.PAYROLL_RUN, entity_id=run.id, approved=True, note=note
    )
    return run


def reject_run(session: Session, actor: Actor, run_id: int, note: str) -> PayrollRun:
    """A rejected run goes back to calculated so payroll can correct and resubmit it."""
    run = _pending_run(session, actor, run_id)
    before = audit.snapshot(run)
    run.status = PayrollStatus.CALCULATED
    run.error = f"Rejected: {note}".strip()[:1000]
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="payroll_run",
        entity_id=run.id,
        action="status_change",
        before=before,
        after=audit.snapshot(run),
    )
    approvals.record_decision(
        session, actor, kind=ApprovalKind.PAYROLL_RUN, entity_id=run.id, approved=False, note=note
    )
    return run


def pay_run(session: Session, actor: Actor, run_id: int, *, paid_on: date | None) -> PayrollRun:
    """Fund the payroll bank account and pay net salaries (two balanced entries)."""
    run = get_run(session, run_id, lock=True)
    if run.status != PayrollStatus.POSTED:
        raise Conflict("Only posted runs can be paid", code="not_payable")
    on = paid_on or run.pay_date
    if on < run.period_end:
        raise ValidationFailed(
            "Payment date cannot precede the end of the month", code="invalid_date"
        )
    before = audit.snapshot(run)
    funding = ledger.post_entry(
        session,
        actor,
        EntryDraft(
            entry_date=on,
            memo=f"Fund payroll account for {run.run_number}",
            source_type="payroll_funding",
            source_id=str(run.id),
            lines=posting.simple_transfer(
                session,
                debit_code=BANK_PAYROLL,
                credit_code=posting.BANK,
                amount=run.net_total,
                description=f"Transfer to payroll account {run.run_number}",
            ),
        ),
    )
    payment = ledger.post_entry(
        session,
        actor,
        EntryDraft(
            entry_date=on,
            memo=f"Net salaries paid for {run.run_number}",
            source_type="payroll_payment",
            source_id=str(run.id),
            lines=posting.simple_transfer(
                session,
                debit_code=SALARIES_PAYABLE,
                credit_code=BANK_PAYROLL,
                amount=run.net_total,
                description=f"Net pay {run.run_number}",
            ),
        ),
    )
    run.funding_entry_id = funding.id
    run.payment_entry_id = payment.id
    run.pay_date = on
    run.status = PayrollStatus.PAID
    run.paid_at = datetime.now(UTC)
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="payroll_run",
        entity_id=run.id,
        action="status_change",
        before=before,
        after=audit.snapshot(run),
    )
    return run


def get_payslip(session: Session, payslip_id: int) -> Payslip:
    slip = repo.get_payslip(session, payslip_id)
    if slip is None:
        raise NotFound("Payslip not found")
    return slip


@dataclass
class DepartmentTotal:
    department: Department
    headcount: int = 0
    gross: Decimal = ZERO
    net: Decimal = ZERO


def department_totals(run: PayrollRun) -> list[DepartmentTotal]:
    """Headcount, gross and net per department, for the run summary."""
    acc: dict[int, DepartmentTotal] = {}
    for slip in run.payslips:
        row = acc.setdefault(slip.department_id, DepartmentTotal(slip.department))
        row.headcount += 1
        row.gross += slip.gross
        row.net += slip.net
    return sorted(acc.values(), key=lambda t: t.department.code)
