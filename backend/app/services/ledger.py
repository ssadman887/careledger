"""Journal engine: the only code path that writes to the general ledger.

Rules enforced here (and again by DB triggers, see migration 0004):
  * an entry has >= 2 lines, each line strictly one-sided and positive;
  * sum(debit) == sum(credit);
  * accounts must exist, be active and postable (not headers);
  * entry_date must fall in an open fiscal period;
  * posted entries are immutable: corrections use reverse_entry().
Services only flush; the caller's transaction (request / job) commits, so the business record,
its journal entry and audit rows are atomic.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.errors import (
    BusinessRuleViolation,
    Conflict,
    NotFound,
    PermissionDenied,
    ValidationFailed,
)
from app.core.money import quantize
from app.models.ledger import EntryStatus, JournalEntry, JournalLine, PeriodStatus
from app.repositories import ledger as repo
from app.services import audit
from app.services.audit import Actor

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class LineInput:
    account_id: int
    debit: Decimal = ZERO
    credit: Decimal = ZERO
    description: str = ""
    department_id: int | None = None
    cost_center_id: int | None = None


@dataclass(frozen=True)
class EntryDraft:
    entry_date: date
    memo: str
    lines: Sequence[LineInput]
    source_type: str
    source_id: str | None = None
    extra: dict[str, object] = field(default_factory=dict)


def validate_lines(session: Session, lines: Sequence[LineInput]) -> Decimal:
    """Validate structure, balance and accounts. Returns the entry total (sum of debits)."""
    if len(lines) < 2:
        raise ValidationFailed("A journal entry needs at least 2 lines", code="too_few_lines")
    debits = credits = ZERO
    for i, line in enumerate(lines, start=1):
        if line.debit < 0 or line.credit < 0:
            raise ValidationFailed(f"Line {i}: amounts cannot be negative", code="negative_amount")
        if (line.debit > 0) == (line.credit > 0):
            raise ValidationFailed(
                f"Line {i}: exactly one of debit or credit must be positive", code="invalid_line"
            )
        if quantize(line.debit) != line.debit or quantize(line.credit) != line.credit:
            raise ValidationFailed(f"Line {i}: at most 2 decimal places", code="invalid_precision")
        debits += line.debit
        credits += line.credit
    if debits != credits:
        raise BusinessRuleViolation(
            "Journal entry is unbalanced: total debits must equal total credits",
            code="unbalanced_entry",
            details={"debits": f"{debits:.2f}", "credits": f"{credits:.2f}"},
        )
    accounts = repo.accounts_by_ids(session, [line.account_id for line in lines])
    for i, line in enumerate(lines, start=1):
        account = accounts.get(line.account_id)
        if account is None:
            raise NotFound(
                f"Line {i}: account {line.account_id} not found", code="account_not_found"
            )
        if account.is_header:
            raise BusinessRuleViolation(
                f"Line {i}: {account.code} is a header account and cannot be posted to",
                code="header_account",
            )
        if not account.is_active:
            raise BusinessRuleViolation(
                f"Line {i}: account {account.code} is inactive", code="inactive_account"
            )
    _validate_dimensions(session, lines)
    return debits


def _validate_dimensions(session: Session, lines: Sequence[LineInput]) -> None:
    dept_ids = {ln.department_id for ln in lines if ln.department_id is not None}
    if dept_ids and repo.department_ids(session, dept_ids) != dept_ids:
        raise NotFound("Unknown department on a journal line", code="department_not_found")
    cc_ids = {ln.cost_center_id for ln in lines if ln.cost_center_id is not None}
    if cc_ids and repo.cost_center_ids(session, cc_ids) != cc_ids:
        raise NotFound("Unknown cost center on a journal line", code="cost_center_not_found")


def require_open_period(session: Session, on: date) -> None:
    period = repo.period_for_date(session, on, lock=True)
    if period is None:
        raise BusinessRuleViolation(f"No fiscal period covers {on}", code="no_fiscal_period")
    if period.status != PeriodStatus.OPEN:
        raise BusinessRuleViolation(
            f"Fiscal period {period.name} is closed; posting into it is not allowed",
            code="period_closed",
        )


def entry_snapshot(entry: JournalEntry) -> dict[str, object]:
    lines = [
        {
            "line_no": ln.line_no,
            "account_id": ln.account_id,
            "debit": ln.debit,
            "credit": ln.credit,
            "description": ln.description,
        }
        for ln in entry.lines
    ]
    return audit.snapshot(entry, extra={"lines": lines})


def _write_entry(
    session: Session,
    actor: Actor,
    draft: EntryDraft,
    *,
    status: EntryStatus,
    total: Decimal,
    reversal_of_id: int | None = None,
    reversal_reason: str | None = None,
) -> JournalEntry:
    now = datetime.now(UTC)
    entry = JournalEntry(
        entry_number=repo.next_entry_number(session),
        entry_date=draft.entry_date,
        memo=draft.memo,
        source_type=draft.source_type,
        source_id=draft.source_id,
        status=status,
        total=total,
        reversal_of_id=reversal_of_id,
        reversal_reason=reversal_reason,
        created_by_id=actor.id,
        posted_at=now if status == EntryStatus.POSTED else None,
        lines=[
            JournalLine(
                line_no=i,
                account_id=ln.account_id,
                debit=ln.debit,
                credit=ln.credit,
                description=ln.description,
                department_id=ln.department_id,
                cost_center_id=ln.cost_center_id,
            )
            for i, ln in enumerate(draft.lines, start=1)
        ],
    )
    session.add(entry)
    session.flush()
    return entry


def post_entry(session: Session, actor: Actor, draft: EntryDraft) -> JournalEntry:
    """Validate and post a balanced entry atomically in the caller's transaction."""
    total = validate_lines(session, draft.lines)
    require_open_period(session, draft.entry_date)
    entry = _write_entry(session, actor, draft, status=EntryStatus.POSTED, total=total)
    audit.record(
        session,
        actor,
        entity_type="journal_entry",
        entity_id=entry.id,
        action="post",
        after=entry_snapshot(entry),
    )
    return entry


