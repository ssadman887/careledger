"""Synthetic patients, visits, service catalog, price list and sample billing activity.

Deterministic (fixed seeds, local RNG instances) and idempotent (each block checks for existing
rows first). Names come from Faker; phone numbers use the fictional 555-01xx range and emails
the reserved example.com domain, so nothing can collide with real people.
"""

import random
from datetime import date, timedelta
from decimal import Decimal

from faker import Faker
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.billing import Invoice
from app.models.catalog import PriceList, Service
from app.models.identity import User
from app.models.org import Department
from app.models.patients import Patient, Visit
from app.services import catalog, invoices, patients, payments
from app.services.audit import SYSTEM_ACTOR, Actor
from app.services.auth import actor_for
from app.services.invoices import LineSpec

SEED = 20260101
D = Decimal

# (code, name, department code, price from 2026-01-01, tax rate, price from 2026-07-01 or None)
SERVICES: tuple[tuple[str, str, str, str, str, str | None], ...] = (
    ("ER-TRIAGE", "Emergency triage assessment", "EMER", "180.00", "0", "195.00"),
    ("ER-L3", "Emergency visit, level 3", "EMER", "420.00", "0", None),
    ("ER-L5", "Emergency visit, level 5 (critical)", "EMER", "1450.00", "0", None),
    ("ER-SUTURE", "Laceration repair", "EMER", "260.00", "0", None),
    ("RAD-XR-CHEST", "Chest X-ray, 2 views", "RAD", "95.00", "0", "105.00"),
    ("RAD-CT-HEAD", "CT head without contrast", "RAD", "780.00", "0", None),
    ("RAD-MRI-KNEE", "MRI knee", "RAD", "1150.00", "0", None),
    ("RAD-US-ABD", "Ultrasound abdomen", "RAD", "340.00", "0", None),
    ("LAB-CBC", "Complete blood count", "LAB", "38.00", "0", None),
    ("LAB-BMP", "Basic metabolic panel", "LAB", "52.00", "0", None),
    ("LAB-LIPID", "Lipid panel", "LAB", "44.00", "0", None),
    ("LAB-CULT", "Blood culture", "LAB", "86.00", "0", "92.00"),
    ("SURG-APPY", "Laparoscopic appendectomy", "SURG", "8900.00", "0", None),
    ("SURG-CHOLE", "Laparoscopic cholecystectomy", "SURG", "10400.00", "0", None),
    ("SURG-OR-HR", "Operating room time (per hour)", "SURG", "2100.00", "0", None),
    ("SURG-ANES", "Anesthesia services", "SURG", "1350.00", "0", None),
    ("INPT-BED", "Inpatient bed day, general ward", "INPT", "1250.00", "0", None),
    ("INPT-ICU", "ICU bed day", "INPT", "4200.00", "0", None),
    ("INPT-NURS", "Specialised nursing (per day)", "INPT", "380.00", "0", None),
    ("OPD-NEW", "Outpatient consultation, new patient", "OPD", "210.00", "0", None),
    ("OPD-FU", "Outpatient follow-up", "OPD", "120.00", "0", None),
    ("OPD-PHYSIO", "Physiotherapy session", "OPD", "95.00", "0", None),
    ("PHAR-ABX", "Antibiotic course (dispensed)", "PHAR", "48.00", "0.0500", None),
    ("PHAR-ANALG", "Analgesics (dispensed)", "PHAR", "18.00", "0.0500", None),
    ("PHAR-IVFL", "IV fluids (per bag)", "PHAR", "26.00", "0.0500", None),
    ("PHAR-INSUL", "Insulin pen", "PHAR", "62.00", "0.0500", None),
)

PRICE_CHANGE = date(2026, 7, 1)
VISIT_WINDOW = (date(2026, 8, 1), date(2026, 11, 20))
PATIENT_COUNT = 40
VISIT_TYPES = {"EMER": "emergency", "INPT": "inpatient", "SURG": "inpatient"}


