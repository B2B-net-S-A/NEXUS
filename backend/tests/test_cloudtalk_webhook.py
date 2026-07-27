"""Integration tests for ``POST /api/calls/webhook``.

Stands up the in-process FastAPI client (``app_client``), seeds a candidate
with a Polish-format phone, and exercises the webhook in three modes:
1. DRY-RUN (CLOUDTALK_ENABLED=False) — no DB writes, no HMAC check
2. Live + bad signature → 401
3. Live + good signature → insert ``Call`` row, then UPDATE on replay

The Champion enrichment path is patched out — covered by
:mod:`test_champion_ai_intake`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import random
import time
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.call import Call
from app.models.candidate import Candidate


WEBHOOK_SECRET = "test-cloudtalk-shared-secret"


def _sign(body: bytes, secret: str = WEBHOOK_SECRET) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _sign_ts(timestamp: str, body: bytes, secret: str = WEBHOOK_SECRET) -> str:
    material = timestamp.encode("utf-8") + b"." + body
    return hmac.new(secret.encode("utf-8"), material, hashlib.sha256).hexdigest()


def _fresh_ts() -> str:
    return str(int(time.time()))


@pytest_asyncio.fixture
async def seeded_candidate():
    """Create a candidate with a PL-formatted phone, yield, then cleanup."""
    unique = uuid.uuid4().hex[:8]
    email = f"webhook-cand-{unique}@example.com"
    # Mixed formatting on purpose — exercises last-9-digit normalization.
    phone = "+48 601-234-567"

    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name=f"Webhook-{unique}",
            lastname="Test",
            email=email,
            phone=phone,
        )
        db.add(cand)
        await db.commit()
        await db.refresh(cand)
        candidate_id = cand.id

    yield {"id": candidate_id, "phone": phone, "email": email}

    async with AsyncSessionLocal() as db:
        await db.execute(delete(Call).where(Call.candidate_id == candidate_id))
        await db.execute(delete(Candidate).where(Candidate.id == candidate_id))
        await db.commit()


@pytest_asyncio.fixture
async def ambiguous_candidates():
    """Seed TWO candidates that share the same trailing-9 phone digits.

    Different surface formatting, identical last-9 → an inbound webhook for that
    number matches both (F-12: ambiguous). A distinctive random suffix keeps
    these out of the way of the single-candidate ``seeded_candidate`` tests, and
    a per-test token isolates teardown of the unassigned (candidate_id NULL)
    Call row.
    """
    token = uuid.uuid4().hex[:8]
    suffix = f"{random.randint(100000000, 999999999)}"  # 9 digits
    async with AsyncSessionLocal() as db:
        c1 = Candidate(
            name=f"AmbA-{token}",
            lastname="Test",
            email=f"amb-a-{token}@example.com",
            phone=f"+48 {suffix[:3]}-{suffix[3:6]}-{suffix[6:]}",
        )
        c2 = Candidate(
            name=f"AmbB-{token}",
            lastname="Test",
            email=f"amb-b-{token}@example.com",
            phone=f"0048{suffix}",  # same last-9, different format
        )
        db.add_all([c1, c2])
        await db.commit()
        await db.refresh(c1)
        await db.refresh(c2)
        ids = [c1.id, c2.id]

    yield {"ids": ids, "token": token, "external_number": f"48{suffix}"}

    async with AsyncSessionLocal() as db:
        # Unassigned call has candidate_id NULL → not caught by the cascade on
        # candidate delete; clean it by its ct_id token first.
        await db.execute(delete(Call).where(Call.cloudtalk_call_id.like(f"%{token}%")))
        await db.execute(delete(Call).where(Call.candidate_id.in_(ids)))
        await db.execute(delete(Candidate).where(Candidate.id.in_(ids)))
        await db.commit()


@pytest.fixture
def _disable_enrichment(monkeypatch):
    """No-op the Champion enrichment LLM call — webhook should still 200."""

    async def _noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.services.champion_draft_service.enrich_from_call", _noop)


@pytest.fixture
def _enable_cloudtalk(monkeypatch):
    monkeypatch.setattr(settings, "CLOUDTALK_ENABLED", True, raising=False)
    monkeypatch.setattr(
        settings, "CLOUDTALK_WEBHOOK_SECRET", WEBHOOK_SECRET, raising=False
    )


@pytest.mark.asyncio
async def test_webhook_dry_run_when_disabled(
    app_client: AsyncClient, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "CLOUDTALK_ENABLED", False, raising=False)

    body = json.dumps({"call": {"id": "ct-abc", "phone": "+48601234567"}}).encode()
    resp = await app_client.post("/api/calls/webhook", content=body)

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "dry-run"
    assert data["enabled"] is False

    # No DB writes in dry-run mode.
    async with AsyncSessionLocal() as db:
        row = await db.scalar(select(Call).where(Call.cloudtalk_call_id == "ct-abc"))
        assert row is None


@pytest.mark.asyncio
async def test_webhook_rejects_bad_signature(
    app_client: AsyncClient, _enable_cloudtalk
) -> None:
    body = json.dumps({"call": {"id": "ct-bad"}}).encode()

    resp = await app_client.post(
        "/api/calls/webhook",
        content=body,
        headers={"X-CloudTalk-Signature": "deadbeef"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_webhook_rejects_when_secret_empty(
    app_client: AsyncClient, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "CLOUDTALK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "CLOUDTALK_WEBHOOK_SECRET", "", raising=False)

    body = json.dumps({"call": {"id": "ct-no-secret"}}).encode()
    sig = _sign(body, "any")
    resp = await app_client.post(
        "/api/calls/webhook",
        content=body,
        headers={"X-CloudTalk-Signature": sig},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_webhook_inserts_call_for_matching_phone(
    app_client: AsyncClient,
    seeded_candidate: dict,
    _enable_cloudtalk,
    _disable_enrichment,
) -> None:
    ct_id = f"ct-insert-{uuid.uuid4().hex[:6]}"
    payload = {
        "call": {
            "id": ct_id,
            "external_number": "48601234567",  # different format than DB
            "type": "outgoing",
            "duration": 125,
            "status": "completed",
            "summary": "Krótkie podsumowanie",
            "recording_url": "https://recordings.cloudtalk.io/abc.mp3",
        }
    }
    body = json.dumps(payload).encode()
    sig = _sign(body)

    resp = await app_client.post(
        "/api/calls/webhook",
        content=body,
        headers={"X-CloudTalk-Signature": sig},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "ok"
    assert data["candidate_matched"] is True
    assert data["enriched"] is False  # no transcript
    assert data["call_id"] is not None

    async with AsyncSessionLocal() as db:
        row = await db.scalar(select(Call).where(Call.cloudtalk_call_id == ct_id))
        assert row is not None
        assert row.candidate_id == seeded_candidate["id"]
        assert row.duration_seconds == 125
        assert row.summary == "Krótkie podsumowanie"
        assert row.recording_url == "https://recordings.cloudtalk.io/abc.mp3"


@pytest.mark.asyncio
async def test_webhook_idempotent_update_by_cloudtalk_call_id(
    app_client: AsyncClient,
    seeded_candidate: dict,
    _enable_cloudtalk,
    _disable_enrichment,
) -> None:
    ct_id = f"ct-idem-{uuid.uuid4().hex[:6]}"

    # First webhook — call-ended, no transcript yet.
    body1 = json.dumps(
        {
            "call": {
                "id": ct_id,
                "external_number": "48601234567",
                "type": "outgoing",
                "duration": 60,
                "status": "completed",
            }
        }
    ).encode()
    resp1 = await app_client.post(
        "/api/calls/webhook",
        content=body1,
        headers={"X-CloudTalk-Signature": _sign(body1)},
    )
    assert resp1.status_code == 200

    # Second webhook — transcript-ready arrives later for the same call.
    body2 = json.dumps(
        {
            "call": {
                "id": ct_id,
                "external_number": "48601234567",
                "transcript": "Cześć, dzwonię w sprawie rekrutacji.",
                "summary": "Kandydat zainteresowany",
            }
        }
    ).encode()
    resp2 = await app_client.post(
        "/api/calls/webhook",
        content=body2,
        headers={"X-CloudTalk-Signature": _sign(body2)},
    )
    assert resp2.status_code == 200

    async with AsyncSessionLocal() as db:
        rows = (
            await db.scalars(select(Call).where(Call.cloudtalk_call_id == ct_id))
        ).all()
        assert len(rows) == 1, "second webhook must UPDATE, not INSERT"
        call = rows[0]
        assert call.transcript == "Cześć, dzwonię w sprawie rekrutacji."
        assert call.summary == "Kandydat zainteresowany"
        assert call.duration_seconds == 60  # preserved from first event


@pytest.mark.asyncio
async def test_webhook_handles_unknown_phone_gracefully(
    app_client: AsyncClient, _enable_cloudtalk, _disable_enrichment
) -> None:
    """No matching candidate → 200 with candidate_matched=False, no row created."""
    ct_id = f"ct-unknown-{uuid.uuid4().hex[:6]}"
    body = json.dumps(
        {"call": {"id": ct_id, "external_number": "+1-555-000-9999"}}
    ).encode()

    resp = await app_client.post(
        "/api/calls/webhook",
        content=body,
        headers={"X-CloudTalk-Signature": _sign(body)},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["candidate_matched"] is False
    assert data["call_id"] is None


@pytest.mark.asyncio
async def test_webhook_leaves_ambiguous_phone_unassigned(
    app_client: AsyncClient,
    ambiguous_candidates: dict,
    _enable_cloudtalk,
    _disable_enrichment,
) -> None:
    """Two candidates share the last-9 phone → leave the call UNASSIGNED (F-12).

    The call must NOT be auto-attached to an arbitrary (e.g. newest) candidate,
    but it must NOT be lost either: a Call row is persisted with candidate_id
    NULL for manual attribution, and candidate-dependent enrichment is skipped
    even though a transcript is present.
    """
    ct_id = f"ct-amb-{ambiguous_candidates['token']}"
    payload = {
        "call": {
            "id": ct_id,
            "external_number": ambiguous_candidates["external_number"],
            "type": "incoming",
            "duration": 42,
            "status": "completed",
            "transcript": "Dzień dobry, dzwonię w sprawie oferty.",
            "summary": "Rozmowa wstępna",
        }
    }
    body = json.dumps(payload).encode()

    resp = await app_client.post(
        "/api/calls/webhook",
        content=body,
        headers={"X-CloudTalk-Signature": _sign(body)},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # Ambiguous → not attached to any candidate, and no enrichment...
    assert data["candidate_matched"] is False
    assert data["enriched"] is False
    # ...but the event is NOT lost: a Call row exists, unassigned.
    assert data["call_id"] is not None

    async with AsyncSessionLocal() as db:
        row = await db.scalar(select(Call).where(Call.cloudtalk_call_id == ct_id))
        assert row is not None, "ambiguous call must still be persisted"
        assert row.candidate_id is None, "ambiguous call must be left UNASSIGNED"
        assert row.candidate_id not in ambiguous_candidates["ids"]
        assert row.transcript == "Dzień dobry, dzwonię w sprawie oferty."


# ── Replay protection + no-secret-in-URL (M6-P0.12) ──────────────────────────


@pytest.mark.asyncio
async def test_webhook_accepts_fresh_timestamped_signature(
    app_client: AsyncClient,
    seeded_candidate: dict,
    _enable_cloudtalk,
    _disable_enrichment,
) -> None:
    """A fresh X-CloudTalk-Timestamp + signature over `ts.body` is accepted."""
    ct_id = f"ct-ts-{uuid.uuid4().hex[:6]}"
    body = json.dumps(
        {"call": {"id": ct_id, "external_number": "48601234567", "duration": 30}}
    ).encode()
    ts = _fresh_ts()

    resp = await app_client.post(
        "/api/calls/webhook",
        content=body,
        headers={
            "X-CloudTalk-Signature": _sign_ts(ts, body),
            "X-CloudTalk-Timestamp": ts,
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_webhook_rejects_stale_timestamp_replay(
    app_client: AsyncClient, _enable_cloudtalk, _disable_enrichment
) -> None:
    """A correctly-signed request with an old timestamp is rejected (replay)."""
    ct_id = f"ct-stale-{uuid.uuid4().hex[:6]}"
    body = json.dumps(
        {"call": {"id": ct_id, "external_number": "48601234567"}}
    ).encode()
    # 20 minutes old — well outside the ±5 min freshness window.
    stale_ts = str(int(time.time()) - 1200)

    resp = await app_client.post(
        "/api/calls/webhook",
        content=body,
        headers={
            "X-CloudTalk-Signature": _sign_ts(stale_ts, body),
            "X-CloudTalk-Timestamp": stale_ts,
        },
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_webhook_rejects_timestamp_signature_reuse_with_new_ts(
    app_client: AsyncClient, _enable_cloudtalk, _disable_enrichment
) -> None:
    """Captured signature replayed under a forged fresh timestamp → 401.

    The signature is bound to the original timestamp, so pairing it with a new
    (still-fresh) timestamp fails the HMAC — the core replay defense.
    """
    ct_id = f"ct-reuse-{uuid.uuid4().hex[:6]}"
    body = json.dumps(
        {"call": {"id": ct_id, "external_number": "48601234567"}}
    ).encode()
    captured_sig = _sign_ts(str(int(time.time()) - 60), body)

    resp = await app_client.post(
        "/api/calls/webhook",
        content=body,
        headers={
            "X-CloudTalk-Signature": captured_sig,
            "X-CloudTalk-Timestamp": _fresh_ts(),  # attacker forges a fresh ts
        },
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_webhook_requires_timestamp_when_configured(
    app_client: AsyncClient, _enable_cloudtalk, _disable_enrichment, monkeypatch
) -> None:
    """With REQUIRE_TIMESTAMP on, a legacy body-only request is rejected."""
    monkeypatch.setattr(
        settings, "CLOUDTALK_WEBHOOK_REQUIRE_TIMESTAMP", True, raising=False
    )
    body = json.dumps(
        {"call": {"id": "ct-req-ts", "external_number": "48601234567"}}
    ).encode()

    resp = await app_client.post(
        "/api/calls/webhook",
        content=body,
        headers={"X-CloudTalk-Signature": _sign(body)},  # no timestamp header
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_url_path_token_route_is_gone(
    app_client: AsyncClient, _enable_cloudtalk
) -> None:
    """The secret-in-URL variant must no longer exist (404, not auth-checked).

    Behavioral proof that the HMAC signing secret is never read from a URL
    path segment: posting to /api/calls/webhook/<anything> — including the
    real secret — routes to no handler.
    """
    body = json.dumps({"call": {"id": "ct-url"}}).encode()
    for token in ("some-token", WEBHOOK_SECRET):
        resp = await app_client.post(f"/api/calls/webhook/{token}", content=body)
        assert resp.status_code == 404, (
            f"URL-path-token webhook must not exist; got {resp.status_code} "
            f"for token={token!r}"
        )
