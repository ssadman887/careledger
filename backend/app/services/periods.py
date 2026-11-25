"""Fiscal period management: create, pre-close check, close (closed periods are locked)."""

import calendar
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation, Conflict, NotFound, ValidationFailed
from app.models.ledger import EntryStatus, FiscalPeriod, PeriodStatus
from app.repositories import ledger as repo
from app.services import audit
from app.services.audit import Actor


@dataclass(frozen=True)
class CloseCheck:
    period_id: int
    can_close: bool
    total_debits: Decimal
    total_credits: Decimal
    trial_balance_balanced: bool
    pending_entries: int
    earlier_open_periods: list[str]
    problems: list[str]


def get_period(session: Session, period_id: int) -> FiscalPeriod:
    period = repo.get_period(session, period_id)
    if period is None:
        raise NotFound("Fiscal period not found")
    return period


def create_period(
    session: Session, actor: Actor, *, name: str, start: date, end: date
) -> FiscalPeriod:
    if end < start:
        raise ValidationFailed("End date must be on or after start date", code="invalid_range")
    if repo.overlapping_period_exists(session, start, end):
        raise Conflict("Period overlaps an existing fiscal period", code="period_overlap")
    period = FiscalPeriod(name=name, start_date=start, end_date=end, status=PeriodStatus.OPEN)
    session.add(period)
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="fiscal_period",
        entity_id=period.id,
        action="create",
        after=audit.snapshot(period),
    )
    return period


def create_month(session: Session, actor: Actor, year: int, month: int) -> FiscalPeriod:
    last = calendar.monthrange(year, month)[1]
    return create_period(
        session,
        actor,
        name=f"{year:04d}-{month:02d}",
        start=date(year, month, 1),
        end=date(year, month, last),
    )


def close_check(session: Session, period: FiscalPeriod) -> CloseCheck:
    debits, credits = repo.ledger_sums(
        session, date_from=period.start_date, date_to=period.end_date
    )
    pending = repo.count_entries(
        session, period.start_date, period.end_date, EntryStatus.PENDING_APPROVAL
    )
    earlier = [p.name for p in repo.open_periods_before(session, period.start_date)]
    problems: list[str] = []
    if period.status == PeriodStatus.CLOSED:
        problems.append("Period is already closed")
    if debits != credits:
        problems.append(f"Trial balance does not balance (debits {debits} vs credits {credits})")
    if pending:
        problems.append(f"{pending} journal entr{'y' if pending == 1 else 'ies'} awaiting approval")
    if earlier:
        problems.append(f"Earlier periods must be closed first: {', '.join(earlier)}")
    return CloseCheck(
        period_id=period.id,
        can_close=not problems,
        total_debits=debits,
        total_credits=credits,
        trial_balance_balanced=debits == credits,
        pending_entries=pending,
        earlier_open_periods=earlier,
        problems=problems,
    )


def close_period(session: Session, actor: Actor, period_id: int) -> FiscalPeriod:
    period = get_period(session, period_id)
    check = close_check(session, period)
    if not check.can_close:
        raise BusinessRuleViolation(
            "Period cannot be closed",
            code="close_check_failed",
            details={"problems": check.problems},
        )
    before = audit.snapshot(period)
    period.status = PeriodStatus.CLOSED
    period.closed_at = datetime.now(UTC)
    period.closed_by_id = actor.id
    session.flush()
    audit.record(
        session,
        actor,
        entity_type="fiscal_period",
        entity_id=period.id,
        action="status_change",
        before=before,
        after=audit.snapshot(period),
    )
    return period
