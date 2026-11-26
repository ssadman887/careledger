"""Tax slabs, employees, payroll runs and 2026 budgets with alerts. Deterministic and idempotent.

Payroll moved onto CareLedger in June 2026: runs June-October are posted and paid, November is
calculated and waiting for finance-manager approval (demo). One employee joined mid-September
and one left on 20 October, so those months show prorated payslips. Budgets for 2026 cover
salaries (from June), supplies and department revenue; Emergency salaries run over budget and
Surgery is close to its alert threshold.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.approvals import ApprovalKind
from app.models.budgets import Budget
from app.models.identity import User
from app.models.ledger import Account
from app.models.org import Department
from app.models.payroll import Employee
from app.repositories import approvals as approvals_repo
from app.services import approvals, budgets, payroll
from app.services.audit import Actor
from app.services.auth import actor_for
from app.services.budgets import LineSpec
from app.services.payroll import EmployeeInput

D = Decimal

# (first, last, department, position, hire date, basic, housing, transport, pension rate,
#  other deduction). Names are invented.
EMPLOYEES: tuple[tuple[str, str, str, str, date, str, str, str, str, str], ...] = (
    ("Avery", "Lindqvist", "EMER", "Emergency Physician", date(2021, 3, 1), "12500.00", "1800.00", "250.00", "0.0500", "120.00"),
    ("Rowan", "Achterberg", "EMER", "Emergency Physician", date(2022, 7, 18), "11800.00", "1700.00", "250.00", "0.0500", "0.00"),
    ("Imani", "Okafor", "EMER", "Charge Nurse", date(2019, 1, 7), "4900.00", "700.00", "180.00", "0.0500", "45.00"),
    ("Theo", "Marchetti", "EMER", "Staff Nurse", date(2023, 4, 3), "3900.00", "550.00", "180.00", "0.0500", "45.00"),
    ("Priya", "Raman", "EMER", "Staff Nurse", date(2024, 2, 12), "3850.00", "550.00", "180.00", "0.0500", "0.00"),
    ("Mateo", "Vasquez", "RAD", "Radiologist", date(2020, 9, 14), "13200.00", "1900.00", "250.00", "0.0600", "0.00"),
    ("Sofia", "Brennan", "RAD", "Radiographer", date(2022, 11, 1), "4200.00", "600.00", "150.00", "0.0500", "30.00"),
    ("Kenji", "Watanabe", "RAD", "Sonographer", date(2021, 6, 21), "4400.00", "600.00", "150.00", "0.0500", "0.00"),
    ("Lena", "Hofmann", "LAB", "Laboratory Manager", date(2018, 5, 2), "6200.00", "900.00", "200.00", "0.0600", "60.00"),
    ("Jamal", "Whitaker", "LAB", "Biomedical Scientist", date(2023, 1, 16), "4100.00", "550.00", "150.00", "0.0500", "0.00"),
    ("Nadia", "Petrova", "LAB", "Phlebotomist", date(2024, 8, 5), "2900.00", "400.00", "150.00", "0.0500", "25.00"),
    ("Elliot", "Fairbanks", "SURG", "Consultant Surgeon", date(2017, 10, 9), "15800.00", "2200.00", "300.00", "0.0700", "150.00"),
    ("Hana", "Kowalczyk", "SURG", "Anaesthetist", date(2020, 2, 24), "14100.00", "2000.00", "300.00", "0.0600", "0.00"),
    ("Marcus", "Delacroix", "SURG", "Theatre Nurse", date(2021, 9, 6), "4300.00", "600.00", "180.00", "0.0500", "45.00"),
    ("Yara", "Haddad", "SURG", "Theatre Nurse", date(2022, 3, 28), "4250.00", "600.00", "180.00", "0.0500", "0.00"),
    ("Oskar", "Nyberg", "SURG", "Surgical Technologist", date(2023, 10, 2), "3600.00", "500.00", "150.00", "0.0500", "0.00"),
    ("Grace", "Adeyemi", "INPT", "Ward Manager", date(2016, 4, 11), "5600.00", "800.00", "180.00", "0.0600", "60.00"),
    ("Felix", "Moreau", "INPT", "Staff Nurse", date(2022, 5, 9), "3800.00", "550.00", "180.00", "0.0500", "45.00"),
    ("Aisha", "Rahman", "INPT", "Staff Nurse", date(2023, 7, 24), "3750.00", "550.00", "180.00", "0.0500", "0.00"),
    ("Daniel", "Szabo", "INPT", "Healthcare Assistant", date(2024, 1, 8), "2600.00", "350.00", "150.00", "0.0400", "0.00"),
    ("Mia", "Castellanos", "INPT", "Hospitalist", date(2021, 11, 15), "10900.00", "1600.00", "250.00", "0.0500", "0.00"),
    ("Samuel", "Oduya", "OPD", "General Practitioner", date(2019, 8, 19), "9800.00", "1400.00", "250.00", "0.0500", "90.00"),
    ("Clara", "Jensen", "OPD", "Practice Nurse", date(2022, 9, 12), "3700.00", "500.00", "150.00", "0.0500", "0.00"),
    ("Ravi", "Menon", "OPD", "Physiotherapist", date(2023, 3, 6), "4000.00", "550.00", "150.00", "0.0500", "30.00"),
    ("Zoe", "Abernathy", "OPD", "Receptionist", date(2024, 6, 3), "2400.00", "300.00", "120.00", "0.0400", "0.00"),
    ("Tomas", "Herrera", "PHAR", "Chief Pharmacist", date(2018, 12, 3), "7400.00", "1000.00", "200.00", "0.0600", "0.00"),
    ("Ingrid", "Solberg", "PHAR", "Pharmacy Technician", date(2023, 5, 15), "2950.00", "400.00", "150.00", "0.0500", "25.00"),
    ("Victor", "Lambert", "ADMIN", "Finance Officer", date(2020, 1, 13), "4600.00", "650.00", "150.00", "0.0500", "0.00"),
    ("Esme", "Callaway", "ADMIN", "HR Coordinator", date(2021, 4, 26), "3900.00", "550.00", "150.00", "0.0500", "0.00"),
    ("Noah", "Featherstone", "ADMIN", "IT Support Analyst", date(2022, 10, 17), "4100.00", "550.00", "150.00", "0.0500", "35.00"),
    # Joined mid-September (prorated September payslip).
    ("Leila", "Navarro", "EMER", "Emergency Physician", date(2026, 9, 15), "11500.00", "1700.00", "250.00", "0.0500", "0.00"),
)  # fmt: skip
TERMINATED = ("Daniel", "Szabo", date(2026, 10, 20))  # left 20 October (prorated October)
POSTED_MONTHS = (6, 7, 8, 9, 10)
PENDING_MONTH = 11
YEAR = 2026

# Salary budget, June-December, as a share of the department's actual monthly gross:
# Emergency is under-budgeted (runs over), Surgery is tight (warning), others have headroom.
SALARY_BUDGET_FACTOR = {"EMER": D("0.80"), "SURG": D("1.06")}
DEFAULT_SALARY_FACTOR = D("1.15")
# Other monthly budgets from June (account code -> monthly amount), sized against the activity
# seed: costs with ~15% headroom; revenue targets near actuals (Emergency falls short).
COSTS: dict[str, tuple[tuple[str, str], ...]] = {
    "EMER": (("5200", "3700.00"),),
    "SURG": (("5200", "5100.00"),),
    "INPT": (("5200", "3250.00"),),
    "LAB": (("5200", "1800.00"),),
    "PHAR": (("5210", "10000.00"),),
    "RAD": (("5500", "2750.00"),),
    "ADMIN": (("5300", "8600.00"), ("5310", "4400.00")),
}
REVENUE = {
    "EMER": "25000.00",
    "RAD": "12000.00",
    "LAB": "6000.00",
    "SURG": "150000.00",
    "INPT": "125000.00",
    "OPD": "7500.00",
    "PHAR": "6500.00",
}
FROM_JUNE = 5  # leading zero months (Jan-May)


def _user(session: Session, username: str) -> Actor:
    return actor_for(session.scalars(select(User).where(User.username == username)).one())


def _account(session: Session, code: str) -> int:
    return session.scalars(select(Account.id).where(Account.code == code)).one()


def seed_employees(session: Session) -> None:
    if session.scalar(select(func.count(Employee.id))):
        return
    accountant = _user(session, "accountant")
    depts = {d.code: d.id for d in session.scalars(select(Department)).all()}
    for i, row in enumerate(EMPLOYEES, start=1):
        first, last, dept, position, hired, basic, housing, transport, rate, other = row
        employee = payroll.create_employee(
            session,
            accountant,
            EmployeeInput(
                first_name=first,
                last_name=last,
                department_id=depts[dept],
                position=position,
                hire_date=hired,
                basic_salary=D(basic),
                housing_allowance=D(housing),
                transport_allowance=D(transport),
                pension_rate=D(rate),
                other_deduction=D(other),
                email=f"{first.lower()}.{last.lower()}@staff.careledger.example",
                bank_reference=f"GB00-CLGH-{700000 + i * 137:06d}",
            ),
        )
        if (first, last) == TERMINATED[:2]:
            payroll.terminate_employee(session, accountant, employee.id, TERMINATED[2])


def seed_payroll_runs(session: Session) -> None:
    from app.repositories import payroll as payroll_repo

    if payroll_repo.run_for_month(session, YEAR, POSTED_MONTHS[0]) is not None:
        return
    accountant = _user(session, "accountant")
    finance = _user(session, "finance")
    for month in (*POSTED_MONTHS, PENDING_MONTH):
        run = payroll.create_run(session, accountant, year=YEAR, month=month, pay_date=None)
        payroll.calculate_run(session, accountant, run.id)
        payroll.submit_run(session, accountant, run.id)
        if month == PENDING_MONTH:
            continue
        approval = approvals_repo.get_by_entity(session, ApprovalKind.PAYROLL_RUN, run.id)
        assert approval is not None
        approvals.decide(
            session, finance, approval.id, approve=True, note="Checked against HR changes"
        )
        payroll.pay_run(session, accountant, run.id, paid_on=None)


def _monthly_gross_by_department(session: Session) -> dict[str, Decimal]:
    """Department gross from the October run (the latest posted month)."""
    from app.repositories import payroll as payroll_repo

    run = payroll_repo.run_for_month(session, YEAR, POSTED_MONTHS[-1])
    assert run is not None
    out: dict[str, Decimal] = {}
    for slip in run.payslips:
        out[slip.department.code] = out.get(slip.department.code, D("0")) + slip.gross
    return out


def seed_budgets(session: Session) -> None:
    if session.scalar(select(func.count(Budget.id))):
        return
    finance = _user(session, "finance")
    gross = _monthly_gross_by_department(session)
    salaries = _account(session, "5100")
    for dept in session.scalars(select(Department).order_by(Department.code)).all():
        if dept.code not in gross:
            continue
        factor = SALARY_BUDGET_FACTOR.get(dept.code, DEFAULT_SALARY_FACTOR)
        monthly_salary = (gross[dept.code] * factor / 100).quantize(D("1")) * 100  # nearest 100

        def june_on(amount: Decimal) -> list[Decimal]:
            return [D("0")] * FROM_JUNE + [amount] * (12 - FROM_JUNE)

        lines = [LineSpec(salaries, monthly=june_on(monthly_salary))]
        lines += [
            LineSpec(_account(session, code), monthly=june_on(D(amount)))
            for code, amount in COSTS.get(dept.code, ())
        ]
        if dept.code in REVENUE and dept.revenue_account_id is not None:
            lines.append(LineSpec(dept.revenue_account_id, monthly=june_on(D(REVENUE[dept.code]))))
        budget = budgets.create_budget(
            session,
            finance,
            year=YEAR,
            department_id=dept.id,
            name=f"{dept.name} {YEAR}",
            alert_threshold_percent=D("90.00"),
            lines=lines,
            notes="Budgeted from June, when the hospital moved its books onto CareLedger.",
        )
        budgets.set_status(session, finance, budget.id, "active")
    # Alerts as at the last posted payroll month (the daily job continues from there).
    budgets.check_alerts(session, Actor(id=None, label="budget-job", roles=frozenset()),
                         as_of=date(YEAR, POSTED_MONTHS[-1], 31))  # fmt: skip


def seed_phase5(session: Session) -> None:
    for year in (YEAR, YEAR + 1):
        payroll.ensure_slabs(session, year)
    seed_employees(session)
    seed_payroll_runs(session)
    seed_budgets(session)
