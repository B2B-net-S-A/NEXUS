"""Integration tests for the eligibility gate on single-assign (SEARCH-P0-04).

``POST /api/candidates/{candidate_id}/assign-to-job/{job_id}`` must return
409 with the eligibility reason code as ``detail`` when the candidate is
globally blacklisted or has an active, unexpired hard client conflict
(blacklist/nda/competitor) for the job's client — and must still assign when
the conflict has expired. Follow-up flagged in PR #738 (the endpoint had no
HTTP-level test; QuickAssignV2 previously swallowed the 409 silently).

Uses the in-process ``app_client`` / ``app_auth_headers`` fixtures from
conftest (real postgres in CI).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient


async def _seed_candidate(status: str = "active") -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="Elig",
            lastname=f"Gate-{uuid.uuid4().hex[:6]}",
            email=f"elig-{uuid.uuid4().hex[:8]}@example.com",
            status=CandidateStatus(status),
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _seed_job() -> tuple[int, int]:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        cli = Client(name=f"EligClient-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        j = Job(
            title=f"Elig-Job-{uuid.uuid4().hex[:6]}",
            status=JobStatus.published,
            client_id=cli.id,
        )
        db.add(j)
        await db.commit()
        await db.refresh(j)
        return j.id, cli.id


async def _seed_conflict(
    candidate_id: int,
    client_id: int,
    type_: str,
    expires_at: datetime | None = None,
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate_conflict import CandidateConflict, ConflictType

    async with AsyncSessionLocal() as db:
        db.add(
            CandidateConflict(
                candidate_id=candidate_id,
                client_id=client_id,
                type=ConflictType(type_),
                active=True,
                expires_at=expires_at,
            )
        )
        await db.commit()


def _assign_url(candidate_id: int, job_id: int) -> str:
    return f"/api/candidates/{candidate_id}/assign-to-job/{job_id}"


async def test_assign_blocked_for_blacklisted_candidate(
    app_client: AsyncClient, app_auth_headers: dict
):
    candidate_id = await _seed_candidate(status="blacklisted")
    job_id, _client_id = await _seed_job()

    resp = await app_client.post(
        _assign_url(candidate_id, job_id), headers=app_auth_headers
    )

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == "blacklisted"


async def test_assign_blocked_for_active_client_nda(
    app_client: AsyncClient, app_auth_headers: dict
):
    candidate_id = await _seed_candidate()
    job_id, client_id = await _seed_job()
    await _seed_conflict(candidate_id, client_id, "nda")

    resp = await app_client.post(
        _assign_url(candidate_id, job_id), headers=app_auth_headers
    )

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == "client_nda"


async def test_assign_allowed_when_conflict_expired(
    app_client: AsyncClient, app_auth_headers: dict
):
    candidate_id = await _seed_candidate()
    job_id, client_id = await _seed_job()
    await _seed_conflict(
        candidate_id,
        client_id,
        "blacklist",
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )

    resp = await app_client.post(
        _assign_url(candidate_id, job_id), headers=app_auth_headers
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "assigned"


async def test_assign_clean_candidate_then_noop_on_repeat(
    app_client: AsyncClient, app_auth_headers: dict
):
    candidate_id = await _seed_candidate()
    job_id, _client_id = await _seed_job()

    first = await app_client.post(
        _assign_url(candidate_id, job_id), headers=app_auth_headers
    )
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "assigned"

    second = await app_client.post(
        _assign_url(candidate_id, job_id), headers=app_auth_headers
    )
    assert second.status_code == 200, second.text
    assert second.json()["status"] == "already_in_pipeline"
