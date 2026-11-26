"""Six months of routine hospital activity (June to November 2026) at a realistic scale.

Runs after the scenario seeds (billing, claims, AR/AP, payroll, budgets) and adds the volume a
real ledger would have: about 120 patient encounters a month across departments, each invoiced
from the price list and mostly paid within a month; monthly supplier bills charged to
departments; monthly depreciation. Then it closes January to September (October stays open so
the demo can close "last month"), raises budget alerts and reminders for the new activity, and
plants two anomalies worth spotting:

* an unusually large ICU invoice, still unpaid, ageing past 30 days;
* a large unexplained manual journal entry waiting for finance-manager approval.

Deterministic (fixed RNG seed and dates) and idempotent (skips if it has run before).
"""

import random
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal

from faker import Faker
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.ap import Vendor
from app.models.approvals import Approval
from app.models.catalog import Service
from app.models.identity import User
from app.models.ledger import FiscalPeriod, PeriodStatus
from app.models.org import Department
from app.models.patients import Patient
from app.services import (
    ap,
    approvals,
    ar,
    budgets,
    invoices,
    ledger,
    patients,
    payments,
    periods,
    posting,
)
from app.services.ap import APLine
from app.services.audit import SYSTEM_ACTOR, Actor
from app.services.auth import actor_for
from app.services.invoices import LineSpec
from app.services.ledger import LineInput

D = Decimal
SEED = 20260601
FIRST_DAY, LAST_DAY = date(2026, 6, 1), date(2026, 11, 24)
TODAY = date(2026, 11, 25)
NEW_PATIENTS = 160
MARKER_PATIENT = ("Quentin", "Ashworth-Vale")  # the ICU anomaly; also marks "already ran"
CLOSE_THROUGH = date(2026, 9, 30)  # periods up to here are closed

Pick = Callable[[random.Random], list[tuple[str, int]]]


def _opd(r: random.Random) -> list[tuple[str, int]]:
    lines = [(r.choice(["OPD-NEW", "OPD-FU", "OPD-FU"]), 1)]
    if r.random() < 0.3:
        lines.append(("OPD-PHYSIO", r.randint(1, 4)))
    if r.random() < 0.4:
        lines.append((r.choice(["LAB-CBC", "LAB-LIPID", "LAB-BMP"]), 1))
    if r.random() < 0.3:
        lines.append((r.choice(["PHAR-ABX", "PHAR-ANALG", "PHAR-INSUL"]), r.randint(1, 2)))
    return lines


def _emer(r: random.Random) -> list[tuple[str, int]]:
    lines = [("ER-TRIAGE", 1), ("ER-L5" if r.random() < 0.2 else "ER-L3", 1)]
    lines.append((r.choice(["LAB-CBC", "LAB-BMP"]), 1))
    if r.random() < 0.35:
        lines.append(("RAD-XR-CHEST", 1))
    if r.random() < 0.15:
        lines.append(("RAD-CT-HEAD", 1))
    if r.random() < 0.25:
        lines.append(("ER-SUTURE", 1))
    lines.append(("PHAR-IVFL", r.randint(0, 3)))
    return [ln for ln in lines if ln[1] > 0]


def _rad(r: random.Random) -> list[tuple[str, int]]:
    return [(r.choice(["RAD-CT-HEAD", "RAD-MRI-KNEE", "RAD-US-ABD", "RAD-XR-CHEST"]), 1)]


def _lab(r: random.Random) -> list[tuple[str, int]]:
    tests = ["LAB-CBC", "LAB-BMP", "LAB-LIPID", "LAB-CULT"]
    return [(t, 1) for t in r.sample(tests, k=r.randint(2, 3))]


def _surg(r: random.Random) -> list[tuple[str, int]]:
    stay = r.randint(1, 3)
    return [
        (r.choice(["SURG-APPY", "SURG-CHOLE"]), 1),
        ("SURG-OR-HR", r.randint(2, 3)),
        ("SURG-ANES", 1),
        ("INPT-BED", stay),
        ("LAB-CBC", 1),
        ("PHAR-ABX", 1),
        ("PHAR-IVFL", stay * 2),
    ]


