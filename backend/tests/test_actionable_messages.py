"""Phase 7.5 — Outlook Actionable Messages tests.

Two layers:
1. Pure-function tests for `app.services.m365.actionable_messages` — JWT
   round-trip, payload shape, fallback link.
2. Integration tests for `POST /api/public/interview-confirmation` — happy
   path, expired/tampered token, mismatched candidate, idempotent re-click.

The integration tests need real DB rows (CalendarEvent + Candidate) so they
go through `app_client` from conftest.py. Pure tests don't touch the DB.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from jose import jwt

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.candidate import Candidate
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


# ── Integration: public endpoint ───────────────────────────────────────────
# Each test below carries its own `@pytest.mark.asyncio`; the pure-function
# block above doesn't need an event loop.


@pytest_asyncio.fixture
async def candidate_and_event() -> tuple[int, int]:
    """Create a candidate + a calendar event linked to that candidate. Returns
    `(candidate_id, event_id)`. Cleanup is left to the test DB lifecycle —
    each test row uses a uuid suffix to avoid collisions."""
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name=f"Test{suffix}",
            lastname=f"Cand{suffix}",
            email=f"cand-{suffix}@example.com",
        )
        db.add(candidate)
        await db.flush()

        event = CalendarEvent(
            title=f"Interview {suffix}",
            event_type=EventType.interview,
            start_time=datetime.now(timezone.utc) + timedelta(days=2),
            end_time=datetime.now(timezone.utc) + timedelta(days=2, hours=1),
            candidate_id=candidate.id,
            status=EventStatus.scheduled,
        )
        db.add(event)
        await db.commit()
        await db.refresh(candidate)
        await db.refresh(event)
        return candidate.id, event.id


@pytest.mark.asyncio
async def test_confirm_interview_happy_path(
    app_client: AsyncClient, candidate_and_event: tuple[int, int]
) -> None:
    candidate_id, event_id = candidate_and_event
    token = sign_confirmation_token(event_id=event_id, candidate_id=candidate_id)

    resp = await app_client.post(
        "/api/public/interview-confirmation", params={"token": token}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["confirmed_at"]

    async with AsyncSessionLocal() as db:
        event = await db.get(CalendarEvent, event_id)
        assert event is not None
        assert event.candidate_confirmed_at is not None
        assert event.candidate_confirmation_source == "outlook_actionable"


@pytest.mark.asyncio
async def test_confirm_interview_is_idempotent(
    app_client: AsyncClient, candidate_and_event: tuple[int, int]
) -> None:
    """Second click returns the original timestamp — Outlook re-renders the
    POST response inline, so flipping the time on the second click would
    confuse the user."""
    candidate_id, event_id = candidate_and_event
    token = sign_confirmation_token(event_id=event_id, candidate_id=candidate_id)

    first = await app_client.post(
        "/api/public/interview-confirmation", params={"token": token}
    )
    assert first.status_code == 200, first.text
    second = await app_client.post(
        "/api/public/interview-confirmation", params={"token": token}
    )
    assert second.status_code == 200, second.text
    assert first.json()["confirmed_at"] == second.json()["confirmed_at"]


@pytest.mark.asyncio
async def test_confirm_interview_rejects_expired_token(
    app_client: AsyncClient, candidate_and_event: tuple[int, int]
) -> None:
    candidate_id, event_id = candidate_and_event
    expired_payload = {
        "event_id": event_id,
        "candidate_id": candidate_id,
        "action": "confirm_interview",
        "purpose": "interview_confirmation",
        "iat": datetime.now(timezone.utc) - timedelta(days=10),
        "exp": datetime.now(timezone.utc) - timedelta(days=1),
    }
    token = jwt.encode(expired_payload, _signing_key(), algorithm="HS256")

    resp = await app_client.post(
        "/api/public/interview-confirmation", params={"token": token}
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_confirm_interview_rejects_wrong_action(
    app_client: AsyncClient, candidate_and_event: tuple[int, int]
) -> None:
    """A token for a different action (future `cancel_interview`?) must not
    fall through to confirmation."""
    candidate_id, event_id = candidate_and_event
    payload = {
        "event_id": event_id,
        "candidate_id": candidate_id,
        "action": "cancel_interview",
        "purpose": "interview_confirmation",
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(days=1),
    }
    token = jwt.encode(payload, _signing_key(), algorithm="HS256")

    resp = await app_client.post(
        "/api/public/interview-confirmation", params={"token": token}
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_confirm_interview_rejects_candidate_mismatch(
    app_client: AsyncClient, candidate_and_event: tuple[int, int]
) -> None:
    """JWT pinned to candidate X but event belongs to candidate Y."""
    _real_candidate_id, event_id = candidate_and_event
    bogus_candidate_id = 999_999_999  # not in DB; must not match
    token = sign_confirmation_token(event_id=event_id, candidate_id=bogus_candidate_id)

    resp = await app_client.post(
        "/api/public/interview-confirmation", params={"token": token}
    )
    assert resp.status_code == 403

    async with AsyncSessionLocal() as db:
        event = await db.get(CalendarEvent, event_id)
        assert event is not None
        assert event.candidate_confirmed_at is None  # unchanged


@pytest.mark.asyncio
async def test_confirm_interview_unknown_event(app_client: AsyncClient) -> None:
    token = sign_confirmation_token(event_id=999_999_999, candidate_id=1)
    resp = await app_client.post(
        "/api/public/interview-confirmation", params={"token": token}
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_confirm_interview_garbage_token(app_client: AsyncClient) -> None:
    resp = await app_client.post(
        "/api/public/interview-confirmation",
        params={"token": "this.is.not.a.real.jwt.token.value"},
    )
    assert resp.status_code == 403
