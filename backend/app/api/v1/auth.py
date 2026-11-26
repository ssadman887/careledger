from typing import Any

from fastapi import APIRouter, Request

from app.core.deps import CurrentActor, DbSession
from app.core.errors import AuthenticationFailed, ErrorEnvelope, RateLimited
from app.core.ratelimit import login_limiter
from app.schemas.auth import LoginRequest, RefreshRequest, TokenPair
from app.schemas.common import Message
from app.schemas.users import UserOut
from app.services import auth as auth_service
from app.services import users as users_service

router = APIRouter(prefix="/auth", tags=["auth"])

_401: dict[int | str, dict[str, Any]] = {401: {"model": ErrorEnvelope}}


def _pair(tokens: auth_service.IssuedTokens) -> TokenPair:
    return TokenPair(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
    )


@router.post(
    "/login",
    response_model=TokenPair,
    responses={**_401, 429: {"model": ErrorEnvelope, "description": "Too many failed sign-ins"}},
)
def login(body: LoginRequest, db: DbSession, request: Request) -> TokenPair:
    """Sign in. Repeated failures for an account or from an address are throttled (429)."""
    limiter = login_limiter()
    ip = request.client.host if request.client else "unknown"
    blocked = limiter.check(body.login, ip)
    if blocked:
        raise RateLimited(
            "Too many failed sign-in attempts. Try again later.",
            details={"retry_after_seconds": blocked.retry_after},
            headers={"Retry-After": str(blocked.retry_after)},
        )
    try:
        tokens = auth_service.login(db, body.login, body.password)
    except AuthenticationFailed:
        limiter.failed(body.login, ip)
        raise
    limiter.succeeded(body.login, ip)
    return _pair(tokens)


@router.post("/refresh", response_model=TokenPair, responses=_401)
def refresh(body: RefreshRequest, db: DbSession) -> TokenPair:
    return _pair(auth_service.refresh(db, body.refresh_token))


@router.post("/logout", response_model=Message)
def logout(body: RefreshRequest, db: DbSession) -> Message:
    auth_service.logout(db, body.refresh_token)
    return Message(message="Logged out")


@router.get("/me", response_model=UserOut, responses=_401)
def me(actor: CurrentActor, db: DbSession) -> UserOut:
    assert actor.id is not None
    return UserOut.model_validate(users_service.get_user(db, actor.id))
