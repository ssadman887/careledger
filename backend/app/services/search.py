"""Global search across records the actor is allowed to read (authorization per group).

Each group is a small case-insensitive query (ILIKE on numbers, names and codes) limited to a
few rows; results carry a link to the record's page.
"""

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session

from app.models.ap import PurchaseOrder, Vendor, VendorBill
from app.models.billing import Invoice
from app.models.identity import RoleName, User
from app.models.insurance import Claim, Insurer
from app.models.ledger import Account, JournalEntry
from app.models.patients import Patient
from app.models.payroll import Employee
from app.services.audit import Actor

R = RoleName
PER_GROUP = 5
MIN_LENGTH = 2


@dataclass(frozen=True)
class Hit:
    id: int
    title: str
    subtitle: str
    href: str


@dataclass(frozen=True)
class Group:
    type: str
    label: str
    hits: list[Hit]


def _st(status: str) -> str:
    return status.replace("_", " ")


def _like(q: str) -> str:
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped.lower()}%"


def _patients(session: Session, like: str) -> list[Hit]:
    name = func.lower(Patient.first_name + " " + Patient.last_name)
    rows = session.scalars(
        select(Patient)
        .where(Patient.deleted_at.is_(None))
        .where(or_(name.like(like, escape="\\"), func.lower(Patient.mrn).like(like, escape="\\")))
        .order_by(Patient.last_name, Patient.first_name)
        .limit(PER_GROUP)
    ).all()
    return [
        Hit(p.id, p.full_name, f"MRN {p.mrn} · born {p.date_of_birth}", f"/patients/{p.id}")
        for p in rows
    ]


def _invoices(session: Session, like: str) -> list[Hit]:
    name = func.lower(Patient.first_name + " " + Patient.last_name)
    rows = session.scalars(
        select(Invoice)
        .join(Patient, Patient.id == Invoice.patient_id)
        .where(
            or_(
                func.lower(Invoice.invoice_number).like(like, escape="\\"),
                name.like(like, escape="\\"),
            )
        )
        .order_by(Invoice.id.desc())
        .limit(PER_GROUP)
    ).all()
    return [
        Hit(i.id, i.invoice_number, f"{i.patient.full_name} · {_st(i.status)} · {i.total:.2f}",
            f"/invoices/{i.id}")
        for i in rows
    ]  # fmt: skip


def _claims(session: Session, like: str) -> list[Hit]:
    rows = session.execute(
        select(Claim, Insurer.name)
        .join(Insurer, Insurer.id == Claim.insurer_id)
        .where(func.lower(Claim.claim_number).like(like, escape="\\"))
        .order_by(Claim.id.desc())
        .limit(PER_GROUP)
    ).all()
    return [
        Hit(c.id, c.claim_number, f"{insurer} · {_st(c.status)} · {c.insurer_amount:.2f}",
            f"/claims/{c.id}")
        for c, insurer in rows
    ]  # fmt: skip


def _journal(session: Session, like: str) -> list[Hit]:
    rows = session.scalars(
        select(JournalEntry)
        .where(
            or_(
                func.lower(JournalEntry.entry_number).like(like, escape="\\"),
                func.lower(JournalEntry.memo).like(like, escape="\\"),
            )
        )
        .order_by(JournalEntry.id.desc())
        .limit(PER_GROUP)
    ).all()
    return [
        Hit(e.id, e.entry_number, f"{e.entry_date} · {e.memo[:80]}", f"/journal/{e.id}")
        for e in rows
    ]


def _accounts(session: Session, like: str) -> list[Hit]:
    rows = session.scalars(
        select(Account)
        .where(
            or_(
                func.lower(Account.code).like(like, escape="\\"),
                func.lower(Account.name).like(like, escape="\\"),
            )
        )
        .order_by(Account.code)
        .limit(PER_GROUP)
    ).all()
    return [Hit(a.id, f"{a.code} {a.name}", a.type, f"/accounts?focus={a.id}") for a in rows]


