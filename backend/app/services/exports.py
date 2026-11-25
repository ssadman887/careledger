"""CSV and PDF exports of reports and lists.

Every export is a `Table` (title, columns, rows of display-ready strings), rendered either as
CSV (UTF-8 with BOM so spreadsheet apps detect the encoding) or as a PDF table with the
synthetic-data notice. Money stays a plain decimal string ("1250.00") in CSV so it imports
exactly; PDF shows it with thousands separators.

CSV injection: text cells beginning with = + - @ (or tab / carriage return) are prefixed with
an apostrophe so spreadsheets do not evaluate them. Numbers (including negatives) are left as
numbers. Each export is written to the audit log (action `export`).
"""

import csv
import io
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.models.billing import Invoice
from app.services import audit
from app.services.ar import AgingReport
from app.services.audit import Actor
from app.services.budgets import VarianceReport, percent
from app.services.pdf import DEMO_NOTICE, _styles
from app.services.reports import BalanceSheet, IncomeStatement, StatementSection, TrialBalance

ExportFormat = Literal["csv", "pdf"]
ColumnFormat = Literal["text", "money", "count", "percent", "date"]
ZERO = Decimal("0.00")
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    format: ColumnFormat = "text"


@dataclass(frozen=True)
class ExportTable:
    """A report flattened to columns and rows. `emphasis` marks total/section rows (by index)."""

    name: str  # file name stem, e.g. trial-balance-2026-11-25
    title: str
    subtitle: str
    columns: Sequence[Column]
    rows: Sequence[dict[str, str]]
    emphasis: frozenset[int] = frozenset()


def _is_number(value: str) -> bool:
    try:
        Decimal(value)
    except InvalidOperation:
        return False
    return True


def safe_cell(value: str) -> str:
    """Neutralise spreadsheet formulas in text cells (numbers pass through unchanged)."""
    if value.startswith(_FORMULA_START) and not _is_number(value):
        return "'" + value
    return value


def to_csv(table: ExportTable) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow([c.label for c in table.columns])
    for row in table.rows:
        writer.writerow([safe_cell(row.get(c.key, "")) for c in table.columns])
    return ("﻿" + buffer.getvalue()).encode("utf-8")


def _display(value: str, fmt: ColumnFormat) -> str:
    if fmt == "money" and value and _is_number(value):
        return f"{Decimal(value):,.2f}"
    if fmt == "percent" and value:
        return f"{value}%"
    return value


def to_pdf(table: ExportTable) -> bytes:
    s = _styles()
    wide = len(table.columns) > 6
    page = landscape(A4) if wide else A4
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=page,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=table.title,
        author="CareLedger (demo)",
    )
    cell = s["small"].clone("cell", textColor=colors.black, fontSize=8, leading=10)
    data = [[Paragraph(f"<b>{c.label}</b>", cell) for c in table.columns]]
    for row in table.rows:
        data.append(
            [
                Paragraph(
                    _display(row.get(c.key, ""), c.format)
                    .replace("&", "&amp;")
                    .replace("<", "&lt;"),
                    cell,
                )
                for c in table.columns
            ]  # fmt: skip
        )
    usable = page[0] - 28 * mm
    weights = [2.6 if c.format == "text" else 1.0 for c in table.columns]
    widths = [usable * w / sum(weights) for w in weights]
    grid = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef6f5")),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#dddddd")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    for i, c in enumerate(table.columns):
        if c.format != "text":
            style.append(("ALIGN", (i, 0), (i, -1), "RIGHT"))
    for r in table.emphasis:
        style.append(("BACKGROUND", (0, r + 1), (-1, r + 1), colors.HexColor("#f4f4f5")))
    grid.setStyle(TableStyle(style))
    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    doc.build(
        [
            Paragraph(f"CareLedger General Hospital - {table.title}", s["title"]),
            Paragraph(
                DEMO_NOTICE.replace("NOT A REAL INVOICE", "NOT REAL FINANCIAL DATA"), s["notice"]
            ),
            Paragraph(table.subtitle, s["normal"]),
            Spacer(1, 6),
            grid,
            Spacer(1, 8),
            Paragraph(f"Generated {generated} by CareLedger.", s["small"]),
        ]
    )
    return buffer.getvalue()


