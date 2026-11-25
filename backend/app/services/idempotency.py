"""Idempotency for payment-creating endpoints (Idempotency-Key header).

Semantics:
  * first request with a key: execute, store the JSON response in the same transaction;
  * retry with the same key and identical payload: return the stored response, execute nothing;
  * same key, different payload: 422 idempotency_key_reused;
  * concurrent duplicates: the unique constraint makes the second wait on the first's row lock,
    then it reads the stored response.
If the first request fails, its transaction (including the key row) rolls back, so the client
may retry with the same key.
"""

import hashlib
import json
from collections.abc import Callable
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.errors import Conflict, ValidationFailed
from app.models.platform import IdempotencyKey
from app.repositories import billing as repo
from app.services.audit import Actor

KEY_MIN, KEY_MAX = 8, 128


def _hash(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def execute(
    session: Session,
    actor: Actor,
    *,
    scope: str,
    key: str | None,
    payload: Any,
    run: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    if key is None:
        return run()
    if not (KEY_MIN <= len(key) <= KEY_MAX) or not key.isprintable():
        raise ValidationFailed(
            f"Idempotency-Key must be {KEY_MIN}-{KEY_MAX} printable characters",
            code="invalid_idempotency_key",
        )
    actor_key = f"user:{actor.id}" if actor.id is not None else "system"
    request_hash = _hash(payload)

    # Claim the key; if another transaction holds it, this blocks until that one finishes.
    session.execute(
        insert(IdempotencyKey)
        .values(
            scope=scope, actor_key=actor_key, key=key, request_hash=request_hash, actor_id=actor.id
        )
        .on_conflict_do_nothing(constraint="uq_idempotency_keys_scope_actor_key")
    )
    record = repo.get_idempotency_key(session, scope, actor_key, key)
    if record is None:  # pragma: no cover - defensive
        raise Conflict("Could not claim idempotency key; retry", code="idempotency_retry")
    if record.request_hash != request_hash:
        raise ValidationFailed(
            "This Idempotency-Key was already used with a different request",
            code="idempotency_key_reused",
        )
    if record.response_body is not None:
        return record.response_body
    body = run()
    record.response_body = body
    record.response_status = 201
    session.flush()
    return body
