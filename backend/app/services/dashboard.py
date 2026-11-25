"""Role-aware dashboard: sections of KPIs, charts and small tables built from SQL aggregates.

Which sections a user receives is decided here (backend authorization), not by the UI:
  finance        accountant, finance manager, auditor
  revenue        billing clerk, finance manager, auditor
  insurance      insurance officer, finance manager, auditor
  administration admin, auditor
Money values are Decimal strings; the UI only converts them to numbers to draw charts.
"""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.models.identity import RoleName
from app.repositories import approvals as approvals_repo
from app.repositories import dashboard as repo
from app.services.audit import Actor

R = RoleName
ZERO = Decimal("0.00")
Format = Literal["money", "count", "percent", "text", "date"]
ChartKind = Literal["bar", "line", "area", "donut", "hbar"]

SECTION_ROLES: dict[str, frozenset[str]] = {
    "finance": frozenset({R.ACCOUNTANT, R.FINANCE_MANAGER, R.AUDITOR}),
    "revenue": frozenset({R.BILLING_CLERK, R.FINANCE_MANAGER, R.AUDITOR}),
    "insurance": frozenset({R.INSURANCE_OFFICER, R.FINANCE_MANAGER, R.AUDITOR}),
    "administration": frozenset({R.ADMIN, R.AUDITOR}),
}


@dataclass(frozen=True)
class Kpi:
    key: str
    label: str
    value: str
    format: Format
    hint: str = ""
    href: str = ""
    tone: Literal["default", "good", "warning", "bad"] = "default"


@dataclass(frozen=True)
class SeriesKey:
    key: str
    label: str
    format: Format = "money"


@dataclass(frozen=True)
class ChartRow:
    label: str
    values: dict[str, str]


@dataclass(frozen=True)
class Chart:
    id: str
    title: str
    kind: ChartKind
    keys: list[SeriesKey]
    rows: list[ChartRow]
    description: str = ""


@dataclass(frozen=True)
class TableColumn:
    key: str
    label: str
    format: Format = "text"


@dataclass(frozen=True)
class SmallTable:
    id: str
    title: str
    columns: list[TableColumn]
    rows: list[dict[str, str]]


@dataclass
class Section:
    id: str
    title: str
    description: str
    kpis: list[Kpi] = field(default_factory=list)
    charts: list[Chart] = field(default_factory=list)
    tables: list[SmallTable] = field(default_factory=list)


@dataclass(frozen=True)
class Dashboard:
    as_of: date
    sections: list[Section]


def _m(value: Decimal) -> str:
    return f"{value:.2f}"


def _n(value: Decimal) -> str:
    """Money for prose (hints): thousands separators, two decimals."""
    return f"{value:,.2f}"


def _pct(part: Decimal | int, whole: Decimal | int) -> str:
    if not whole:
        return "0.0"
    return str((Decimal(part) * 100 / Decimal(whole)).quantize(Decimal("0.1"), ROUND_HALF_UP))


def _month_label(d: date) -> str:
    return d.strftime("%b %Y")


def _months_back(as_of: date, n: int) -> date:
    """First day of the month n-1 months before as_of's month (n months inclusive)."""
    y, m = as_of.year, as_of.month - (n - 1)
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1)


