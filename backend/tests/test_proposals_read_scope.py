"""P0-01 / FRESH-3: proposal READ endpoints honour job membership scope.

GET /jobs/{id}/proposals/latest hydrates candidate PII (name/email/phone/
location); GET /jobs/{id}/proposals returns snapshot history. Both were only
OperationalUser + job-exists gated — no ``ensure_job_membership`` — while the
write path (regenerate) and the sibling /recommendations already scope. So a
delivery_lead outside the job's client scope (or any non-member operational
user) could read another team's proposals with PII. These tests pin both sides
of the gate: a non-member operational user gets 403; a member (admin bypass)
gets 200.

Uses ``app_client`` + ``app_auth_headers`` (admin member) and mints a token for
a fresh non-member recruiter directly.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token, hash_password


async def _seed_job_with_snapshot() -> int:
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.proposal_snapshot import ProposalSnapshot

    async with AsyncSessionLocal() as db:
        cli = Client(name=f"PropScope-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        job = Job(
            title=f"PropScope-Job-{uuid.uuid4().hex[:6]}",
            status=JobStatus.published,
            client_id=cli.id,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        db.add(
            ProposalSnapshot(
                job_id=job.id,
                source="handoff",
                status="ready",
                top_k=20,
                run_id=uuid.uuid4().hex,
                candidate_ids=[],
                breakdowns=[],
            )
        )
        await db.commit()
        return job.id


async def _non_member_headers() -> dict[str, str]:
    from app.models.user import User, UserRole

    async with AsyncSessionLocal() as db:
        u = User(
            email=f"propscope-{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("x"),
            name="Prop Scope Outsider",
            role=UserRole.recruiter,
            roles=["recruiter"],
            is_active=True,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        token = create_access_token(u.id, UserRole.recruiter.value)
        return {"Authorization": f"Bearer {token}"}


async def test_latest_proposal_forbidden_for_non_member(
    app_client: AsyncClient, app_auth_headers: dict
):
    job_id = await _seed_job_with_snapshot()
    outsider = await _non_member_headers()

    forbidden = await app_client.get(
        f"/api/jobs/{job_id}/proposals/latest", headers=outsider
    )
    assert forbidden.status_code == 403, forbidden.text

    # Admin is a member (bypass) → reads the snapshot.
    ok = await app_client.get(
        f"/api/jobs/{job_id}/proposals/latest", headers=app_auth_headers
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["job_id"] == job_id


async def test_proposal_history_forbidden_for_non_member(
    app_client: AsyncClient, app_auth_headers: dict
):
    job_id = await _seed_job_with_snapshot()
    outsider = await _non_member_headers()

    forbidden = await app_client.get(f"/api/jobs/{job_id}/proposals", headers=outsider)
    assert forbidden.status_code == 403, forbidden.text

    ok = await app_client.get(f"/api/jobs/{job_id}/proposals", headers=app_auth_headers)
    assert ok.status_code == 200, ok.text
    assert ok.json()["total"] >= 1
