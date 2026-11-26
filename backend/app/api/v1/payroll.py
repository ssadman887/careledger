"""Payroll: employees, tax slabs, monthly runs, payslips (accountants prepare, finance approves)."""

from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Query, Response, status

from app.core.deps import DbSession, read_roles, require_roles
from app.core.errors import ErrorEnvelope, ValidationFailed
from app.core.masking import mask
from app.core.money import CENT, quantize
from app.core.pagination import Page, PageParams, page_params
from app.models.approvals import ApprovalKind
from app.models.identity import RoleName
from app.models.payroll import Employee, EmployeeStatus, PayrollRun, PayrollStatus, Payslip
from app.repositories import approvals as approvals_repo
from app.repositories import payroll as repo
from app.schemas.phase5 import (
    DepartmentTotalOut,
    EmployeeCreate,
    EmployeeOut,
    EmployeeUpdate,
    PayrollRunCreate,
    PayrollRunDetail,
    PayrollRunOut,
    PayRunIn,
    PayslipOut,
    RunDecisionIn,
    TaxPreviewIn,
    TaxPreviewOut,
    TaxSlabIO,
    TaxTableIn,
    TaxTableOut,
    TerminateIn,
)
from app.services import idempotency, payroll, pdf
from app.services import payroll_math as pm
from app.services.audit import Actor

router = APIRouter(
    prefix="/payroll",
    tags=["payroll"],
    responses={
        401: {"model": ErrorEnvelope},
        403: {"model": ErrorEnvelope},
        404: {"model": ErrorEnvelope},
        409: {"model": ErrorEnvelope},
        422: {"model": ErrorEnvelope},
    },
)

R = RoleName
PayrollRead = Annotated[Actor, Depends(read_roles(R.ACCOUNTANT, R.FINANCE_MANAGER))]
PayrollWrite = Annotated[Actor, Depends(require_roles(R.ACCOUNTANT))]
PayrollApprove = Annotated[Actor, Depends(require_roles(R.FINANCE_MANAGER))]
TaxWrite = Annotated[Actor, Depends(require_roles(R.ACCOUNTANT, R.FINANCE_MANAGER))]
IdemKey = Annotated[str | None, Header(alias="Idempotency-Key")]
BANK_ROLES = frozenset({R.ACCOUNTANT.value, R.FINANCE_MANAGER.value})
PDF_RESPONSE: dict[int | str, dict[str, Any]] = {
    200: {"content": {"application/pdf": {}}, "description": "PDF document"}
}


def employee_out(e: Employee, actor: Actor) -> EmployeeOut:
    reveal = bool(actor.roles & BANK_ROLES)
    return EmployeeOut(
        id=e.id,
        employee_number=e.employee_number,
        first_name=e.first_name,
        last_name=e.last_name,
        full_name=e.full_name,
        email=e.email,
        department_id=e.department_id,
        department_name=e.department.name,
        position=e.position,
        hire_date=e.hire_date,
        termination_date=e.termination_date,
        status=EmployeeStatus(e.status),
        bank_reference=e.bank_reference if reveal else mask(e.bank_reference),
        basic_salary=e.basic_salary,
        housing_allowance=e.housing_allowance,
        transport_allowance=e.transport_allowance,
        other_allowance=e.other_allowance,
        monthly_gross=e.monthly_gross,
        pension_rate=e.pension_rate,
        other_deduction=e.other_deduction,
    )


def payslip_out(p: Payslip) -> PayslipOut:
    out = PayslipOut.model_validate(p)
    out.department_name = p.department.name
    return out


def run_out(db: DbSession, run: PayrollRun, approval_id: int | None = -1) -> PayrollRunOut:
    """`approval_id` is passed in by list endpoints (batch lookup); -1 means look it up."""
    if approval_id == -1:
        approval = approvals_repo.get_by_entity(db, ApprovalKind.PAYROLL_RUN, run.id)
        approval_id = approval.id if approval else None
    return PayrollRunOut(
        id=run.id,
        run_number=run.run_number,
        year=run.year,
        month=run.month,
        period_start=run.period_start,
        period_end=run.period_end,
        pay_date=run.pay_date,
        status=PayrollStatus(run.status),
        employee_count=run.employee_count,
        gross_total=run.gross_total,
        pension_total=run.pension_total,
        tax_total=run.tax_total,
        other_deduction_total=run.other_deduction_total,
        net_total=run.net_total,
        error=run.error,
        calculated_at=run.calculated_at,
        posting_entry_id=run.posting_entry_id,
        funding_entry_id=run.funding_entry_id,
        payment_entry_id=run.payment_entry_id,
        approved_at=run.approved_at,
        paid_at=run.paid_at,
        created_by_id=run.created_by_id,
        approval_id=approval_id,
    )