def finance_section(session: Session, actor: Actor, as_of: date) -> Section:
    year_start, month_start = date(as_of.year, 1, 1), as_of.replace(day=1)
    bal = repo.balances(session, ["1010", "1020", "1030", "1100", "1110", "2010"], as_of)
    cash = bal["1010"] + bal["1020"] + bal["1030"]
    ytd = repo.profit_and_loss(session, year_start, as_of)
    mtd = repo.profit_and_loss(session, month_start, as_of)
    net = ytd.revenue - ytd.expenses
    pending = approvals_repo.pending_count(session, sorted(actor.roles))
    alerts = repo.budget_alert_count(session, as_of.year)
    section = Section(
        "finance",
        "Financial position",
        f"Ledger balances as of {as_of.isoformat()}; year to date from {year_start.isoformat()}.",
        kpis=[
            Kpi(
                "cash", "Cash and bank", _m(cash), "money", "Accounts 1010, 1020, 1030", "/reports"
            ),
            Kpi(
                "ar",
                "Receivables",
                _m(bal["1100"] + bal["1110"]),
                "money",
                f"Patients {_n(bal['1100'])} · insurers {_n(bal['1110'])}",
                "/ar",
            ),  # fmt: skip
            Kpi("ap", "Payables", _m(-bal["2010"]), "money", "Account 2010", "/payables"),
            Kpi(
                "revenue_ytd",
                "Net revenue YTD",
                _m(ytd.revenue),
                "money",
                f"This month {_n(mtd.revenue)}",
                "/reports",
            ),  # fmt: skip
            Kpi(
                "expenses_ytd",
                "Expenses YTD",
                _m(ytd.expenses),
                "money",
                f"This month {_n(mtd.expenses)}",
                "/reports",
            ),  # fmt: skip
            Kpi(
                "net_income_ytd",
                "Net income YTD",
                _m(net),
                "money",
                "Revenue minus expenses",
                "/reports",
                "good" if net >= 0 else "bad",
            ),  # fmt: skip
            Kpi(
                "pending_approvals",
                "Waiting for you",
                str(pending),
                "count",
                "Approval requests you can decide",
                "/approvals",
                "warning" if pending else "default",
            ),  # fmt: skip
            Kpi(
                "budget_alerts",
                "Budget alerts",
                str(alerts),
                "count",
                f"Raised in {as_of.year}",
                "/budgets",
                "warning" if alerts else "default",
            ),  # fmt: skip
        ],
    )
    trend = repo.monthly_pl(session, _months_back(as_of, 12), as_of)
    section.charts.append(
        Chart(
            "pl_trend",
            "Revenue and expenses, last 12 months",
            "bar",
            [SeriesKey("revenue", "Revenue"), SeriesKey("expenses", "Expenses")],
            [
                ChartRow(
                    _month_label(t.month), {"revenue": _m(t.revenue), "expenses": _m(t.expenses)}
                )
                for t in trend
            ],
        )
    )
    section.charts.append(
        Chart(
            "revenue_by_department",
            "Net revenue by department, year to date",
            "hbar",
            [SeriesKey("revenue", "Revenue")],
            [
                ChartRow(name, {"revenue": _m(v)})
                for name, v in repo.revenue_by_department(session, year_start, as_of)
            ],
        )
    )
    # Budgets are compared through the last complete month (the current one is still posting).
    through = max(as_of.month - 1, 1)
    uses = repo.budget_utilisation(session, as_of.year, through)
    if uses:
        section.charts.append(
            Chart(
                "budget_use",
                f"Expense budget used, year to date through {date(as_of.year, through, 1):%B}",
                "hbar",
                [SeriesKey("used", "Used", "percent")],
                [ChartRow(u.department, {"used": _pct(u.actual_ytd, u.budget_ytd)}) for u in uses],
                "Actual expense as a percentage of the year-to-date expense budget.",
            )
        )
    return section


def revenue_section(session: Session, as_of: date) -> Section:
    year_start, month_start = date(as_of.year, 1, 1), as_of.replace(day=1)
    count, amount = repo.invoices_issued(session, month_start, as_of)
    collected = repo.collections(session, month_start, as_of)
    outstanding, overdue_n, overdue_amt = repo.patient_receivables(session, as_of)
    section = Section(
        "revenue",
        "Revenue cycle",
        "Invoicing, collections and patient balances.",
        kpis=[
            Kpi(
                "invoices_mtd",
                "Invoiced this month",
                _m(amount),
                "money",
                f"{count} invoices",
                "/invoices",
            ),
            Kpi(
                "collections_mtd",
                "Collected this month",
                _m(collected),
                "money",
                "Patient payments net of refunds",
                "/payments",
            ),  # fmt: skip
            Kpi("patient_ar", "Patient balances", _m(outstanding), "money", "Open invoices", "/ar"),
            Kpi(
                "overdue",
                "Overdue",
                _m(overdue_amt),
                "money",
                f"{overdue_n} invoices past due",
                "/ar?tab=dunning",
                "bad" if overdue_n else "good",
            ),  # fmt: skip
        ],
    )
    section.charts.append(
        Chart(
            "collections_trend",
            "Money received, last 6 months",
            "area",
            [SeriesKey("amount", "Received")],
            [
                ChartRow(_month_label(m), {"amount": _m(v)})
                for m, v in repo.collections_by_month(session, _months_back(as_of, 6), as_of)
            ],
            "All payments including insurer remittances, net of refunds.",
        )
    )
    section.charts.append(
        Chart(
            "payment_mix",
            "Payment methods, year to date",
            "donut",
            [SeriesKey("amount", "Amount")],
            [
                ChartRow(method.replace("_", " ").title(), {"amount": _m(v)})
                for method, v in repo.payment_mix(session, year_start, as_of)
            ],  # fmt: skip
        )
    )
    return section


