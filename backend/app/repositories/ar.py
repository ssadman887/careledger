"""AR queries: aging (SQL aggregates), dunning candidates, write-offs, notices."""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, func, select, text
from sqlalchemy.orm import Session

from app.core.pagination import PageParams
from app.models.ar import DunningNotice, WriteOff
from app.models.billing import Invoice
from app.repositories.billing import _page

OPEN_INVOICE = ("issued", "partially_paid")

# (label, lower bound in days, upper bound in days or None). Boundaries are inclusive.
BUCKETS: tuple[tuple[str, int, int | None], ...] = (
    ("0-30", 0, 30),
    ("31-60", 31, 60),
    ("61-90", 61, 90),
    ("90+", 91, None),
)


def patient_due_expr() -> ColumnElement[Decimal]:
    return Invoice.total - Invoice.amount_paid - Invoice.adjusted_amount - Invoice.insurance_pending


# ---------------------------------------------------------------- ledger-derived aging
#
# Aging is computed from the general ledger, not from current document balances: every posted
# line on the receivable account dated on/before `as_of` is traced to its invoice (AR-Patients)
# or claim (AR-Insurers) through the entry's source. Reversals are traced through the entry they
# reverse. Lines that cannot be traced (e.g. manual journals) land in an "unallocated" row, so the
# report total always equals the GL balance of the account on `as_of`.

_RESOLVED_LINES = """
    WITH lines AS (
        SELECT l.debit - l.credit AS amount, e.source_type, e.source_id, e.reversal_of_id
        FROM journal_lines l
        JOIN journal_entries e ON e.id = l.entry_id
        JOIN accounts a ON a.id = l.account_id
        WHERE a.code = :account AND e.status = 'posted' AND e.entry_date <= :as_of
    ), resolved AS (
        SELECT lines.amount,
               COALESCE(o.source_type, lines.source_type) AS st,
               COALESCE(o.source_id, lines.source_id) AS sid
        FROM lines
        LEFT JOIN journal_entries o
               ON lines.source_type = 'reversal' AND o.id = lines.reversal_of_id
    )
"""

_PATIENT_SQL = (
    _RESOLVED_LINES
    + """
    , by_invoice AS (
        SELECT COALESCE(i.id, p.invoice_id, rp.invoice_id, w.invoice_id, c.invoice_id)
               AS invoice_id,
               SUM(r.amount) AS balance
        FROM resolved r
        LEFT JOIN invoices i    ON r.st = 'invoice'   AND i.id::text = r.sid
        LEFT JOIN payments p    ON r.st = 'payment'   AND p.id::text = r.sid
        LEFT JOIN refunds rf    ON r.st = 'refund'    AND rf.id::text = r.sid
        LEFT JOIN payments rp   ON rp.id = rf.payment_id
        LEFT JOIN write_offs w  ON r.st = 'write_off' AND w.id::text = r.sid
        LEFT JOIN claims c      ON r.st = 'claim'     AND c.id::text = r.sid
        GROUP BY 1
    )
    SELECT b.invoice_id, inv.patient_id,
           pt.first_name || ' ' || pt.last_name AS name, pt.mrn,
           (:as_of - inv.invoice_date) AS age, b.balance
    FROM by_invoice b
    LEFT JOIN invoices inv ON inv.id = b.invoice_id
    LEFT JOIN patients pt  ON pt.id = inv.patient_id
    WHERE b.balance <> 0
"""
)

_INSURER_SQL = (
    _RESOLVED_LINES
    + """
    , by_claim AS (
        SELECT c.id AS claim_id, SUM(r.amount) AS balance
        FROM resolved r
        LEFT JOIN claims c ON r.st = 'claim' AND c.id::text = r.sid
        GROUP BY 1
    )
    SELECT b.claim_id, c.insurer_id, ins.name, ins.code,
           (:as_of - COALESCE(te.entry_date, c.service_date)) AS age, b.balance
    FROM by_claim b
    LEFT JOIN claims c            ON c.id = b.claim_id
    LEFT JOIN insurers ins        ON ins.id = c.insurer_id
    LEFT JOIN journal_entries te  ON te.id = c.transfer_entry_id
    WHERE b.balance <> 0
"""
)

UNALLOCATED = (0, "Unallocated (manual journal entries)", "-")


