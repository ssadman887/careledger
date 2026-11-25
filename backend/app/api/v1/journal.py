from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status

from app.core.config import get_settings
from app.core.deps import DbSession, read_roles, require_roles
from app.core.errors import ErrorEnvelope
from app.core.pagination import Page, PageParams, page_params
from app.models.identity import RoleName
from app.models.ledger import EntryStatus, JournalEntry
from app.repositories import ledger as repo
from app.schemas.ledger import (
    JournalEntryCreate,
    JournalEntryOut,
    JournalLineOut,
    ReasonIn,
    ReverseIn,
)
from app.services import ledger as ledger_service
from app.services.audit import Actor
from app.services.ledger import LineInput

router = APIRouter(
    prefix="/journal-entries",
    tags=["journal"],
    responses={401: {"model": ErrorEnvelope}, 403: {"model": ErrorEnvelope}},
)

R = RoleName
JournalRead = Annotated[Actor, Depends(read_roles(R.ACCOUNTANT, R.FINANCE_MANAGER))]
JournalWrite = Annotated[Actor, Depends(require_roles(R.ACCOUNTANT))]
Approver = Annotated[Actor, Depends(require_roles(R.FINANCE_MANAGER))]
_ERRORS: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorEnvelope},
    409: {"model": ErrorEnvelope},
    422: {"model": ErrorEnvelope},
}


def to_out(entry: JournalEntry, reversed_by: dict[int, int]) -> JournalEntryOut:
    return JournalEntryOut(
        id=entry.id,
        entry_number=entry.entry_number,
        entry_date=entry.entry_date,
        memo=entry.memo,
        source_type=entry.source_type,
        source_id=entry.source_id,
        status=EntryStatus(entry.status),
        total=entry.total,
        reversal_of_id=entry.reversal_of_id,
        reversed_by_id=reversed_by.get(entry.id),
        reversal_reason=entry.reversal_reason,
        created_by_id=entry.created_by_id,
        approved_by_id=entry.approved_by_id,
        posted_at=entry.posted_at,
        rejection_reason=entry.rejection_reason,
        created_at=entry.created_at,
        lines=[
            JournalLineOut(
                line_no=ln.line_no,
                account_id=ln.account_id,
                account_code=ln.account.code,
                account_name=ln.account.name,
                debit=ln.debit,
                credit=ln.credit,
                description=ln.description,
                department_id=ln.department_id,
                cost_center_id=ln.cost_center_id,
            )
            for ln in entry.lines
        ],
    )


def _single(db: DbSession, entry: JournalEntry) -> JournalEntryOut:
    return to_out(entry, repo.reversal_of(db, [entry.id]))


@router.get("", response_model=Page[JournalEntryOut])
def list_entries(
    _: JournalRead,
    db: DbSession,
    params: Annotated[PageParams, Depends(page_params)],
    status: EntryStatus | None = None,
    source_type: Annotated[str | None, Query(max_length=40)] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    account_id: int | None = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
) -> Page[JournalEntryOut]:
    rows, total = repo.list_entries(
        db,
        params,
        status=status.value if status else None,
        source_type=source_type,
        date_from=date_from,
        date_to=date_to,
        account_id=account_id,
        search=search,
    )
    reversed_by = repo.reversal_of(db, [e.id for e in rows])
    return Page(
        items=[to_out(e, reversed_by) for e in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.post(
    "", response_model=JournalEntryOut, status_code=status.HTTP_201_CREATED, responses=_ERRORS
)
def create_entry(body: JournalEntryCreate, actor: JournalWrite, db: DbSession) -> JournalEntryOut:
    """Manual journal entry. Totals above the approval threshold wait for a finance manager."""
    entry = ledger_service.create_manual_entry(
        db,
        actor,
        entry_date=body.entry_date,
        memo=body.memo,
        lines=[
            LineInput(
                ln.account_id,
                ln.debit,
                ln.credit,
                ln.description,
                ln.department_id,
                ln.cost_center_id,
            )
            for ln in body.lines
        ],
        approval_threshold=get_settings().manual_journal_approval_threshold,
    )
    return _single(db, entry)


@router.get("/{entry_id}", response_model=JournalEntryOut, responses=_ERRORS)
def get_entry(entry_id: int, _: JournalRead, db: DbSession) -> JournalEntryOut:
    return _single(db, ledger_service.get_entry(db, entry_id))


@router.post(
    "/{entry_id}/reverse",
    response_model=JournalEntryOut,
    status_code=status.HTTP_201_CREATED,
    responses=_ERRORS,
)
def reverse_entry(
    entry_id: int, body: ReverseIn, actor: JournalWrite, db: DbSession
) -> JournalEntryOut:
    entry = ledger_service.reverse_entry(
        db, actor, entry_id, body.reason, reversal_date=body.reversal_date
    )
    return _single(db, entry)


@router.post("/{entry_id}/approve", response_model=JournalEntryOut, responses=_ERRORS)
def approve_entry(entry_id: int, actor: Approver, db: DbSession) -> JournalEntryOut:
    return _single(db, ledger_service.approve_entry(db, actor, entry_id))


@router.post("/{entry_id}/reject", response_model=JournalEntryOut, responses=_ERRORS)
def reject_entry(entry_id: int, body: ReasonIn, actor: Approver, db: DbSession) -> JournalEntryOut:
    return _single(db, ledger_service.reject_entry(db, actor, entry_id, body.reason))