def get_entry(session: Session, entry_id: int, *, lock: bool = False) -> JournalEntry:
    entry = repo.get_entry(session, entry_id, lock=lock)
    if entry is None:
        raise NotFound("Journal entry not found")
    return entry


def reverse_entry(
    session: Session,
    actor: Actor,
    entry_id: int,
    reason: str,
    *,
    reversal_date: date | None = None,
) -> JournalEntry:
    """Post a mirror entry (debits <-> credits) linked to the original."""
    original = get_entry(session, entry_id, lock=True)
    if original.status != EntryStatus.POSTED:
        raise Conflict("Only posted entries can be reversed", code="not_posted")
    if original.reversal_of_id is not None:
        raise Conflict("A reversing entry cannot itself be reversed", code="is_reversal")
    if repo.reversal_of(session, [original.id]):
        raise Conflict("This entry has already been reversed", code="already_reversed")
    if not reason.strip():
        raise ValidationFailed("A reversal reason is required", code="reason_required")

    if reversal_date is None:
        period = repo.period_for_date(session, original.entry_date)
        open_original = period is not None and period.status == PeriodStatus.OPEN
        reversal_date = original.entry_date if open_original else datetime.now(UTC).date()
    lines = [
        LineInput(
            account_id=ln.account_id,
            debit=ln.credit,
            credit=ln.debit,
            description=ln.description,
            department_id=ln.department_id,
            cost_center_id=ln.cost_center_id,
        )
        for ln in original.lines
    ]
    draft = EntryDraft(
        entry_date=reversal_date,
        memo=f"Reversal of {original.entry_number}: {reason}",
        lines=lines,
        source_type="reversal",
        source_id=str(original.id),
    )
    total = validate_lines_for_reversal(lines)
    require_open_period(session, reversal_date)
    entry = _write_entry(
        session,
        actor,
        draft,
        status=EntryStatus.POSTED,
        total=total,
        reversal_of_id=original.id,
        reversal_reason=reason,
    )
    audit.record(
        session,
        actor,
        entity_type="journal_entry",
        entity_id=entry.id,
        action="post",
        after=entry_snapshot(entry),
    )
    audit.record(
        session,
        actor,
        entity_type="journal_entry",
        entity_id=original.id,
        action="reverse",
        after={"reversed_by_id": entry.id, "reason": reason},
    )
    return entry