def _group(rows: Sequence[Any]) -> list[tuple[int, str, str, list[Decimal]]]:
    """Group traced balances by party into the four buckets (python only arranges SQL rows)."""
    from app.services.ar import bucket_for  # bucket rule lives in the service layer

    labels = [label for label, _, _ in BUCKETS]
    parties: dict[int, tuple[str, str, dict[str, Decimal]]] = {}
    for _doc_id, party_id, name, code, age, balance in rows:
        key = int(party_id) if party_id is not None else UNALLOCATED[0]
        if key not in parties:
            label_name, label_code = (name, code) if party_id is not None else UNALLOCATED[1:]
            parties[key] = (label_name, label_code, dict.fromkeys(labels, Decimal("0.00")))
        bucket = bucket_for(int(age)) if age is not None else labels[0]
        parties[key][2][bucket] += Decimal(balance)
    out = [(pid, n, c, [b[label] for label in labels]) for pid, (n, c, b) in parties.items()]
    return sorted(out, key=lambda r: (r[0] == 0, -sum(r[3], Decimal("0"))))


def aging_by_patient(session: Session, as_of: date) -> list[tuple[int, str, str, list[Decimal]]]:
    rows = session.execute(text(_PATIENT_SQL), {"account": "1100", "as_of": as_of}).all()
    return _group(rows)


def aging_by_insurer(session: Session, as_of: date) -> list[tuple[int, str, str, list[Decimal]]]:
    rows = session.execute(text(_INSURER_SQL), {"account": "1110", "as_of": as_of}).all()
    return _group(rows)


def gl_balance(session: Session, account_code: str, as_of: date) -> Decimal:
    stmt = text(
        "SELECT COALESCE(SUM(l.debit - l.credit), 0) FROM journal_lines l "
        "JOIN journal_entries e ON e.id = l.entry_id JOIN accounts a ON a.id = l.account_id "
        "WHERE a.code = :code AND e.status = 'posted' AND e.entry_date <= :as_of"
    )
    return Decimal(session.scalar(stmt, {"code": account_code, "as_of": as_of}) or 0)


def dunning_candidates(session: Session, as_of: date) -> Sequence[Invoice]:
    due = patient_due_expr()
    stmt = (
        select(Invoice)
        .where(Invoice.status.in_(OPEN_INVOICE), Invoice.due_date < as_of, due > 0)
        .order_by(Invoice.due_date, Invoice.id)
    )
    return session.scalars(stmt).unique().all()


def notice_levels(session: Session, invoice_id: int) -> set[int]:
    stmt = select(DunningNotice.level).where(DunningNotice.invoice_id == invoice_id)
    return set(session.scalars(stmt).all())


def list_notices(
    session: Session, params: PageParams, *, patient_id: int | None, level: int | None
) -> tuple[Sequence[DunningNotice], int]:
    stmt = select(DunningNotice)
    if patient_id is not None:
        stmt = stmt.where(DunningNotice.patient_id == patient_id)
    if level is not None:
        stmt = stmt.where(DunningNotice.level == level)
    sorts = {"sent_at": DunningNotice.sent_at, "days_overdue": DunningNotice.days_overdue}
    return _page(session, stmt, params, sorts, "-sent_at", DunningNotice.id.desc())


def get_write_off(session: Session, write_off_id: int, *, lock: bool = False) -> WriteOff | None:
    if lock:
        stmt = select(WriteOff).where(WriteOff.id == write_off_id).with_for_update(of=WriteOff)
        return session.scalars(stmt).unique().first()
    return session.get(WriteOff, write_off_id)


def pending_write_off_total(session: Session, invoice_id: int) -> Decimal:
    stmt = select(func.coalesce(func.sum(WriteOff.amount), 0)).where(
        WriteOff.invoice_id == invoice_id, WriteOff.status == "pending_approval"
    )
    return Decimal(session.scalar(stmt) or 0)


def list_write_offs(
    session: Session, params: PageParams, *, status: str | None, invoice_id: int | None
) -> tuple[Sequence[WriteOff], int]:
    stmt = select(WriteOff)
    if status:
        stmt = stmt.where(WriteOff.status == status)
    if invoice_id is not None:
        stmt = stmt.where(WriteOff.invoice_id == invoice_id)
    sorts = {"created_at": WriteOff.created_at, "amount": WriteOff.amount}
    return _page(session, stmt, params, sorts, "-created_at", WriteOff.id.desc())
