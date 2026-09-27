"""Unit tests for the signed OAuth state JWT."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import pytest
from jose import JWTError, jwt

from app.core.config import settings
from app.services.m365 import oauth as m365_oauth


def _signing_key() -> str:
    return settings.M365_STATE_SIGNING_KEY or settings.SECRET_KEY


def test_sign_and_verify_roundtrip() -> None:
    token = m365_oauth.sign_state(user_id=42, nonce="losowy-nonce")
    parsed = m365_oauth.verify_state(token)
    assert parsed.user_id == 42
    assert parsed.verifier == m365_oauth.pkce_verifier_for("losowy-nonce")
    assert 43 <= len(parsed.verifier) <= 128


def test_tampered_token_rejected() -> None:
    token = m365_oauth.sign_state(user_id=1)
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
    token = m365_oauth.sign_state(user_id=1)
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
        "n": "x",
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
        "n": "x",
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        "purpose": "something_else",
    }
    token = jwt.encode(payload, _signing_key(), algorithm="HS256")
    with pytest.raises(JWTError):
        m365_oauth.verify_state(token)


def test_pkce_pair_is_valid_length() -> None:
    verifier = m365_oauth.pkce_verifier_for("n")
    challenge = m365_oauth._derive_challenge(verifier)
    assert 43 <= len(verifier) <= 128
    # Challenge is URL-safe base64 of SHA-256 digest → 43 chars without padding.
    assert len(challenge) == 43


# ── Runda 11 (SEC): weryfikator poza adresem, `state` jednorazowy ────────────


def _query(url: str) -> dict[str, list[str]]:
    from urllib.parse import parse_qs, urlsplit

    return parse_qs(urlsplit(url).query)


def test_authorize_url_does_not_carry_the_pkce_verifier(monkeypatch) -> None:
    monkeypatch.setattr(settings, "M365_CLIENT_ID", "client-id")
    monkeypatch.setattr(settings, "M365_CLIENT_SECRET", "client-secret")
    url = m365_oauth.new_authorize_url(7)
    qs = _query(url)
    state = qs["state"][0]
    parsed = m365_oauth.verify_state(state)
    # Weryfikator nie stoi ani w adresie, ani w treści `state`.
    assert parsed.verifier not in url
    claims = jwt.get_unverified_claims(state)
    assert "pkce" not in claims
    assert parsed.verifier not in str(claims)
    # Challenge w adresie pasuje do weryfikatora wyliczanego przez serwer.
    assert qs["code_challenge"] == [m365_oauth._derive_challenge(parsed.verifier)]


def test_state_from_before_round_11_is_rejected() -> None:
    """``state`` z weryfikatorem w treści (bez ``n``) — łączenie od nowa."""
    payload = {
        "sub": "1",
        "pkce": "jawny-weryfikator",
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        "purpose": "m365_oauth_state",
    }
    token = jwt.encode(payload, _signing_key(), algorithm="HS256")
    with pytest.raises(JWTError):
        m365_oauth.verify_state(token)


def test_verifier_depends_on_the_signing_key(monkeypatch) -> None:
    before = m365_oauth.pkce_verifier_for("n")
    monkeypatch.setattr(settings, "M365_STATE_SIGNING_KEY", "inny-klucz-" + "k" * 40)
    assert m365_oauth.pkce_verifier_for("n") != before


class _Row:
    def __init__(self) -> None:
        self.value: dict = {}


class _StateDb:
    """Atrapa sesji dla ``consume_state`` — jeden wiersz ``app_settings``."""

    def __init__(self) -> None:
        self.row = _Row()

    async def execute(self, _stmt):
        return None

    async def scalar(self, _stmt):
        return self.row

    async def flush(self) -> None:
        return None


@pytest.mark.asyncio
async def test_state_is_consumed_only_once() -> None:
    db = _StateDb()
    parsed = m365_oauth.verify_state(m365_oauth.sign_state(user_id=3))
    assert await m365_oauth.consume_state(db, parsed) is True
    assert await m365_oauth.consume_state(db, parsed) is False
    # W bazie leży skrót `n`, nie sam `n`.
    assert list(db.row.value) == [parsed.nonce_digest]


@pytest.mark.asyncio
async def test_consumed_entries_expire_with_the_state() -> None:
    db = _StateDb()
    db.row.value = {
        "stary": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
        "zepsuty": "nie-data",
    }
    parsed = m365_oauth.verify_state(m365_oauth.sign_state(user_id=3))
    assert await m365_oauth.consume_state(db, parsed) is True
    assert set(db.row.value) == {parsed.nonce_digest}
