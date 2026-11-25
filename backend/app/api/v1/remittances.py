from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Header, UploadFile, status

from app.api.v1.insurance_presenters import remittance_out, remittance_summary
from app.core.deps import DbSession, read_roles, require_roles
from app.core.errors import ErrorEnvelope, ValidationFailed
from app.core.pagination import Page, PageParams, page_params
from app.models.identity import RoleName
from app.models.insurance import RemittanceStatus
from app.repositories import insurance as repo
from app.schemas.insurance import RemittanceOut, RemittanceSummaryOut
from app.services import idempotency, remittances
from app.services.audit import Actor

router = APIRouter(
    prefix="/remittances",
    tags=["remittances"],
    responses={
        401: {"model": ErrorEnvelope},
        403: {"model": ErrorEnvelope},
        404: {"model": ErrorEnvelope},
        409: {"model": ErrorEnvelope},
        422: {"model": ErrorEnvelope},
    },
)

R = RoleName
RemitRead = Annotated[
    Actor, Depends(read_roles(R.INSURANCE_OFFICER, R.FINANCE_MANAGER, R.ACCOUNTANT))
]
RemitWrite = Annotated[Actor, Depends(require_roles(R.INSURANCE_OFFICER))]
IdemKey = Annotated[str | None, Header(alias="Idempotency-Key")]


@router.get("", response_model=Page[RemittanceSummaryOut])
def list_remittances(
    _: RemitRead,
    db: DbSession,
    params: Annotated[PageParams, Depends(page_params)],
    insurer_id: int | None = None,
    status: RemittanceStatus | None = None,
) -> Page[RemittanceSummaryOut]:
    rows, total = repo.list_remittances(
        db, params, insurer_id=insurer_id, status=status.value if status else None
    )
    return Page(
        items=[remittance_summary(r) for r in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.post("", response_model=RemittanceOut, status_code=status.HTTP_201_CREATED)
async def import_remittance(
    actor: RemitWrite,
    db: DbSession,
    insurer_id: Annotated[int, Form()],
    reference: Annotated[str, Form(min_length=1, max_length=80)],
    payment_date: Annotated[date, Form()],
    file: Annotated[UploadFile, File(description="CSV: claim_number,paid_amount[,remark]")],
    expected_total: Annotated[str | None, Form(description="Optional EFT total to check")] = None,
) -> RemittanceOut:
    """Import a remittance CSV and reconcile it against claims (nothing is posted yet)."""
    raw = await file.read(remittances.MAX_BYTES + 1)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationFailed("File must be UTF-8 CSV", code="invalid_csv") from exc
    total: Decimal | None = None
    if expected_total:
        try:
            total = Decimal(expected_total)
        except InvalidOperation as exc:
            raise ValidationFailed(
                "expected_total is not a valid amount", code="invalid_amount"
            ) from exc
    remittance = remittances.import_remittance(
        db,
        actor,
        insurer_id=insurer_id,
        reference=reference,
        payment_date=payment_date,
        filename=file.filename or "remittance.csv",
        csv_text=text,
        expected_total=total,
    )
    return remittance_out(remittance)


@router.get("/{remittance_id}", response_model=RemittanceOut)
def get_remittance(remittance_id: int, _: RemitRead, db: DbSession) -> RemittanceOut:
    return remittance_out(remittances.get_remittance(db, remittance_id))


@router.post("/{remittance_id}/post", response_model=RemittanceOut)
def post_remittance(
    remittance_id: int, actor: RemitWrite, db: DbSession, idempotency_key: IdemKey = None
) -> dict[str, Any]:
    """Post matched and short-paid lines: Dr Bank / Cr AR-Insurers, one payment per line."""

    def run() -> dict[str, Any]:
        return remittance_out(remittances.post_remittance(db, actor, remittance_id)).model_dump(
            mode="json"
        )

    return idempotency.execute(
        db,
        actor,
        scope=f"remittance-post:{remittance_id}",
        key=idempotency_key,
        payload={"remittance_id": remittance_id},
        run=run,
    )
