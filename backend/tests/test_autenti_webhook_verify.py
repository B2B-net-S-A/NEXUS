"""Unit tests for the Autenti webhook JWT verifier.

Generates a fresh RSA keypair per test run, signs synthetic webhook
payloads, and exercises the verify_jwt code path against the produced
JWKS. No network — :func:`_fetch_jwks` is monkeypatched.
"""

from __future__ import annotations

import base64
import time
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt

from app.services.autenti.webhook_verify import (
    AutentiWebhookError,
    _reset_cache_for_tests,
    verify_jwt,
)


def _generate_rsa_keypair() -> tuple[rsa.RSAPrivateKey, dict[str, Any]]:
    """Return (private_key, jwk-dict) for signing + JWKS injection."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    numbers = public_key.public_numbers()

    def _b64(value: int) -> str:
        byte_length = (value.bit_length() + 7) // 8
        raw = value.to_bytes(byte_length, "big")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    jwk = {
        "kty": "RSA",
        "kid": "test-key-1",
        "use": "sig",
        "alg": "RS256",
        "n": _b64(numbers.n),
        "e": _b64(numbers.e),
    }
    return private_key, jwk


def _sign(private_key: rsa.RSAPrivateKey, payload: dict[str, Any], kid: str) -> str:
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return jwt.encode(payload, pem, algorithm="RS256", headers={"kid": kid})


@pytest.fixture(autouse=True)
def _clear_cache():
    """Reset module-level JWKS cache between tests."""
    _reset_cache_for_tests()
    yield
    _reset_cache_for_tests()


@pytest.fixture
def keypair():
    return _generate_rsa_keypair()


def _patch_jwks(monkeypatch, jwks: dict[str, dict[str, Any]]):
    async def fake_fetch(force: bool = False):
        return jwks

    monkeypatch.setattr("app.services.autenti.webhook_verify._fetch_jwks", fake_fetch)


@pytest.mark.asyncio
async def test_verify_returns_claims_on_valid_signature(monkeypatch, keypair):
    private_key, jwk = keypair
    _patch_jwks(monkeypatch, {jwk["kid"]: jwk})

    payload = {
        "iat": int(time.time()),
        "iss": "autenti.com",
        "jti": "evt-001",
        "eventType": "SIGNING_PROCESS_COMPLETED",
        "processId": "proc-1",
    }
    token = _sign(private_key, payload, kid=jwk["kid"])

    claims = await verify_jwt(token)

    assert claims["jti"] == "evt-001"
    assert claims["eventType"] == "SIGNING_PROCESS_COMPLETED"


@pytest.mark.asyncio
async def test_verify_rejects_tampered_signature(monkeypatch, keypair):
    private_key, jwk = keypair
    _patch_jwks(monkeypatch, {jwk["kid"]: jwk})

    payload = {"iat": int(time.time()), "jti": "evt-002"}
    token = _sign(private_key, payload, kid=jwk["kid"])

    # Mangle the signature segment.
    head, body, sig = token.split(".")
    tampered = f"{head}.{body}.{'A' * len(sig)}"

    with pytest.raises(AutentiWebhookError):
        await verify_jwt(tampered)


@pytest.mark.asyncio
async def test_verify_rejects_unknown_kid(monkeypatch, keypair):
    private_key, jwk = keypair
    # JWKS contains only kid=test-key-1; we'll sign with a different one.
    _patch_jwks(monkeypatch, {jwk["kid"]: jwk})

    payload = {"iat": int(time.time()), "jti": "evt-003"}
    token = _sign(private_key, payload, kid="rotated-key-99")

    with pytest.raises(AutentiWebhookError, match="Unknown JWT kid"):
        await verify_jwt(token)


@pytest.mark.asyncio
async def test_verify_rejects_old_iat(monkeypatch, keypair):
    private_key, jwk = keypair
    _patch_jwks(monkeypatch, {jwk["kid"]: jwk})

    # 2 days old — exceeds the default 24h window.
    payload = {
        "iat": int(time.time()) - (2 * 24 * 3600),
        "jti": "evt-004",
        "processId": "proc-1",
    }
    token = _sign(private_key, payload, kid=jwk["kid"])

    with pytest.raises(AutentiWebhookError, match="iat"):
        await verify_jwt(token)


@pytest.mark.asyncio
async def test_verify_accepts_iat_within_window(monkeypatch, keypair):
    private_key, jwk = keypair
    _patch_jwks(monkeypatch, {jwk["kid"]: jwk})

    # 30 minutes ago — well within window.
    payload = {
        "iat": int(time.time()) - 1800,
        "jti": "evt-005",
        "processId": "proc-1",
    }
    token = _sign(private_key, payload, kid=jwk["kid"])

    claims = await verify_jwt(token)
    assert claims["jti"] == "evt-005"


@pytest.mark.asyncio
async def test_verify_rejects_jwt_without_kid(monkeypatch, keypair):
    private_key, jwk = keypair
    _patch_jwks(monkeypatch, {jwk["kid"]: jwk})

    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    # No kid header.
    token = jwt.encode({"jti": "evt-006"}, pem, algorithm="RS256")

    with pytest.raises(AutentiWebhookError, match="kid"):
        await verify_jwt(token)