def render(table: ExportTable, fmt: ExportFormat) -> tuple[bytes, str, str]:
    """(content, media type, file name)."""
    if fmt == "csv":
        return to_csv(table), "text/csv; charset=utf-8", f"{table.name}.csv"
    return to_pdf(table), "application/pdf", f"{table.name}.pdf"


def record_export(
    session: Session,
    actor: Actor,
    table: ExportTable,
    fmt: ExportFormat,
    filters: Mapping[str, object],
) -> None:
    audit.record(
        session,
        actor,
        entity_type="export",
        entity_id=table.name[:64],
        action="export",
        after={"report": table.title, "format": fmt, "rows": len(table.rows), "filters": filters},
    )


# ------------------------------------------------------------------ report adapters


def _m(value: Decimal) -> str:
    return f"{value:.2f}"


def _range(date_from: date | None, date_to: date | None) -> str:
    if date_from and date_to:
        return f"{date_from.isoformat()} to {date_to.isoformat()}"
    if date_to:
        return f"up to {date_to.isoformat()}"
    if date_from:
        return f"from {date_from.isoformat()}"
    return "all dates"


def trial_balance(tb: TrialBalance, stamp: date) -> ExportTable:
    rows = [
        {
            "code": r.code,
            "name": r.name,
            "type": r.type,
            "debit": _m(r.debit),
            "credit": _m(r.credit),
            "balance_debit": _m(r.balance_debit),
            "balance_credit": _m(r.balance_credit),
        }
        for r in tb.rows
    ]
    rows.append(
        {
            "code": "",
            "name": "Totals" + ("" if tb.balanced else " (NOT BALANCED)"),
            "type": "",
            "debit": _m(tb.total_debit),
            "credit": _m(tb.total_credit),
            "balance_debit": _m(tb.total_balance_debit),
            "balance_credit": _m(tb.total_balance_credit),
        }
    )
    return ExportTable(
        f"trial-balance-{stamp.isoformat()}",
        "Trial balance",
        f"Posted entries, {_range(tb.date_from, tb.date_to)}.",
        [
            Column("code", "Code"),
            Column("name", "Account"),
            Column("type", "Type"),
            Column("debit", "Debits", "money"),
            Column("credit", "Credits", "money"),
            Column("balance_debit", "Balance Dr", "money"),
            Column("balance_credit", "Balance Cr", "money"),
        ],
        rows,
        frozenset({len(rows) - 1}),
    )


def _statement_rows(sections: Iterable[StatementSection]) -> tuple[list[dict[str, str]], set[int]]:
    rows: list[dict[str, str]] = []
    emphasis: set[int] = set()
    for sec in sections:
        emphasis.add(len(rows))
        rows.append({"code": "", "name": sec.title, "amount": ""})
        rows += [{"code": ln.code, "name": ln.name, "amount": _m(ln.amount)} for ln in sec.lines]
        emphasis.add(len(rows))
        rows.append({"code": "", "name": f"Total {sec.title.lower()}", "amount": _m(sec.total)})
    return rows, emphasis


STATEMENT_COLUMNS = (
    Column("code", "Code"),
    Column("name", "Line"),
    Column("amount", "Amount", "money"),
)


def income_statement(st: IncomeStatement, stamp: date) -> ExportTable:
    rows, emphasis = _statement_rows([st.revenue, st.expenses])
    emphasis.add(len(rows))
    rows.append({"code": "", "name": "Net income", "amount": _m(st.net_income)})
    return ExportTable(
        f"income-statement-{stamp.isoformat()}",
        "Income statement",
        f"Posted entries, {_range(st.date_from, st.date_to)}.",
        STATEMENT_COLUMNS,
        rows,
        frozenset(emphasis),
    )


def balance_sheet(bs: BalanceSheet) -> ExportTable:
    rows, emphasis = _statement_rows([bs.assets, bs.liabilities, bs.equity])
    emphasis.add(len(rows))
    rows.append(
        {
            "code": "",
            "name": "Total liabilities and equity",
            "amount": _m(bs.total_liabilities_and_equity),
        }
    )
    return ExportTable(
        f"balance-sheet-{bs.as_of.isoformat()}",
        "Balance sheet",
        f"As of {bs.as_of.isoformat()}." + ("" if bs.balanced else " WARNING: not balanced."),
        STATEMENT_COLUMNS,
        rows,
        frozenset(emphasis),
    )


