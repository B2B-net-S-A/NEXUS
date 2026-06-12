"""Integration tests for GET /api/dialer/calls/{id}/recording (authed proxy).

The recording is candidate PII — the endpoint must require auth and 404 when
there is no stored recording.
"""

from __future__ import annotations

import uuid

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.call import Call, CallStatus
from app.models.candidate import Candidate


@pytest_asyncio.fixture
async def call_without_recording():
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name=f"Rec-{unique}",
            lastname="Test",
            email=f"rec-{unique}@example.com",
            phone="+48 601-000-000",
        )
        db.add(cand)
        await db.commit()
        await db.refresh(cand)
        call = Call(
            candidate_id=cand.id,
            status=CallStatus.completed,
            provider_type="dialer",
            recording_storage_key=None,  # no stored audio
        )
        db.add(call)
        await db.commit()
        await db.refresh(call)
        ids = {"call_id": call.id, "candidate_id": cand.id}

    yield ids

    async with AsyncSessionLocal() as db:
        await db.execute(delete(Call).where(Call.candidate_id == ids["candidate_id"]))
        await db.execute(delete(Candidate).where(Candidate.id == ids["candidate_id"]))
        await db.commit()


async def test_recording_requires_auth(app_client: AsyncClient):
    # No Authorization header → HTTPBearer rejects before the handler.
    resp = await app_client.get("/api/dialer/calls/1/recording")
    assert resp.status_code in (401, 403)


async def test_recording_404_without_stored_key(
    app_client: AsyncClient, app_auth_headers, call_without_recording
):
    resp = await app_client.get(
        f"/api/dialer/calls/{call_without_recording['call_id']}/recording",
        headers=app_auth_headers,
    )
    assert resp.status_code == 404
