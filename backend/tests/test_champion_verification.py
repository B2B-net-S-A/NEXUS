"""Tests for the Champion Profile two-sided verification.

Covers:
  - validation rules (delta-or-confirm for the client side, reason for skip,
    insights required for the consultant side),
  - server-side stamping of who/when,
  - the PUT champion-profile endpoint preserving stored verification,
  - the consultant-suggestions endpoint (hired-latest at this client).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


async def _seed_client_and_job():
    """Seed a minimal client + job directly through the DB."""
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job

    async with AsyncSessionLocal() as db:
        client = Client(name="VerifClient Sp. z o.o.")
        db.add(client)
        await db.flush()
        job = Job(
            title="Senior Java Developer",
            client_id=client.id,
            description="",
            requirements="",
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return client.id, job.id


async def _seed_hired_candidate(client_id: int, *, lastname: str = "Konsultant"):
    """Seed a candidate whose LATEST stage is `hired` on a job of `client_id`."""
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.job import Job
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    async with AsyncSessionLocal() as db:
        job = Job(
            title="Java Developer (placed)",
            client_id=client_id,
            description="",
            requirements="",
        )
        candidate = Candidate(name="Janina", lastname=lastname)
        db.add_all([job, candidate])
        await db.flush()
        stage = CandidateStage(
            candidate_id=candidate.id,
            job_id=job.id,
            stage=PipelineStage.hired,
            moved_at=datetime.now(timezone.utc) - timedelta(days=30),
        )
        db.add(stage)
        await db.commit()
        return candidate.id


@pytest.mark.asyncio
async def test_client_verification_requires_delta_or_confirmation(
    app_client, app_auth_headers
):
    _, job_id = await _seed_client_and_job()
    resp = await app_client.post(
        f"/api/jobs/{job_id}/champion-profile/verification",
        json={
            "side": "client",
            "client": {"method": "call", "key_corrections": "  ", "confirmed_as_is": False},
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 422
    assert "request" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_client_verification_happy_path_stamps_actor(
    app_client, app_auth_headers
):
    _, job_id = await _seed_client_and_job()
    resp = await app_client.post(
        f"/api/jobs/{job_id}/champion-profile/verification",
        json={
            "side": "client",
            "client": {
                "method": "meeting",
                "key_corrections": "Klient pisał Java 8, realnie migrują na 17.",
                "confirmed_as_is": False,
            },
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 200
    verification = resp.json()["champion_profile"]["verification"]
    assert verification["client"]["status"] == "verified"
    assert verification["client"]["verified_by_id"] is not None
    assert verification["client"]["verified_by_name"]
    assert verification["client"]["verified_at"]
    assert verification["client"]["method"] == "meeting"
    assert verification["consultant"]["status"] == "pending"


@pytest.mark.asyncio
async def test_consultant_skip_requires_reason(app_client, app_auth_headers):
    _, job_id = await _seed_client_and_job()
    resp = await app_client.post(
        f"/api/jobs/{job_id}/champion-profile/verification",
        json={"side": "consultant", "consultant": {"skipped": True, "skip_reason": ""}},
        headers=app_auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_consultant_verification_requires_insights(
    app_client, app_auth_headers
):
    _, job_id = await _seed_client_and_job()
    resp = await app_client.post(
        f"/api/jobs/{job_id}/champion-profile/verification",
        json={
            "side": "consultant",
            "consultant": {"consultant_name": "Jan Kowalski", "insights": "   "},
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_consultant_verification_resolves_candidate_name(
    app_client, app_auth_headers
):
    client_id, job_id = await _seed_client_and_job()
    consultant_id = await _seed_hired_candidate(client_id, lastname="Nowakowska")
    resp = await app_client.post(
        f"/api/jobs/{job_id}/champion-profile/verification",
        json={
            "side": "consultant",
            "consultant": {
                "consultant_candidate_id": consultant_id,
                "insights": "Dużo legacy, standupy po angielsku, realnie 3 dni z biura.",
            },
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 200
    consultant = resp.json()["champion_profile"]["verification"]["consultant"]
    assert consultant["status"] == "verified"
    assert consultant["consultant_candidate_id"] == consultant_id
    assert consultant["consultant_name"] == "Janina Nowakowska"


@pytest.mark.asyncio
async def test_put_profile_preserves_verification(app_client, app_auth_headers):
    _, job_id = await _seed_client_and_job()
    verify = await app_client.post(
        f"/api/jobs/{job_id}/champion-profile/verification",
        json={
            "side": "client",
            "client": {"method": "call", "key_corrections": "x", "confirmed_as_is": True},
        },
        headers=app_auth_headers,
    )
    assert verify.status_code == 200

    # A regular profile save (even one trying to forge/clear verification)
    # must not touch the stored block.
    put = await app_client.put(
        f"/api/jobs/{job_id}/champion-profile",
        json={
            "sourcing": {"sources": ["linkedin"], "keywords": "kafka", "target_companies": "", "notes": ""},
            "verification": {
                "client": {"status": "pending", "key_corrections": "", "confirmed_as_is": False},
                "consultant": {"status": "verified", "insights": "forged", "skip_reason": ""},
            },
        },
        headers=app_auth_headers,
    )
    assert put.status_code == 200
    verification = put.json()["champion_profile"]["verification"]
    assert verification["client"]["status"] == "verified"
    assert verification["consultant"]["status"] == "pending"

    got = await app_client.get(
        f"/api/jobs/{job_id}/champion-profile", headers=app_auth_headers
    )
    assert got.json()["champion_profile"]["verification"]["client"]["status"] == "verified"


@pytest.mark.asyncio
async def test_verification_reset(app_client, app_auth_headers):
    _, job_id = await _seed_client_and_job()
    await app_client.post(
        f"/api/jobs/{job_id}/champion-profile/verification",
        json={
            "side": "client",
            "client": {"method": "call", "key_corrections": "y", "confirmed_as_is": False},
        },
        headers=app_auth_headers,
    )
    resp = await app_client.post(
        f"/api/jobs/{job_id}/champion-profile/verification",
        json={"side": "client", "reset": True},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200
    client_v = resp.json()["champion_profile"]["verification"]["client"]
    assert client_v["status"] == "pending"
    assert client_v["verified_by_id"] is None


@pytest.mark.asyncio
async def test_consultant_suggestions_returns_hired_at_client(
    app_client, app_auth_headers
):
    client_id, job_id = await _seed_client_and_job()
    consultant_id = await _seed_hired_candidate(client_id, lastname="Hirowana")

    resp = await app_client.get(
        f"/api/jobs/{job_id}/champion-profile/consultant-suggestions",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200
    rows = resp.json()
    by_id = {r["candidate_id"]: r for r in rows}
    assert consultant_id in by_id
    assert by_id[consultant_id]["name"] == "Janina Hirowana"
    assert by_id[consultant_id]["job_title"] == "Java Developer (placed)"