def seed_catalog(session: Session) -> PriceList:
    price_list = session.scalars(select(PriceList).where(PriceList.code == "STD-2026")).first()
    if price_list is None:
        price_list = catalog.create_price_list(
            session, SYSTEM_ACTOR, code="STD-2026", name="Standard tariff 2026", is_default=True
        )
    depts = {d.code: d for d in session.scalars(select(Department)).all()}
    existing = {s.code for s in session.scalars(select(Service)).all()}
    for code, name, dept, price, tax, new_price in SERVICES:
        if code in existing:
            continue
        service = catalog.create_service(
            session,
            SYSTEM_ACTOR,
            code=code,
            name=name,
            department_id=depts[dept].id,
            tax_rate=D(tax),
        )
        catalog.set_price(
            session,
            SYSTEM_ACTOR,
            price_list_id=price_list.id,
            service_id=service.id,
            unit_price=D(price),
            effective_from=date(2026, 1, 1),
        )
        if new_price:
            catalog.set_price(
                session,
                SYSTEM_ACTOR,
                price_list_id=price_list.id,
                service_id=service.id,
                unit_price=D(new_price),
                effective_from=PRICE_CHANGE,
            )
    return price_list


def seed_patients(session: Session) -> list[Patient]:
    count = session.scalar(select(func.count(Patient.id))) or 0
    if count >= PATIENT_COUNT:
        return list(session.scalars(select(Patient).order_by(Patient.id)).all())
    fake = Faker("en_US")
    fake.seed_instance(SEED)
    rng = random.Random(SEED)
    created: list[Patient] = []
    for n in range(PATIENT_COUNT):
        sex = rng.choice(["female", "male"])
        first = fake.first_name_female() if sex == "female" else fake.first_name_male()
        last = fake.last_name()
        dob = date(1940, 1, 1) + timedelta(days=rng.randint(0, 80 * 365))
        if n < count:
            continue  # keep the RNG stream identical on partial re-runs
        created.append(
            patients.create_patient(
                session,
                SYSTEM_ACTOR,
                first_name=first,
                last_name=last,
                date_of_birth=dob,
                sex=sex,
                phone=f"555-01{n:02d}",
                email=f"{first}.{last}@example.com".lower(),
                today=date(2026, 11, 25),
            )
        )
    return list(session.scalars(select(Patient).order_by(Patient.id)).all())


def seed_visits(session: Session, people: list[Patient]) -> list[Visit]:
    if session.scalar(select(func.count(Visit.id))):
        return list(session.scalars(select(Visit).order_by(Visit.id)).all())
    fake = Faker("en_US")
    fake.seed_instance(SEED + 1)
    rng = random.Random(SEED + 1)
    depts = [
        d
        for d in session.scalars(select(Department).order_by(Department.code)).all()
        if d.code != "ADMIN"
    ]
    physicians = [f"Dr. {fake.last_name()}" for _ in range(10)]
    span = (VISIT_WINDOW[1] - VISIT_WINDOW[0]).days
    for patient in people:
        for _ in range(rng.choice([1, 1, 2])):
            dept = rng.choice(depts)
            admit = VISIT_WINDOW[0] + timedelta(days=rng.randint(0, span))
            stay = rng.randint(1, 5) if VISIT_TYPES.get(dept.code) == "inpatient" else 0
            patients.create_visit(
                session,
                SYSTEM_ACTOR,
                patient_id=patient.id,
                department_id=dept.id,
                visit_type=VISIT_TYPES.get(dept.code, "outpatient"),
                admit_date=admit,
                discharge_date=min(admit + timedelta(days=stay), VISIT_WINDOW[1]),
                attending_physician=rng.choice(physicians),
            )
    return list(session.scalars(select(Visit).order_by(Visit.admit_date, Visit.id)).all())


def _user(session: Session, username: str) -> Actor:
    user = session.scalars(select(User).where(User.username == username)).one()
    return actor_for(user)


