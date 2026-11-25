"""Default hospital chart of accounts, departments, cost centers, fiscal periods, opening balances.

Idempotent: existing rows (matched by code / name / source) are left in place.
Account codes here are referenced by auto-posting (docs/ARCHITECTURE.md section 4).
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ledger import Account, FiscalPeriod
from app.models.org import CostCenter, Department
from app.repositories import ledger as ledger_repo
from app.services import ledger, periods
from app.services.audit import SYSTEM_ACTOR
from app.services.ledger import EntryDraft, LineInput


@dataclass(frozen=True)
class AccountSpec:
    code: str
    name: str
    type: str
    parent: str | None = None
    header: bool = False


A, L, E, R, X = "asset", "liability", "equity", "revenue", "expense"

CHART_OF_ACCOUNTS: tuple[AccountSpec, ...] = (
    AccountSpec("1000", "Assets", A, header=True),
    AccountSpec("1010", "Cash on Hand", A, "1000"),
    AccountSpec("1020", "Bank - Operating", A, "1000"),
    AccountSpec("1030", "Bank - Payroll", A, "1000"),
    AccountSpec("1100", "Accounts Receivable - Patients", A, "1000"),
    AccountSpec("1110", "Accounts Receivable - Insurers", A, "1000"),
    AccountSpec("1150", "Allowance for Doubtful Accounts", A, "1000"),
    AccountSpec("1200", "Medical Supplies Inventory", A, "1000"),
    AccountSpec("1210", "Pharmacy Inventory", A, "1000"),
    AccountSpec("1300", "Prepaid Expenses", A, "1000"),
    AccountSpec("1500", "Medical Equipment", A, "1000"),
    AccountSpec("1510", "Buildings", A, "1000"),
    AccountSpec("1590", "Accumulated Depreciation", A, "1000"),
    AccountSpec("2000", "Liabilities", L, header=True),
    AccountSpec("2010", "Accounts Payable", L, "2000"),
    AccountSpec("2100", "Salaries Payable", L, "2000"),
    AccountSpec("2110", "Payroll Tax Payable", L, "2000"),
    AccountSpec("2120", "Other Payroll Deductions Payable", L, "2000"),
    AccountSpec("2200", "Patient Deposits", L, "2000"),
    AccountSpec("2300", "Sales Tax Payable", L, "2000"),
    AccountSpec("2400", "Accrued Expenses", L, "2000"),
    AccountSpec("2500", "Long-term Loan", L, "2000"),
    AccountSpec("3000", "Equity", E, header=True),
    AccountSpec("3010", "Retained Earnings", E, "3000"),
    AccountSpec("3020", "Opening Balance Equity", E, "3000"),
    AccountSpec("4000", "Revenue", R, header=True),
    AccountSpec("4100", "Patient Service Revenue", R, "4000", header=True),
    AccountSpec("4110", "Emergency Revenue", R, "4100"),
    AccountSpec("4120", "Radiology Revenue", R, "4100"),
    AccountSpec("4130", "Laboratory Revenue", R, "4100"),
    AccountSpec("4140", "Surgery Revenue", R, "4100"),
    AccountSpec("4150", "Inpatient Revenue", R, "4100"),
    AccountSpec("4160", "Outpatient Clinic Revenue", R, "4100"),
    AccountSpec("4170", "Pharmacy Revenue", R, "4100"),
    AccountSpec("4900", "Contractual Adjustments", R, "4000"),
    AccountSpec("4910", "Patient Discounts", R, "4000"),
    AccountSpec("4950", "Other Income", R, "4000"),
    AccountSpec("5000", "Expenses", X, header=True),
    AccountSpec("5100", "Salaries & Wages", X, "5000"),
    AccountSpec("5110", "Employer Payroll Taxes", X, "5000"),
    AccountSpec("5200", "Medical Supplies Expense", X, "5000"),
    AccountSpec("5210", "Pharmaceuticals Expense", X, "5000"),
    AccountSpec("5300", "Utilities", X, "5000"),
    AccountSpec("5310", "Rent & Facilities", X, "5000"),
    AccountSpec("5400", "Bad Debt Expense", X, "5000"),
    AccountSpec("5500", "Equipment Maintenance", X, "5000"),
    AccountSpec("5600", "Depreciation Expense", X, "5000"),
    AccountSpec("5700", "Insurance Expense", X, "5000"),
    AccountSpec("5800", "Professional Fees", X, "5000"),
    AccountSpec("5900", "General & Administrative", X, "5000"),
)

# (code, name, revenue account code)
DEPARTMENTS: tuple[tuple[str, str, str | None], ...] = (
    ("EMER", "Emergency", "4110"),
    ("RAD", "Radiology", "4120"),
    ("LAB", "Laboratory", "4130"),
    ("SURG", "Surgery", "4140"),
    ("INPT", "Inpatient Wards", "4150"),
    ("OPD", "Outpatient Clinics", "4160"),
    ("PHAR", "Pharmacy", "4170"),
    ("ADMIN", "Administration", None),
)

FIRST_PERIOD = date(2026, 1, 1)
OPENING_DATE = date(2026, 1, 1)
OPENING_BALANCES: tuple[tuple[str, Decimal, Decimal], ...] = (
    ("1020", Decimal("2500000.00"), Decimal("0")),
    ("1500", Decimal("1800000.00"), Decimal("0")),
    ("1510", Decimal("4200000.00"), Decimal("0")),
    ("2500", Decimal("0"), Decimal("3000000.00")),
    ("3020", Decimal("0"), Decimal("5500000.00")),
)


def seed_chart_of_accounts(session: Session) -> dict[str, Account]:
    existing = {a.code: a for a in session.scalars(select(Account)).all()}
    for spec in CHART_OF_ACCOUNTS:
        if spec.code in existing:
            continue
        parent = existing[spec.parent] if spec.parent else None
        account = Account(
            code=spec.code,
            name=spec.name,
            type=spec.type,
            parent_id=parent.id if parent else None,
            is_header=spec.header,
            is_active=True,
            description="",
        )
        session.add(account)
        session.flush()
        existing[spec.code] = account
    return existing


def seed_departments(session: Session, accounts: dict[str, Account]) -> None:
    depts = {d.code: d for d in session.scalars(select(Department)).all()}
    centers = set(session.scalars(select(CostCenter.code)).all())
    for code, name, revenue_code in DEPARTMENTS:
        dept = depts.get(code)
        if dept is None:
            dept = Department(
                code=code,
                name=name,
                revenue_account_id=accounts[revenue_code].id if revenue_code else None,
            )
            session.add(dept)
            session.flush()
        cc_code = f"CC-{code}"
        if cc_code not in centers:
            session.add(CostCenter(code=cc_code, name=f"{name} cost center", department_id=dept.id))
    session.flush()


def _months_until(last: date) -> list[tuple[int, int]]:
    out, y, m = [], FIRST_PERIOD.year, FIRST_PERIOD.month
    while (y, m) <= (last.year, last.month):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def seed_periods(session: Session, *, through: date | None = None) -> None:
    """Monthly periods from Jan 2026 through 12 months past today (so the demo keeps working)."""
    today = datetime.now(UTC).date()
    end = through or date(today.year + 1, today.month, 1)
    names = set(session.scalars(select(FiscalPeriod.name)).all())
    for year, month in _months_until(end):
        if f"{year:04d}-{month:02d}" not in names:
            periods.create_month(session, SYSTEM_ACTOR, year, month)


def seed_opening_balances(session: Session, accounts: dict[str, Account]) -> None:
    if ledger_repo.entries_for_source(session, "opening_balance", str(OPENING_DATE.year)):
        return
    ledger.post_entry(
        session,
        SYSTEM_ACTOR,
        EntryDraft(
            entry_date=OPENING_DATE,
            memo="Opening balances",
            source_type="opening_balance",
            source_id=str(OPENING_DATE.year),
            lines=[
                LineInput(accounts[code].id, debit, credit, "Opening balance")
                for code, debit, credit in OPENING_BALANCES
            ],
        ),
    )


def seed_ledger(session: Session) -> dict[str, Account]:
    accounts = seed_chart_of_accounts(session)
    seed_departments(session, accounts)
    seed_periods(session)
    seed_opening_balances(session, accounts)
    return accounts
