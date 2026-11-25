"""Roles and demo users. Keep in sync with docs/DEMO_USERS.md.

All demo users share one password (settings.demo_password) by design: this is a demo.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password, verify_password
from app.models.identity import Role, RoleName, User

ROLE_DESCRIPTIONS: dict[RoleName, str] = {
    RoleName.ADMIN: "Users, roles, settings, chart of accounts",
    RoleName.BILLING_CLERK: "Invoices, payments, claim drafting",
    RoleName.INSURANCE_OFFICER: "Claim submission, denials, appeals, remittance reconciliation",
    RoleName.ACCOUNTANT: "Journal entries, ledger, fiscal period closing",
    RoleName.FINANCE_MANAGER: "Approvals, budgets, reports",
    RoleName.AUDITOR: "Read-only access to everything including the audit log",
}


@dataclass(frozen=True)
class DemoUser:
    username: str
    full_name: str
    role: RoleName

    @property
    def email(self) -> str:
        return f"{self.username}@careledger.example"


DEMO_USERS: tuple[DemoUser, ...] = (
    DemoUser("admin", "Avery Admin", RoleName.ADMIN),
    DemoUser("billing", "Blake Billing", RoleName.BILLING_CLERK),
    DemoUser("insurance", "Indira Insurance", RoleName.INSURANCE_OFFICER),
    DemoUser("accountant", "Casey Accountant", RoleName.ACCOUNTANT),
    DemoUser("finance", "Morgan Finance", RoleName.FINANCE_MANAGER),
    DemoUser("auditor", "Jordan Auditor", RoleName.AUDITOR),
)


def seed_roles(session: Session) -> dict[str, Role]:
    existing = {r.name: r for r in session.scalars(select(Role)).all()}
    for name, description in ROLE_DESCRIPTIONS.items():
        role = existing.get(name.value)
        if role is None:
            role = Role(name=name.value, description=description)
            session.add(role)
            existing[name.value] = role
        else:
            role.description = description
    session.flush()
    return existing


def seed_users(session: Session, roles: dict[str, Role]) -> list[User]:
    password = get_settings().demo_password
    users: list[User] = []
    for demo in DEMO_USERS:
        user = session.scalars(select(User).where(User.username == demo.username)).first()
        if user is None:
            user = User(
                username=demo.username,
                email=demo.email,
                full_name=demo.full_name,
                password_hash=hash_password(password),
                is_active=True,
            )
            session.add(user)
        else:
            user.email, user.full_name, user.is_active = demo.email, demo.full_name, True
            if not verify_password(password, user.password_hash):
                user.password_hash = hash_password(password)
        user.roles = [roles[demo.role.value]]
        users.append(user)
    session.flush()
    return users
