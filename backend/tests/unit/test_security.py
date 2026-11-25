from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.security import (
    create_token,
    decode_token,
    encode_token,
    hash_password,
    verify_password,
)


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("s3cret-pass")
    assert hashed.startswith("$argon2")
    assert verify_password("s3cret-pass", hashed)
    assert not verify_password("wrong", hashed)
    assert not verify_password("x", "not-a-hash")


def test_token_roundtrip() -> None:
    payload = create_token(42, "access", ["accountant"])
    decoded = decode_token(encode_token(payload), "access")
    assert decoded.sub == 42
    assert decoded.roles == ["accountant"]
    assert decoded.jti == payload.jti


def test_token_type_is_enforced() -> None:
    token = encode_token(create_token(1, "refresh", []))
    with pytest.raises(ValueError, match="wrong token type"):
        decode_token(token, "access")


def test_expired_token_rejected() -> None:
    past = datetime.now(UTC) - timedelta(days=30)
    token = encode_token(create_token(1, "access", [], now=past))
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_token(token, "access")


def test_tampered_token_rejected() -> None:
    token = encode_token(create_token(1, "access", []))
    with pytest.raises(jwt.PyJWTError):
        decode_token(token[:-2] + ("aa" if not token.endswith("aa") else "bb"), "access")
