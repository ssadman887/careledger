# Decisions log

Non-blocking ambiguities resolved during the build. Newest last.

| # | Phase | Decision | Rationale |
|---|-------|----------|-----------|
| 1 | 0 | **One shared demo password** for every seeded user, set via `DEMO_PASSWORD` (default `CareLedger!2026`). Users are listed in `docs/DEMO_USERS.md`. | Owner request: simplicity when showcasing. Real deployments would use per-user credentials + SSO/MFA. |
| 2 | 0 | **Sync** SQLAlchemy 2.0 + psycopg 3 with sync FastAPI endpoints (threadpool). | Simpler transactions, triggers and Hypothesis tests; throughput is irrelevant for a demo. |
| 3 | 0 | **Celery** (Redis broker) for background jobs rather than ARQ. | Pairs naturally with the sync stack. |
| 4 | 0 | **ReportLab** for PDFs rather than WeasyPrint. | Pure Python; no GTK/Pango system libs, works on Windows dev boxes and slim images. |
| 5 | 0 | Login accepts **email or username**. Emails use the reserved `careledger.example` domain and are validated with a simple pattern instead of `EmailStr`. | `email-validator` rejects special-use domains; demo addresses must not be real. |
| 6 | 0 | `admin` is **not** a superuser over financial data. Admin manages users, roles, settings and the chart of accounts only. | Segregation of duties. `auditor` is added automatically to every read endpoint. |
| 7 | 0 | Refresh tokens are persisted (`refresh_tokens` table, by `jti`) and rotated on each refresh; logout revokes. | Enables real logout with stateless access tokens. |
| 8 | 0 | One request = one transaction; services `flush()` only, `get_db` commits. | Guarantees business record + ledger entry + audit row are atomic. |
| 9 | 0 | `updated_at` maintained by SQLAlchemy `onupdate` rather than DB triggers. | Fewer triggers; all writes go through the ORM. |
| 10 | 0 | Python packages live only in `backend/.venv` locally (and in a `/opt/venv` virtualenv inside the image). | Owner request. |
| 11 | 0 | Frontend keeps tokens in `localStorage` and refreshes on 401 via an openapi-fetch middleware. | Simplest for a localhost demo; production would use an httpOnly refresh cookie (see README). |
| 12 | 0 | Audit log readable by `auditor`, `admin` and `finance_manager`. | Auditor is required by spec; admin needs it for user-change history, finance manager for approvals oversight. |
| 13 | 0 | TanStack Table pinned to v8; Next.js 15 (App Router) with Tailwind v4 and shadcn/ui (new-york, radix). | Stable APIs; v9 was a breaking alpha-era API at build time. |
| 14 | 0 | Nav items for not-yet-built modules render disabled with a "Phase N" badge (`CURRENT_PHASE` in `lib/nav.ts`). | Keeps the shell honest while phases land. |
| 15 | 0 | Generated OpenAPI spec (`frontend/openapi.json`) and types are committed; CI fails if they drift. | Never hand-write API types; drift is caught automatically. |
