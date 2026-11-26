"""FastAPI dependencies: DB session, current user, role-based access control."""

from collections.abc import Callable
from typing import Annotated

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import AuthenticationFailed, PermissionDenied
from app.core.security import decode_token
from app.models.identity import RoleName
from app.repositories import users as users_repo
from app.services.audit import Actor
from app.services.auth import actor_for

DbSession = Annotated[Session, Depends(get_db)]

_bearer = HTTPBearer(auto_error=False)


def current_actor(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Actor:
    if credentials is None:
        raise AuthenticationFailed("Missing bearer token")
    try:
        payload = decode_token(credentials.credentials, "access")
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise AuthenticationFailed("Invalid or expired token", code="invalid_token") from exc
    user = users_repo.get(db, payload.sub)
    if user is None or not user.is_active or user.deleted_at is not None:
        raise AuthenticationFailed("User inactive", code="invalid_token")
    # Roles come from the DB, not the token, so revocations apply immediately.
    return actor_for(user)


CurrentActor = Annotated[Actor, Depends(current_actor)]


def require_roles(*roles: RoleName) -> Callable[[Actor], Actor]:
    """Write access: the actor must hold at least one of `roles`."""
    allowed = frozenset(r.value for r in roles)

    def _dep(actor: CurrentActor) -> Actor:
        if not actor.roles.intersection(allowed):
            raise PermissionDenied(
                "You do not have permission to perform this action",
                details={"required_any_of": sorted(allowed)},
            )
        return actor

    _dep.allowed_roles = allowed  # type: ignore[attr-defined]  # read by app.authz
    return _dep


def read_roles(*roles: RoleName) -> Callable[[Actor], Actor]:
    """Read access: like require_roles, but auditors can always read."""
    return require_roles(*roles, RoleName.AUDITOR)
