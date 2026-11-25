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
| 16 | 1 | Manual journal approval uses entry statuses `pending_approval -> posted / rejected` (finance manager approves; creator can never approve their own). The generic approval engine (Phase 4) will wrap this. | Ships the spec'd threshold now without inventing the Phase 4 engine early. |
| 17 | 1 | Threshold rule: approval required when total **>** `MANUAL_JOURNAL_APPROVAL_THRESHOLD` (default 10,000.00); equal amounts post directly. | Simplest unambiguous reading of "above". |
| 18 | 1 | Closed periods can **never** be reopened (DB trigger) and periods must be closed in date order. | Strongest guarantee for "closed periods are locked"; corrections post into an open period via reversal. |
| 19 | 1 | No year-end closing entries; the balance sheet shows cumulative revenue minus expenses as a computed "Retained earnings" line. | Keeps the ledger append-only and the statements always tie out. |
| 20 | 1 | Header accounts cannot be posted to; a parent must be a header of the same type; code and type are immutable after creation; accounts with a non-zero balance cannot be deactivated. | Protects report integrity. |
| 21 | 1 | Chart of accounts writable by `admin` and `accountant` (read by finance manager, auditor). | Spec names admin; accountants maintain the CoA day to day. |
| 22 | 1 | Revenue by department: each department maps to its own revenue account (4110–4170); journal lines also carry optional department / cost-center dimensions. | Makes revenue-by-department reports a simple GROUP BY. |
| 23 | 1 | Seed creates monthly fiscal periods from 2026-01 through 12 months after the current month, plus an opening-balance entry on 2026-01-01. | The demo keeps working whenever it is run. |
| 24 | 1 | Default reversal date = original date if its period is still open, otherwise today (must be open). | Matches common practice. |
| 25 | 1 | Deferred constraint triggers check balance at COMMIT; tests fire them with `SET CONSTRAINTS ALL IMMEDIATE` because test transactions never commit. | Multi-row inserts need deferred checks; tests still exercise the DB safeguard. |
| 26 | 1 | Validation error details never echo the submitted `input` (and `ctx` is stringified). | Avoids reflecting passwords back; fixed a 500 on float money input. |
| 27 | 1 | `openapi-typescript --default-non-nullable false` so request fields with server defaults stay optional in TS. | Matches FastAPI semantics. |
| 28 | 1 | **Native Windows stack, no Docker** (owner decision). Hardware virtualization is disabled on the dev machine, so Docker/WSL cannot run. PostgreSQL 16 runs as a Windows service; `scripts\setup.ps1`, `dev.ps1`, `seed.ps1`, `test.ps1`, `gen-client.ps1` replace `docker compose` and the Makefile. The CI compose job was removed. `docker-compose.yml` and the Dockerfiles stay in the repo, unused, in case Docker returns later. | Spec said `docker compose up`; the owner chose native given the hardware limit. |
| 29 | 1 | **Microsoft Garnet** (winget `Microsoft.Garnet.DN8`) as the Redis-compatible broker. | Memurai's installer failed (its custom action cannot create a temp directory, MSI 1603); Garnet is a portable, MIT-licensed Redis-protocol server that Celery works with unchanged. |
| 30 | 1 | Celery worker runs with `--pool=solo --without-mingle --without-gossip`. | Prefork is unsupported on Windows; mingle/gossip only add startup delay with a single worker. |
| 31 | 1 | Backend settings read the root `.env` then `backend\.env`; environment variables win. `.env` also holds the local `POSTGRES_SUPERUSER_PASSWORD`, used only by `setup.ps1` to create the `careledger` role. | One config file for scripts and app; superuser password never committed. |
