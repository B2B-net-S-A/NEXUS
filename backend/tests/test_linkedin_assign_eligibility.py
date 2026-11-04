"""Eligibility remains enforced by the supported extension-key assignment API."""

from __future__ import annotations

import time
from typing import Optional

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.candidate_conflict import CandidateConflict, ConflictType
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.recruitment_pipeline import CandidateStage


@pytest_asyncio.fixture
async def extension_headers(app_client, app_auth_headers, monkeypatch):
    extension_id = "abcdefghijklmnopabcdefghijklmnop"
    monkeypatch.setattr(settings, "LINKEDIN_EXTENSION_IDS", extension_id)
    monkeypatch.setattr(settings, "LINKEDIN_EXTENSION_ENABLED", True)
    response = await app_client.post(
        "/api/extension/connect",
        headers=app_auth_headers,
        json={"extension_id": extension_id, "extension_version": "1.0.0"},
    )
    assert response.status_code == 200, response.text
    return {"X-Extension-Key": response.json()["key"]}


@pytest_asyncio.fixture
async def job_with_client(app_auth_headers) -> tuple[int, int]:  # noqa: ARG001
    """(job_id, client_id) — opublikowana rekrutacja z własnym klientem."""
    async with AsyncSessionLocal() as db:
        cli = Client(name=f"EligClient-{time.time_ns()}")
        db.add(cli)
        await db.flush()
        job = Job(
            title=f"Elig Engineer {time.time_ns()}",
            status=JobStatus.published,
            is_open=True,
            client_id=cli.id,
        )
        db.add(job)
        await db.commit()
        return job.id, cli.id


async def _seed_existing_candidate(slug: str, status: str = "active") -> int:
    from app.models.candidate import CandidateStatus

    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Nda",
            lastname=f"Blocked-{time.time_ns()}",
            email=f"elig-{time.time_ns()}@example.com",
            linkedin=f"https://www.linkedin.com/in/{slug}",
            status=CandidateStatus(status),
        )
        db.add(cand)
        await db.commit()
        return cand.id


async def _stage_for(candidate_id: int, job_id: int) -> Optional[CandidateStage]:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(CandidateStage).where(
                CandidateStage.candidate_id == candidate_id,
                CandidateStage.job_id == job_id,
            )
        )


@pytest.mark.asyncio
async def test_nda_conflict_does_not_block_the_linkedin_assignment(
    app_client: AsyncClient,
    extension_headers,
    job_with_client,
) -> None:
    job_id, client_id = job_with_client
    candidate_id = await _seed_existing_candidate(f"nda-allowed-{time.time_ns()}")
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateConflict(
                candidate_id=candidate_id,
                client_id=client_id,
                type=ConflictType.nda,
                reason="NDA z klientem",
                active=True,
            )
        )
        await db.commit()
    response = await app_client.post(
        f"/api/extension/candidates/{candidate_id}/jobs",
        headers=extension_headers,
        json={"job_ids": [job_id]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["assigned_job_ids"] == [job_id]
    assert response.json()["skipped"] == []
    assert await _stage_for(candidate_id, job_id) is not None


@pytest.mark.asyncio
async def test_global_blacklist_blocks_the_linkedin_assignment(
    app_client: AsyncClient,
    extension_headers,
    job_with_client,
) -> None:
    job_id, _client_id = job_with_client
    candidate_id = await _seed_existing_candidate(
        f"global-blacklist-{time.time_ns()}",
        status="blacklisted",
    )
    response = await app_client.post(
        f"/api/extension/candidates/{candidate_id}/jobs",
        headers=extension_headers,
        json={"job_ids": [job_id]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["assigned_job_ids"] == []
    assert len(body["skipped"]) == 1
    assert body["skipped"][0]["job_id"] == job_id
    assert "czarnej liście" in body["skipped"][0]["reason"]
    assert await _stage_for(candidate_id, job_id) is None


@pytest.mark.asyncio
async def test_clean_candidate_is_still_assigned(
    app_client: AsyncClient,
    extension_headers,
    job_with_client,
) -> None:
    job_id, _client_id = job_with_client
    candidate_id = await _seed_existing_candidate(f"clean-{time.time_ns()}")
    response = await app_client.post(
        f"/api/extension/candidates/{candidate_id}/jobs",
        headers=extension_headers,
        json={"job_ids": [job_id]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["assigned_job_ids"] == [job_id]
    assert response.json()["skipped"] == []
    assert await _stage_for(candidate_id, job_id) is not None
