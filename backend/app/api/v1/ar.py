from datetime import UTC, date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, status

from app.core.deps import DbSession, read_roles, require_roles
from app.core.errors import ErrorEnvelope
from app.core.pagination import Page, PageParams, page_params
from app.models.ar import DunningNotice, WriteOff, WriteOffStatus
from app.models.identity import RoleName
from app.repositories import ar as repo
from app.schemas.phase4 import (
    AgingReportOut,
    AgingRowOut,
    DunningNoticeOut,
    DunningRunIn,
    DunningRunOut,
    WriteOffIn,
    WriteOffOut,
)
from app.services import ar
from app.services.audit import Actor

router = APIRouter(
    prefix="/ar",
    tags=["accounts-receivable"],
    responses={
        401: {"model": ErrorEnvelope},
        403: {"model": ErrorEnvelope},
        404: {"model": ErrorEnvelope},
        409: {"model": ErrorEnvelope},
        422: {"model": ErrorEnvelope},
    },
)

R = RoleName
ARRead = Annotated[
    Actor,
    Depends(read_roles(R.BILLING_CLERK, R.INSURANCE_OFFICER, R.FINANCE_MANAGER, R.ACCOUNTANT)),
]
Collections = Annotated[Actor, Depends(require_roles(R.BILLING_CLERK, R.FINANCE_MANAGER))]


def _today() -> date:
    return datetime.now(UTC).date()


def notice_out(n: DunningNotice) -> DunningNoticeOut:
    return DunningNoticeOut(
        id=n.id,
        invoice_id=n.invoice_id,
        invoice_number=n.invoice.invoice_number,
        patient_id=n.patient_id,
        patient_name=n.invoice.patient.full_name,
        level=n.level,
        days_overdue=n.days_overdue,
        amount_due=n.amount_due,
        channel=n.channel,
        message=n.message,
        sent_at=n.sent_at,
    )


def write_off_out(w: WriteOff) -> WriteOffOut:
    return WriteOffOut(
        id=w.id,
        write_off_number=w.write_off_number,
        invoice_id=w.invoice_id,
        invoice_number=w.invoice.invoice_number,
        patient_name=w.invoice.patient.full_name,
        amount=w.amount,
        reason=w.reason,
        status=WriteOffStatus(w.status),
        posted_on=w.posted_on,
        journal_entry_id=w.journal_entry_id,
        created_at=w.created_at,
    )


@router.get("/aging", response_model=AgingReportOut)
def aging(
    _: ARRead,
    db: DbSession,
    by: Literal["patient", "insurer"] = "patient",
    as_of: date | None = None,
) -> AgingReportOut:
    """AR aging buckets (0-30, 31-60, 61-90, 90+ days) by patient or by insurer."""
    report = ar.aging(db, by=by, as_of=as_of or _today())
    return AgingReportOut(
        as_of=report.as_of,
        by=by,
        buckets=list(ar.BUCKET_LABELS),
        rows=[
            AgingRowOut(
                party_id=r.party_id, name=r.name, code=r.code, buckets=r.buckets, total=r.total
            )
            for r in report.rows
        ],
        totals=report.totals,
        total=report.total,
    )


@router.post("/dunning/run", response_model=DunningRunOut)
def run_dunning(body: DunningRunIn, actor: Collections, db: DbSession) -> DunningRunOut:
    """Send (simulated) reminders for overdue patient balances; one notice per invoice per level."""
    created = ar.run_dunning(db, actor, as_of=body.as_of or _today())
    return DunningRunOut(created=len(created), notices=[notice_out(n) for n in created])


@router.get("/dunning", response_model=Page[DunningNoticeOut])
def list_notices(
    _: ARRead,
    db: DbSession,
    params: Annotated[PageParams, Depends(page_params)],
    patient_id: int | None = None,
    level: int | None = None,
) -> Page[DunningNoticeOut]:
    rows, total = repo.list_notices(db, params, patient_id=patient_id, level=level)
    return Page(
        items=[notice_out(n) for n in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.post("/write-offs", response_model=WriteOffOut, status_code=status.HTTP_201_CREATED)
def request_write_off(body: WriteOffIn, actor: Collections, db: DbSession) -> WriteOffOut:
    """Request a bad-debt write-off; posts Dr Bad Debt / Cr AR-Patients once approved."""
    write_off = ar.request_write_off(
        db, actor, invoice_id=body.invoice_id, amount=body.amount, reason=body.reason
    )
    return write_off_out(write_off)


@router.get("/write-offs", response_model=Page[WriteOffOut])
def list_write_offs(
    _: ARRead,
    db: DbSession,
    params: Annotated[PageParams, Depends(page_params)],
    status: WriteOffStatus | None = None,
    invoice_id: int | None = None,
) -> Page[WriteOffOut]:
    rows, total = repo.list_write_offs(
        db, params, status=status.value if status else None, invoice_id=invoice_id
    )
    return Page(
        items=[write_off_out(w) for w in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )
