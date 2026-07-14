"""Contract tests for the central PyJWT boundary."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.jwt import JWTError, jwt, key_from_jwk

_HMAC_KEY = "nexus-test-signing-key-that-is-long-enough"


def _access_token(*, expires_at: datetime) -> str:
    return jwt.encode(
        {"sub": "42", "type": "access", "exp": expires_at},
        _HMAC_KEY,
        algorithm="HS256",
    )


def _base64url_uint(value: int) -> str:
    byte_length = (value.bit_length() + 7) // 8
    raw = value.to_bytes(byte_length, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _public_jwk(private_key: rsa.RSAPrivateKey) -> dict[str, Any]:
    numbers = private_key.public_key().public_numbers()
    return {
        "kty": "RSA",
        "kid": "compat-test-key",
        "use": "sig",
        "alg": "RS256",
        "n": _base64url_uint(numbers.n),
        "e": _base64url_uint(numbers.e),
    }


def test_hs256_round_trip() -> None:
    token = _access_token(
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5)
    )

    payload = jwt.decode(token, _HMAC_KEY, algorithms=["HS256"])

    assert payload["sub"] == "42"
    assert payload["type"] == "access"


def test_common_error_catches_bad_signature() -> None:
    token = _access_token(
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5)
    )

    with pytest.raises(JWTError):
        jwt.decode(
            token,
            "different-test-signing-key-that-is-also-long-enough",
            algorithms=["HS256"],
        )


def test_common_error_catches_expired_token() -> None:
    token = _access_token(
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)
    )

    with pytest.raises(JWTError):
        jwt.decode(token, _HMAC_KEY, algorithms=["HS256"])


def test_common_error_catches_disallowed_algorithm() -> None:
    token = _access_token(
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5)
    )

    with pytest.raises(JWTError):
        jwt.decode(token, _HMAC_KEY, algorithms=["HS384"])


def test_rs256_jwk_round_trip_and_header() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    token = jwt.encode(
        {"jti": "event-1", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        private_pem,
        algorithm="RS256",
        headers={"kid": "compat-test-key"},
    )

    header = jwt.get_unverified_header(token)
    payload = jwt.decode(
        token,
        key_from_jwk(_public_jwk(private_key)),
        algorithms=["RS256"],
        options={"verify_aud": False},
    )

    assert header["kid"] == "compat-test-key"
    assert header["alg"] == "RS256"
    assert payload["jti"] == "event-1"