def validate_lines_for_reversal(lines: Sequence[LineInput]) -> Decimal:
    """Reversals mirror an already-valid entry; accounts may since have been deactivated."""
    debits = sum((ln.debit for ln in lines), ZERO)
    credits = sum((ln.credit for ln in lines), ZERO)
    if debits != credits or len(lines) < 2:  # defensive: cannot happen for a posted entry
        raise BusinessRuleViolation("Original entry is not balanced", code="unbalanced_entry")
    return debits


# ------------------------------------------------------------ manual entries with approval


def create_manual_entry(
    session: Session,
    actor: Actor,
    *,
    entry_date: date,
    memo: str,
    lines: Sequence[LineInput],
    approval_threshold: Decimal,
) -> JournalEntry:
    """Accountant-entered entry. Above the threshold it waits for finance-manager approval."""
    draft = EntryDraft(entry_date=entry_date, memo=memo, lines=lines, source_type="manual")
    total = validate_lines(session, lines)
    require_open_period(session, entry_date)
    if total <= approval_threshold:
        entry = _write_entry(session, actor, draft, status=EntryStatus.POSTED, total=total)
        action = "post"
    else:
        entry = _write_entry(
            session, actor, draft, status=EntryStatus.PENDING_APPROVAL, total=total
        )
        action = "create"
    audit.record(
        session,
        actor,
        entity_type="journal_entry",
        entity_id=entry.id,
        action=action,
        after=entry_snapshot(entry),
    )
    return entry


def _pending(session: Session, actor: Actor, entry_id: int) -> JournalEntry:
    entry = get_entry(session, entry_id, lock=True)
    if entry.status != EntryStatus.PENDING_APPROVAL:
        raise Conflict("Entry is not awaiting approval", code="not_pending")
    if entry.created_by_id is not None and entry.created_by_id == actor.id:
        raise PermissionDenied("You cannot approve or reject your own entry", code="self_approval")
    return entry


def approve_entry(session: Session, actor: Actor, entry_id: int) -> JournalEntry:
    entry = _pending(session, actor, entry_id)
    before = entry_snapshot(entry)
    lines = [
        LineInput(
            ln.account_id, ln.debit, ln.credit, ln.description, ln.department_id, ln.cost_center_id
        )
        for ln in entry.lines
    ]
    validate_lines(session, lines)  # accounts may have changed since submission
    require_open_period(session, entry.entry_date)
    entry.status = EntryStatus.POSTED
    entry.approved_by_id = actor.id
    entry.posted_at = datetime.now(UTC)
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="journal_entry",
        entity_id=entry.id,
        action="approve",
        before=before,
        after=entry_snapshot(entry),
    )
    return entry


def reject_entry(session: Session, actor: Actor, entry_id: int, reason: str) -> JournalEntry:
    entry = _pending(session, actor, entry_id)
    if not reason.strip():
        raise ValidationFailed("A rejection reason is required", code="reason_required")
    before = entry_snapshot(entry)
    entry.status = EntryStatus.REJECTED
    entry.rejection_reason = reason
    entry.approved_by_id = actor.id
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="journal_entry",
        entity_id=entry.id,
        action="reject",
        before=before,
        after=entry_snapshot(entry),
    )
    return entry
