"""P0-A: POST /jobs/{id}/proposals/regenerate is RecruiterPlus + membership.

Previously guarded by TacPlus, so the recruiter-visible "Odśwież propozycje"
button always 403'd for recruiters; and it had LESS scope than the read
endpoint (a Delivery Lead could recompute for a client outside their scope).
Now the assigned recruiter (job member) can refresh, and a non-member is 403.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient

from app.core.database import AsyncSessionLocal


async def _seed_recruiter(app_client: AsyncClient) -> tuple[dict[str, str], int]:
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    unique = uuid.uuid4().hex[:8]
    email = f"regen-{unique}@example.com"
    password = f"T3st_{unique}!Regen"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name="Regen Recruiter",
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
        cli = Client(name=f"RegenClient-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        job = Job(
            title=f"Regen-Job-{uuid.uuid4().hex[:6]}",
            status=JobStatus.published,
            client_id=cli.id,
            recruiter_id=owner_id,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id


def _url(job_id: int) -> str:
    return f"/api/jobs/{job_id}/proposals/regenerate"


async def test_regenerate_blocked_for_non_member_recruiter(app_client: AsyncClient):
    headers, _uid = await _seed_recruiter(app_client)
    job_id = await _seed_job(owner_id=None)  # unowned → recruiter is not a member

    resp = await app_client.post(_url(job_id), headers=headers)

    assert resp.status_code == 403, resp.text


async def test_regenerate_allowed_for_member_recruiter(
    app_client: AsyncClient, monkeypatch
):
    from app.services import embedding_service, match_score_cache

    async def _empty(*_a, **_k):
        return []

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(embedding_service, "search_candidates_semantic", _empty)
    monkeypatch.setattr(embedding_service, "embed_job", _noop)
    monkeypatch.setattr(match_score_cache, "bulk_get_or_compute", _empty)

    headers, uid = await _seed_recruiter(app_client)
    job_id = await _seed_job(owner_id=uid)  # recruiter owns the job → member

    resp = await app_client.post(_url(job_id), headers=headers)

    assert resp.status_code == 202, resp.text
