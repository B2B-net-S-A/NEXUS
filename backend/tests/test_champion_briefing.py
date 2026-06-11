"""Tests for the DL briefing (breakout session) on the Champion Profile.

Covers: attaching a meeting Note as the briefing (with server-side stamps),
validation (meeting-type only, no cross-job steal), detach, PUT preservation
and the audio-url endpoint's 404 when no audio was captured.

All calls use enrich=False — enrichment is LLM-backed and covered by the
Phase 14 intake tests.
"""

from __future__ import annotations

import pytest


async def _seed_job(title: str = "Senior Python Developer") -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job

    async with AsyncSessionLocal() as db:
        client = Client(name="BriefClient Sp. z o.o.")
        db.add(client)
        await db.flush()
        job = Job(title=title, client_id=client.id, description="", requirements="")
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id


async def _seed_meeting_note(
    job_id: int | None,
    *,
    note_type: str = "meeting",
    audio_url: str | None = None,
) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.note import Note, NoteType

    async with AsyncSessionLocal() as db:
        note = Note(
            content="# Briefing: Senior Python\n\nDL opowiada o roli…",
            note_type=NoteType(note_type),
            job_id=job_id,
            source_ref=None,
            audio_url=audio_url,
        )
        db.add(note)
        await db.commit()
        await db.refresh(note)
        return note.id


@pytest.mark.asyncio
async def test_attach_briefing_happy_path(app_client, app_auth_headers):
    job_id = await _seed_job()
    note_id = await _seed_meeting_note(job_id)
    resp = await app_client.post(
        f"/api/jobs/{job_id}/champion-profile/briefing",
        json={"note_id": note_id, "enrich": False},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200
    briefing = resp.json()["champion_profile"]["briefing"]
    assert briefing["status"] == "attached"
    assert briefing["note_id"] == note_id
    assert briefing["title"] == "Briefing: Senior Python"
    assert briefing["attached_by_id"] is not None
    assert briefing["attached_at"]
    # Test env has no object storage configured → no audio copied.
    assert briefing["audio_storage_key"] is None


@pytest.mark.asyncio
async def test_attach_briefing_rejects_non_meeting_note(
    app_client, app_auth_headers
):
    job_id = await _seed_job()
    note_id = await _seed_meeting_note(job_id, note_type="general")
    resp = await app_client.post(
        f"/api/jobs/{job_id}/champion-profile/briefing",
        json={"note_id": note_id, "enrich": False},
        headers=app_auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_attach_briefing_rejects_other_jobs_note(
    app_client, app_auth_headers
):
    job_a = await _seed_job("Job A")
    job_b = await _seed_job("Job B")
    note_id = await _seed_meeting_note(job_a)
    resp = await app_client.post(
        f"/api/jobs/{job_b}/champion-profile/briefing",
        json={"note_id": note_id, "enrich": False},
        headers=app_auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_attach_briefing_links_unattached_note(app_client, app_auth_headers):
    job_id = await _seed_job()
    note_id = await _seed_meeting_note(None)  # meeting bez job_id
    resp = await app_client.post(
        f"/api/jobs/{job_id}/champion-profile/briefing",
        json={"note_id": note_id, "enrich": False},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["champion_profile"]["briefing"]["note_id"] == note_id


@pytest.mark.asyncio
async def test_detach_briefing(app_client, app_auth_headers):
    job_id = await _seed_job()
    note_id = await _seed_meeting_note(job_id)
    await app_client.post(
        f"/api/jobs/{job_id}/champion-profile/briefing",
        json={"note_id": note_id, "enrich": False},
        headers=app_auth_headers,
    )
    resp = await app_client.delete(
        f"/api/jobs/{job_id}/champion-profile/briefing",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["champion_profile"]["briefing"]["status"] == "pending"


@pytest.mark.asyncio
async def test_put_profile_preserves_briefing(app_client, app_auth_headers):
    job_id = await _seed_job()
    note_id = await _seed_meeting_note(job_id)
    await app_client.post(
        f"/api/jobs/{job_id}/champion-profile/briefing",
        json={"note_id": note_id, "enrich": False},
        headers=app_auth_headers,
    )
    put = await app_client.put(
        f"/api/jobs/{job_id}/champion-profile",
        json={
            "sourcing": {
                "sources": ["linkedin"],
                "keywords": "python",
                "target_companies": "",
                "notes": "",
            },
            "briefing": {"status": "pending"},  # próba wyczyszczenia
        },
        headers=app_auth_headers,
    )
    assert put.status_code == 200
    briefing = put.json()["champion_profile"]["briefing"]
    assert briefing["status"] == "attached"
    assert briefing["note_id"] == note_id


@pytest.mark.asyncio
async def test_audio_url_404_when_no_audio(app_client, app_auth_headers):
    job_id = await _seed_job()
    note_id = await _seed_meeting_note(job_id)
    await app_client.post(
        f"/api/jobs/{job_id}/champion-profile/briefing",
        json={"note_id": note_id, "enrich": False},
        headers=app_auth_headers,
    )
    resp = await app_client.get(
        f"/api/jobs/{job_id}/champion-profile/briefing/audio-url",
        headers=app_auth_headers,
    )
    assert resp.status_code == 404
