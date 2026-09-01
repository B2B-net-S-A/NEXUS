"""Integration tests for Phase 3 action endpoints.

Covers:
  * POST /api/recommendations/send-candidate-shortlist-email
      - happy path returns draft with subject + bodies + job_count
      - 400 when candidate has no email
      - 400 when job_ids list is empty
      - 400 when none of the supplied jobs are published
  * POST /api/recommendations/prepare-client-proposal
      - happy path returns blind_summary + draft_email
      - 404 when candidate or job missing
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate, CandidateStatus
from app.models.client import Client
from app.models.job import Job, JobStatus, RemotePolicy


async def _seed_candidate(*, email: str | None = "shortlist@example.com") -> int:
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Anna",
            lastname="Tester",
            email=email,
            status=CandidateStatus.active,
            skills=[{"name": "Python"}, {"name": "FastAPI"}],
            experience=[],
            languages=[{"lang": "Polski", "level": "C2"}],
            years_it_experience=5,
            competence_category="Backend",
            ai_summary="5 lat Pythona w fintechu.",
        )
        db.add(cand)
        await db.commit()
        await db.refresh(cand)
        return cand.id


async def _seed_published_job(
    title: str,
    *,
    location: str = "Warszawa",
    client_id: int | None = None,
) -> int:
    async with AsyncSessionLocal() as db:
        job = Job(
            title=title,
            description="desc",
            requirements="Python",
            location=location,
            salary_min=15000,
            salary_max=20000,
            remote_policy=RemotePolicy.remote,
            status=JobStatus.published,
            client_id=client_id,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id


async def _seed_client() -> int:
    async with AsyncSessionLocal() as db:
        client = Client(name="Phase3Co")
        db.add(client)
        await db.commit()
        await db.refresh(client)
        return client.id


async def _cleanup(
    *, candidate_ids: list[int], job_ids: list[int], client_ids: list[int]
):
    async with AsyncSessionLocal() as db:
        if job_ids:
            await db.execute(delete(Job).where(Job.id.in_(job_ids)))
        if candidate_ids:
            await db.execute(delete(Candidate).where(Candidate.id.in_(candidate_ids)))
        if client_ids:
            await db.execute(delete(Client).where(Client.id.in_(client_ids)))
        await db.commit()


# ── send-candidate-shortlist-email ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_shortlist_email_happy_path(
    app_client: AsyncClient, app_auth_headers: dict
):
    cid = await _seed_candidate()
    j1 = await _seed_published_job("Python Eng A")
    j2 = await _seed_published_job("Python Eng B")
    try:
        resp = await app_client.post(
            "/api/recommendations/send-candidate-shortlist-email",
            headers=app_auth_headers,
            json={"candidate_id": cid, "job_ids": [j1, j2]},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["candidate_id"] == cid
        assert body["to"] == "shortlist@example.com"
        assert body["job_count"] == 2
        assert "Mamy 2 propozycji" in body["subject"]
        assert "Python Eng A" in body["text_body"]
        assert "Python Eng B" in body["html_body"]
    finally:
        await _cleanup(candidate_ids=[cid], job_ids=[j1, j2], client_ids=[])


@pytest.mark.asyncio
async def test_shortlist_email_400_when_no_email(
    app_client: AsyncClient, app_auth_headers: dict
):
    cid = await _seed_candidate(email=None)
    j1 = await _seed_published_job("Python Eng C")
    try:
        resp = await app_client.post(
            "/api/recommendations/send-candidate-shortlist-email",
            headers=app_auth_headers,
            json={"candidate_id": cid, "job_ids": [j1]},
        )
        assert resp.status_code == 400
        assert "email" in resp.json()["detail"].lower()
    finally:
        await _cleanup(candidate_ids=[cid], job_ids=[j1], client_ids=[])


@pytest.mark.asyncio
async def test_shortlist_email_400_when_job_ids_empty(
    app_client: AsyncClient, app_auth_headers: dict
):
    cid = await _seed_candidate()
    try:
        resp = await app_client.post(
            "/api/recommendations/send-candidate-shortlist-email",
            headers=app_auth_headers,
            json={"candidate_id": cid, "job_ids": []},
        )
        assert resp.status_code == 400
        assert "pust" in resp.json()["detail"].lower()
    finally:
        await _cleanup(candidate_ids=[cid], job_ids=[], client_ids=[])


@pytest.mark.asyncio
async def test_shortlist_email_400_when_no_published_jobs(
    app_client: AsyncClient, app_auth_headers: dict
):
    """All passed job_ids point to non-existent rows → 400."""
    cid = await _seed_candidate()
    try:
        resp = await app_client.post(
            "/api/recommendations/send-candidate-shortlist-email",
            headers=app_auth_headers,
            json={"candidate_id": cid, "job_ids": [9_999_999]},
        )
        assert resp.status_code == 400
        assert "publikowana" in resp.json()["detail"].lower()
    finally:
        await _cleanup(candidate_ids=[cid], job_ids=[], client_ids=[])


# ── prepare-client-proposal ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_client_proposal_happy_path(
    app_client: AsyncClient, app_auth_headers: dict
):
    cid = await _seed_candidate()
    client_id = await _seed_client()
    job_id = await _seed_published_job("Senior Python Engineer", client_id=client_id)
    try:
        resp = await app_client.post(
            "/api/recommendations/prepare-client-proposal",
            headers=app_auth_headers,
            json={"candidate_id": cid, "job_id": job_id},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["candidate_id"] == cid
        assert body["job_id"] == job_id
        assert body["client_id"] == client_id
        # Blind summary stays anonymous — no name/email
        bs = body["blind_summary"]
        assert "Anna" not in str(bs)
        assert "shortlist@example.com" not in str(bs)
        assert bs["experience_years"] == 5
        assert "Python" in bs["skills_summary"]
        # Draft email targets the role
        draft = body["draft_email"]
        assert "Senior Python Engineer" in draft["subject"]
        assert "anonimowy" in draft["text_body"].lower()
    finally:
        await _cleanup(candidate_ids=[cid], job_ids=[job_id], client_ids=[client_id])


@pytest.mark.asyncio
async def test_client_proposal_404_when_candidate_missing(
    app_client: AsyncClient, app_auth_headers: dict
):
    job_id = await _seed_published_job("Backend Eng")
    try:
        resp = await app_client.post(
            "/api/recommendations/prepare-client-proposal",
            headers=app_auth_headers,
            json={"candidate_id": 9_999_999, "job_id": job_id},
        )
        assert resp.status_code == 404
    finally:
        await _cleanup(candidate_ids=[], job_ids=[job_id], client_ids=[])


@pytest.mark.asyncio
async def test_client_proposal_404_when_job_missing(
    app_client: AsyncClient, app_auth_headers: dict
):
    cid = await _seed_candidate()
    try:
        resp = await app_client.post(
            "/api/recommendations/prepare-client-proposal",
            headers=app_auth_headers,
            json={"candidate_id": cid, "job_id": 9_999_999},
        )
        assert resp.status_code == 404
    finally:
        await _cleanup(candidate_ids=[cid], job_ids=[], client_ids=[])
