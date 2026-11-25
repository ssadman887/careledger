from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status

from app.api.v1.insurance_presenters import claim_out, claim_summary
from app.core.deps import DbSession, read_roles, require_roles
from app.core.errors import ErrorEnvelope, ValidationFailed
from app.core.pagination import Page, PageParams, page_params
from app.models.identity import RoleName
from app.models.insurance import Claim, ClaimStatus
from app.repositories import insurance as repo
from app.schemas.insurance import (
    AdjudicateIn,
    BatchResultOut,
    ClaimAttachmentOut,
    ClaimCountsOut,
    ClaimCreate,
    ClaimOut,
    ClaimSummaryOut,
    CoveragePreviewOut,
    NoteIn,
    RequiredNoteIn,
)
from app.services import claim_attachments, claims, mock_insurer
from app.services.audit import Actor

router = APIRouter(
    prefix="/claims",
    tags=["claims"],
    responses={
        401: {"model": ErrorEnvelope},
        403: {"model": ErrorEnvelope},
        404: {"model": ErrorEnvelope},
        409: {"model": ErrorEnvelope},
        422: {"model": ErrorEnvelope},
    },
)

R = RoleName
ClaimRead = Annotated[
    Actor,
    Depends(read_roles(R.INSURANCE_OFFICER, R.BILLING_CLERK, R.FINANCE_MANAGER, R.ACCOUNTANT)),
]
ClaimDraft = Annotated[Actor, Depends(require_roles(R.BILLING_CLERK, R.INSURANCE_OFFICER))]
ClaimWork = Annotated[Actor, Depends(require_roles(R.INSURANCE_OFFICER))]
MAX_UPLOAD = claim_attachments.MAX_BYTES


def _out(db: DbSession, claim: Claim, actor: Actor) -> ClaimOut:
    code = repo.get_denial_code(db, claim.denial_code) if claim.denial_code else None
    return claim_out(
        claim, repo.attachments(db, claim.id), actor, code.description if code else None
    )


