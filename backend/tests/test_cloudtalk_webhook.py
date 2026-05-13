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


@pytest.fixture
def _disable_enrichment(monkeypatch):
    """No-op the Champion enrichment LLM call — webhook should still 200."""

    async def _noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        "app.services.champion_draft_service.enrich_from_call", _noop
    )


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
        row = await db.scalar(
            select(Call).where(Call.cloudtalk_call_id == "ct-abc")
        )
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
