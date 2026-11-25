# Build phases

## Phase 0: Foundation ✅

- [x] Repo scaffold matching the spec layout
- [x] Docker Compose: `db`, `redis`, `api`, `worker`, `web` (healthchecks, migrations on api start)
- [x] FastAPI app with `/api/v1/health` (DB check), OpenAPI at `/api/v1/openapi.json`, docs at `/api/docs`
- [x] pydantic-settings config + `.env.example`
- [x] Structured logging (structlog) with request IDs (`X-Request-ID`)
- [x] Consistent error envelope for app, HTTP, validation, integrity and trigger errors
- [x] Alembic setup; migrations `0001_identity`, `0002_audit_log`
- [x] Auth: admin-only user registration, login (username or email), refresh rotation, logout revocation, `/auth/me`
- [x] argon2 hashing, JWT access/refresh tokens
- [x] RBAC dependencies (`require_roles`, `read_roles` with auditor read access)
- [x] Audit-log infrastructure (same-transaction writes, DB trigger makes it append-only)
- [x] Money type: Decimal, NUMERIC(14,2), serialized as strings, floats rejected
- [x] Deterministic, idempotent seed (roles + demo users, shared demo password)
- [x] `docs/DEMO_USERS.md` with every demo username/email
- [x] Next.js shell: login, role-aware navigation, persistent demo banner, users admin page (TanStack Table)
- [x] Generated TS client pipeline (`make gen-client`, openapi-typescript + openapi-fetch)
- [x] Tests: pytest 40 (94% coverage), Vitest 9, Playwright 3
- [x] ruff, mypy strict, eslint (no `any`), prettier, pre-commit
- [x] CI workflow (backend, frontend, compose smoke test)

## Phase 1: Ledger core ✅

- [x] Migrations `0003_org` (departments, cost centers) and `0004_ledger` (accounts, periods, entries, lines)
- [x] Chart of accounts CRUD (5 types, header/child hierarchy, cycle checks, cost centers) + 50-account hospital CoA seed
- [x] Departments mapped to revenue accounts; cost centers per department
- [x] Fiscal periods: monthly seed, create, pre-close check, close (locked forever, in order)
- [x] Journal engine `post_entry`, `reverse_entry` (mirror entry, linked both ways)
- [x] DB safeguards: deferred balance triggers, immutability triggers, open-period trigger, period guard, no-overlap exclusion
- [x] Manual journal entries with approval above threshold; finance-manager approve/reject; no self-approval
- [x] Reports: trial balance, income statement, balance sheet (computed retained earnings), account ledger (window-function running balance, paginated)
- [x] UI: chart of accounts (tree, create/edit/deactivate), journal list with filters, line-item entry editor with live balance, entry detail with reverse/approve/reject, fiscal periods with pre-close check, reports with 4 tabs
- [x] Tests: unbalanced rejected (service + DB), closed-period posting rejected (service + DB), UPDATE/DELETE on posted lines rejected at DB level, reversal nets to zero, Hypothesis invariant (60 random sequences incl. reversals keep TB at exactly zero)
- [x] Totals: pytest 92 (96% coverage; every service ≥ 88%), Vitest 15, Playwright 7

## Phase 2: Patient billing

- [ ] Patients & visits (synthetic), service catalog, price lists with effective dates
- [ ] Invoices (lines, discounts, tax), lifecycle, void with reversal
- [ ] Payments (cash, card mock, transfer), partial, deposits, refunds with approval
- [ ] Idempotency-Key on payment endpoints
- [ ] Auto-posting per ARCHITECTURE section 4; PDF invoice & receipt
- [ ] UI: invoice editor, payment recording, invoice list
