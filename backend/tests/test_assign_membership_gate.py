"""Assign-to-job and the job-membership gate.

`POST /api/candidates/{candidate_id}/assign-to-job/{job_id}`
(recommendations.assign_candidate_to_job) writes a CandidateStage — a pipeline
mutation — and runs the same job-membership gate as the shortlist and
pipeline-move ingresses. Since 23.09.2026 (decyzja Artura: „wszystko w
rekrutacji robi każdy, nie musisz być przypisany") every internal role passes
that gate, so a recruiter outside the team assigns like a member. The legacy
viewer role ``user`` is still refused.

Uses the in-process ``app_client`` fixture (real postgres in CI).
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient

from app.core.database import AsyncSessionLocal


async def _seed_recruiter(
    app_client: AsyncClient, role: str = "recruiter"
) -> tuple[dict[str, str], int]:
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    unique = uuid.uuid4().hex[:8]
    email = f"assign-gate-{unique}@example.com"
    password = f"T3st_{unique}!Assign"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name="Assign Gate Recruiter",
            role=UserRole(role),
            roles=[role],
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        uid = user.id

    resp = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}, uid


async def _seed_job(owner_id: int | None = None) -> int:
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        cli = Client(name=f"AssignGateClient-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        job = Job(
            title=f"AssignGate-Job-{uuid.uuid4().hex[:6]}",
            status=JobStatus.published,
            client_id=cli.id,
            recruiter_id=owner_id,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id


async def _seed_candidate() -> int:
    from app.models.candidate import Candidate, CandidateStatus

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="Assign",
            lastname=f"Cand-{uuid.uuid4().hex[:6]}",
            email=f"assign-{uuid.uuid4().hex[:8]}@example.com",
            status=CandidateStatus.active,
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


def _url(candidate_id: int, job_id: int) -> str:
    return f"/api/candidates/{candidate_id}/assign-to-job/{job_id}"


async def _stage_rows(candidate_id: int, job_id: int) -> list[int]:
    from sqlalchemy import select

    from app.models.recruitment_pipeline import CandidateStage

    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(CandidateStage.id).where(
                        CandidateStage.candidate_id == candidate_id,
                        CandidateStage.job_id == job_id,
                    )
                )
            ).all()
        )


async def test_assign_allowed_for_non_member_recruiter(app_client: AsyncClient):
    headers, _uid = await _seed_recruiter(app_client)
    job_id = await _seed_job(owner_id=None)  # unowned → recruiter is not a member
    candidate_id = await _seed_candidate()

    resp = await app_client.post(_url(candidate_id, job_id), headers=headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "assigned"
    assert resp.json()["stage_id"] in await _stage_rows(candidate_id, job_id)


async def test_assign_refused_for_legacy_viewer(app_client: AsyncClient):
    headers, _uid = await _seed_recruiter(app_client, role="user")
    job_id = await _seed_job(owner_id=None)
    candidate_id = await _seed_candidate()

    resp = await app_client.post(_url(candidate_id, job_id), headers=headers)

    assert resp.status_code == 403, resp.text
    assert await _stage_rows(candidate_id, job_id) == []


async def test_assign_allowed_for_member_recruiter(app_client: AsyncClient):
    headers, uid = await _seed_recruiter(app_client)
    job_id = await _seed_job(owner_id=uid)  # recruiter owns the job → member
    candidate_id = await _seed_candidate()

    resp = await app_client.post(_url(candidate_id, job_id), headers=headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "assigned"
