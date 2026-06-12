"""Integration test for the dialer recording retention purge.

Recordings older than DIALER_RECORDING_RETENTION_DAYS get their Object-Storage
blob deleted and ``recording_storage_key`` nulled; recent recordings are kept.
Storage deletion is monkeypatched (no real bucket).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest_asyncio
from sqlalchemy import delete

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.call import Call, CallStatus
from app.models.candidate import Candidate
from app.tasks.dialer_retention import purge_expired_recordings


@pytest_asyncio.fixture
async def two_calls():
    """One old call (past retention) + one recent call, both with recordings."""
    unique = uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name=f"Ret-{unique}",
            lastname="Test",
            email=f"ret-{unique}@example.com",
            phone="+48 601-555-000",
        )
        db.add(cand)
        await db.commit()
        await db.refresh(cand)

        old_call = Call(
            candidate_id=cand.id,
            status=CallStatus.completed,
            provider_type="dialer",
            recording_storage_key="recordings/old-key.mp3",
            created_at=now - timedelta(days=400),
        )
        recent_call = Call(
            candidate_id=cand.id,
            status=CallStatus.completed,
            provider_type="dialer",
            recording_storage_key="recordings/recent-key.mp3",
            created_at=now,
        )
        db.add_all([old_call, recent_call])
        await db.commit()
        await db.refresh(old_call)
        await db.refresh(recent_call)
        ids = {
            "candidate_id": cand.id,
            "old_id": old_call.id,
            "recent_id": recent_call.id,
        }

    yield ids

    async with AsyncSessionLocal() as db:
        await db.execute(delete(Call).where(Call.candidate_id == ids["candidate_id"]))
        await db.execute(delete(Candidate).where(Candidate.id == ids["candidate_id"]))
        await db.commit()


async def test_purge_expired_recordings(two_calls, monkeypatch):
    deleted: list[str] = []
    monkeypatch.setattr(
        "app.services.object_storage.is_available", lambda: True, raising=False
    )
    monkeypatch.setattr(
        "app.services.object_storage.delete_cv",
        lambda key: deleted.append(key),
        raising=False,
    )
    monkeypatch.setattr(settings, "DIALER_RECORDING_RETENTION_DAYS", 60, raising=False)

    async with AsyncSessionLocal() as db:
        purged = await purge_expired_recordings(db)

    assert purged == 1
    assert deleted == ["recordings/old-key.mp3"]

    async with AsyncSessionLocal() as db:
        old_call = await db.get(Call, two_calls["old_id"])
        recent_call = await db.get(Call, two_calls["recent_id"])
        assert old_call.recording_storage_key is None  # purged
        assert recent_call.recording_storage_key == "recordings/recent-key.mp3"  # kept


async def test_purge_nulls_key_even_if_storage_delete_fails(two_calls, monkeypatch):
    def _boom(key):
        raise RuntimeError("storage down")

    monkeypatch.setattr(
        "app.services.object_storage.is_available", lambda: True, raising=False
    )
    monkeypatch.setattr("app.services.object_storage.delete_cv", _boom, raising=False)
    monkeypatch.setattr(settings, "DIALER_RECORDING_RETENTION_DAYS", 60, raising=False)

    async with AsyncSessionLocal() as db:
        purged = await purge_expired_recordings(db)

    assert purged == 1  # best-effort: key nulled despite storage error
    async with AsyncSessionLocal() as db:
        old_call = await db.get(Call, two_calls["old_id"])
        assert old_call.recording_storage_key is None
