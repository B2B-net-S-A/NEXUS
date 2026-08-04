"""P0-A: assign-to-job enforces job membership.

`POST /api/candidates/{candidate_id}/assign-to-job/{job_id}`
(recommendations.assign_candidate_to_job) writes a CandidateStage — a pipeline
mutation — so the caller must belong to the job, exactly like the shortlist and
pipeline-move ingresses. Previously it only checked the role
(CandidateWriteAccess), so a recruiter who is NOT on a recruitment could push a
candidate straight into its pipeline from the recommendations widget. Now a
non-member gets a uniform 403; a member (recruiter_id owner) can assign.

Uses the in-process ``app_client`` fixture (real postgres in CI).
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient

from app.core.database import AsyncSessionLocal


async def _seed_recruiter(app_client: AsyncClient) -> tuple[dict[str, str], int]:
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
            role=UserRole.recruiter,
            roles=["recruiter"],
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


async def test_assign_blocked_for_non_member_recruiter(app_client: AsyncClient):
    headers, _uid = await _seed_recruiter(app_client)
    job_id = await _seed_job(owner_id=None)  # unowned → recruiter is not a member
    candidate_id = await _seed_candidate()

    resp = await app_client.post(_url(candidate_id, job_id), headers=headers)

    assert resp.status_code == 403, resp.text


async def test_assign_allowed_for_member_recruiter(app_client: AsyncClient):
    headers, uid = await _seed_recruiter(app_client)
    job_id = await _seed_job(owner_id=uid)  # recruiter owns the job → member
    candidate_id = await _seed_candidate()

    resp = await app_client.post(_url(candidate_id, job_id), headers=headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "assigned"