def aging(report: AgingReport) -> ExportTable:
    buckets = list(report.totals)
    party = "Patient" if report.by == "patient" else "Insurer"
    rows = [
        {"party": r.name, "code": r.code, **{b: _m(r.buckets.get(b, ZERO)) for b in buckets},
         "total": _m(r.total)}
        for r in report.rows
    ]  # fmt: skip
    rows.append(
        {
            "party": "Totals",
            "code": "",
            **{b: _m(report.totals[b]) for b in buckets},
            "total": _m(report.total),
        }
    )
    return ExportTable(
        f"ar-aging-{report.by}-{report.as_of.isoformat()}",
        f"Accounts receivable aging by {report.by}",
        f"Outstanding as of {report.as_of.isoformat()}, from the ledger (ties to the GL balance).",
        [
            Column("party", party),
            Column("code", "Reference"),
            *[Column(b, f"{b} days", "money") for b in buckets],
            Column("total", "Total", "money"),
        ],  # fmt: skip
        rows,
        frozenset({len(rows) - 1}),
    )


def variance(report: VarianceReport) -> ExportTable:
    b, t = report.budget, report.through_month
    rows = [
        {
            "code": r.account.code,
            "name": r.account.name,
            "type": r.account.type,
            "annual": _m(r.annual_budget),
            "budget_ytd": _m(r.budget_ytd(t)),
            "actual_ytd": _m(r.actual_ytd(t)),
            "variance": _m(r.variance_ytd(t)),
            "used": str(percent(r.actual_ytd(t), r.budget_ytd(t)) or ""),
        }
        for r in report.rows
    ]
    return ExportTable(
        f"budget-variance-{b.year}-{b.department.code.lower()}-m{t:02d}",
        f"Budget variance: {b.name}",
        f"{b.department.name}, {b.year}, year to date through month {t}. "
        "Positive variance is favourable.",
        [
            Column("code", "Code"),
            Column("name", "Account"),
            Column("type", "Type"),
            Column("annual", "Annual budget", "money"),
            Column("budget_ytd", "Budget YTD", "money"),
            Column("actual_ytd", "Actual YTD", "money"),
            Column("variance", "Variance", "money"),
            Column("used", "Used", "percent"),
        ],
        rows,
    )


def audit_log(entries: Sequence[AuditLog], filters_text: str) -> ExportTable:
    rows = [
        {
            "when": e.occurred_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S"),
            "actor": e.actor_label,
            "action": e.action,
            "entity_type": e.entity_type,
            "entity_id": e.entity_id,
            "request_id": e.request_id or "",
        }
        for e in entries
    ]
    return ExportTable(
        f"audit-log-{datetime.now(UTC).date().isoformat()}",
        "Audit log",
        filters_text,
        [
            Column("when", "When (UTC)", "date"),
            Column("actor", "Actor"),
            Column("action", "Action"),
            Column("entity_type", "Record type"),
            Column("entity_id", "Record id"),
            Column("request_id", "Request"),
        ],
        rows,
    )


def invoices(rows_: Sequence[Invoice], filters_text: str) -> ExportTable:
    rows = [
        {
            "number": inv.invoice_number,
            "date": inv.invoice_date.isoformat() if inv.invoice_date else "",
            "due": inv.due_date.isoformat() if inv.due_date else "",
            "patient": inv.patient.full_name,
            "mrn": inv.patient.mrn,
            "status": inv.status,
            "total": _m(inv.total),
            "paid": _m(inv.amount_paid),
            "insurance_pending": _m(inv.insurance_pending),
            "patient_due": _m(inv.patient_due),
        }
        for inv in rows_
    ]
    return ExportTable(
        f"invoices-{datetime.now(UTC).date().isoformat()}",
        "Invoices",
        filters_text,
        [
            Column("number", "Invoice"),
            Column("date", "Date", "date"),
            Column("due", "Due", "date"),
            Column("patient", "Patient"),
            Column("mrn", "MRN"),
            Column("status", "Status"),
            Column("total", "Total", "money"),
            Column("paid", "Paid", "money"),
            Column("insurance_pending", "With insurer", "money"),
            Column("patient_due", "Patient due", "money"),
        ],
        rows,
    )
