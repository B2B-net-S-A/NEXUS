"""Unit tests for the signed OAuth state JWT."""

from __future__ import annotations

import base64
import time
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.core.jwt import JWTError, jwt
from app.services.m365 import oauth as m365_oauth


def _signing_key() -> str:
    return settings.M365_STATE_SIGNING_KEY or settings.SECRET_KEY


def test_sign_and_verify_roundtrip() -> None:
    verifier, challenge = m365_oauth.generate_pkce_pair()
    token = m365_oauth.sign_state(user_id=42, pkce_verifier=verifier)
    uid, v = m365_oauth.verify_state(token)
    assert uid == 42
    assert v == verifier


def test_tampered_token_rejected() -> None:
    token = m365_oauth.sign_state(user_id=1, pkce_verifier="x")
    # Flip the FIRST character of the signature — that position carries 6
    # full data bits, so any substitution decodes to different bytes and the
    # HMAC check fails. We deliberately avoid the last char: an HS256
    # signature is 32 bytes → 43 base64url chars, and the trailing char only
    # carries 4 data bits + 2 padding bits. b64 decoders ignore padding
    # bits, so {A,B,C,D}, {E,F,G,H}, … each form an equivalence class that
    # decodes to the same byte. Flipping the last char hit that class ~1/16
    # of the time and the "tampered" token still verified — flaky CI fail.
    header, payload, sig = token.split(".")
    flipped_sig = ("A" if sig[0] != "A" else "B") + sig[1:]
    tampered = ".".join([header, payload, flipped_sig])
    with pytest.raises(JWTError):
        m365_oauth.verify_state(tampered)


def test_signature_byte_flip_rejected() -> None:
    """Regression: flipping any byte of the raw HMAC signature must be rejected.

    Anchors the strict-signature-verification invariant at the raw-byte
    level, independent of base64 encoding quirks (see the comment on
    test_tampered_token_rejected for why the encoded-form variant was
    flaky).
    """
    token = m365_oauth.sign_state(user_id=1, pkce_verifier="x")
    header, payload, sig_b64 = token.split(".")
    padded = sig_b64 + "=" * (-len(sig_b64) % 4)
    raw_sig = base64.urlsafe_b64decode(padded)
    flipped = bytes([raw_sig[0] ^ 0xFF]) + raw_sig[1:]
    new_sig = base64.urlsafe_b64encode(flipped).rstrip(b"=").decode("ascii")
    tampered = ".".join([header, payload, new_sig])
    with pytest.raises(JWTError):
        m365_oauth.verify_state(tampered)


def test_expired_state_rejected() -> None:
    """Mint a state JWT with a past `exp` and verify it's rejected."""
    payload = {
        "sub": "1",
        "pkce": "x",
        "iat": datetime.now(timezone.utc) - timedelta(seconds=60),
        "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
        "purpose": "m365_oauth_state",
    }
    token = jwt.encode(payload, _signing_key(), algorithm="HS256")
    with pytest.raises(JWTError):
        m365_oauth.verify_state(token)


def test_wrong_purpose_rejected() -> None:
    payload = {
        "sub": "1",
        "pkce": "x",
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        "purpose": "something_else",
    }
    token = jwt.encode(payload, _signing_key(), algorithm="HS256")
    with pytest.raises(JWTError):
        m365_oauth.verify_state(token)


def test_pkce_pair_is_valid_length() -> None:
    verifier, challenge = m365_oauth.generate_pkce_pair()
    assert 43 <= len(verifier) <= 128
    # Challenge is URL-safe base64 of SHA-256 digest → 43 chars without padding.
    assert len(challenge) == 43
