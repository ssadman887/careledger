"""User administration (admin only). Registration happens here: there is no self sign-up."""

from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation, Conflict, NotFound, ValidationFailed
from app.core.security import hash_password
from app.models.identity import Role, RoleName, User
from app.repositories import users as users_repo
from app.services import audit
from app.services.audit import Actor

VALID_ROLES = {r.value for r in RoleName}


def _resolve_roles(session: Session, names: Sequence[str]) -> list[Role]:
    unknown = set(names) - VALID_ROLES
    if unknown:
        raise ValidationFailed("Unknown roles", details={"roles": sorted(unknown)})
    roles = users_repo.roles_by_names(session, names)
    if len(roles) != len(set(names)):
        raise ValidationFailed("Roles are not seeded", details={"roles": sorted(names)})
    return roles


def _snap(user: User) -> dict[str, object]:
    return audit.snapshot(user, extra={"roles": user.role_names})


def create_user(
    session: Session,
    actor: Actor,
    *,
    email: str,
    username: str,
    full_name: str,
    password: str,
    roles: Sequence[str],
) -> User:
    if users_repo.exists_email_or_username(session, email, username):
        raise Conflict("A user with that email or username already exists", code="user_exists")
    user = User(
        email=email.lower(),
        username=username.lower(),
        full_name=full_name,
        password_hash=hash_password(password),
        is_active=True,
        roles=_resolve_roles(session, roles),
    )
    session.add(user)
    session.flush()
    audit.record(
        session, actor, entity_type="user", entity_id=user.id, action="create", after=_snap(user)
    )
    return user


def get_user(session: Session, user_id: int) -> User:
    user = users_repo.get(session, user_id)
    if user is None or user.deleted_at is not None:
        raise NotFound("User not found")
    return user


def update_user(
    session: Session,
    actor: Actor,
    user_id: int,
    *,
    full_name: str | None,
    roles: Sequence[str] | None,
    is_active: bool | None,
    password: str | None,
) -> User:
    user = get_user(session, user_id)
    before = _snap(user)
    if actor.id == user.id and (
        is_active is False or (roles is not None and RoleName.ADMIN not in roles)
    ):
        raise BusinessRuleViolation(
            "Admins cannot deactivate or demote themselves", code="self_lockout"
        )
    if full_name is not None:
        user.full_name = full_name
    if roles is not None:
        user.roles = _resolve_roles(session, roles)
    if is_active is not None:
        user.is_active = is_active
    if password is not None:
        user.password_hash = hash_password(password)
    session.flush()
    action = (
        "status_change" if is_active is not None and before["is_active"] != is_active else "update"
    )
    audit.record(
        session,
        actor,
        entity_type="user",
        entity_id=user.id,
        action=action,
        before=before,
        after=_snap(user),
    )
    return user
