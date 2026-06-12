"""Integration tests for ``POST /api/dialer/webhook`` (in-process app_client).

Mirrors test_cloudtalk_webhook.py: DRY-RUN when disabled, 401 on bad HMAC,
INSERT on a matching phone, idempotent UPSERT by provider_call_id, and no row
for an unknown phone. The background transcription dispatch is patched out.
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

WEBHOOK_SECRET = "test-dialer-shared-secret"


def _sign(body: bytes, secret: str = WEBHOOK_SECRET) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


@pytest_asyncio.fixture
async def seeded_candidate():
    unique = uuid.uuid4().hex[:8]
    phone = "+48 601-234-567"  # mixed formatting → exercises last-9 normalization
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name=f"Dialer-{unique}",
            lastname="Test",
            email=f"dialer-cand-{unique}@example.com",
            phone=phone,
        )
        db.add(cand)
        await db.commit()
        await db.refresh(cand)
        candidate_id = cand.id

    yield {"id": candidate_id, "phone": phone}

    async with AsyncSessionLocal() as db:
        await db.execute(delete(Call).where(Call.candidate_id == candidate_id))
        await db.execute(delete(Candidate).where(Candidate.id == candidate_id))
        await db.commit()


@pytest.fixture
def _enable_dialer(monkeypatch):
    monkeypatch.setattr(settings, "OWN_DIALER_ENABLED", True, raising=False)
    monkeypatch.setattr(
        settings, "DIALER_WEBHOOK_SECRET", WEBHOOK_SECRET, raising=False
    )


@pytest.fixture
def _no_transcription(monkeypatch):
    """Stop the webhook from spawning a real background transcription task."""
    monkeypatch.setattr(
        "app.services.dialer.transcription.schedule_transcription",
        lambda *a, **k: None,
    )


async def test_dry_run_when_disabled(app_client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "OWN_DIALER_ENABLED", False, raising=False)
    body = json.dumps({"call_sid": "cs-dry", "to": "+48601234567"}).encode()
    resp = await app_client.post(
        "/api/dialer/webhook", content=body, headers={"X-Dialer-Signature": "whatever"}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "dry-run"


async def test_bad_signature_rejected(app_client: AsyncClient, _enable_dialer):
    body = json.dumps({"call_sid": "cs-bad", "to": "+48601234567"}).encode()
    resp = await app_client.post(
        "/api/dialer/webhook", content=body, headers={"X-Dialer-Signature": "deadbeef"}
    )
    assert resp.status_code == 401


async def test_insert_on_matching_phone(
    app_client: AsyncClient, seeded_candidate, _enable_dialer, _no_transcription
):
    call_sid = f"cs-{uuid.uuid4().hex[:10]}"
    payload = {
        "call_sid": call_sid,
        "direction": "outbound",
        "to": "+48601234567",
        "call_status": "completed",
        "duration": 95,
        "recording_url": "https://gw.example/rec/abc.mp3",
    }
    body = json.dumps(payload).encode()
    resp = await app_client.post(
        "/api/dialer/webhook", content=body, headers={"X-Dialer-Signature": _sign(body)}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "ok"
    assert data["candidate_matched"] is True

    async with AsyncSessionLocal() as db:
        call = await db.scalar(select(Call).where(Call.provider_call_id == call_sid))
        assert call is not None
        assert call.candidate_id == seeded_candidate["id"]
        assert call.provider_type == "dialer"
        assert call.duration_seconds == 95
        assert call.recording_url == "https://gw.example/rec/abc.mp3"


async def test_idempotent_update_by_provider_call_id(
    app_client: AsyncClient, seeded_candidate, _enable_dialer, _no_transcription
):
    call_sid = f"cs-{uuid.uuid4().hex[:10]}"
    first = {"call_sid": call_sid, "to": "+48601234567", "duration": 30}
    b1 = json.dumps(first).encode()
    r1 = await app_client.post(
        "/api/dialer/webhook", content=b1, headers={"X-Dialer-Signature": _sign(b1)}
    )
    assert r1.status_code == 200

    second = {"call_sid": call_sid, "to": "+48601234567", "duration": 120}
    b2 = json.dumps(second).encode()
    r2 = await app_client.post(
        "/api/dialer/webhook", content=b2, headers={"X-Dialer-Signature": _sign(b2)}
    )
    assert r2.status_code == 200

    async with AsyncSessionLocal() as db:
        rows = (
            (await db.execute(select(Call).where(Call.provider_call_id == call_sid)))
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].duration_seconds == 120  # updated, not duplicated


async def test_unknown_phone_no_row(
    app_client: AsyncClient, _enable_dialer, _no_transcription
):
    payload = {"call_sid": f"cs-{uuid.uuid4().hex[:8]}", "to": "+48999000111"}
    body = json.dumps(payload).encode()
    resp = await app_client.post(
        "/api/dialer/webhook", content=body, headers={"X-Dialer-Signature": _sign(body)}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["candidate_matched"] is False
    assert data["call_id"] is None