def _payables(session: Session, like: str) -> list[Hit]:
    vendors = session.scalars(
        select(Vendor)
        .where(
            or_(
                func.lower(Vendor.name).like(like, escape="\\"),
                func.lower(Vendor.code).like(like, escape="\\"),
            )
        )
        .order_by(Vendor.name)
        .limit(PER_GROUP)
    ).all()
    bills = session.scalars(
        select(VendorBill)
        .where(
            or_(
                func.lower(VendorBill.bill_number).like(like, escape="\\"),
                func.lower(VendorBill.vendor_invoice_number).like(like, escape="\\"),
            )
        )
        .order_by(VendorBill.id.desc())
        .limit(PER_GROUP)
    ).all()
    pos = session.scalars(
        select(PurchaseOrder)
        .where(func.lower(PurchaseOrder.po_number).like(like, escape="\\"))
        .order_by(PurchaseOrder.id.desc())
        .limit(PER_GROUP)
    ).all()
    hits = [Hit(v.id, v.name, f"Vendor {v.code}", "/payables?tab=vendors") for v in vendors]
    hits += [
        Hit(b.id, b.bill_number, f"{b.vendor.name} #{b.vendor_invoice_number} · {_st(b.status)}",
            f"/payables/bills/{b.id}")
        for b in bills
    ]  # fmt: skip
    hits += [
        Hit(p.id, p.po_number, f"{p.vendor.name} · {p.status}", f"/payables/purchase-orders/{p.id}")
        for p in pos
    ]
    return hits[:PER_GROUP]


def _employees(session: Session, like: str) -> list[Hit]:
    name = func.lower(Employee.first_name + " " + Employee.last_name)
    rows = session.scalars(
        select(Employee)
        .where(
            or_(
                name.like(like, escape="\\"),
                func.lower(Employee.employee_number).like(like, escape="\\"),
                func.lower(Employee.position).like(like, escape="\\"),
            )
        )
        .order_by(Employee.last_name)
        .limit(PER_GROUP)
    ).all()
    return [
        Hit(e.id, e.full_name, f"{e.employee_number} · {e.position} · {e.department.name}",
            f"/payroll?tab=employees&q={e.employee_number}")
        for e in rows
    ]  # fmt: skip


def _users(session: Session, like: str) -> list[Hit]:
    rows = session.scalars(
        select(User)
        .where(User.deleted_at.is_(None))
        .where(
            or_(
                func.lower(User.full_name).like(like, escape="\\"),
                func.lower(User.username).like(like, escape="\\"),
                func.lower(cast(User.email, String)).like(like, escape="\\"),
            )
        )
        .order_by(User.username)
        .limit(PER_GROUP)
    ).all()
    return [Hit(u.id, u.full_name, f"{u.username} · {u.email}", "/admin/users") for u in rows]


Searcher = Callable[[Session, str], list[Hit]]
_LEDGER = frozenset({R.ACCOUNTANT, R.FINANCE_MANAGER, R.AUDITOR})
_PATIENT = frozenset({R.BILLING_CLERK, R.INSURANCE_OFFICER, R.FINANCE_MANAGER, R.AUDITOR})
GROUPS: tuple[tuple[str, str, frozenset[str], Searcher], ...] = (
    ("patient", "Patients", _PATIENT, _patients),
    ("invoice", "Invoices", _PATIENT | {R.ACCOUNTANT}, _invoices),
    ("claim", "Claims", _PATIENT, _claims),
    ("journal_entry", "Journal entries", _LEDGER, _journal),
    ("account", "Accounts", _LEDGER | {R.ADMIN}, _accounts),
    ("payables", "Payables", _LEDGER, _payables),
    ("employee", "Employees", _LEDGER, _employees),
    ("user", "Users", frozenset({R.ADMIN}), _users),
)


def search(session: Session, actor: Actor, q: str) -> list[Group]:
    q = q.strip()
    if len(q) < MIN_LENGTH:
        return []
    like = _like(q)
    groups = []
    for kind, label, roles, fn in GROUPS:
        if not actor.roles & roles:
            continue
        hits = fn(session, like)
        if hits:
            groups.append(Group(kind, label, hits))
    return groups
