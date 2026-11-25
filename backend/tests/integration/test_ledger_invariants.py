"""Accounting invariants: service rules AND the database safeguards behind them."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation, Conflict, PermissionDenied, ValidationFailed
from app.models.ledger import EntryStatus, FiscalPeriod, JournalEntry
from app.services import ledger, periods, reports
from app.services.audit import SYSTEM_ACTOR
from app.services.ledger import EntryDraft, LineInput
from tests.conftest import check_deferred

D = Decimal


def _draft(acct, amount: str = "100.00", on: date = date(2026, 3, 15)) -> EntryDraft:  # type: ignore[no-untyped-def]
    return EntryDraft(
        entry_date=on,
        memo="test",
        source_type="test",
        lines=[
            LineInput(acct("1010"), debit=D(amount)),
            LineInput(acct("4110"), credit=D(amount)),
        ],
    )


def _close(db: Session, name: str) -> FiscalPeriod:
    period = db.scalars(select(FiscalPeriod).where(FiscalPeriod.name == name)).one()
    return periods.close_period(db, SYSTEM_ACTOR, period.id)


# ------------------------------------------------------------------ balance


def test_unbalanced_entry_rejected_by_service(db: Session, acct) -> None:  # type: ignore[no-untyped-def]
    draft = EntryDraft(
        entry_date=date(2026, 3, 1),
        memo="bad",
        source_type="test",
        lines=[
            LineInput(acct("1010"), debit=D("100.00")),
            LineInput(acct("4110"), credit=D("99.99")),
        ],
    )
    with pytest.raises(BusinessRuleViolation) as exc:
        ledger.post_entry(db, SYSTEM_ACTOR, draft)
    assert exc.value.code == "unbalanced_entry"
    assert exc.value.details == {"debits": "100.00", "credits": "99.99"}


@pytest.mark.parametrize(
    ("lines", "code"),
    [
        ([("1010", "10.00", "0")], "too_few_lines"),
        ([("1010", "10.00", "10.00"), ("4110", "0", "10.00")], "invalid_line"),
        ([("1010", "0", "0"), ("4110", "0", "0")], "invalid_line"),
        ([("1010", "-5.00", "0"), ("4110", "0", "-5.00")], "negative_amount"),
        ([("1010", "1.005", "0"), ("4110", "0", "1.005")], "invalid_precision"),
    ],
)
def test_malformed_lines_rejected(db: Session, acct, lines, code: str) -> None:  # type: ignore[no-untyped-def]
    draft = EntryDraft(
        entry_date=date(2026, 3, 1),
        memo="bad",
        source_type="test",
        lines=[LineInput(acct(c), debit=D(d), credit=D(cr)) for c, d, cr in lines],
    )
    with pytest.raises(ValidationFailed) as exc:
        ledger.post_entry(db, SYSTEM_ACTOR, draft)
    assert exc.value.code == code


def test_header_and_inactive_accounts_rejected(db: Session, acct) -> None:  # type: ignore[no-untyped-def]
    draft = EntryDraft(
        entry_date=date(2026, 3, 1),
        memo="bad",
        source_type="test",
        lines=[LineInput(acct("1000"), debit=D("5.00")), LineInput(acct("4110"), credit=D("5.00"))],
    )
    with pytest.raises(BusinessRuleViolation, match="header account"):
        ledger.post_entry(db, SYSTEM_ACTOR, draft)


def test_unbalanced_entry_rejected_at_db_level(db: Session, acct) -> None:  # type: ignore[no-untyped-def]
    """Bypass the service entirely: the deferred constraint trigger still refuses it."""
    nested = db.begin_nested()
    entry_id = db.execute(
        text(
            "INSERT INTO journal_entries (entry_number, entry_date, memo, source_type, status, total, posted_at)"
            " VALUES ('RAW-1', '2026-03-01', 'raw', 'test', 'posted', 100, now()) RETURNING id"
        )
    ).scalar_one()
    db.execute(
        text(
            "INSERT INTO journal_lines (entry_id, line_no, account_id, debit, credit) VALUES"
            " (:e, 1, :a, 100, 0), (:e, 2, :b, 0, 60)"
        ),
        {"e": entry_id, "a": acct("1010"), "b": acct("4110")},
    )
    with pytest.raises(DBAPIError, match="unbalanced"):
        db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    nested.rollback()


def test_single_line_entry_rejected_at_db_level(db: Session, acct) -> None:  # type: ignore[no-untyped-def]
    nested = db.begin_nested()
    entry_id = db.execute(
        text(
            "INSERT INTO journal_entries (entry_number, entry_date, memo, source_type, status, total, posted_at)"
            " VALUES ('RAW-2', '2026-03-01', 'raw', 'test', 'posted', 0, now()) RETURNING id"
        )
    ).scalar_one()
    db.execute(
        text(
            "INSERT INTO journal_lines (entry_id, line_no, account_id, debit, credit)"
            " VALUES (:e, 1, :a, 10, 0)"
        ),
        {"e": entry_id, "a": acct("1010")},
    )
    with pytest.raises(DBAPIError, match="at least 2 lines"):
        db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    nested.rollback()


# ------------------------------------------------------------------ immutability


@pytest.mark.parametrize(
    "stmt",
    [
        "UPDATE journal_lines SET debit = debit + 1 WHERE entry_id = :e",
        "UPDATE journal_lines SET account_id = account_id WHERE entry_id = :e",
        "DELETE FROM journal_lines WHERE entry_id = :e",
        "UPDATE journal_entries SET memo = 'tampered' WHERE id = :e",
        "DELETE FROM journal_entries WHERE id = :e",
    ],
)
def test_posted_entries_immutable_at_db_level(db: Session, acct, stmt: str) -> None:  # type: ignore[no-untyped-def]
    entry = ledger.post_entry(db, SYSTEM_ACTOR, _draft(acct))
    check_deferred(db)
    nested = db.begin_nested()
    with pytest.raises(DBAPIError, match="immutable|cannot be deleted"):
        db.execute(text(stmt), {"e": entry.id})
    nested.rollback()


# ------------------------------------------------------------------ periods


def test_posting_into_closed_period_rejected(db: Session, acct) -> None:  # type: ignore[no-untyped-def]
    _close(db, "2026-01")
    with pytest.raises(BusinessRuleViolation) as exc:
        ledger.post_entry(db, SYSTEM_ACTOR, _draft(acct, on=date(2026, 1, 20)))
    assert exc.value.code == "period_closed"


def test_posting_into_closed_period_rejected_at_db_level(db: Session, acct) -> None:  # type: ignore[no-untyped-def]
    _close(db, "2026-01")
    db.flush()
    nested = db.begin_nested()
    with pytest.raises(DBAPIError, match="is closed"):
        db.execute(
            text(
                "INSERT INTO journal_entries (entry_number, entry_date, memo, source_type, status, total, posted_at)"
                " VALUES ('RAW-3', '2026-01-20', 'raw', 'test', 'posted', 1, now())"
            )
        )
    nested.rollback()


def test_posting_without_period_rejected(db: Session, acct) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(BusinessRuleViolation) as exc:
        ledger.post_entry(db, SYSTEM_ACTOR, _draft(acct, on=date(2019, 6, 1)))
    assert exc.value.code == "no_fiscal_period"


def test_closed_period_cannot_be_reopened(db: Session) -> None:
    period = _close(db, "2026-01")
    db.flush()
    nested = db.begin_nested()
    with pytest.raises(DBAPIError, match="closed and locked"):
        db.execute(
            text("UPDATE fiscal_periods SET status = 'open' WHERE id = :p"), {"p": period.id}
        )
    nested.rollback()


def test_periods_must_close_in_order(db: Session) -> None:
    period = db.scalars(select(FiscalPeriod).where(FiscalPeriod.name == "2026-03")).one()
    check = periods.close_check(db, period)
    assert not check.can_close
    assert check.earlier_open_periods == ["2026-01", "2026-02"]
    with pytest.raises(BusinessRuleViolation):
        periods.close_period(db, SYSTEM_ACTOR, period.id)


def test_overlapping_period_rejected(db: Session) -> None:
    with pytest.raises(Conflict):
        periods.create_period(
            db, SYSTEM_ACTOR, name="X", start=date(2026, 2, 15), end=date(2026, 3, 15)
        )


# ------------------------------------------------------------------ reversal


def test_reversal_nets_to_zero(db: Session, acct) -> None:  # type: ignore[no-untyped-def]
    before = {r.code: (r.debit - r.credit) for r in reports.trial_balance(db, None, None).rows}
    entry = ledger.post_entry(db, SYSTEM_ACTOR, _draft(acct, "1234.56"))
    reversal = ledger.reverse_entry(db, SYSTEM_ACTOR, entry.id, "keyed twice")
    check_deferred(db)

    assert reversal.reversal_of_id == entry.id
    assert reversal.entry_date == entry.entry_date
    for orig, rev in zip(entry.lines, reversal.lines, strict=True):
        assert (rev.debit, rev.credit) == (orig.credit, orig.debit)
    after = {r.code: (r.debit - r.credit) for r in reports.trial_balance(db, None, None).rows}
    assert after.get("1010", D(0)) == before.get("1010", D(0))
    assert after.get("4110", D(0)) == before.get("4110", D(0))
    # Original untouched (immutable), linked both ways.
    assert db.get(JournalEntry, entry.id).status == EntryStatus.POSTED  # type: ignore[union-attr]


def test_cannot_reverse_twice_or_reverse_a_reversal(db: Session, acct) -> None:  # type: ignore[no-untyped-def]
    entry = ledger.post_entry(db, SYSTEM_ACTOR, _draft(acct))
    reversal = ledger.reverse_entry(db, SYSTEM_ACTOR, entry.id, "oops")
    with pytest.raises(Conflict, match="already been reversed"):
        ledger.reverse_entry(db, SYSTEM_ACTOR, entry.id, "again")
    with pytest.raises(Conflict, match="cannot itself be reversed"):
        ledger.reverse_entry(db, SYSTEM_ACTOR, reversal.id, "undo")


def test_reversal_of_closed_period_entry_lands_in_open_period(db: Session, acct) -> None:  # type: ignore[no-untyped-def]
    entry = ledger.post_entry(db, SYSTEM_ACTOR, _draft(acct, on=date(2026, 1, 10)))
    _close(db, "2026-01")
    reversal = ledger.reverse_entry(
        db, SYSTEM_ACTOR, entry.id, "late fix", reversal_date=date(2026, 2, 1)
    )
    assert reversal.entry_date == date(2026, 2, 1)
    with pytest.raises(Conflict):
        ledger.reverse_entry(db, SYSTEM_ACTOR, entry.id, "again")


# ------------------------------------------------------------------ approval


def test_manual_entry_threshold_and_segregation_of_duties(db: Session, acct, actor_for) -> None:  # type: ignore[no-untyped-def]
    accountant = actor_for("accountant")
    lines = [
        LineInput(acct("5300"), debit=D("10000.01")),
        LineInput(acct("1020"), credit=D("10000.01")),
    ]
    entry = ledger.create_manual_entry(
        db,
        accountant,
        entry_date=date(2026, 4, 1),
        memo="Utilities",
        lines=lines,
        approval_threshold=D("10000.00"),
    )
    assert entry.status == EntryStatus.PENDING_APPROVAL
    assert entry.posted_at is None
    with pytest.raises(PermissionDenied):
        ledger.approve_entry(db, accountant, entry.id)
    approved = ledger.approve_entry(db, actor_for("finance"), entry.id)
    check_deferred(db)
    assert approved.status == EntryStatus.POSTED
    assert approved.approved_by_id is not None

    small = ledger.create_manual_entry(
        db,
        accountant,
        entry_date=date(2026, 4, 1),
        memo="Small",
        lines=[
            LineInput(acct("5300"), debit=D("10000.00")),
            LineInput(acct("1020"), credit=D("10000.00")),
        ],
        approval_threshold=D("10000.00"),
    )
    assert small.status == EntryStatus.POSTED  # at the threshold: no approval needed


def test_pending_entries_excluded_from_reports_and_block_close(
    db: Session, acct, actor_for
) -> None:  # type: ignore[no-untyped-def]
    before = reports.trial_balance(db, None, None).total_debit
    ledger.create_manual_entry(
        db,
        actor_for("accountant"),
        entry_date=date(2026, 1, 5),
        memo="Big",
        lines=[
            LineInput(acct("5300"), debit=D("50000.00")),
            LineInput(acct("1020"), credit=D("50000.00")),
        ],
        approval_threshold=D("10000.00"),
    )
    assert reports.trial_balance(db, None, None).total_debit == before
    period = db.scalars(select(FiscalPeriod).where(FiscalPeriod.name == "2026-01")).one()
    check = periods.close_check(db, period)
    assert check.pending_entries == 1 and not check.can_close


def test_reject_requires_reason(db: Session, acct, actor_for) -> None:  # type: ignore[no-untyped-def]
    entry = ledger.create_manual_entry(
        db,
        actor_for("accountant"),
        entry_date=date(2026, 4, 1),
        memo="Big",
        lines=[
            LineInput(acct("5300"), debit=D("20000.00")),
            LineInput(acct("1020"), credit=D("20000.00")),
        ],
        approval_threshold=D("10000.00"),
    )
    finance = actor_for("finance")
    with pytest.raises(ValidationFailed):
        ledger.reject_entry(db, finance, entry.id, "  ")
    rejected = ledger.reject_entry(db, finance, entry.id, "No invoice attached")
    assert rejected.status == EntryStatus.REJECTED
    with pytest.raises(Conflict):
        ledger.approve_entry(db, finance, entry.id)


# ------------------------------------------------------------------ statements


def test_statements_tie_out(db: Session, acct) -> None:  # type: ignore[no-untyped-def]
    ledger.post_entry(db, SYSTEM_ACTOR, _draft(acct, "5000.00", on=date(2026, 5, 3)))  # revenue
    ledger.post_entry(
        db,
        SYSTEM_ACTOR,
        EntryDraft(
            entry_date=date(2026, 5, 9),
            memo="supplies",
            source_type="test",
            lines=[
                LineInput(acct("5200"), debit=D("1200.00")),
                LineInput(acct("1020"), credit=D("1200.00")),
            ],
        ),
    )
    inc = reports.income_statement(db, date(2026, 5, 1), date(2026, 5, 31))
    assert inc.revenue.total == D("5000.00")
    assert inc.expenses.total == D("1200.00")
    assert inc.net_income == D("3800.00")

    bs = reports.balance_sheet(db, date(2026, 5, 31))
    assert bs.balanced
    assert bs.total_assets == bs.total_liabilities_and_equity
    earnings = [ln for ln in bs.equity.lines if ln.name.startswith("Retained earnings")]
    assert earnings and earnings[0].amount >= D("3800.00")

    tb = reports.trial_balance(db, None, None)
    assert tb.balanced and tb.total_balance_debit == tb.total_balance_credit