def _inpt(r: random.Random) -> list[tuple[str, int]]:
    days = r.randint(2, 6)
    lines = [("INPT-BED", days), ("INPT-NURS", days), ("LAB-BMP", 1), ("PHAR-IVFL", days)]
    if r.random() < 0.12:
        lines.append(("INPT-ICU", r.randint(1, 2)))
    return lines


def _phar(r: random.Random) -> list[tuple[str, int]]:
    return [
        (c, r.randint(1, 3))
        for c in r.sample(["PHAR-ABX", "PHAR-ANALG", "PHAR-INSUL"], k=r.randint(1, 2))
    ]


# department code -> (encounters per month, visit type, length of stay in days, line picker)
MIX: dict[str, tuple[int, str, int, Pick]] = {
    "OPD": (30, "outpatient", 0, _opd),
    "EMER": (25, "emergency", 0, _emer),
    "RAD": (12, "outpatient", 0, _rad),
    "LAB": (20, "outpatient", 0, _lab),
    "SURG": (9, "inpatient", 2, _surg),
    "INPT": (12, "inpatient", 4, _inpt),
    "PHAR": (15, "outpatient", 0, _phar),
}

# Monthly supplier bills: vendor code -> (expense account, [(department, amount)], description)
MONTHLY_BILLS: dict[str, tuple[str, list[tuple[str, str]], str]] = {
    "MEDSUP": (
        "5200",
        [("EMER", "3200.00"), ("SURG", "4400.00"), ("INPT", "2800.00"), ("LAB", "1550.00")],
        "Medical consumables",
    ),  # fmt: skip
    "PHARMA": ("5210", [("PHAR", "8900.00")], "Pharmacy stock"),
    "UTIL": ("5300", [("ADMIN", "7450.00")], "Electricity and water"),
    "CLEAN": ("5310", [("ADMIN", "3800.00")], "Cleaning and facilities"),
    "BIOMED": ("5500", [("RAD", "2350.00")], "Imaging equipment maintenance"),
}
DEPRECIATION = D("25000.00")  # (1.8M equipment / 10y + 4.2M buildings / 40y) / 12, rounded


def _user(session: Session, username: str) -> Actor:
    return actor_for(session.scalars(select(User).where(User.username == username)).one())


def _months() -> list[date]:
    return [date(2026, m, 1) for m in range(FIRST_DAY.month, LAST_DAY.month + 1)]