@router.get("", response_model=Page[ClaimSummaryOut])
def list_claims(
    _: ClaimRead,
    db: DbSession,
    params: Annotated[PageParams, Depends(page_params)],
    status: ClaimStatus | None = None,
    insurer_id: int | None = None,
    patient_id: int | None = None,
    invoice_id: int | None = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> Page[ClaimSummaryOut]:
    rows, total = repo.list_claims(
        db,
        params,
        status=status.value if status else None,
        insurer_id=insurer_id,
        patient_id=patient_id,
        invoice_id=invoice_id,
        search=search,
        date_from=date_from,
        date_to=date_to,
    )
    return Page(
        items=[claim_summary(c) for c in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.get("/counts", response_model=ClaimCountsOut)
def claim_counts(_: ClaimRead, db: DbSession) -> ClaimCountsOut:
    return ClaimCountsOut(counts=repo.claim_status_counts(db))


@router.get("/preview", response_model=CoveragePreviewOut)
def coverage_preview(
    invoice_id: int, policy_id: int, _: ClaimRead, db: DbSession
) -> CoveragePreviewOut:
    """How the invoice would split between insurer and patient under this policy (no changes)."""
    pv = claims.preview(db, invoice_id=invoice_id, policy_id=policy_id)
    r = pv.result
    return CoveragePreviewOut(
        policy_id=pv.policy_id,
        invoice_id=pv.invoice_id,
        billed=r.billed,
        collectible=pv.collectible,
        deductible_met_before=pv.deductible_met,
        insurer_used_before=pv.insurer_used,
        copay=r.copay,
        deductible=r.deductible,
        coinsurance=r.coinsurance,
        over_limit=r.over_limit,
        insurer_amount=r.insurer,
        patient_amount=r.patient,
    )


@router.post("", response_model=ClaimOut, status_code=status.HTTP_201_CREATED)
def create_claim(body: ClaimCreate, actor: ClaimDraft, db: DbSession) -> ClaimOut:
    return _out(
        db,
        claims.create_claim(db, actor, invoice_id=body.invoice_id, policy_id=body.policy_id),
        actor,
    )


@router.post("/run-mock-insurer", response_model=BatchResultOut)
def run_mock_insurer(actor: ClaimWork, db: DbSession) -> BatchResultOut:
    """Adjudicate every submitted or appealed claim with the mock insurer."""
    done = mock_insurer.run_batch(db, actor)
    return BatchResultOut(processed=len(done), claims=[claim_summary(c) for c in done])


@router.get("/{claim_id}", response_model=ClaimOut)
def get_claim(claim_id: int, actor: ClaimRead, db: DbSession) -> ClaimOut:
    return _out(db, claims.get_claim(db, claim_id), actor)


@router.post("/{claim_id}/submit", response_model=ClaimOut)
def submit_claim(claim_id: int, actor: ClaimWork, db: DbSession) -> ClaimOut:
    """Submit to the insurer: moves the insurer share from AR-Patients to AR-Insurers."""
    return _out(db, claims.submit_claim(db, actor, claim_id), actor)


@router.post("/{claim_id}/cancel", response_model=ClaimOut)
def cancel_claim(claim_id: int, body: NoteIn, actor: ClaimDraft, db: DbSession) -> ClaimOut:
    return _out(db, claims.cancel_claim(db, actor, claim_id, body.note), actor)


@router.post("/{claim_id}/adjudicate", response_model=ClaimOut)
def adjudicate_claim(
    claim_id: int, body: AdjudicateIn, actor: ClaimWork, db: DbSession
) -> ClaimOut:
    """Mock insurer decision for one claim (deterministic unless `outcome` is given)."""
    claim = mock_insurer.adjudicate(
        db,
        actor,
        claim_id,
        outcome=body.outcome,
        approved_amount=body.approved_amount,
        denial_code=body.denial_code,
    )
    return _out(db, claim, actor)


@router.post("/{claim_id}/appeal", response_model=ClaimOut)
def appeal_claim(claim_id: int, body: RequiredNoteIn, actor: ClaimWork, db: DbSession) -> ClaimOut:
    return _out(db, claims.appeal_claim(db, actor, claim_id, body.note), actor)


@router.post("/{claim_id}/close", response_model=ClaimOut)
def close_claim(claim_id: int, body: NoteIn, actor: ClaimWork, db: DbSession) -> ClaimOut:
    """Close a denied claim; the insurer share returns to the patient's balance."""
    return _out(db, claims.close_claim(db, actor, claim_id, body.note), actor)


@router.post("/{claim_id}/accept-short-pay", response_model=ClaimOut)
def accept_short_pay(claim_id: int, body: NoteIn, actor: ClaimWork, db: DbSession) -> ClaimOut:
    return _out(db, claims.accept_short_pay(db, actor, claim_id, body.note), actor)


@router.post("/{claim_id}/notes", response_model=ClaimOut)
def add_note(claim_id: int, body: RequiredNoteIn, actor: ClaimDraft, db: DbSession) -> ClaimOut:
    return _out(db, claims.add_note(db, actor, claim_id, body.note), actor)


@router.post(
    "/{claim_id}/attachments",
    response_model=ClaimAttachmentOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_attachment(
    claim_id: int, actor: ClaimWork, db: DbSession, file: Annotated[UploadFile, File()]
) -> ClaimAttachmentOut:
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise ValidationFailed("Files must be 5 MB or smaller", code="invalid_file_size")
    attachment = claim_attachments.add_attachment(
        db,
        actor,
        claim_id,
        filename=file.filename or "attachment",
        content_type=(file.content_type or "").split(";")[0].strip(),
        data=data,
    )
    return ClaimAttachmentOut.model_validate(attachment)


@router.get(
    "/{claim_id}/attachments/{attachment_id}",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
def download_attachment(claim_id: int, attachment_id: int, _: ClaimRead, db: DbSession) -> Response:
    attachment = claim_attachments.get_attachment(db, claim_id, attachment_id)
    headers: dict[str, Any] = {
        "Content-Disposition": f'attachment; filename="{attachment.filename}"',
        "X-Content-Type-Options": "nosniff",
    }
    return Response(content=attachment.data, media_type=attachment.content_type, headers=headers)
