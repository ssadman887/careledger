"""Payroll queries: employees, tax slabs, runs, payslips."""

from collections.abc import Sequence
from datetime import date

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.core.pagination import PageParams
from app.models.payroll import Employee, PayrollRun, Payslip, TaxSlab
from app.repositories.billing import _page


def get_employee(session: Session, employee_id: int) -> Employee | None:
    return session.get(Employee, employee_id)


def list_employees(
    session: Session,
    params: PageParams,
    *,
    search: str | None,
    department_id: int | None,
    status: str | None,
) -> tuple[Sequence[Employee], int]:
    stmt = select(Employee)
    if search:
        like = f"%{search.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Employee.first_name + " " + Employee.last_name).like(like),
                func.lower(Employee.employee_number).like(like),
                func.lower(Employee.position).like(like),
            )
        )
    if department_id is not None:
        stmt = stmt.where(Employee.department_id == department_id)
    if status:
        stmt = stmt.where(Employee.status == status)
    sorts = {
        "employee_number": Employee.employee_number,
        "last_name": Employee.last_name,
        "basic_salary": Employee.basic_salary,
        "hire_date": Employee.hire_date,
    }
    return _page(session, stmt, params, sorts, "employee_number", Employee.id)


def employed_between(session: Session, first: date, last: date) -> Sequence[Employee]:
    """Employees with at least one day of employment in [first, last]."""
    stmt = (
        select(Employee)
        .where(Employee.hire_date <= last)
        .where(or_(Employee.termination_date.is_(None), Employee.termination_date >= first))
        .order_by(Employee.employee_number)
    )
    return session.scalars(stmt).unique().all()


def slabs_for_year(session: Session, year: int) -> Sequence[TaxSlab]:
    stmt = select(TaxSlab).where(TaxSlab.year == year).order_by(TaxSlab.lower_bound)
    return session.scalars(stmt).all()


def tax_years(session: Session) -> list[int]:
    return list(session.scalars(select(TaxSlab.year).distinct().order_by(TaxSlab.year)).all())


def delete_slabs(session: Session, year: int) -> None:
    session.execute(delete(TaxSlab).where(TaxSlab.year == year))


def get_run(session: Session, run_id: int, *, lock: bool = False) -> PayrollRun | None:
    if lock:
        stmt = select(PayrollRun).where(PayrollRun.id == run_id).with_for_update()
        return session.scalars(stmt).first()
    return session.get(PayrollRun, run_id)


def run_for_month(session: Session, year: int, month: int) -> PayrollRun | None:
    stmt = select(PayrollRun).where(PayrollRun.year == year, PayrollRun.month == month)
    return session.scalars(stmt).first()


def list_runs(
    session: Session, params: PageParams, *, status: str | None, year: int | None
) -> tuple[Sequence[PayrollRun], int]:
    stmt = select(PayrollRun)
    if status:
        stmt = stmt.where(PayrollRun.status == status)
    if year is not None:
        stmt = stmt.where(PayrollRun.year == year)
    sorts = {"period_start": PayrollRun.period_start, "net_total": PayrollRun.net_total}
    return _page(session, stmt, params, sorts, "-period_start", PayrollRun.id.desc())


def get_payslip(session: Session, payslip_id: int) -> Payslip | None:
    return session.get(Payslip, payslip_id)


def payslips_for_employee(session: Session, employee_id: int) -> Sequence[Payslip]:
    stmt = (
        select(Payslip)
        .join(PayrollRun, PayrollRun.id == Payslip.payroll_run_id)
        .where(Payslip.employee_id == employee_id)
        .order_by(PayrollRun.period_start.desc())
    )
    return session.scalars(stmt).unique().all()


def employee_has_payslips(session: Session, employee_id: int) -> bool:
    stmt = select(func.count(Payslip.id)).where(Payslip.employee_id == employee_id)
    return bool(session.scalar(stmt))


def year_has_submitted_runs(session: Session, year: int) -> bool:
    stmt = select(func.count(PayrollRun.id)).where(
        PayrollRun.year == year,
        PayrollRun.status.in_(("pending_approval", "posted", "paid")),
    )
    return bool(session.scalar(stmt))
