# Build phases

> Runtime: native Windows (PostgreSQL 16 service + Garnet + local processes via `scripts\dev.ps1`). No Docker; see DECISIONS #28.

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
- [x] CI workflow (backend, frontend; the compose smoke test was later removed, see DECISIONS #28)

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

## Phase 2: Patient billing ✅

- [x] Migrations `0005_patients`, `0006_catalog`, `0007_billing`, `0008_idempotency` (sequences, check constraints, guards)
- [x] Patients (synthetic MRNs) and visits (outpatient / inpatient / emergency; open, closed, cancelled)
- [x] Service catalog (26 services, 7 departments) and an effective-dated price list with a mid-year price change
- [x] Invoices: draft charge capture, line discounts (percent or amount), tax, issue, void with reversal
- [x] Payments (cash, mock card, bank transfer), partial payments, deposits and deposit application, refunds with approval above 500.00
- [x] Idempotency-Key on all payment-creating endpoints
- [x] Auto-posting per ARCHITECTURE section 4 (department revenue, discounts, tax, cash/bank, deposits, refunds)
- [x] PDF invoice and receipt (ReportLab, synthetic-data notice)
- [x] Masking of bank references by role; card = last 4 digits only
- [x] UI: patients (register, visits, deposits), invoice list with filters, new invoice, draft line editor, invoice detail (issue, pay, apply deposit, refund, void, PDF), payments and refunds (finance approval)
- [x] Tests: invoice -> payment -> ledger balanced, partial payments, void reverses, idempotent retry does not double-post, role restrictions, DB guards, deposits, refund approval, price history, rounding
- [x] Totals: pytest 135 (95% coverage; every service >= 88%), Vitest 18, Playwright 10

## Phase 3: Insurance and claims

- [ ] Insurers, policies, coverage rules (coverage %, copay, deductible, annual limit)
- [ ] Claim generation from invoice; lifecycle state machine; denial codes; appeals
- [ ] Mock insurer adjudication job (configurable rates)
- [ ] Remittance CSV import and reconciliation; ledger posting
- [ ] UI: claim worklist and detail with event timeline
