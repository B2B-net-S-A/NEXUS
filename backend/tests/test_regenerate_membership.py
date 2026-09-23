"""P0-A: POST /jobs/{id}/proposals/regenerate is RecruiterPlus + membership.

Previously guarded by TacPlus, so the recruiter-visible "Odśwież propozycje"
button always 403'd for recruiters; and it had LESS scope than the read
endpoint (a Delivery Lead could recompute for a client outside their scope).
Since 23.09.2026 (decyzja Artura: „wszystko w rekrutacji robi każdy, nie
musisz być przypisany") every internal role passes the job-membership gate, so
a recruiter outside the team refreshes like a member; the legacy viewer role
``user`` is refused by the role guard.
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
    email = f"regen-{unique}@example.com"
    password = f"T3st_{unique}!Regen"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name="Regen Recruiter",
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


def _stub_engine(monkeypatch) -> None:
    from app.services import canonical_fit, embedding_service

    async def _empty(*_a, **_k):
        return []

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(embedding_service, "search_candidates_semantic", _empty)
    monkeypatch.setattr(embedding_service, "embed_job", _noop)
    monkeypatch.setattr(canonical_fit, "score_candidates", _empty)


async def _snapshot_sources(job_id: int) -> list[str]:
    from sqlalchemy import select

    from app.models.proposal_snapshot import ProposalSnapshot

    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(ProposalSnapshot.source).where(
                        ProposalSnapshot.job_id == job_id
                    )
                )
            ).all()
        )


async def test_regenerate_allowed_for_non_member_recruiter(
    app_client: AsyncClient, monkeypatch
):
    _stub_engine(monkeypatch)
    headers, _uid = await _seed_recruiter(app_client)
    job_id = await _seed_job(owner_id=None)  # unowned → recruiter is not a member

    resp = await app_client.post(_url(job_id), headers=headers)

    assert resp.status_code == 202, resp.text
    assert resp.json()["job_id"] == job_id
    assert resp.json()["source"] == "manual_regenerate"
    assert "manual_regenerate" in await _snapshot_sources(job_id)


async def test_regenerate_refused_for_legacy_viewer(
    app_client: AsyncClient, monkeypatch
):
    _stub_engine(monkeypatch)
    headers, _uid = await _seed_recruiter(app_client, role="user")
    job_id = await _seed_job(owner_id=None)

    resp = await app_client.post(_url(job_id), headers=headers)

    assert resp.status_code == 403, resp.text
    assert await _snapshot_sources(job_id) == []


async def test_regenerate_allowed_for_member_recruiter(
    app_client: AsyncClient, monkeypatch
):
    _stub_engine(monkeypatch)

    headers, uid = await _seed_recruiter(app_client)
    job_id = await _seed_job(owner_id=uid)  # recruiter owns the job → member

    resp = await app_client.post(_url(job_id), headers=headers)

    assert resp.status_code == 202, resp.text
