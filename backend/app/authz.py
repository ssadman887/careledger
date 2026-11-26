"""Authorization matrix derived from the live route table (python -m app.authz writes
docs/AUTHORIZATION.md). Tests use the same introspection to prove every route is protected."""

import sys
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

from app.core.deps import current_actor

# Routes that must work without a signed-in user.
PUBLIC = frozenset(
    {
        ("GET", "/api/v1/health"),
        ("POST", "/api/v1/auth/login"),
        ("POST", "/api/v1/auth/refresh"),
        ("POST", "/api/v1/auth/logout"),
    }
)
ROLE_ORDER = (
    "admin",
    "billing_clerk",
    "insurance_officer",
    "accountant",
    "finance_manager",
    "auditor",
)


@dataclass(frozen=True)
class RouteAccess:
    method: str
    path: str
    authenticated: bool
    roles: frozenset[str] | None  # None = any signed-in user
    summary: str

    @property
    def public(self) -> bool:
        return (self.method, self.path) in PUBLIC


def _walk(dep: Dependant) -> list[Dependant]:
    out = [dep]
    for sub in dep.dependencies:
        out += _walk(sub)
    return out


def routes(app: FastAPI) -> list[RouteAccess]:
    out = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        deps = _walk(route.dependant)
        calls = [d.call for d in deps if d.call is not None]
        authenticated = any(c is current_actor for c in calls)
        role_sets = [frozenset(c.allowed_roles) for c in calls if hasattr(c, "allowed_roles")]
        roles: frozenset[str] | None = None
        for rs in role_sets:  # several role dependencies must all pass
            roles = rs if roles is None else roles & rs
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            out.append(
                RouteAccess(method, route.path, authenticated, roles, route.summary or route.name)
            )
    return sorted(out, key=lambda r: (r.path, r.method))


def markdown(app: FastAPI) -> str:
    rows = routes(app)
    lines = [
        "# Authorization matrix",
        "",
        "Generated from the route table by `python -m app.authz` (do not edit by hand; a test",
        "fails when it is out of date). Enforcement is in the backend; the UI only hides",
        "affordances. ✓ = allowed. *Any user* = any signed-in user (content may still be",
        "filtered by role, e.g. dashboard sections, search groups, own notifications).",
        "Service-level rules not visible here: segregation of duties (requesters never approve",
        "their own requests), finance-manager-only voids of posted bills, masking of sensitive",
        "fields for roles that do not need them, and record-level checks on approvals (visible",
        "to the requester, holders of the approver role and oversight roles; decisions need the",
        "approver role; auditors are read-only).",
        "",
        "| Method | Path | " + " | ".join(ROLE_ORDER) + " |",
        "|---|---|" + "---|" * len(ROLE_ORDER),
    ]
    for r in rows:
        if r.public:
            cells = ["public"] + [""] * (len(ROLE_ORDER) - 1)
        elif r.roles is None:
            cells = ["*any user*"] + [""] * (len(ROLE_ORDER) - 1)
        else:
            cells = ["✓" if role in r.roles else "" for role in ROLE_ORDER]
        lines.append(f"| {r.method} | `{r.path}` | " + " | ".join(cells) + " |")
    protected = sum(1 for r in rows if not r.public)
    lines += ["", f"{len(rows)} operations; {protected} require authentication.", ""]
    return "\n".join(lines)


def main() -> None:
    from app.main import app

    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("../docs/AUTHORIZATION.md")
    target.write_text(markdown(app), encoding="utf-8")
    print(f"Wrote {target}")


if __name__ == "__main__":
    main()
