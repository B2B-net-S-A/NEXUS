"""Tests for `GET /api/team-structure/my-team` (DL Hub PR 2).

Cover:
- DL widzi swoje przypisane TAC-i z metrykami (active_jobs + active_candidates)
- Non-DL (recruiter) dostaje pustą listę, nie 403 (graceful)
- active_jobs liczy tylko status=published joby
- active_candidates pomija kandydatów których najnowszy stage jest terminalny
  (hired/rejected/withdrawn)
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import delete


async def _seed_user(role: str = "recruiter") -> tuple[int, str, str]:
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    unique = uuid.uuid4().hex[:8]
    email = f"mt-{role}-{unique}@example.com"
    password = f"T3st_{unique}!Mt"
    async with AsyncSessionLocal() as db:
        u = User(
            email=email,
            password_hash=hash_password(password),
            name=f"MT {role} {unique}",
            role=UserRole(role),
            is_active=True,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id, email, password


async def _seed_job(
    *,
    title_suffix: str = "",
    status: str = "published",
    tac_id: int | None = None,
    delivery_lead_id: int | None = None,
) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job, JobStatus, RemotePolicy

    async with AsyncSessionLocal() as db:
        cli = Client(name=f"MTClient-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        j = Job(
            title=f"MT Job {title_suffix or uuid.uuid4().hex[:6]}",
            location="Warszawa",
            status=JobStatus(status),
            remote_policy=RemotePolicy.hybrid,
            tac_id=tac_id,
            delivery_lead_id=delivery_lead_id,
            client_id=cli.id,
        )
        db.add(j)
        await db.commit()
        await db.refresh(j)
        return j.id


async def _seed_candidate() -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="Mt",
            lastname=f"Cand{uuid.uuid4().hex[:6]}",
            email=f"mt-cand-{uuid.uuid4().hex[:6]}@example.com",
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _assign_tac_to_dl(tac_user_id: int, dl_user_id: int) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.team_structure import TacDeliveryLeadAssignment

    async with AsyncSessionLocal() as db:
        a = TacDeliveryLeadAssignment(
            tac_user_id=tac_user_id, delivery_lead_user_id=dl_user_id
        )
        db.add(a)
        await db.commit()
        await db.refresh(a)
        return a.id


async def _seed_stage(candidate_id: int, job_id: int, stage: str) -> int:
    """Insert a CandidateStage row. Returns id."""
    from app.core.database import AsyncSessionLocal
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    async with AsyncSessionLocal() as db:
        cs = CandidateStage(
            candidate_id=candidate_id,
            job_id=job_id,
            stage=PipelineStage(stage),
        )
        db.add(cs)
        await db.commit()
        await db.refresh(cs)
        return cs.id


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, f"login failed: {resp.text}"
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _cleanup(*, candidate_ids: list[int], job_ids: list[int]) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.job import Job
    from app.models.recruitment_pipeline import CandidateStage

    async with AsyncSessionLocal() as db:
        if candidate_ids or job_ids:
            await db.execute(
                delete(CandidateStage).where(
                    CandidateStage.candidate_id.in_(candidate_ids or [-1])
                )
            )
        if candidate_ids:
            await db.execute(
                delete(Candidate).where(Candidate.id.in_(candidate_ids))
            )
        if job_ids:
            await db.execute(delete(Job).where(Job.id.in_(job_ids)))
        await db.commit()


@pytest.mark.asyncio
async def test_my_team_returns_tac_metrics_for_dl(app_client: AsyncClient):
    """DL widzi przypisany TAC z poprawnymi active_jobs + active_candidates."""
    dl_id, dl_email, dl_pw = await _seed_user("delivery_lead")
    tac_id, _, _ = await _seed_user("tac")
    await _assign_tac_to_dl(tac_id, dl_id)

    # Setup: 2 jobs dla TAC, jeden published, jeden draft (nie powinien być liczony)
    job_pub = await _seed_job(status="published", tac_id=tac_id)
    job_draft = await _seed_job(status="draft", tac_id=tac_id)
    # Job innego TAC (nie powinien być liczony)
    other_tac_id, _, _ = await _seed_user("tac")
    job_other = await _seed_job(status="published", tac_id=other_tac_id)

    # 2 kandydatów na published jobie TAC: jeden aktywny, jeden hired (terminal)
    cand_active = await _seed_candidate()
    cand_terminal = await _seed_candidate()
    await _seed_stage(cand_active, job_pub, "screening")
    await _seed_stage(cand_terminal, job_pub, "screening")
    await _seed_stage(cand_terminal, job_pub, "hired")  # najnowszy = terminal

    dl_headers = await _login(app_client, dl_email, dl_pw)
    try:
        resp = await app_client.get("/api/team-structure/my-team", headers=dl_headers)
        assert resp.status_code == 200, resp.text
        rows = resp.json()
        # Znajdź wiersz dla naszego TAC
        row = next((r for r in rows if r["tac_user_id"] == tac_id), None)
        assert row is not None, f"TAC {tac_id} nie znaleziony w {rows}"
        assert row["active_jobs"] == 1  # tylko published, nie draft
        assert row["active_candidates"] == 1  # tylko cand_active, hired skipped
    finally:
        await _cleanup(
            candidate_ids=[cand_active, cand_terminal],
            job_ids=[job_pub, job_draft, job_other],
        )


@pytest.mark.asyncio
async def test_my_team_empty_for_non_dl(app_client: AsyncClient):
    """Recruiter (non-DL) dostaje pustą listę, nie 403 — graceful empty state."""
    _, email, pw = await _seed_user("recruiter")
    headers = await _login(app_client, email, pw)
    resp = await app_client.get("/api/team-structure/my-team", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


@pytest.mark.asyncio
async def test_my_team_empty_for_dl_without_assigned_tacs(app_client: AsyncClient):
    """DL bez przypisanych TAC dostaje pustą listę."""
    _, dl_email, dl_pw = await _seed_user("delivery_lead")
    headers = await _login(app_client, dl_email, dl_pw)
    resp = await app_client.get("/api/team-structure/my-team", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


@pytest.mark.asyncio
async def test_jobs_filter_by_delivery_lead_id(
    app_client: AsyncClient, app_auth_headers: dict
):
    """`/api/jobs?delivery_lead_id=X` zwraca tylko Joby z Job.delivery_lead_id=X."""
    dl_a_id, _, _ = await _seed_user("delivery_lead")
    dl_b_id, _, _ = await _seed_user("delivery_lead")
    job_a = await _seed_job(status="published", delivery_lead_id=dl_a_id)
    job_b = await _seed_job(status="published", delivery_lead_id=dl_b_id)
    try:
        resp = await app_client.get(
            f"/api/jobs?delivery_lead_id={dl_a_id}&page_size=100",
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        ids = {item["id"] for item in resp.json()["items"]}
        assert job_a in ids
        assert job_b not in ids
    finally:
        await _cleanup(candidate_ids=[], job_ids=[job_a, job_b])


@pytest.mark.asyncio
async def test_jobs_include_stage_counts(
    app_client: AsyncClient, app_auth_headers: dict
):
    """`include_stage_counts=true` zwraca `stage_breakdown: {<stage>: n}` per Job.

    Liczy tylko najnowszy stage per (candidate, job) — kandydat z hired po
    screening pojawia się TYLKO w `hired`, nie w `screening`.
    """
    job_id = await _seed_job(status="published")
    # Kand A: screening → hired (terminal)
    cand_a = await _seed_candidate()
    await _seed_stage(cand_a, job_id, "screening")
    await _seed_stage(cand_a, job_id, "hired")
    # Kand B: screening (aktywny)
    cand_b = await _seed_candidate()
    await _seed_stage(cand_b, job_id, "screening")
    try:
        resp = await app_client.get(
            f"/api/jobs?include_stage_counts=true&page_size=100",
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        item = next(
            (i for i in resp.json()["items"] if i["id"] == job_id), None
        )
        assert item is not None
        breakdown = item.get("stage_breakdown", {})
        # Latest stage per kandydat: A=hired, B=screening
        assert breakdown.get("hired") == 1
        assert breakdown.get("screening") == 1
    finally:
        await _cleanup(candidate_ids=[cand_a, cand_b], job_ids=[job_id])


@pytest.mark.asyncio
async def test_jobs_without_include_stage_counts_omits_breakdown(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Bez `include_stage_counts` response nie ma klucza `stage_breakdown` (backward compat)."""
    job_id = await _seed_job(status="published")
    try:
        resp = await app_client.get(
            "/api/jobs?page_size=100", headers=app_auth_headers
        )
        assert resp.status_code == 200
        item = next(
            (i for i in resp.json()["items"] if i["id"] == job_id), None
        )
        assert item is not None
        assert "stage_breakdown" not in item
    finally:
        await _cleanup(candidate_ids=[], job_ids=[job_id])
