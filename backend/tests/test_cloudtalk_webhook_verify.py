"""Unit tests for :func:`app.services.cloudtalk.verify_signature`.

Pure functional — no DB, no HTTP. Exercises HMAC-SHA256 signature comparison
with the shared secret CloudTalk delivers in dashboard → Integrations →
Webhooks.
"""

from __future__ import annotations

import hashlib
import hmac

import pytest

from app.services.cloudtalk import verify_signature


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def test_verify_signature_accepts_valid_hex() -> None:
    body = b'{"call":{"id":"abc"}}'
    secret = "topsecret"
    sig = _sign(body, secret)
    assert verify_signature(body, sig, secret) is True


def test_verify_signature_accepts_sha256_prefix() -> None:
    body = b'{"call":{"id":"abc"}}'
    secret = "topsecret"
    sig = "sha256=" + _sign(body, secret)
    assert verify_signature(body, sig, secret) is True


def test_verify_signature_accepts_uppercase_prefix() -> None:
    body = b"x"
    secret = "s"
    sig = "SHA256=" + _sign(body, secret)
    assert verify_signature(body, sig, secret) is True


def test_verify_signature_strips_whitespace() -> None:
    body = b"x"
    secret = "s"
    sig = "  " + _sign(body, secret) + "\n"
    assert verify_signature(body, sig, secret) is True


def test_verify_signature_rejects_mismatch() -> None:
    body = b'{"call":{"id":"abc"}}'
    assert verify_signature(body, "deadbeef", "topsecret") is False


def test_verify_signature_rejects_wrong_secret() -> None:
    body = b"hello"
    sig = _sign(body, "right")
    assert verify_signature(body, sig, "wrong") is False


def test_verify_signature_rejects_body_tamper() -> None:
    sig = _sign(b'{"call":{"id":"abc"}}', "s")
    assert verify_signature(b'{"call":{"id":"XXX"}}', sig, "s") is False


@pytest.mark.parametrize(
    "secret, header",
    [
        ("", "abc"),
        ("s", ""),
        ("", ""),
    ],
)
def test_verify_signature_fail_closed_on_empty(secret: str, header: str) -> None:
    assert verify_signature(b"x", header, secret) is False
