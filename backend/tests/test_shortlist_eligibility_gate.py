"""FRESH-1 / P0-06d: add_to_shortlist enforces the eligibility gate.

`add_to_shortlist` previously checked only job membership, candidate existence
and dedup — NOT eligibility. So a globally-blacklisted / active client-conflict
(NDA/competitor) / hiring-manager-vetoed candidate found via manual search
(which does not conflict-filter) could be parked on a job's shortlist and even
trigger candidate outreach on promote, whereas the sibling bulk-add and promote
ingresses both reject it. This closes that asymmetry: ineligible ids are routed
to ``skipped`` before insert, using the same policy source
(``evaluate_candidates_for_job``) as the deployed recommendations/snapshot path.

Uses the in-process ``app_client`` / ``app_auth_headers`` (admin = job member
via bypass) fixtures.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal


async def _seed_job() -> tuple[int, int]:
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        cli = Client(name=f"SLElig-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        job = Job(
            title=f"SLElig-Job-{uuid.uuid4().hex[:6]}",
            status=JobStatus.published,
            client_id=cli.id,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id, cli.id


async def _seed_candidate(status: str = "active") -> int:
    from app.models.candidate import Candidate, CandidateStatus

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="SLElig",
            lastname=f"Cand-{uuid.uuid4().hex[:6]}",
            email=f"slelig-{uuid.uuid4().hex[:8]}@example.com",
            status=CandidateStatus(status),
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _seed_conflict(candidate_id: int, client_id: int, type_: str) -> None:
    from app.models.candidate_conflict import CandidateConflict, ConflictType

    async with AsyncSessionLocal() as db:
        db.add(
            CandidateConflict(
                candidate_id=candidate_id,
                client_id=client_id,
                type=ConflictType(type_),
                active=True,
            )
        )
        await db.commit()


async def _shortlisted_ids(job_id: int) -> set[int]:
    from app.models.job_shortlist import JobShortlistEntry

    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(JobShortlistEntry.candidate_id).where(
                    JobShortlistEntry.job_id == job_id
                )
            )
        ).scalars()
        return set(rows.all())


async def test_shortlist_skips_blacklisted_keeps_clean(
    app_client: AsyncClient, app_auth_headers: dict
):
    job_id, _client_id = await _seed_job()
    clean = await _seed_candidate()
    black = await _seed_candidate(status="blacklisted")

    resp = await app_client.post(
        f"/api/jobs/{job_id}/shortlist",
        headers=app_auth_headers,
        json={"candidate_ids": [clean, black]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert clean in body["added"]
    assert black in body["skipped"]
    assert black not in body["added"]

    # And it never reached the table (so promote can't later contact them).
    assert await _shortlisted_ids(job_id) == {clean}


async def test_shortlist_skips_active_client_conflict(
    app_client: AsyncClient, app_auth_headers: dict
):
    job_id, client_id = await _seed_job()
    clean = await _seed_candidate()
    nda = await _seed_candidate()
    await _seed_conflict(nda, client_id, "nda")

    resp = await app_client.post(
        f"/api/jobs/{job_id}/shortlist",
        headers=app_auth_headers,
        json={"candidate_ids": [clean, nda]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["added"] == [clean]
    assert nda in body["skipped"]
    assert await _shortlisted_ids(job_id) == {clean}


async def test_shortlist_skips_hiring_manager_veto(
    app_client: AsyncClient, app_auth_headers: dict
):
    # The third ineligibility vector: a candidate the job's hiring manager
    # interviewed and disqualifyingly rejected. Reuse the canonical veto seed
    # (append-only stage history + manager-met machinery) from the veto contract
    # test so this stays in lockstep with how load_manager_rejections reads it.
    from tests.test_manager_rejection_gate import _seed_vetoed_candidate

    world = await _seed_vetoed_candidate()

    resp = await app_client.post(
        f"/api/jobs/{world['target_job_id']}/shortlist",
        headers=app_auth_headers,
        json={"candidate_ids": [world["candidate_id"]]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["added"] == []
    assert world["candidate_id"] in body["skipped"]
    assert await _shortlisted_ids(world["target_job_id"]) == set()