def insurance_section(session: Session) -> Section:
    by_status = repo.claims_by_status(session)
    stats = repo.denial_stats(session)
    open_claims = sum(n for s, n, _ in by_status if s in ("submitted", "under_review", "appealed"))
    section = Section(
        "insurance",
        "Insurance claims",
        "Claim pipeline, insurer balances and denials.",
        kpis=[
            Kpi(
                "claims_open",
                "Claims with insurers",
                str(open_claims),
                "count",
                "Submitted, under review or appealed",
                "/claims",
            ),  # fmt: skip
            Kpi(
                "insurer_outstanding",
                "Awaiting insurer payment",
                _m(stats.outstanding),
                "money",
                "Claimed minus paid and adjusted",
                "/ar?tab=insurers",
            ),  # fmt: skip
            Kpi(
                "denial_rate",
                "Denial rate",
                _pct(stats.denied, stats.adjudicated),
                "percent",
                f"{stats.denied} of {stats.adjudicated} adjudicated claims",
                "/claims",
                "warning"
                if stats.adjudicated and stats.denied * 10 > stats.adjudicated
                else "default",
            ),  # fmt: skip
        ],
    )
    section.charts.append(
        Chart(
            "claims_by_status",
            "Claims by status",
            "bar",
            [SeriesKey("count", "Claims", "count"), SeriesKey("amount", "Insurer amount")],
            [
                ChartRow(s.replace("_", " ").capitalize(), {"count": str(n), "amount": _m(v)})
                for s, n, v in by_status
            ],  # fmt: skip
        )
    )
    section.tables.append(
        SmallTable(
            "top_denials",
            "Most common denial reasons",
            [
                TableColumn("code", "Code"),
                TableColumn("description", "Reason"),
                TableColumn("count", "Claims", "count"),
            ],  # fmt: skip
            [
                {"code": c, "description": d, "count": str(n)}
                for c, d, n in repo.top_denials(session)
            ],
        )
    )
    return section


def administration_section(session: Session, as_of: date) -> Section:
    first = as_of - timedelta(days=6)
    since = datetime.combine(first, time.min, tzinfo=UTC)
    by_day = repo.audit_by_day(session, first, as_of)
    section = Section(
        "administration",
        "System activity",
        "Users and audit trail over the last 7 days.",
        kpis=[
            Kpi(
                "active_users",
                "Active users",
                str(repo.active_users(session)),
                "count",
                "",
                "/admin/users",
            ),
            Kpi(
                "audit_7d",
                "Audited changes, 7 days",
                str(sum(n for _, n in by_day)),
                "count",
                "",
                "/audit",
            ),
        ],
    )
    section.charts.append(
        Chart(
            "audit_by_day",
            "Audited changes per day",
            "line",
            [SeriesKey("events", "Changes", "count")],
            [ChartRow(d.strftime("%a %d"), {"events": str(n)}) for d, n in by_day],
        )
    )
    section.charts.append(
        Chart(
            "audit_by_action",
            "Most frequent actions, 7 days",
            "hbar",
            [SeriesKey("events", "Changes", "count")],
            [
                ChartRow(a.replace("_", " "), {"events": str(n)})
                for a, n in repo.audit_by_action(session, since)
            ],
        )
    )
    recent = session.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(8)).all()
    section.tables.append(
        SmallTable(
            "recent_activity",
            "Latest activity",
            [
                TableColumn("when", "When", "date"),
                TableColumn("actor", "Who"),
                TableColumn("action", "Action"),
                TableColumn("entity", "Record"),
            ],  # fmt: skip
            [
                {
                    "when": a.occurred_at.isoformat(),
                    "actor": a.actor_label,
                    "action": a.action.replace("_", " "),
                    "entity": f"{a.entity_type.replace('_', ' ')} #{a.entity_id}",
                }
                for a in recent
            ],
        )
    )
    return section


def build(session: Session, actor: Actor, as_of: date) -> Dashboard:
    allowed = {k for k, roles in SECTION_ROLES.items() if actor.roles & roles}
    sections: list[Section] = []
    if "finance" in allowed:
        sections.append(finance_section(session, actor, as_of))
    if "revenue" in allowed:
        sections.append(revenue_section(session, as_of))
    if "insurance" in allowed:
        sections.append(insurance_section(session))
    if "administration" in allowed:
        sections.append(administration_section(session, as_of))
    return Dashboard(as_of=as_of, sections=sections)
