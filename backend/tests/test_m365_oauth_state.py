"""Unit tests for the signed OAuth state JWT."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest
from jose import JWTError, jwt

from app.core.config import settings
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
    # Tamper with last character → signature mismatch.
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
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
