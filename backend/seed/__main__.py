"""Deterministic, idempotent seed. Run with: python -m seed"""

import random

from faker import Faker

from app.core.db import session_scope
from seed.billing import seed_billing
from seed.insurance import seed_insurance
from seed.ledger import CHART_OF_ACCOUNTS, seed_ledger
from seed.phase4 import seed_approval_policies, seed_phase4
from seed.phase5 import seed_phase5
from seed.phase6 import seed_phase6
from seed.users import DEMO_USERS, seed_roles, seed_users

SEED = 20260101


def main() -> None:
    random.seed(SEED)
    Faker.seed(SEED)
    with session_scope() as session:
        roles = seed_roles(session)
        seed_users(session, roles)
        seed_ledger(session)
        seed_approval_policies(session)
        seed_billing(session)
        seed_insurance(session)
        seed_phase4(session)
        seed_phase5(session)
        seed_phase6(session)
    print(f"Seeded {len(roles)} roles and {len(DEMO_USERS)} demo users.")
    print(f"Chart of accounts: {len(CHART_OF_ACCOUNTS)} accounts, departments, fiscal periods.")
    print("Billing: service catalog, price list, 40 synthetic patients, visits, invoices.")
    print("Insurance: denial codes, 4 insurers, policies, claims in every state, remittances.")
    print("AR/AP: approval policies, vendors, POs, bills, payments, a pending write-off, dunning.")
    print("Payroll: tax slabs, 31 employees, runs Jun-Oct paid, Nov awaiting approval.")
    print("Budgets: 2026 per department (salaries, supplies, revenue) with alerts.")
    print("Notifications: pending approvals and budget alerts for the finance manager.")
    print("All demo users share DEMO_PASSWORD. See docs/DEMO_USERS.md.")


if __name__ == "__main__":
    main()
