"""CSV and PDF exports. Same role checks as the reports and lists they export; audited."""

from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Response

from app.core.deps import DbSession, read_roles
from app.core.errors import ErrorEnvelope
from app.core.pagination import PageParams
from app.models.billing import InvoiceStatus
from app.models.identity import RoleName
from app.repositories import audit as audit_repo
from app.repositories import billing as billing_repo
from app.services import ar, budgets, exports, reports
from app.services.audit import Actor
from app.services.exports import ExportFormat, ExportTable

router = APIRouter(
    prefix="/exports",
    tags=["exports"],
    responses={
        401: {"model": ErrorEnvelope},
        403: {"model": ErrorEnvelope},
        404: {"model": ErrorEnvelope},
        422: {"model": ErrorEnvelope},
    },
)

R = RoleName
LedgerRead = Annotated[Actor, Depends(read_roles(R.ACCOUNTANT, R.FINANCE_MANAGER))]
ARRead = Annotated[
    Actor,
    Depends(read_roles(R.BILLING_CLERK, R.INSURANCE_OFFICER, R.FINANCE_MANAGER, R.ACCOUNTANT)),
]
AuditRead = Annotated[Actor, Depends(read_roles(R.ADMIN, R.FINANCE_MANAGER))]
Fmt = Annotated[Literal["csv", "pdf"], Query(description="csv or pdf")]
FILE_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {
        "content": {"text/csv": {}, "application/pdf": {}},
        "description": "The exported file",
    }
}
MAX_ROWS = 5000  # list exports are capped; narrow the filters for more


def _today() -> date:
    return datetime.now(UTC).date()


def _send(
    db: DbSession,
    actor: Actor,
    table: ExportTable,
    fmt: ExportFormat,
    filters: Mapping[str, object],
) -> Response:
    content, media_type, filename = exports.render(table, fmt)
    exports.record_export(db, actor, table, fmt, filters)
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/trial-balance", response_class=Response, responses=FILE_RESPONSES)
def trial_balance(
    actor: LedgerRead,
    db: DbSession,
    format: Fmt = "csv",
    date_from: date | None = None,
    date_to: date | None = None,
) -> Response:
    tb = reports.trial_balance(db, date_from, date_to)
    table = exports.trial_balance(tb, date_to or _today())
    return _send(db, actor, table, format, {"date_from": date_from, "date_to": date_to})


@router.get("/income-statement", response_class=Response, responses=FILE_RESPONSES)
def income_statement(
    actor: LedgerRead,
    db: DbSession,
    format: Fmt = "csv",
    date_from: date | None = None,
    date_to: date | None = None,
) -> Response:
    st = reports.income_statement(db, date_from, date_to)
    table = exports.income_statement(st, date_to or _today())
    return _send(db, actor, table, format, {"date_from": date_from, "date_to": date_to})


@router.get("/balance-sheet", response_class=Response, responses=FILE_RESPONSES)
def balance_sheet(
    actor: LedgerRead, db: DbSession, format: Fmt = "csv", as_of: date | None = None
) -> Response:
    on = as_of or _today()
    table = exports.balance_sheet(reports.balance_sheet(db, on))
    return _send(db, actor, table, format, {"as_of": on})


@router.get("/ar-aging", response_class=Response, responses=FILE_RESPONSES)
def ar_aging(
    actor: ARRead,
    db: DbSession,
    format: Fmt = "csv",
    by: Literal["patient", "insurer"] = "patient",
    as_of: date | None = None,
) -> Response:
    on = as_of or _today()
    table = exports.aging(ar.aging(db, by=by, as_of=on))
    return _send(db, actor, table, format, {"by": by, "as_of": on})


@router.get("/budgets/{budget_id}/variance", response_class=Response, responses=FILE_RESPONSES)
def budget_variance(
    budget_id: int,
    actor: LedgerRead,
    db: DbSession,
    format: Fmt = "csv",
    through_month: Annotated[int, Query(ge=1, le=12)] = 12,
) -> Response:
    table = exports.variance(budgets.variance(db, budget_id, through_month=through_month))
    return _send(db, actor, table, format, {"budget_id": budget_id, "through_month": through_month})


@router.get("/audit-log", response_class=Response, responses=FILE_RESPONSES)
def audit_log(
    actor: AuditRead,
    db: DbSession,
    format: Fmt = "csv",
    entity_type: Annotated[str | None, Query(max_length=64)] = None,
    action: Annotated[str | None, Query(max_length=64)] = None,
    actor_label: Annotated[str | None, Query(max_length=255)] = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> Response:
    rows, total = audit_repo.list_entries(
        db,
        PageParams(page=1, page_size=MAX_ROWS, sort=None),
        entity_type=entity_type,
        entity_id=None,
        actor_id=None,
        action=action,
        date_from=date_from,
        date_to=date_to,
        actor_label=actor_label,
    )
    filters = {
        "entity_type": entity_type,
        "action": action,
        "actor": actor_label,
        "date_from": date_from,
        "date_to": date_to,
    }
    shown = ", ".join(f"{k}={v}" for k, v in filters.items() if v) or "no filters"
    note = f" Showing the newest {MAX_ROWS} of {total}." if total > MAX_ROWS else ""
    table = exports.audit_log(rows, f"Filters: {shown}. {len(rows)} entries.{note}")
    return _send(db, actor, table, format, filters)


@router.get("/invoices", response_class=Response, responses=FILE_RESPONSES)
def invoices(
    actor: ARRead,
    db: DbSession,
    format: Fmt = "csv",
    status: InvoiceStatus | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    overdue: bool = False,
) -> Response:
    rows, total = billing_repo.list_invoices(
        db,
        PageParams(page=1, page_size=MAX_ROWS, sort="-invoice_date"),
        status=status.value if status else None,
        patient_id=None,
        search=None,
        date_from=date_from,
        date_to=date_to,
        overdue=overdue,
    )
    filters = {
        "status": status.value if status else None,
        "date_from": date_from,
        "date_to": date_to,
        "overdue": overdue,
    }
    shown = ", ".join(f"{k}={v}" for k, v in filters.items() if v) or "no filters"
    table = exports.invoices(rows, f"Filters: {shown}. {len(rows)} of {total} invoices.")
    return _send(db, actor, table, format, filters)
