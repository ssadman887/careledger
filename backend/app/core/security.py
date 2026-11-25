"""Password hashing (argon2) and JWT encoding/decoding."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import get_settings

_hasher = PasswordHasher()

TokenType = Literal["access", "refresh"]


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


@dataclass(frozen=True)
class TokenPayload:
    sub: int
    type: TokenType
    jti: str
    exp: datetime
    roles: list[str]


def create_token(
    user_id: int, token_type: TokenType, roles: list[str], *, now: datetime | None = None
) -> TokenPayload:
    settings = get_settings()
    issued = now or datetime.now(UTC)
    lifetime = (
        timedelta(minutes=settings.access_token_minutes)
        if token_type == "access"
        else timedelta(days=settings.refresh_token_days)
    )
    return TokenPayload(
        sub=user_id, type=token_type, jti=uuid.uuid4().hex, exp=issued + lifetime, roles=roles
    )


def encode_token(payload: TokenPayload) -> str:
    settings = get_settings()
    claims = {
        "sub": str(payload.sub),
        "type": payload.type,
        "jti": payload.jti,
        "exp": payload.exp,
        "roles": payload.roles,
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str, expected_type: TokenType) -> TokenPayload:
    """Raises jwt.PyJWTError (or ValueError) on any invalid token."""
    settings = get_settings()
    claims = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    if claims.get("type") != expected_type:
        raise ValueError("wrong token type")
    return TokenPayload(
        sub=int(claims["sub"]),
        type=expected_type,
        jti=str(claims["jti"]),
        exp=datetime.fromtimestamp(int(claims["exp"]), tz=UTC),
        roles=[str(r) for r in claims.get("roles", [])],
    )
