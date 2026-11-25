"""Domain errors and the consistent error envelope: {"error": {"code", "message", "details"}}."""

from collections.abc import Sequence
from typing import Any

import structlog
from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import DBAPIError, IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

log = structlog.get_logger(__name__)


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any | None = None


class ErrorEnvelope(BaseModel):
    error: ErrorBody


class AppError(Exception):
    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "bad_request"

    def __init__(self, message: str, *, code: str | None = None, details: Any = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        self.details = details


class NotFound(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class Conflict(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"


class BusinessRuleViolation(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "business_rule_violation"


class ValidationFailed(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "validation_error"


class AuthenticationFailed(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "unauthenticated"


class PermissionDenied(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "forbidden"


class RateLimited(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "rate_limited"


def _envelope(status_code: int, code: str, message: str, details: Any = None) -> JSONResponse:
    body = ErrorEnvelope(error=ErrorBody(code=code, message=message, details=details))
    return JSONResponse(status_code=status_code, content=jsonable_encoder(body))


def _clean_validation_errors(errors: Sequence[Any]) -> list[dict[str, Any]]:
    """JSON-safe validation details. Drops `input` so submitted values (e.g. passwords) are
    never echoed back, and stringifies `ctx` (it can hold exception objects)."""
    cleaned: list[dict[str, Any]] = []
    for err in errors:
        item = {k: v for k, v in dict(err).items() if k not in {"input", "ctx", "url"}}
        if "ctx" in err:
            item["ctx"] = {str(k): str(v) for k, v in dict(err["ctx"]).items()}
        cleaned.append(item)
    return cleaned


# Custom SQLSTATEs raised by our accounting triggers (see alembic migrations).
LEDGER_SQLSTATES = {"P0001"}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return _envelope(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {
            401: "unauthenticated",
            403: "forbidden",
            404: "not_found",
            405: "method_not_allowed",
        }
        return _envelope(exc.status_code, code.get(exc.status_code, "http_error"), str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _envelope(
            422,
            "validation_error",
            "Request validation failed",
            _clean_validation_errors(exc.errors()),
        )

    @app.exception_handler(IntegrityError)
    async def _integrity_error(_: Request, exc: IntegrityError) -> JSONResponse:
        log.warning("integrity_error", error=str(exc.orig))
        return _envelope(409, "integrity_error", "The request conflicts with existing data")

    @app.exception_handler(DBAPIError)
    async def _db_error(_: Request, exc: DBAPIError) -> JSONResponse:
        sqlstate = getattr(exc.orig, "sqlstate", None)
        if sqlstate in LEDGER_SQLSTATES:
            msg = str(exc.orig).splitlines()[0]
            return _envelope(409, "ledger_violation", msg)
        log.error("database_error", error=str(exc.orig))
        return _envelope(500, "database_error", "A database error occurred")

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_error", error=str(exc))
        return _envelope(500, "internal_error", "An unexpected error occurred")
