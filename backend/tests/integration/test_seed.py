"""The full demo seed keeps every accounting invariant and is idempotent (runs in a rolled-back
transaction on the test database)."""

from datetime import date
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.conftest import check_deferred

D = Decimal


def _run_seed(db: Session) -> None:
    from seed.activity import seed_activity
    from seed.billing import seed_billing
    from seed.insurance import seed_insurance
    from seed.ledger import seed_ledger
    from seed.phase4 import seed_approval_policies, seed_phase4
    from seed.phase5 import seed_phase5
    from seed.phase6 import seed_phase6
    from seed.users import seed_roles, seed_users

    seed_users(db, seed_roles(db))
    seed_ledger(db)
    seed_approval_policies(db)
    seed_billing(db)
    seed_insurance(db)
    seed_phase4(db)
    seed_phase5(db)
    seed_activity(db)
    seed_phase6(db)


def _one(db: Session, sql: str) -> object:
    return db.execute(text(sql)).scalar()


def _balance(db: Session, code: str) -> Decimal:
    return D(
        str(
            db.execute(
                text(
                    "SELECT coalesce(sum(l.debit - l.credit), 0) FROM journal_lines l "
                    "JOIN journal_entries e ON e.id = l.entry_id AND e.status = 'posted' "
                    "JOIN accounts a ON a.id = l.account_id WHERE a.code = :c"
                ),
                {"c": code},
            ).scalar()
        )
    )


def test_full_seed_is_consistent_and_idempotent(db: Session) -> None:
    _run_seed(db)
    check_deferred(db)  # balanced-entry triggers fire as on COMMIT

    # Ledger and sub-ledgers.
    assert _one(db, "SELECT sum(debit) - sum(credit) FROM journal_lines") == 0
    assert _balance(db, "1110") == D(str(_one(db, "SELECT sum(insurance_pending) FROM invoices")))
    open_bills = _one(
        db,
        "SELECT coalesce(sum(total - amount_paid), 0) FROM vendor_bills "
        "WHERE status IN ('approved', 'partially_paid')",
    )
    assert -_balance(db, "2010") == D(str(open_bills))
    patient_due = _one(
        db,
        "SELECT sum(total - amount_paid - adjusted_amount - insurance_pending) FROM invoices "
        "WHERE status IN ('issued', 'partially_paid')",
    )
    assert _balance(db, "1100") == D(str(patient_due))
    assert _balance(db, "1030") == 0 and _balance(db, "2100") == 0  # payroll cleared

    from app.services import ar

    assert ar.aging(db, by="patient", as_of=date(2026, 11, 25)).total == _balance(db, "1100")

    # Demo scenario.
    closed = (
        db.execute(
            text("SELECT name FROM fiscal_periods WHERE status = 'closed' ORDER BY start_date")
        )
        .scalars()
        .all()
    )
    assert closed[-1] == "2026-09" and "2026-10" not in closed
    assert _one(db, "SELECT count(*) FROM approvals WHERE status = 'pending'") >= 4  # type: ignore[operator]
    assert _one(db, "SELECT count(*) FROM budget_alerts WHERE level = 'exceeded'") >= 1  # type: ignore[operator]
    statuses = set(db.execute(text("SELECT DISTINCT status FROM claims")).scalars())
    assert {
        "draft",
        "submitted",
        "approved",
        "partially_approved",
        "denied",
        "appealed",
        "paid",
    } <= statuses
    assert _one(db, "SELECT count(*) FROM invoices") > 700  # type: ignore[operator]

    # Running it again changes nothing.
    fingerprint = "SELECT (SELECT count(*) FROM journal_entries), (SELECT count(*) FROM invoices), (SELECT count(*) FROM notifications)"
    before = db.execute(text(fingerprint)).one()
    _run_seed(db)
    assert db.execute(text(fingerprint)).one() == before
