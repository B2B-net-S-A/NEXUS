"""Audyt procesów 14.09.2026 — F05: optymistyczna współbieżność ruchu w pipeline.

Blokady w `transition_process` serializują zapisy, ale nie wykrywają
nieaktualnej intencji: osoba B zapisywała ruch z dawno otwartej karty po
zmianie dokonanej przez A. Klient może teraz przesłać `expected_state_version`
(= `RecruitmentProcess.state_version`, którą widział); rozjazd = 409
PIPELINE_VERSION_CONFLICT bez zapisu. Brak pola = zachowanie dotychczasowe
(ścieżki importu/automatów mają osobną, jawną politykę).
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus, RemotePolicy
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.recruitment_process import RecruitmentProcess
from app.models.user import User, UserRole
from app.services.recruitment_process_commands import transition_process

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def api_client():
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as c:
        yield c


async def _seed_user(role: UserRole) -> tuple[int, str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"f05-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!F5"
    async with AsyncSessionLocal() as db:
        u = User(
            email=email,
            password_hash=hash_password(password),
            name=f"F05 {role.value}",
            role=role,
            is_active=True,
            profile_completed=True,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id, email, password


async def _seed_pair(recruiter_id: int | None = None) -> tuple[int, int]:
    """Para kandydat + rekrutacja; `recruiter_id` = właściciel rekrutacji
    (bramka członkostwa `/pipeline/move` wymaga bycia w zespole)."""
    unique = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        cli = Client(name=f"F05Client-{unique}")
        cand = Candidate(
            name="F05", lastname=f"Test{unique}", email=f"f05-{unique}@example.com"
        )
        db.add_all([cli, cand])
        await db.flush()
        job = Job(
            title=f"F05 Job {unique}",
            location="Warszawa",
            status=JobStatus.published,
            remote_policy=RemotePolicy.hybrid,
            client_id=cli.id,
            recruiter_id=recruiter_id,
        )
        db.add(job)
        await db.commit()
        await db.refresh(cand)
        await db.refresh(job)
        return cand.id, job.id


async def _cleanup(candidate_id: int, job_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(CandidateStage).where(CandidateStage.candidate_id == candidate_id)
        )
        # RecruitmentProcess kaskaduje z kandydata.
        await db.execute(delete(Candidate).where(Candidate.id == candidate_id))
        await db.execute(delete(Job).where(Job.id == job_id))
        await db.commit()


async def _state_version(candidate_id: int, job_id: int) -> int:
    async with AsyncSessionLocal() as db:
        version = await db.scalar(
            select(RecruitmentProcess.state_version).where(
                RecruitmentProcess.candidate_id == candidate_id,
                RecruitmentProcess.job_id == job_id,
            )
        )
    assert version is not None, "ruch powinien był założyć proces"
    return int(version)


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def test_stale_expected_version_is_refused_with_409(api_client: AsyncClient):
    """Dwie karty: B klika z wersją sprzed ruchu A → 409, etap nietknięty;
    z aktualną wersją → 200 i wersja rośnie."""
    recruiter_id, email, pw = await _seed_user(UserRole.recruiter)
    headers = await _login(api_client, email, pw)
    cand_id, job_id = await _seed_pair(recruiter_id)
    try:
        first = await api_client.post(
            "/api/pipeline/move",
            headers=headers,
            json={"candidate_id": cand_id, "job_id": job_id, "stage": "new"},
        )
        assert first.status_code == 200, first.text
        seen_by_a = await _state_version(cand_id, job_id)

        # A przesuwa dalej — wersja rośnie; B nadal ma starą kartę.
        by_a = await api_client.post(
            "/api/pipeline/move",
            headers=headers,
            json={
                "candidate_id": cand_id,
                "job_id": job_id,
                "stage": "screening",
                "expected_state_version": seen_by_a,
            },
        )
        assert by_a.status_code == 200, by_a.text
        after_a = await _state_version(cand_id, job_id)
        assert after_a == seen_by_a + 1

        by_b = await api_client.post(
            "/api/pipeline/move",
            headers=headers,
            json={
                "candidate_id": cand_id,
                "job_id": job_id,
                "stage": "interview",
                "expected_state_version": seen_by_a,
            },
        )
        assert by_b.status_code == 409, by_b.text
        detail = by_b.json()["detail"]
        assert detail["code"] == "PIPELINE_VERSION_CONFLICT"
        assert detail["current_state_version"] == after_a
        assert "Odśwież" in detail["message"]

        # Odmowa niczego nie zapisała: etap i wersja jak po ruchu A.
        async with AsyncSessionLocal() as db:
            latest = await db.scalar(
                select(CandidateStage.stage)
                .where(
                    CandidateStage.candidate_id == cand_id,
                    CandidateStage.job_id == job_id,
                )
                .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
                .limit(1)
            )
        assert latest == PipelineStage.screening
        assert await _state_version(cand_id, job_id) == after_a
    finally:
        await _cleanup(cand_id, job_id)


async def test_first_move_treats_missing_process_as_version_zero():
    """Karta bez procesu (nikt jeszcze nie ruszył pary) = wersja 0: zgodna
    przechodzi, każda inna liczba to nieaktualny obraz."""
    actor_id, _, _ = await _seed_user(UserRole.recruiter)
    cand_id, job_id = await _seed_pair()
    try:
        async with AsyncSessionLocal() as db:
            with pytest.raises(HTTPException) as exc:
                await transition_process(
                    db,
                    candidate_id=cand_id,
                    job_id=job_id,
                    stage=PipelineStage.new,
                    actor_user_id=actor_id,
                    expected_state_version=5,
                )
            assert exc.value.status_code == 409
            await db.rollback()

        async with AsyncSessionLocal() as db:
            stage = await transition_process(
                db,
                candidate_id=cand_id,
                job_id=job_id,
                stage=PipelineStage.new,
                actor_user_id=actor_id,
                expected_state_version=0,
            )
            await db.commit()
        assert stage.stage == PipelineStage.new
        assert await _state_version(cand_id, job_id) >= 1
    finally:
        await _cleanup(cand_id, job_id)
