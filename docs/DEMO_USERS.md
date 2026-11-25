# Demo users

> **Demo system. Synthetic data only.** Every account below uses the **same password**, chosen
> for easy showcasing. Never reuse this setup outside a local demo.

**Shared password:** `CareLedger!2026` (set by `DEMO_PASSWORD` in `.env`; run `make seed` again after changing it)

You can sign in with either the **username** or the **email**.

| Role | Username | Email | What to demo |
|------|----------|-------|--------------|
| admin | `admin` | `admin@careledger.example` | Users, roles, settings, chart of accounts |
| billing_clerk | `billing` | `billing@careledger.example` | Invoices, payments, claim drafting |
| insurance_officer | `insurance` | `insurance@careledger.example` | Claim submission, denials, appeals, remittances |
| accountant | `accountant` | `accountant@careledger.example` | Journal entries, ledger, period close |
| finance_manager | `finance` | `finance@careledger.example` | Approvals, budgets, reports |
| auditor | `auditor` | `auditor@careledger.example` | Read-only access to everything, including the audit log |

This file is kept in sync with `backend/seed/users.py`. Update both together.