def run_detail(db: DbSession, run: PayrollRun) -> PayrollRunDetail:
    return PayrollRunDetail(
        **run_out(db, run).model_dump(),
        payslips=[payslip_out(p) for p in run.payslips],
        departments=[
            DepartmentTotalOut(
                department_id=t.department.id,
                department_name=t.department.name,
                headcount=t.headcount,
                gross=t.gross,
                net=t.net,
            )
            for t in payroll.department_totals(run)
        ],
    )


# ------------------------------------------------------------------ employees


@router.get("/employees", response_model=Page[EmployeeOut])
def list_employees(
    actor: PayrollRead,
    db: DbSession,
    params: Annotated[PageParams, Depends(page_params)],
    search: Annotated[str | None, Query(max_length=100)] = None,
    department_id: int | None = None,
    status: EmployeeStatus | None = None,
) -> Page[EmployeeOut]:
    rows, total = repo.list_employees(
        db,
        params,
        search=search,
        department_id=department_id,
        status=status.value if status else None,
    )
    return Page(
        items=[employee_out(e, actor) for e in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.post("/employees", response_model=EmployeeOut, status_code=status.HTTP_201_CREATED)
def create_employee(body: EmployeeCreate, actor: PayrollWrite, db: DbSession) -> EmployeeOut:
    employee = payroll.create_employee(db, actor, payroll.EmployeeInput(**dict(body)))
    return employee_out(employee, actor)


@router.get("/employees/{employee_id}", response_model=EmployeeOut)
def get_employee(employee_id: int, actor: PayrollRead, db: DbSession) -> EmployeeOut:
    return employee_out(payroll.get_employee(db, employee_id), actor)


@router.patch("/employees/{employee_id}", response_model=EmployeeOut)
def update_employee(
    employee_id: int, body: EmployeeUpdate, actor: PayrollWrite, db: DbSession
) -> EmployeeOut:
    # Attribute values (Decimal), not model_dump(): money serialises to strings.
    changes = {k: getattr(body, k) for k in body.model_fields_set if getattr(body, k) is not None}
    return employee_out(payroll.update_employee(db, actor, employee_id, changes), actor)


@router.post("/employees/{employee_id}/terminate", response_model=EmployeeOut)
def terminate_employee(
    employee_id: int, body: TerminateIn, actor: PayrollWrite, db: DbSession
) -> EmployeeOut:
    employee = payroll.terminate_employee(db, actor, employee_id, body.termination_date)
    return employee_out(employee, actor)


@router.get("/employees/{employee_id}/payslips", response_model=list[PayslipOut])
def employee_payslips(employee_id: int, _: PayrollRead, db: DbSession) -> list[PayslipOut]:
    payroll.get_employee(db, employee_id)
    return [payslip_out(p) for p in repo.payslips_for_employee(db, employee_id)]


# ------------------------------------------------------------------ tax slabs


def _tax_table(db: DbSession, year: int) -> TaxTableOut:
    return TaxTableOut(
        year=year,
        slabs=[
            TaxSlabIO(lower_bound=s.lower, upper_bound=s.upper, rate=s.rate)
            for s in payroll.slabs(db, year)
        ],
        locked=repo.year_has_submitted_runs(db, year),
        years=repo.tax_years(db),
    )


@router.get("/tax-slabs/{year}", response_model=TaxTableOut)
def get_tax_slabs(year: int, _: PayrollRead, db: DbSession) -> TaxTableOut:
    return _tax_table(db, year)


@router.put("/tax-slabs/{year}", response_model=TaxTableOut)
def put_tax_slabs(year: int, body: TaxTableIn, actor: TaxWrite, db: DbSession) -> TaxTableOut:
    payroll.replace_slabs(
        db, actor, year, [pm.Slab(s.lower_bound, s.upper_bound, s.rate) for s in body.slabs]
    )
    return _tax_table(db, year)


@router.post("/tax-preview", response_model=TaxPreviewOut)
def tax_preview(body: TaxPreviewIn, _: PayrollRead, db: DbSession) -> TaxPreviewOut:
    """What income tax would a given monthly taxable pay attract? (Explains the slabs.)"""
    slabs = payroll.slabs(db, body.year)
    annual_income = body.monthly_taxable * 12
    annual = quantize(pm.annual_tax(annual_income, slabs))
    monthly = pm.monthly_tax(body.monthly_taxable, slabs)
    effective = (
        (annual * 100 / annual_income).quantize(CENT) if annual_income > 0 else Decimal("0.00")
    )
    return TaxPreviewOut(
        annual_taxable=annual_income,
        annual_tax=annual,
        monthly_tax=monthly,
        effective_rate_percent=effective,
    )


# ------------------------------------------------------------------ runs


@router.get("/runs", response_model=Page[PayrollRunOut])
def list_runs(
    _: PayrollRead,
    db: DbSession,
    params: Annotated[PageParams, Depends(page_params)],
    status: PayrollStatus | None = None,
    year: int | None = None,
) -> Page[PayrollRunOut]:
    rows, total = repo.list_runs(db, params, status=status.value if status else None, year=year)
    approval_ids = approvals_repo.ids_by_entities(
        db, ApprovalKind.PAYROLL_RUN, [r.id for r in rows]
    )
    return Page(
        items=[run_out(db, r, approval_ids.get(r.id)) for r in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


def _dispatch(run_id: int) -> None:
    from app.jobs.worker import dispatch_payroll_run

    dispatch_payroll_run(run_id)


@router.post("/runs", response_model=PayrollRunDetail, status_code=status.HTTP_201_CREATED)
def create_run(
    body: PayrollRunCreate, actor: PayrollWrite, db: DbSession, tasks: BackgroundTasks
) -> PayrollRunDetail:
    """Create the month's run. With `background` (default) the calculation is queued on the
    job worker after this request commits; poll GET /payroll/runs/{id} until it is calculated."""
    run = payroll.create_run(db, actor, year=body.year, month=body.month, pay_date=body.pay_date)
    if body.background:
        tasks.add_task(_dispatch, run.id)  # runs after the response, i.e. after commit
    else:
        run = payroll.calculate_run(db, actor, run.id)
    return run_detail(db, run)


@router.get("/runs/{run_id}", response_model=PayrollRunDetail)
def get_run(run_id: int, _: PayrollRead, db: DbSession) -> PayrollRunDetail:
    return run_detail(db, payroll.get_run(db, run_id))


@router.post("/runs/{run_id}/recalculate", response_model=PayrollRunDetail)
def recalculate_run(run_id: int, actor: PayrollWrite, db: DbSession) -> PayrollRunDetail:
    return run_detail(db, payroll.calculate_run(db, actor, run_id))


@router.post("/runs/{run_id}/submit", response_model=PayrollRunDetail)
def submit_run(run_id: int, actor: PayrollWrite, db: DbSession) -> PayrollRunDetail:
    return run_detail(db, payroll.submit_run(db, actor, run_id))


@router.post("/runs/{run_id}/approve", response_model=PayrollRunDetail)
def approve_run(
    run_id: int, body: RunDecisionIn, actor: PayrollApprove, db: DbSession
) -> PayrollRunDetail:
    return run_detail(db, payroll.approve_run(db, actor, run_id, body.note))


@router.post("/runs/{run_id}/reject", response_model=PayrollRunDetail)
def reject_run(
    run_id: int, body: RunDecisionIn, actor: PayrollApprove, db: DbSession
) -> PayrollRunDetail:
    if not body.note.strip():
        raise ValidationFailed("A rejection needs a reason", code="reason_required")
    return run_detail(db, payroll.reject_run(db, actor, run_id, body.note))


@router.post("/runs/{run_id}/pay", response_model=PayrollRunDetail)
def pay_run(
    run_id: int,
    body: PayRunIn,
    actor: PayrollWrite,
    db: DbSession,
    idempotency_key: IdemKey = None,
) -> Any:
    """Pay net salaries. Send an Idempotency-Key so a retried request cannot pay twice."""

    def run() -> dict[str, Any]:
        paid = payroll.pay_run(db, actor, run_id, paid_on=body.paid_on)
        return run_detail(db, paid).model_dump(mode="json")

    return idempotency.execute(
        db,
        actor,
        scope=f"payroll-pay:{run_id}",
        key=idempotency_key,
        payload=body.model_dump(mode="json"),
        run=run,
    )


@router.get("/payslips/{payslip_id}/pdf", response_class=Response, responses=PDF_RESPONSE)
def payslip_pdf(payslip_id: int, _: PayrollRead, db: DbSession) -> Response:
    slip = payroll.get_payslip(db, payslip_id)
    run = payroll.get_run(db, slip.payroll_run_id)
    employee = payroll.get_employee(db, slip.employee_id)
    content = pdf.payslip_pdf(run, slip, mask(employee.bank_reference))
    filename = f"payslip-{run.run_number}-{slip.employee_number}.pdf"
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
