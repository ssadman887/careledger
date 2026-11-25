"""Property-based test: any sequence of valid postings (and reversals) keeps the ledger balanced."""

from datetime import date, timedelta
from decimal import Decimal

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ledger import Account
from app.repositories import ledger as repo
from app.services import ledger, reports
from app.services.audit import SYSTEM_ACTOR
from app.services.ledger import EntryDraft, LineInput
from tests.conftest import check_deferred

CENTS = st.integers(min_value=1, max_value=50_000_000)  # 0.01 .. 500,000.00
DATES = st.integers(min_value=0, max_value=364).map(lambda d: date(2026, 1, 1) + timedelta(days=d))


@st.composite
def entries(draw: st.DrawFn, account_count: int) -> tuple[date, list[tuple[int, int, int]], bool]:
    """(date, [(account index, debit cents, credit cents)], reverse?) — balanced by construction."""
    acc = st.integers(min_value=0, max_value=account_count - 1)
    debits = draw(st.lists(st.tuples(acc, CENTS), min_size=1, max_size=4))
    credits = draw(st.lists(st.tuples(acc, CENTS), min_size=1, max_size=4))
    legs = [(a, c, 0) for a, c in debits] + [(a, 0, c) for a, c in credits]
    diff = sum(c for _, c in debits) - sum(c for _, c in credits)
    if diff > 0:
        legs.append((draw(acc), 0, diff))
    elif diff < 0:
        legs.append((draw(acc), -diff, 0))
    return draw(DATES), legs, draw(st.booleans())


def _postable(db: Session) -> list[int]:
    stmt = select(Account.id).where(Account.is_header.is_(False), Account.is_active.is_(True))
    return list(db.scalars(stmt.order_by(Account.code)).all())


@settings(
    max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(data=st.data())
def test_random_valid_sequences_keep_trial_balance_at_zero(
    db: Session, data: st.DataObject
) -> None:
    accounts = _postable(db)
    batch = data.draw(st.lists(entries(len(accounts)), min_size=1, max_size=8))
    nested = db.begin_nested()
    try:
        for on, legs, reverse in batch:
            entry = ledger.post_entry(
                db,
                SYSTEM_ACTOR,
                EntryDraft(
                    entry_date=on,
                    memo="property",
                    source_type="property",
                    lines=[
                        LineInput(accounts[i], Decimal(d) / 100, Decimal(c) / 100)
                        for i, d, c in legs
                    ],
                ),
            )
            if reverse:
                ledger.reverse_entry(db, SYSTEM_ACTOR, entry.id, "property reversal")
        check_deferred(db)  # DB-level balance triggers agree with the service

        debits, credits = repo.ledger_sums(db, date_from=None, date_to=None)
        assert debits - credits == Decimal("0")
        tb = reports.trial_balance(db, None, None)
        assert tb.balanced
        assert sum((r.debit - r.credit for r in tb.rows), Decimal("0")) == Decimal("0")
        assert reports.balance_sheet(db, date(2026, 12, 31)).balanced
    finally:
        nested.rollback()
