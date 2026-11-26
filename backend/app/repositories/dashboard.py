"""Dashboard metrics. Every figure is one SQL aggregate (no Python loops over records)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

ZERO = Decimal("0.00")

# Posted ledger lines; every ledger metric starts from this.
_POSTED = """
FROM journal_lines l
JOIN journal_entries e ON e.id = l.entry_id AND e.status = 'posted'
JOIN accounts a ON a.id = l.account_id
"""


def _dec(value: object) -> Decimal:
    return Decimal(str(value)) if value is not None else ZERO


def balances(session: Session, codes: Sequence[str], as_of: date) -> dict[str, Decimal]:
    """Debit-minus-credit balance per account code as of a date."""
    rows = session.execute(
        text(
            "SELECT a.code, coalesce(sum(l.debit - l.credit), 0)"
            + _POSTED
            + "WHERE a.code = ANY(:codes) AND e.entry_date <= :as_of GROUP BY a.code"
        ),
        {"codes": list(codes), "as_of": as_of},
    ).all()
    out = dict.fromkeys(codes, ZERO)
    out.update({code: _dec(v) for code, v in rows})
    return out


@dataclass(frozen=True)
class PL:
    revenue: Decimal
    expenses: Decimal


def profit_and_loss(session: Session, start: date, end: date) -> PL:
    row = session.execute(
        text(
            "SELECT coalesce(sum(CASE WHEN a.type = 'revenue' THEN l.credit - l.debit END), 0),"
            " coalesce(sum(CASE WHEN a.type = 'expense' THEN l.debit - l.credit END), 0)"
            + _POSTED
            + "WHERE e.entry_date BETWEEN :start AND :end"
        ),
        {"start": start, "end": end},
    ).one()
    return PL(_dec(row[0]), _dec(row[1]))


@dataclass(frozen=True)
class MonthPL:
    month: date
    revenue: Decimal
    expenses: Decimal


def monthly_pl(session: Session, start: date, end: date) -> list[MonthPL]:
    """Revenue and expenses per calendar month, including months with no activity."""
    rows = session.execute(
        text(
            """
            WITH months AS (
              SELECT generate_series(date_trunc('month', CAST(:start AS date)),
                                     date_trunc('month', CAST(:end AS date)),
                                     interval '1 month')::date AS month
            ), totals AS (
              SELECT date_trunc('month', e.entry_date)::date AS month,
                     sum(CASE WHEN a.type = 'revenue' THEN l.credit - l.debit ELSE 0 END) AS rev,
                     sum(CASE WHEN a.type = 'expense' THEN l.debit - l.credit ELSE 0 END) AS exp
            """
            + _POSTED
            + """
              WHERE e.entry_date BETWEEN :start AND :end
              GROUP BY 1
            )
            SELECT m.month, coalesce(t.rev, 0), coalesce(t.exp, 0)
            FROM months m LEFT JOIN totals t ON t.month = m.month
            ORDER BY m.month
            """
        ),
        {"start": start, "end": end},
    ).all()
    return [MonthPL(m, _dec(r), _dec(x)) for m, r, x in rows]


def revenue_by_department(session: Session, start: date, end: date) -> list[tuple[str, Decimal]]:
    rows = session.execute(
        text(
            "SELECT coalesce(d.name, 'Discounts (no dept.)'),"
            " sum(l.credit - l.debit)"
            + _POSTED
            + "LEFT JOIN departments d ON d.id = l.department_id "
            "WHERE a.type = 'revenue' AND e.entry_date BETWEEN :start AND :end "
            "GROUP BY 1 HAVING sum(l.credit - l.debit) <> 0 ORDER BY 2 DESC"
        ),
        {"start": start, "end": end},
    ).all()
    return [(name, _dec(v)) for name, v in rows]


@dataclass(frozen=True)
class BudgetUse:
    budget_id: int
    department: str
    budget_ytd: Decimal
    actual_ytd: Decimal


def budget_utilisation(session: Session, year: int, through_month: int) -> list[BudgetUse]:
    """Expense budget vs actual, year to date, per active budget (department dimension)."""
    rows = session.execute(
        text(
            """
            WITH planned AS (
              SELECT b.id, sum(bl.amount) AS amount
              FROM budgets b
              JOIN budget_lines bl ON bl.budget_id = b.id
              JOIN accounts a ON a.id = bl.account_id AND a.type = 'expense'
              WHERE b.year = :year AND b.status = 'active' AND bl.month <= :through
              GROUP BY b.id
            ), actual AS (
              SELECT b.id, sum(l.debit - l.credit) AS amount
              FROM budgets b
              JOIN journal_lines l ON l.department_id = b.department_id
              JOIN journal_entries e ON e.id = l.entry_id AND e.status = 'posted'
              JOIN accounts a ON a.id = l.account_id AND a.type = 'expense'
              WHERE b.year = :year AND b.status = 'active'
                AND l.account_id IN (SELECT account_id FROM budget_lines WHERE budget_id = b.id)
                AND e.entry_date >= make_date(:year, 1, 1)
                AND e.entry_date < make_date(:year, 1, 1) + make_interval(months => :through)
              GROUP BY b.id
            )
            SELECT b.id, d.name, coalesce(p.amount, 0), coalesce(x.amount, 0)
            FROM budgets b
            JOIN departments d ON d.id = b.department_id
            LEFT JOIN planned p ON p.id = b.id
            LEFT JOIN actual x ON x.id = b.id
            WHERE b.year = :year AND b.status = 'active'
            ORDER BY d.name
            """
        ),
        {"year": year, "through": through_month},
    ).all()
    return [BudgetUse(i, name, _dec(p), _dec(a)) for i, name, p, a in rows]


def budget_alert_count(session: Session, year: int) -> int:
    return int(
        session.scalar(
            text(
                "SELECT count(*) FROM budget_alerts al JOIN budgets b ON b.id = al.budget_id "
                "WHERE b.year = :year"
            ),
            {"year": year},
        )
        or 0
    )


# ------------------------------------------------------------------ revenue cycle


def invoices_issued(session: Session, start: date, end: date) -> tuple[int, Decimal]:
    row = session.execute(
        text(
            "SELECT count(*), coalesce(sum(total), 0) FROM invoices "
            "WHERE status NOT IN ('draft', 'void') AND invoice_date BETWEEN :start AND :end"
        ),
        {"start": start, "end": end},
    ).one()
    return int(row[0]), _dec(row[1])


def collection_rate(session: Session, start: date, end: date) -> tuple[Decimal, Decimal]:
    """(collected, billed) for invoices issued in [start, end]: payments and adjustments made
    against them so far, versus their totals. Voided invoices excluded."""
    row = session.execute(
        text(
            "SELECT coalesce(sum(amount_paid), 0), coalesce(sum(total), 0) FROM invoices "
            "WHERE status NOT IN ('draft', 'void') AND invoice_date BETWEEN :start AND :end"
        ),
        {"start": start, "end": end},
    ).one()
    return _dec(row[0]), _dec(row[1])


def collections(session: Session, start: date, end: date) -> Decimal:
    """Money received from patients (not insurer remittances, not deposit applications)."""
    return _dec(
        session.scalar(
            text(
                "SELECT coalesce(sum(amount - refunded_amount), 0) FROM payments "
                "WHERE method NOT IN ('insurance', 'deposit') "
                "AND received_on BETWEEN :start AND :end"
            ),
            {"start": start, "end": end},
        )
    )


def collections_by_month(session: Session, start: date, end: date) -> list[tuple[date, Decimal]]:
    rows = session.execute(
        text(
            """
            WITH months AS (
              SELECT generate_series(date_trunc('month', CAST(:start AS date)),
                                     date_trunc('month', CAST(:end AS date)),
                                     interval '1 month')::date AS month
            ), totals AS (
              SELECT date_trunc('month', received_on)::date AS month,
                     sum(amount - refunded_amount) AS amount
              FROM payments
              WHERE received_on BETWEEN :start AND :end
              GROUP BY 1
            )
            SELECT m.month, coalesce(t.amount, 0)
            FROM months m LEFT JOIN totals t ON t.month = m.month ORDER BY m.month
            """
        ),
        {"start": start, "end": end},
    ).all()
    return [(m, _dec(v)) for m, v in rows]


def payment_mix(session: Session, start: date, end: date) -> list[tuple[str, Decimal]]:
    rows = session.execute(
        text(
            "SELECT method, sum(amount - refunded_amount) FROM payments "
            "WHERE received_on BETWEEN :start AND :end GROUP BY method ORDER BY 2 DESC"
        ),
        {"start": start, "end": end},
    ).all()
    return [(m, _dec(v)) for m, v in rows]


def patient_receivables(session: Session, as_of: date) -> tuple[Decimal, int, Decimal]:
    """(patient balance outstanding, overdue invoice count, overdue amount)."""
    row = session.execute(
        text(
            """
            SELECT
              coalesce(sum(total - amount_paid - adjusted_amount - insurance_pending), 0),
              count(*) FILTER (WHERE due_date < :as_of
                               AND total - amount_paid - adjusted_amount - insurance_pending > 0),
              coalesce(sum(total - amount_paid - adjusted_amount - insurance_pending)
                       FILTER (WHERE due_date < :as_of), 0)
            FROM invoices
            WHERE status IN ('issued', 'partially_paid')
              AND total - amount_paid - adjusted_amount - insurance_pending > 0
            """
        ),
        {"as_of": as_of},
    ).one()
    return _dec(row[0]), int(row[1]), _dec(row[2])


# ------------------------------------------------------------------ insurance


def claims_by_status(session: Session) -> list[tuple[str, int, Decimal]]:
    rows = session.execute(
        text(
            "SELECT status, count(*), coalesce(sum(insurer_amount), 0) FROM claims "
            "GROUP BY status ORDER BY count(*) DESC"
        )
    ).all()
    return [(s, int(c), _dec(v)) for s, c, v in rows]


@dataclass(frozen=True)
class DenialStats:
    adjudicated: int
    denied: int
    outstanding: Decimal


def denial_stats(session: Session) -> DenialStats:
    row = session.execute(
        text(
            """
            SELECT
              count(*) FILTER (WHERE adjudicated_at IS NOT NULL),
              count(*) FILTER (WHERE adjudicated_at IS NOT NULL AND denial_code IS NOT NULL),
              coalesce(sum(insurer_amount - paid_amount - adjustment_amount)
                       FILTER (WHERE status IN ('submitted','under_review','approved',
                                                'partially_approved','appealed')), 0)
            FROM claims
            """
        )
    ).one()
    return DenialStats(int(row[0]), int(row[1]), _dec(row[2]))


def top_denials(session: Session, limit: int = 5) -> list[tuple[str, str, int]]:
    rows = session.execute(
        text(
            "SELECT c.denial_code, coalesce(dc.description, ''), count(*) FROM claims c "
            "LEFT JOIN denial_codes dc ON dc.code = c.denial_code "
            "WHERE c.denial_code IS NOT NULL GROUP BY 1, 2 ORDER BY 3 DESC, 1 LIMIT :limit"
        ),
        {"limit": limit},
    ).all()
    return [(code, desc, int(n)) for code, desc, n in rows]


# ------------------------------------------------------------------ administration


def active_users(session: Session) -> int:
    return int(
        session.scalar(text("SELECT count(*) FROM users WHERE is_active AND deleted_at IS NULL"))
        or 0
    )


def audit_by_day(session: Session, first: date, last: date) -> list[tuple[date, int]]:
    """Audited changes per UTC calendar day from `first` to `last` inclusive."""
    rows = session.execute(
        text(
            """
            WITH days AS (
              SELECT generate_series(CAST(:first AS date), CAST(:last AS date),
                                     interval '1 day')::date AS day
            )
            SELECT d.day, count(a.id)
            FROM days d
            LEFT JOIN audit_log a ON a.occurred_at >= (d.day::timestamp AT TIME ZONE 'UTC')
                                 AND a.occurred_at < ((d.day + 1)::timestamp AT TIME ZONE 'UTC')
            GROUP BY d.day ORDER BY d.day
            """
        ),
        {"first": first, "last": last},
    ).all()
    return [(d, int(n)) for d, n in rows]


def audit_by_action(session: Session, since: datetime) -> list[tuple[str, int]]:
    rows = session.execute(
        text(
            "SELECT action, count(*) FROM audit_log WHERE occurred_at >= :since "
            "GROUP BY action ORDER BY 2 DESC LIMIT 8"
        ),
        {"since": since},
    ).all()
    return [(a, int(n)) for a, n in rows]
