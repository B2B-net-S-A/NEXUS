"""Unit tests for :func:`app.services.cloudtalk.verify_signature`.

Pure functional — no DB, no HTTP. Exercises HMAC-SHA256 signature comparison
with the shared secret CloudTalk delivers in dashboard → Integrations →
Webhooks.
"""

from __future__ import annotations

import hashlib
import hmac

import pytest

from app.services.cloudtalk import timestamp_is_fresh, verify_signature


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _sign_ts(timestamp: str, body: bytes, secret: str) -> str:
    material = timestamp.encode("utf-8") + b"." + body
    return hmac.new(secret.encode("utf-8"), material, hashlib.sha256).hexdigest()


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


# ── Replay protection: timestamp-bound signatures (M6-P0.12) ─────────────────


def test_verify_signature_accepts_valid_timestamped() -> None:
    body = b'{"call":{"id":"abc"}}'
    secret = "topsecret"
    ts = "1721577600"
    sig = _sign_ts(ts, body, secret)
    assert verify_signature(body, sig, secret, timestamp=ts) is True


def test_verify_signature_timestamped_rejects_body_only_sig() -> None:
    # A signature computed over the body only must NOT verify when a timestamp
    # is folded into the signed material — this is what stops replay under a
    # forged fresh timestamp.
    body = b'{"call":{"id":"abc"}}'
    secret = "topsecret"
    ts = "1721577600"
    body_only_sig = _sign(body, secret)
    assert verify_signature(body, body_only_sig, secret, timestamp=ts) is False


def test_verify_signature_rejects_tampered_timestamp() -> None:
    # Signature is bound to the original timestamp; swapping the timestamp
    # (as a replay attacker would to stay fresh) breaks verification.
    body = b'{"call":{"id":"abc"}}'
    secret = "topsecret"
    sig = _sign_ts("1721577600", body, secret)
    assert verify_signature(body, sig, secret, timestamp="1721580000") is False


def test_verify_signature_timestamped_accepts_sha256_prefix() -> None:
    body = b"x"
    secret = "s"
    ts = "1721577600"
    sig = "sha256=" + _sign_ts(ts, body, secret)
    assert verify_signature(body, sig, secret, timestamp=ts) is True


def test_timestamp_is_fresh_within_window() -> None:
    now = 1_721_577_600.0
    assert timestamp_is_fresh("1721577500", 300, now=now) is True  # 100s old
    assert timestamp_is_fresh("1721577700", 300, now=now) is True  # 100s ahead


def test_timestamp_is_fresh_rejects_stale() -> None:
    now = 1_721_577_600.0
    # 10 minutes old — outside the ±5 min window → replay rejected.
    assert timestamp_is_fresh("1721577000", 300, now=now) is False
    # 10 minutes in the future → also rejected.
    assert timestamp_is_fresh("1721578200", 300, now=now) is False


def test_timestamp_is_fresh_boundary_inclusive() -> None:
    now = 1_721_577_600.0
    assert timestamp_is_fresh("1721577300", 300, now=now) is True  # exactly 300s


@pytest.mark.parametrize("bad", ["", "  ", "not-a-number", "abc123", None])
def test_timestamp_is_fresh_fail_closed_on_malformed(bad) -> None:
    assert timestamp_is_fresh(bad, 300, now=1_721_577_600.0) is False