def _month_end(first: date) -> date:
    nxt = date(first.year + first.month // 12, first.month % 12 + 1, 1)
    return nxt - timedelta(days=1)


def _new_patients(session: Session) -> list[Patient]:
    fake = Faker("en_US")
    fake.seed_instance(SEED)
    rng = random.Random(SEED)
    out = []
    for n in range(NEW_PATIENTS):
        sex = rng.choice(["female", "male"])
        first = fake.first_name_female() if sex == "female" else fake.first_name_male()
        last = fake.last_name()
        out.append(
            patients.create_patient(
                session,
                SYSTEM_ACTOR,
                first_name=first,
                last_name=last,
                date_of_birth=date(1938, 1, 1) + timedelta(days=rng.randint(0, 85 * 365)),
                sex=sex,
                phone=f"555-01{n % 100:02d}",  # fictional 555-01xx range
                email=f"{first}.{last}.{n}@example.com".lower(),
                today=TODAY,
            )
        )
    return out


def _pay(
    session: Session,
    clerk: Actor,
    rng: random.Random,
    invoice_id: int,
    total: Decimal,
    issued: date,
) -> None:
    """Most bills are paid within a month; some in part; some not yet."""
    roll = rng.random()
    if roll < 0.15:
        return
    pay_on = issued + timedelta(days=rng.randint(0, 35))
    if pay_on > LAST_DAY:
        return
    method = rng.choices(["cash", "card", "bank_transfer"], weights=[25, 45, 30])[0]
    reference = (
        f"{rng.randint(0, 9999):04d}"
        if method == "card"
        else f"TRX-{rng.randint(100000, 999999)}"
        if method == "bank_transfer"
        else ""
    )
    amount = total if roll >= 0.27 else (total * D("0.5")).quantize(D("0.01"))
    payments.record_payment(
        session,
        clerk,
        invoice_id=invoice_id,
        method=method,
        amount=amount,
        received_on=pay_on,
        reference=reference,
        notes="" if amount == total else "Part payment",
    )


def _encounters(session: Session, clerk: Actor, people: list[Patient]) -> None:
    rng = random.Random(SEED + 1)
    services = {s.code: s.id for s in session.scalars(select(Service)).all()}
    depts = {d.code: d.id for d in session.scalars(select(Department)).all()}
    physicians = [f"Dr. {n}" for n in ("Okoro", "Lindgren", "Haddad", "Moreau", "Tanaka", "Reyes",
                                       "Kowalski", "Bianchi")]  # fmt: skip
    for month in _months():
        last = min(_month_end(month), LAST_DAY)
        span = (last - month).days
        for code, (count, visit_type, stay, pick) in MIX.items():
            for _ in range(count):
                admit = month + timedelta(days=rng.randint(0, span))
                discharge = min(
                    admit + timedelta(days=rng.randint(stay, stay + 2) if stay else 0), last
                )
                patient = rng.choice(people)
                visit = patients.create_visit(
                    session,
                    clerk,
                    patient_id=patient.id,
                    department_id=depts[code],
                    visit_type=visit_type,
                    admit_date=admit,
                    discharge_date=discharge,
                    attending_physician=rng.choice(physicians),
                )
                invoice = invoices.create_invoice(
                    session,
                    clerk,
                    patient_id=patient.id,
                    visit_id=visit.id,
                    price_list_id=None,
                    notes="",
                    lines=[
                        LineSpec(quantity=D(q), service_id=services[s], service_date=admit)
                        for s, q in pick(rng)
                    ],
                )
                invoices.issue_invoice(session, clerk, invoice.id, invoice_date=discharge)
                _pay(session, clerk, rng, invoice.id, invoice.total, discharge)


def _supplier_bills(session: Session, accountant: Actor, finance: Actor) -> None:
    rng = random.Random(SEED + 2)
    vendors = {v.code: v for v in session.scalars(select(Vendor)).all()}
    depts = {d.code: d.id for d in session.scalars(select(Department)).all()}
    for month in _months():
        bill_date = min(_month_end(month), LAST_DAY)
        for code, (account, splits, desc) in MONTHLY_BILLS.items():
            vendor = vendors[code]
            wobble = D(rng.randint(-60, 60)) / 1000  # +/- 6% month to month
            lines = [
                APLine(
                    f"{desc}, {month:%B %Y}",
                    posting.account_id(session, account),
                    D(1),
                    (D(amount) * (1 + wobble)).quantize(D("0.01")),
                    depts[dept],
                )
                for dept, amount in splits
            ]
            bill = ap.create_bill(
                session,
                accountant,
                vendor_id=vendor.id,
                vendor_invoice_number=f"{code}-{month:%Y%m}",
                bill_date=bill_date,
                due_date=None,
                purchase_order_id=None,
                lines=lines,
                notes="Monthly account",
            )
            ap.submit_bill(session, accountant, bill.id)
            if bill.status == "pending_approval":
                approval = session.scalars(
                    select(Approval).where(
                        Approval.kind == "vendor_bill", Approval.entity_id == bill.id
                    )
                ).one()
                approvals.decide(
                    session, finance, approval.id, approve=True, note="Monthly account"
                )
            pay_on = bill_date + timedelta(days=vendor.payment_terms_days)
            if pay_on <= LAST_DAY:
                ap.pay_bill(
                    session,
                    accountant,
                    bill.id,
                    amount=None,
                    paid_on=pay_on,
                    method="bank_transfer",
                    reference=f"RUN-{pay_on.isoformat()}",
                )


def _depreciation(session: Session, accountant: Actor, finance: Actor) -> None:
    for month in _months()[:-1]:  # through October; November is not over
        entry = ledger.create_manual_entry(
            session,
            accountant,
            entry_date=_month_end(month),
            memo=f"Depreciation {month:%B %Y}",
            lines=[
                LineInput(
                    posting.account_id(session, "5600"),
                    debit=DEPRECIATION,
                    description="Equipment and buildings, straight line",
                ),  # fmt: skip
                LineInput(
                    posting.account_id(session, "1590"),
                    credit=DEPRECIATION,
                    description="Accumulated depreciation",
                ),  # fmt: skip
            ],
            approval_threshold=approvals.threshold(session, "manual_journal"),
        )
        approval = session.scalars(
            select(Approval).where(
                Approval.kind == "manual_journal", Approval.entity_id == entry.id
            )
        ).first()
        if approval is not None:
            approvals.decide(session, finance, approval.id, approve=True, note="Standard schedule")


def _anomalies(session: Session, clerk: Actor, accountant: Actor) -> None:
    services = {s.code: s.id for s in session.scalars(select(Service)).all()}
    icu = patients.create_patient(
        session,
        SYSTEM_ACTOR,
        first_name=MARKER_PATIENT[0],
        last_name=MARKER_PATIENT[1],
        date_of_birth=date(1951, 3, 14),
        sex="male",
        phone="555-0199",
        email="q.ashworth-vale@example.com",
        today=TODAY,
    )
    inpt = session.scalars(select(Department).where(Department.code == "INPT")).one()
    visit = patients.create_visit(
        session,
        clerk,
        patient_id=icu.id,
        department_id=inpt.id,
        visit_type="inpatient",
        admit_date=date(2026, 10, 2),
        discharge_date=date(2026, 10, 16),
        attending_physician="Dr. Okoro",
    )
    invoice = invoices.create_invoice(
        session,
        clerk,
        patient_id=icu.id,
        visit_id=visit.id,
        price_list_id=None,
        notes="Prolonged ICU stay; financial counselling referred",
        lines=[
            LineSpec(quantity=D(12), service_id=services["INPT-ICU"]),
            LineSpec(quantity=D(14), service_id=services["INPT-NURS"]),
            LineSpec(quantity=D(2), service_id=services["INPT-BED"]),
            LineSpec(quantity=D(4), service_id=services["RAD-CT-HEAD"]),
            LineSpec(quantity=D(30), service_id=services["PHAR-IVFL"]),
        ],
    )
    invoices.issue_invoice(session, clerk, invoice.id, invoice_date=date(2026, 10, 16))
    ledger.create_manual_entry(
        session,
        accountant,
        entry_date=date(2026, 11, 20),
        memo="Suspense clearing adjustment (supporting documents to follow)",
        lines=[
            LineInput(
                posting.account_id(session, "5900"),
                debit=D("48500.00"),
                description="Clear suspense to G&A",
            ),  # fmt: skip
            LineInput(
                posting.account_id(session, "2400"),
                credit=D("48500.00"),
                description="Accrued expenses",
            ),  # fmt: skip
        ],
        approval_threshold=approvals.threshold(session, "manual_journal"),
    )


def _close_periods(session: Session, accountant: Actor) -> None:
    to_close = session.scalars(
        select(FiscalPeriod)
        .where(FiscalPeriod.status == PeriodStatus.OPEN, FiscalPeriod.end_date <= CLOSE_THROUGH)
        .order_by(FiscalPeriod.start_date)
    ).all()
    for period in to_close:
        periods.close_period(session, accountant, period.id)


def seed_activity(session: Session) -> None:
    exists = session.scalar(
        select(func.count(Patient.id)).where(
            Patient.first_name == MARKER_PATIENT[0], Patient.last_name == MARKER_PATIENT[1]
        )
    )
    if exists:
        return
    clerk = _user(session, "billing")
    accountant, finance = _user(session, "accountant"), _user(session, "finance")
    people = list(session.scalars(select(Patient).order_by(Patient.id)).all()) + _new_patients(
        session
    )
    _encounters(session, clerk, people)
    _supplier_bills(session, accountant, finance)
    _depreciation(session, accountant, finance)
    _anomalies(session, clerk, accountant)
    ar.run_dunning(session, SYSTEM_ACTOR, as_of=TODAY)
    budgets.check_alerts(session, SYSTEM_ACTOR, as_of=date(2026, 10, 31))
    _close_periods(session, accountant)
