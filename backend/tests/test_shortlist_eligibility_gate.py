"""FRESH-1 / P0-06d: add_to_shortlist enforces the eligibility gate.

`add_to_shortlist` previously checked only job membership, candidate existence
and dedup — NOT eligibility. So a globally-blacklisted / hiring-manager-vetoed
candidate found via manual search could be parked on a job's shortlist and even
trigger candidate outreach on promote, whereas the sibling bulk-add and promote
ingresses both reject it. Since 17.09.2026 a client conflict (blacklist / NDA /
competitor) is a warning and does NOT stop a shortlist add or a promote. This closes that asymmetry: ineligible ids are routed
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


async def _entry_id(job_id: int, candidate_id: int) -> int:
    from app.models.job_shortlist import JobShortlistEntry

    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(JobShortlistEntry.id).where(
                JobShortlistEntry.job_id == job_id,
                JobShortlistEntry.candidate_id == candidate_id,
            )
        )


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


async def test_shortlist_adds_and_promotes_despite_active_client_conflict(
    app_client: AsyncClient, app_auth_headers: dict
):
    """17.09.2026: NDA with the client is a warning — added and promotable."""
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
    assert sorted(body["added"]) == sorted([clean, nda])
    assert body["skipped"] == []
    assert await _shortlisted_ids(job_id) == {clean, nda}

    entry_id = await _entry_id(job_id, nda)
    promote = await app_client.post(
        f"/api/shortlist/{entry_id}/promote", headers=app_auth_headers
    )
    assert promote.status_code == 200, promote.text
    assert promote.json()["already_in_pipeline"] is False


async def test_promote_blocked_by_hiring_manager_veto(
    app_client: AsyncClient, app_auth_headers: dict
):
    """A veto that lands AFTER the shortlist add still stops the promote (409)."""
    from app.models.job_shortlist import JobShortlistEntry
    from tests.test_manager_rejection_gate import _seed_vetoed_candidate

    world = await _seed_vetoed_candidate()
    async with AsyncSessionLocal() as db:
        entry = JobShortlistEntry(
            job_id=world["target_job_id"], candidate_id=world["candidate_id"]
        )
        db.add(entry)
        await db.commit()
        await db.refresh(entry)
        entry_id = entry.id

    promote = await app_client.post(
        f"/api/shortlist/{entry_id}/promote", headers=app_auth_headers
    )
    assert promote.status_code == 409, promote.text
    assert world["manager_name"] in promote.json()["detail"]


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
