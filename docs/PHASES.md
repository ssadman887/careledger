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

## Phase 1: Ledger core

- [ ] Chart of accounts (hierarchy, types, cost centers) + default hospital CoA seed
- [ ] Fiscal periods (open/close with trial-balance pre-check)
- [ ] Journal engine `post_entry`, `reverse_entry`
- [ ] DB safeguards: balance constraint trigger, immutability trigger, closed-period trigger
- [ ] Reports: trial balance, income statement, balance sheet, account ledger
- [ ] Manual journal entries with approval threshold
- [ ] UI: accounts, journal entries, reports
- [ ] Tests incl. Hypothesis trial-balance invariant
