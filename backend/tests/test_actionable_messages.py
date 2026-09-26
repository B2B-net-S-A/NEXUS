"""Phase 7.5 — Outlook Actionable Messages tests.

Pure-function tests for `app.services.m365.actionable_messages` — JWT
round-trip, payload shape, fallback link.

Runda 7 (R7-N5-5): publiczny `POST /api/public/interview-confirmation` został
usunięty — nic nie wysyłało karty (`send_interview_invitation` bez wywołań),
a karta i link zapasowy robiły GET, więc trasa POST dawała 405. Ostatni test
pilnuje, że nieuwierzytelniony zapis do wydarzenia nie wróci po cichu.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt

from app.core.config import settings
from app.services.m365.actionable_messages import (
    ActionableMessageError,
    build_interview_confirmation_card,
    sign_confirmation_token,
    verify_confirmation_token,
)


# ── Pure: JWT round-trip ───────────────────────────────────────────────────


def _signing_key() -> str:
    return settings.M365_STATE_SIGNING_KEY or settings.SECRET_KEY


def test_sign_and_verify_roundtrip() -> None:
    token = sign_confirmation_token(event_id=42, candidate_id=7)
    payload = verify_confirmation_token(token)
    assert payload["event_id"] == 42
    assert payload["candidate_id"] == 7
    assert payload["action"] == "confirm_interview"
    assert payload["purpose"] == "interview_confirmation"


def test_tampered_token_rejected() -> None:
    token = sign_confirmation_token(event_id=1, candidate_id=2)
    # Flip the first char of the signature (6 real bits). The last char of
    # an HS256 signature only carries 4 data bits + 2 padding bits that b64
    # decoders ignore, so substituting the last char hits a same-byte
    # equivalence class ~1/16 of the time and the "tampered" token still
    # verifies — see tests/test_m365_oauth_state.py for the full writeup.
    header, payload, sig = token.split(".")
    flipped_sig = ("A" if sig[0] != "A" else "B") + sig[1:]
    tampered = ".".join([header, payload, flipped_sig])
    with pytest.raises(ActionableMessageError):
        verify_confirmation_token(tampered)


def test_expired_token_rejected() -> None:
    """Mint a token with a past `exp` and verify it's rejected."""
    payload = {
        "event_id": 1,
        "candidate_id": 1,
        "action": "confirm_interview",
        "purpose": "interview_confirmation",
        "iat": datetime.now(timezone.utc) - timedelta(seconds=120),
        "exp": datetime.now(timezone.utc) - timedelta(seconds=60),
    }
    token = jwt.encode(payload, _signing_key(), algorithm="HS256")
    with pytest.raises(ActionableMessageError):
        verify_confirmation_token(token)


def test_wrong_purpose_rejected() -> None:
    """Token signed for a different purpose (e.g. M365 OAuth state) must not
    be reusable here even though the signing key is shared."""
    payload = {
        "event_id": 1,
        "candidate_id": 1,
        "action": "confirm_interview",
        "purpose": "m365_oauth_state",
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    token = jwt.encode(payload, _signing_key(), algorithm="HS256")
    with pytest.raises(ActionableMessageError):
        verify_confirmation_token(token)


def test_missing_required_claim_rejected() -> None:
    payload = {
        # event_id missing
        "candidate_id": 1,
        "action": "confirm_interview",
        "purpose": "interview_confirmation",
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    token = jwt.encode(payload, _signing_key(), algorithm="HS256")
    with pytest.raises(ActionableMessageError):
        verify_confirmation_token(token)


# ── Pure: card builder ─────────────────────────────────────────────────────


def test_card_contains_jsonld_block() -> None:
    snippet, payload = build_interview_confirmation_card(event_id=99, candidate_id=11)
    assert '<script type="application/ld+json">' in snippet
    assert "</script>" in snippet
    assert payload["@type"] == "EmailMessage"
    assert payload["potentialAction"]["@type"] == "ViewAction"
    assert payload["potentialAction"]["name"] == "Potwierdzam interview"


def test_card_jsonld_target_carries_signed_token() -> None:
    snippet, payload = build_interview_confirmation_card(event_id=99, candidate_id=11)
    target = payload["potentialAction"]["target"]
    # Extract the token from the URL and verify it round-trips.
    m = re.search(r"token=([^&\s\"]+)", target)
    assert m is not None, f"token query missing from target URL: {target}"
    decoded = verify_confirmation_token(m.group(1))
    assert decoded["event_id"] == 99
    assert decoded["candidate_id"] == 11


def test_card_includes_visible_fallback_link() -> None:
    """Non-Outlook clients (Gmail, Apple Mail) ignore JSON-LD — they need a
    plain `<a>` link or the candidate has no way to confirm."""
    snippet, _ = build_interview_confirmation_card(event_id=1, candidate_id=2)
    assert '<a href="' in snippet
    assert "interview-confirmation" in snippet


def test_card_label_is_html_escaped() -> None:
    """If a future caller passes an attacker-controlled label (unlikely but
    defence-in-depth), the fallback link must HTML-escape it."""
    snippet, _ = build_interview_confirmation_card(
        event_id=1, candidate_id=2, button_label="<script>alert(1)</script>"
    )
    assert "<script>alert(1)</script>" not in snippet
    assert "&lt;script&gt;" in snippet


def test_card_jsonld_is_valid_json() -> None:
    """The JSON-LD block must parse — Outlook's parser is strict."""
    snippet, _ = build_interview_confirmation_card(event_id=1, candidate_id=2)
    m = re.search(
        r'<script type="application/ld\+json">(.*?)</script>', snippet, re.DOTALL
    )
    assert m is not None
    parsed = json.loads(m.group(1))
    assert parsed["@context"] == "https://schema.org/extensions"


# ── Runda 7 (R7-N5-5): trasa publiczna usunięta ────────────────────────────


def test_public_interview_confirmation_route_is_gone() -> None:
    from app.main import app

    paths = {getattr(route, "path", "") for route in app.routes}
    assert "/api/public/interview-confirmation" not in paths
