"""P0-A: create→handoff reorder + Champion-edit staleness.

The operational ranking is no longer produced at job-create time (it would be a
pre-Champion ranking that then persisted). It is produced by the explicit
"Przekaż do searchu" handoff, which requires a filled Champion (readiness gate)
and binds a recruiter via ``recruiter_id``. Separately, editing a Champion now
re-embeds the job and marks its cached match scores stale, so the Delivery
Lead's work reaches the recruiter's ranking.

Uses the in-process ``app_client`` / ``app_auth_headers`` (admin) fixtures.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient

from app.core.database import AsyncSessionLocal

_READY_CHAMPION = {
    "project_context": {
        "about": "Platforma płatności B2B",
        "responsibilities": "Rozwój usług backendowych",
    },
    "screening_questions": [
        {"id": "q1", "question": "Doświadczenie z Pythonem?"},
        {"id": "q2", "question": "Doświadczenie z Postgres?"},
    ],
}


async def _seed_client() -> int:
    from app.models.client import Client

    async with AsyncSessionLocal() as db:
        cli = Client(name=f"HandoffClient-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        return cli.id


async def _seed_job(*, champion: dict | None = None, status=None) -> int:
    from app.models.job import Job, JobStatus

    client_id = await _seed_client()
    async with AsyncSessionLocal() as db:
        job = Job(
            title=f"Handoff-Job-{uuid.uuid4().hex[:6]}",
            status=status or JobStatus.published,
            client_id=client_id,
            champion_profile=champion,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id


async def _seed_recruiter() -> int:
    from app.models.user import User, UserRole
    from app.core.security import hash_password

    async with AsyncSessionLocal() as db:
        u = User(
            email=f"ho-rec-{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("x"),
            name="Handoff Recruiter",
            role=UserRole.recruiter,
            roles=["recruiter"],
            is_active=True,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id


async def _seed_candidate() -> int:
    from app.models.candidate import Candidate, CandidateStatus

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="Ho",
            lastname=f"Cand-{uuid.uuid4().hex[:6]}",
            email=f"ho-{uuid.uuid4().hex[:8]}@example.com",
            status=CandidateStatus.active,
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


# ── handoff readiness + binding ──────────────────────────────────────────────


async def test_handoff_blocked_without_champion(
    app_client: AsyncClient, app_auth_headers: dict
):
    job_id = await _seed_job(champion=None)
    recruiter_id = await _seed_recruiter()

    resp = await app_client.post(
        f"/api/jobs/{job_id}/handoff",
        headers=app_auth_headers,
        json={"recruiter_id": recruiter_id},
    )

    assert resp.status_code == 422, resp.text
    blockers = resp.json()["detail"]["blockers"]
    assert any("Champion" in b for b in blockers)


async def test_handoff_binds_recruiter_and_creates_snapshot(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    # Keep the background compute offline + fast.
    from app.services import embedding_service, match_score_cache

    async def _empty(*_a, **_k):
        return []

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(embedding_service, "search_candidates_semantic", _empty)
    monkeypatch.setattr(embedding_service, "embed_job", _noop)
    monkeypatch.setattr(match_score_cache, "bulk_get_or_compute", _empty)

    job_id = await _seed_job(champion=_READY_CHAMPION)
    recruiter_id = await _seed_recruiter()

    resp = await app_client.post(
        f"/api/jobs/{job_id}/handoff",
        headers=app_auth_headers,
        json={"recruiter_id": recruiter_id},
    )

    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "handed_off"
    assert body["recruiter_id"] == recruiter_id

    from sqlalchemy import select
    from app.models.job import Job
    from app.models.proposal_snapshot import ProposalSnapshot

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        assert job.recruiter_id == recruiter_id  # bound → job member
        snap = await db.scalar(
            select(ProposalSnapshot).where(ProposalSnapshot.job_id == job_id)
        )
        assert snap is not None
        assert snap.source == "handoff"


async def test_handoff_rejects_non_operational_recruiter(
    app_client: AsyncClient, app_auth_headers: dict
):
    from app.models.user import User, UserRole
    from app.core.security import hash_password

    job_id = await _seed_job(champion=_READY_CHAMPION)
    async with AsyncSessionLocal() as db:
        finance = User(
            email=f"fin-{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("x"),
            name="Finance",
            role=UserRole.finance,
            roles=["finance"],
            is_active=True,
        )
        db.add(finance)
        await db.commit()
        await db.refresh(finance)
        finance_id = finance.id

    resp = await app_client.post(
        f"/api/jobs/{job_id}/handoff",
        headers=app_auth_headers,
        json={"recruiter_id": finance_id},
    )

    assert resp.status_code == 422, resp.text


async def test_handoff_rejects_closed_job(
    app_client: AsyncClient, app_auth_headers: dict
):
    from app.models.job import JobStatus

    job_id = await _seed_job(champion=_READY_CHAMPION, status=JobStatus.closed)
    recruiter_id = await _seed_recruiter()

    resp = await app_client.post(
        f"/api/jobs/{job_id}/handoff",
        headers=app_auth_headers,
        json={"recruiter_id": recruiter_id},
    )

    assert resp.status_code == 409, resp.text


# ── create no longer produces a ranking ──────────────────────────────────────


async def test_create_job_does_not_create_snapshot(
    app_client: AsyncClient, app_auth_headers: dict
):
    from sqlalchemy import select
    from app.models.proposal_snapshot import ProposalSnapshot

    client_id = await _seed_client()
    resp = await app_client.post(
        "/api/jobs",
        headers=app_auth_headers,
        json={"title": f"NoSnap-{uuid.uuid4().hex[:6]}", "client_id": client_id},
    )
    assert resp.status_code in (200, 201), resp.text
    job_id = resp.json()["id"]

    async with AsyncSessionLocal() as db:
        snap = await db.scalar(
            select(ProposalSnapshot).where(ProposalSnapshot.job_id == job_id)
        )
    assert snap is None


# ── Champion edit invalidates cached scores ──────────────────────────────────


async def test_champion_edit_marks_cached_scores_stale(
    app_client: AsyncClient, app_auth_headers: dict
):
    from sqlalchemy import select
    from app.models.match_score import CandidateJobMatchScore

    job_id = await _seed_job(champion=None)
    candidate_id = await _seed_candidate()
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateJobMatchScore(
                candidate_id=candidate_id,
                job_id=job_id,
                profile_id=0,
                total_score=55.0,
                breakdown={},
                scoring_algorithm_version="test",
                stale=False,
            )
        )
        await db.commit()

    resp = await app_client.put(
        f"/api/jobs/{job_id}/champion-profile",
        headers=app_auth_headers,
        json=_READY_CHAMPION,
    )
    assert resp.status_code == 200, resp.text

    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(CandidateJobMatchScore).where(
                CandidateJobMatchScore.job_id == job_id,
                CandidateJobMatchScore.candidate_id == candidate_id,
            )
        )
        assert row.stale is True