def seed_billing_activity(session: Session, visits: list[Visit]) -> None:
    """A spread of invoices in every state, payments, deposits and refunds (one pending)."""
    if session.scalar(select(func.count(Invoice.id))):
        return
    clerk, finance = _user(session, "billing"), _user(session, "finance")
    rng = random.Random(SEED + 2)
    services = {s.code: s for s in session.scalars(select(Service)).all()}
    by_dept: dict[str, list[Service]] = {}
    for s in services.values():
        by_dept.setdefault(s.department.code, []).append(s)
    for s_list in by_dept.values():
        s_list.sort(key=lambda s: s.code)

    for i, visit in enumerate(visits[:30]):
        dept_code = visit.department.code
        picks = rng.sample(by_dept[dept_code], k=min(len(by_dept[dept_code]), rng.randint(1, 3)))
        lines = [LineSpec(quantity=D(rng.choice([1, 1, 1, 2])), service_id=s.id) for s in picks]
        if rng.random() < 0.5:
            lab = rng.choice(by_dept["LAB"])
            lines.append(LineSpec(quantity=D(1), service_id=lab.id))
        if rng.random() < 0.4:
            drug = rng.choice(by_dept["PHAR"])
            lines.append(LineSpec(quantity=D(rng.randint(1, 3)), service_id=drug.id))
        if i % 7 == 3:
            lines[0] = LineSpec(
                quantity=lines[0].quantity, service_id=lines[0].service_id, discount_percent=D("10")
            )
        invoice = invoices.create_invoice(
            session,
            clerk,
            patient_id=visit.patient_id,
            visit_id=visit.id,
            price_list_id=None,
            notes="",
            lines=lines,
        )
        if i % 10 == 9:
            continue  # leave as draft
        issued_on = visit.discharge_date or visit.admit_date
        invoices.issue_invoice(session, clerk, invoice.id, invoice_date=issued_on)
        if i % 10 == 8:
            invoices.void_invoice(session, clerk, invoice.id, "Duplicate charge entered")
            continue
        pay_on = min(issued_on + timedelta(days=rng.randint(0, 20)), date(2026, 11, 24))
        method = rng.choice(["cash", "card", "bank_transfer"])
        reference = (
            f"{rng.randint(0, 9999):04d}"
            if method == "card"
            else f"TRX-{rng.randint(100000, 999999)}"
            if method == "bank_transfer"
            else ""
        )
        if i % 3 == 0:
            payments.record_payment(
                session,
                clerk,
                invoice_id=invoice.id,
                method=method,
                amount=invoice.total,
                received_on=pay_on,
                reference=reference,
                notes="",
            )
        elif i % 3 == 1:
            part = (invoice.total * D("0.4")).quantize(D("0.01"))
            payments.record_payment(
                session,
                clerk,
                invoice_id=invoice.id,
                method=method,
                amount=part,
                received_on=pay_on,
                reference=reference,
                notes="Partial payment",
            )

    # Deposits: one partly applied, one waiting.
    people = list(session.scalars(select(Patient).order_by(Patient.id)).all())
    dep = payments.record_deposit(
        session,
        clerk,
        patient_id=people[0].id,
        method="cash",
        amount=D("500.00"),
        received_on=date(2026, 11, 2),
        reference="",
        notes="Pre-admission deposit",
    )
    payments.record_deposit(
        session,
        clerk,
        patient_id=people[1].id,
        method="card",
        amount=D("1200.00"),
        received_on=date(2026, 11, 10),
        reference="4242",
        notes="Surgery deposit",
    )
    open_invoice = session.scalars(
        select(Invoice)
        .where(
            Invoice.patient_id == dep.patient_id, Invoice.status.in_(["issued", "partially_paid"])
        )
        .order_by(Invoice.id)
    ).first()
    if open_invoice is not None:
        payments.apply_deposit(
            session,
            clerk,
            invoice_id=open_invoice.id,
            amount=min(D("200.00"), open_invoice.balance_due),
            applied_on=date(2026, 11, 12),
        )

    # Refunds: a small one completes immediately; a large one waits for approval.
    paid = list(
        session.scalars(select(Invoice).where(Invoice.status == "paid").order_by(Invoice.id)).all()
    )
    from app.repositories import billing as billing_repo

    threshold = D("500.00")
    if paid:
        first_payment = billing_repo.payments_for_invoice(session, paid[0].id)[0]
        payments.request_refund(
            session,
            clerk,
            payment_id=first_payment.id,
            amount=min(D("25.00"), first_payment.amount),
            reason="Duplicate lab charge",
            approval_threshold=threshold,
            refunded_on=date(2026, 11, 20),
        )
    big = next(
        (
            p
            for inv in paid
            for p in billing_repo.payments_for_invoice(session, inv.id)
            if p.amount > threshold + D("100")
        ),
        None,
    )
    if big is not None:
        payments.request_refund(
            session,
            clerk,
            payment_id=big.id,
            amount=threshold + D("100"),
            reason="Procedure cancelled; patient overcharged",
            approval_threshold=threshold,
        )
    _ = finance  # approval of the pending refund is left for the demo


def seed_billing(session: Session) -> None:
    seed_catalog(session)
    people = seed_patients(session)
    visits = seed_visits(session, people)
    seed_billing_activity(session, visits)
