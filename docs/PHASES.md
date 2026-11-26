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

## Phase 3: Insurance and claims ✅

- [x] Migrations `0009_insurance`, `0010_claims` (plus invoice AR fields), `0011_remittances`
- [x] Insurers (fictional) with mock adjudication rates; policies with coverage %, copay, deductible, annual limit; denial codes
- [x] Coverage calculation (copay, deductible, coinsurance, limit, already-paid cap) with edge-case and property tests
- [x] Claim generation from invoices with line allocation; coverage preview endpoint
- [x] Claim state machine (draft → submitted → under_review → approved / partially_approved / denied → paid; denied → appealed / closed; draft → cancelled) with an append-only event timeline
- [x] Mock insurer (deterministic, scripted override, batch endpoint, Celery task)
- [x] Denials with reason codes; appeals with notes and attachments (max 2)
- [x] Remittance CSV import, reconciliation (matched / short_paid / overpaid / unmatched), idempotent posting; accept short pay
- [x] Ledger posting: AR transfer on submit, contractual adjustments, insurer payments, denied-and-closed back to patient; AR-Insurers reconciles to invoices
- [x] UI: insurers, patient coverage, invoice insurance section with preview, claims worklist (status counts, mock insurer), claim detail (timeline, attachments, actions), remittances (import, reconcile, post)
- [x] Seed: 4 insurers, 34 policies, claims in every state, remittances with matched, short-paid and unmatched lines
- [x] Totals: pytest 276 (95% coverage; every service >= 88%), Vitest 19, Playwright 12

## Phase 4: AR / AP and approvals ✅

- [x] Migrations `0012_approvals`, `0013_ar`, `0014_ap`
- [x] Generic approval engine (policies with thresholds and approver roles, requests, decisions, comments); manual journals and refunds routed through it
- [x] AR aging by patient and by insurer, computed from the ledger as of any date (ties to the GL; unallocated row for manual entries)
- [x] Dunning reminder job (Celery + endpoint), one notice per invoice per level
- [x] Write-offs with approval, posting to bad-debt expense
- [x] Vendors (masked bank details), purchase orders (issue, receive, cancel), vendor bills with three-way match, approval, scheduled payment runs, idempotent payments; finance managers can void approved unpaid bills via reversal
- [x] Ledger: AP approval posts expenses / AP; payments AP / bank; AP and AR-Insurers reconcile to sub-ledgers (tested)
- [x] UI: approvals inbox (to decide, mine, all, policies) with sidebar badge, AR page (aging charts and tables, reminders, write-offs), invoice write-off action, payables (bills, POs, vendors, payments) with bill and PO detail pages
- [x] Seed: approval policies, 6 vendors, POs and bills in every state, a pending write-off, a variance bill pending approval, dunning notices
- [x] Totals: pytest 315 (95% coverage; every service >= 88%), Vitest 22, Playwright 16

## Phase 5: Payroll and budgets ✅

- [x] Migrations `0016_payroll` (employees, tax slabs, runs, payslips, frozen-after-posting triggers) and `0017_budgets` (budgets, lines, append-only alerts)
- [x] Employees with salary structure (basic, housing, transport, other allowance, pension rate, other deduction), masked bank details, termination (never deleted)
- [x] Payroll arithmetic with Decimal and documented rounding: proration, annualised progressive tax slabs, pension, capped deductions (unit + Hypothesis tests)
- [x] Monthly run as a background job (Celery, in-process fallback, monthly beat), recalculation, approval through the generic engine, posting by department, idempotent payment via the payroll bank account, payslip PDFs
- [x] Budgets per department and account (monthly amounts), variance report from SQL aggregates of the ledger, alert job with warning/exceeded levels
- [x] UI: payroll (runs, employees, tax slabs with calculator), run detail (polling, approve/reject, pay, payslips), budgets list with alerts, budget detail with chart and variance table
- [x] Seed: 2026-2027 tax slabs, 31 employees (one mid-month joiner, one leaver), runs June-October paid, November awaiting approval, 2026 budgets with an Emergency overrun and a Surgery warning
- [x] Totals: pytest 362 (95% coverage), Vitest 29, Playwright 19

## Phase 6: Reporting and dashboards ✅

- [x] Migrations `0018_notifications` (append-only), `0019_alert_percent`
- [x] Dashboard metrics endpoint with role-selected sections, all SQL aggregates (financial position, revenue cycle, insurance claims, system activity); KPIs reconcile with the ledger (tested)
- [x] Charts: P&L trend, revenue by department, budget use, collections, payment mix, claims by status, audit activity
- [x] CSV / PDF exports for trial balance, income statement, balance sheet, AR aging, budget variance, invoices and audit log (audited, formula-injection safe)
- [x] Notifications for approvals, decisions, budget alerts and payroll jobs; bell with unread count, mark read / all read
- [x] Audit log viewer with filters, field-level before/after diff and export
- [x] Global search (header, `/` or Ctrl+K) across records the user may read
- [x] Seed: notifications tidied so only pending approvals and budget alerts are unread
- [x] Totals: pytest 380 (95% coverage), Vitest 33, Playwright 24

## Phase 7: Hardening and demo readiness ✅

- [x] Deterministic, idempotent seed with six months of realistic activity (about 780 invoices, payments, claims in every state, supplier bills, payroll, depreciation), January–September closed, pending approvals, a budget overrun and two anomalies
- [x] Playwright E2E for the eight-step demo script (`frontend/tests/e2e/demo.spec.ts`)
- [x] N+1 fixes (payroll runs, purchase orders) with query-count tests for list endpoints; migration `0020_indexes`
- [x] Login rate limiting (per account and per address, Redis-backed, 429 + Retry-After)
- [x] Authorization review of every endpoint: generated matrix (`docs/AUTHORIZATION.md`) and tests for anonymous access, role denial and auditor read-only access
- [x] Dashboard: collection rate and receivables by age; invoices link to their audit trail
- [x] README: Mermaid architecture diagram, native setup, demo credentials per role, demo script, screenshots, production requirements; `seed.ps1 -Reset`
- [x] Totals: pytest 556 (95% coverage), Vitest 33, Playwright 31

## Phase 8 (optional stretch): analytics module

- [ ] Not started
