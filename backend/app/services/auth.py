"""Authentication: login, refresh-token rotation, logout."""

from dataclasses import dataclass
from datetime import UTC, datetime

import jwt
from sqlalchemy.orm import Session

from app.core.errors import AuthenticationFailed
from app.core.security import create_token, decode_token, encode_token, verify_password
from app.models.identity import User
from app.repositories import users as users_repo
from app.services import audit
from app.services.audit import Actor


@dataclass(frozen=True)
class IssuedTokens:
    access_token: str
    refresh_token: str
    expires_in: int


def actor_for(user: User) -> Actor:
    return Actor(id=user.id, label=user.email, roles=frozenset(user.role_names))


def _issue(session: Session, user: User) -> IssuedTokens:
    roles = user.role_names
    access = create_token(user.id, "access", roles)
    refresh = create_token(user.id, "refresh", roles)
    users_repo.add_refresh_token(session, refresh.jti, user.id, refresh.exp)
    session.flush()
    expires_in = int((access.exp - datetime.now(UTC)).total_seconds())
    return IssuedTokens(encode_token(access), encode_token(refresh), expires_in)


def login(session: Session, login_name: str, password: str) -> IssuedTokens:
    user = users_repo.get_by_login(session, login_name)
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        raise AuthenticationFailed("Invalid credentials", code="invalid_credentials")
    user.last_login_at = datetime.now(UTC)
    audit.record(session, actor_for(user), entity_type="user", entity_id=user.id, action="login")
    return _issue(session, user)


def refresh(session: Session, refresh_token: str) -> IssuedTokens:
    try:
        payload = decode_token(refresh_token, "refresh")
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise AuthenticationFailed("Invalid refresh token", code="invalid_token") from exc
    stored = users_repo.get_refresh_token(session, payload.jti)
    if stored is None or stored.revoked_at is not None:
        raise AuthenticationFailed("Refresh token revoked", code="invalid_token")
    user = users_repo.get(session, payload.sub)
    if user is None or not user.is_active or user.deleted_at is not None:
        raise AuthenticationFailed("User inactive", code="invalid_token")
    stored.revoked_at = datetime.now(UTC)  # rotation: each refresh token is single-use
    return _issue(session, user)


def logout(session: Session, refresh_token: str) -> None:
    try:
        payload = decode_token(refresh_token, "refresh")
    except (jwt.PyJWTError, ValueError, KeyError):
        return  # logging out with a bad token is a no-op
    stored = users_repo.get_refresh_token(session, payload.jti)
    if stored is not None and stored.revoked_at is None:
        stored.revoked_at = datetime.now(UTC)
        session.flush()
