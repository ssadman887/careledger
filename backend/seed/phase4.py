"""Approval policies, vendors, purchase orders, vendor bills/payments, write-offs and dunning.

Deterministic and idempotent. Leaves pending approvals for the demo: a write-off (demo step 5)
and a vendor bill with a three-way-match variance.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.ap import Vendor
from app.models.ar import DunningNotice, WriteOff
from app.models.billing import Invoice
from app.models.identity import User
from app.models.ledger import Account
from app.services import ap, approvals, ar
from app.services.ap import APLine
from app.services.audit import SYSTEM_ACTOR, Actor
from app.services.auth import actor_for

D = Decimal

# (code, name, email, default expense account, terms, bank reference)
VENDORS: tuple[tuple[str, str, str, str, int, str], ...] = (
    (
        "MEDSUP",
        "Northgate Medical Supplies",
        "orders@northgate.example",
        "5200",
        30,
        "GB00-NGMS-448812",
    ),
    (
        "PHARMA",
        "Brightwell Pharmaceuticals",
        "ar@brightwell.example",
        "5210",
        45,
        "GB00-BWPH-210377",
    ),
    (
        "UTIL",
        "Riverside Power & Water",
        "billing@riverside.example",
        "5300",
        15,
        "GB00-RPWU-993104",
    ),
    (
        "BIOMED",
        "Helix Biomedical Services",
        "service@helix.example",
        "5500",
        30,
        "GB00-HXBS-551920",
    ),
    (
        "CLEAN",
        "Clearview Facility Services",
        "accounts@clearview.example",
        "5310",
        30,
        "GB00-CVFS-118253",
    ),
    ("LAWCO", "Ashby & Partners LLP", "fees@ashby.example", "5800", 30, "GB00-ASPL-660471"),
)


def seed_approval_policies(session: Session) -> None:
    approvals.ensure_policies(session)


def _user(session: Session, username: str) -> Actor:
    return actor_for(session.scalars(select(User).where(User.username == username)).one())


def seed_payables(session: Session) -> None:
    if session.scalar(select(func.count(Vendor.id))):
        return
    accountant, finance = _user(session, "accountant"), _user(session, "finance")
    accounts = {a.code: a.id for a in session.scalars(select(Account)).all()}
    vendors = {}
    for code, name, email, expense, terms, bank in VENDORS:
        vendors[code] = ap.create_vendor(
            session,
            accountant,
            code=code,
            name=name,
            email=email,
            tax_id=f"TAX-{code}-01",
            bank_reference=bank,
            payment_terms_days=terms,
            default_expense_account_id=accounts[expense],
        )

    # 1. Supplies PO -> received -> matched bill (auto-approved) -> paid.
    po1 = ap.create_po(
        session,
        accountant,
        vendor_id=vendors["MEDSUP"].id,
        order_date=date(2026, 9, 2),
        expected_date=date(2026, 9, 9),
        notes="",
        lines=[
            APLine("Nitrile gloves (case of 1000)", accounts["5200"], D(20), D("42.50")),
            APLine("Surgical masks (box of 50)", accounts["5200"], D(60), D("9.80")),
        ],
    )
    ap.issue_po(session, accountant, po1.id)
    ap.receive_po(session, accountant, po1.id, received_on=date(2026, 9, 8))
    bill1 = ap.create_bill(
        session,
        accountant,
        vendor_id=vendors["MEDSUP"].id,
        vendor_invoice_number="NG-55102",
        bill_date=date(2026, 9, 9),
        due_date=None,
        purchase_order_id=po1.id,
        lines=None,
        notes="",
    )
    ap.submit_bill(session, accountant, bill1.id)
    ap.pay_bill(
        session,
        accountant,
        bill1.id,
        amount=None,
        paid_on=date(2026, 10, 5),
        method="bank_transfer",
        reference="BACS-0915",
    )

    # 2. Pharmaceuticals above threshold -> approved by finance -> scheduled for payment.
    po2 = ap.create_po(
        session,
        accountant,
        vendor_id=vendors["PHARMA"].id,
        order_date=date(2026, 10, 1),
        expected_date=None,
        notes="",
        lines=[
            APLine("Antibiotics restock", accounts["5210"], D(1), D("6400.00")),
        ],
    )
    ap.issue_po(session, accountant, po2.id)
    ap.receive_po(session, accountant, po2.id, received_on=date(2026, 10, 6))
    bill2 = ap.create_bill(
        session,
        accountant,
        vendor_id=vendors["PHARMA"].id,
        vendor_invoice_number="BW-2026-1187",
        bill_date=date(2026, 10, 7),
        due_date=None,
        purchase_order_id=po2.id,
        lines=None,
        notes="",
    )
    ap.submit_bill(session, accountant, bill2.id)
    ap.approve_bill(session, finance, bill2.id, "Within formulary budget")
    ap.schedule_payment(session, accountant, bill2.id, date(2026, 11, 21))

    # 3. Utilities without a PO, under threshold -> auto-approved, partially paid.
    bill3 = ap.create_bill(
        session,
        accountant,
        vendor_id=vendors["UTIL"].id,
        vendor_invoice_number="RPW-OCT-26",
        bill_date=date(2026, 10, 31),
        due_date=None,
        purchase_order_id=None,
        notes="October utilities",
        lines=[
            APLine("Electricity October", accounts["5300"], D(1), D("2860.40")),
            APLine("Water October", accounts["5300"], D(1), D("640.10")),
        ],
    )
    ap.submit_bill(session, accountant, bill3.id)
    ap.pay_bill(
        session,
        accountant,
        bill3.id,
        amount=D("1500.00"),
        paid_on=date(2026, 11, 10),
        method="bank_transfer",
        reference="BACS-1110",
    )

    # 4. Biomedical service: billed more than the PO -> variance -> pending approval (demo).
    po4 = ap.create_po(
        session,
        accountant,
        vendor_id=vendors["BIOMED"].id,
        order_date=date(2026, 11, 2),
        expected_date=None,
        notes="",
        lines=[
            APLine("Quarterly ventilator maintenance", accounts["5500"], D(1), D("1800.00")),
        ],
    )
    ap.issue_po(session, accountant, po4.id)
    ap.receive_po(session, accountant, po4.id, received_on=date(2026, 11, 12))
    bill4 = ap.create_bill(
        session,
        accountant,
        vendor_id=vendors["BIOMED"].id,
        vendor_invoice_number="HX-90233",
        bill_date=date(2026, 11, 14),
        due_date=None,
        purchase_order_id=po4.id,
        notes="Includes call-out fee",
        lines=[
            APLine("Quarterly ventilator maintenance", accounts["5500"], D(1), D("1800.00")),
            APLine("Emergency call-out", accounts["5500"], D(1), D("240.00")),
        ],
    )
    ap.submit_bill(session, accountant, bill4.id)

    # 5. An issued (not yet received) PO and a draft bill, for the worklists.
    po5 = ap.create_po(
        session,
        accountant,
        vendor_id=vendors["CLEAN"].id,
        order_date=date(2026, 11, 18),
        expected_date=date(2026, 12, 1),
        notes="",
        lines=[APLine("Deep clean, theatres", accounts["5310"], D(1), D("3200.00"))],
    )
    ap.issue_po(session, accountant, po5.id)
    ap.create_bill(
        session,
        accountant,
        vendor_id=vendors["LAWCO"].id,
        vendor_invoice_number="AP-7781",
        bill_date=date(2026, 11, 20),
        due_date=None,
        purchase_order_id=None,
        notes="Contract review",
        lines=[APLine("Supplier contract review", accounts["5800"], D(6), D("275.00"))],
    )


def seed_receivables(session: Session) -> None:
    """A pending write-off for the oldest unpaid patient balance and dunning notices."""
    clerk = _user(session, "billing")
    if not session.scalar(select(func.count(WriteOff.id))):
        oldest = [
            inv
            for inv in session.scalars(
                select(Invoice)
                .where(Invoice.status.in_(["issued", "partially_paid"]))
                .order_by(Invoice.invoice_date, Invoice.id)
            ).all()
            if inv.patient_due > 0
        ]
        if oldest:
            target = oldest[0]
            ar.request_write_off(
                session,
                clerk,
                invoice_id=target.id,
                amount=target.patient_due,
                reason="Patient unreachable after three notices; uncollectible",
            )
    if not session.scalar(select(func.count(DunningNotice.id))):
        ar.run_dunning(session, SYSTEM_ACTOR, as_of=date(2026, 11, 25))


def seed_phase4(session: Session) -> None:
    seed_approval_policies(session)
    seed_payables(session)
    seed_receivables(session)
