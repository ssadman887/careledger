"""Deterministic, idempotent seed. Run with: python -m seed"""

import random

from faker import Faker

from app.core.db import session_scope
from seed.users import DEMO_USERS, seed_roles, seed_users

SEED = 20260101


def main() -> None:
    random.seed(SEED)
    Faker.seed(SEED)
    with session_scope() as session:
        roles = seed_roles(session)
        seed_users(session, roles)
    print(f"Seeded {len(roles)} roles and {len(DEMO_USERS)} demo users.")
    print("All demo users share DEMO_PASSWORD. See docs/DEMO_USERS.md.")


if __name__ == "__main__":
    main()
