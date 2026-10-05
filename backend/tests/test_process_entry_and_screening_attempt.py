"""Audyt 05.10.2026 — źródło wejścia „przepięcie” i arkusz bieżącej próby.

1. Otwarta propozycja przepięcia (``JobProposal.source='reassign'``) daje
   procesowi ``entry_source='reassign'`` i rekrutację źródłową NIEZALEŻNIE od
   ekranu dodania (0352). Do tej poprawki robiła to wyłącznie ścieżka zbiorcza
   (``proposals/bulk``); dodanie z historii, shortlisty, rekomendacji, profilu
   i ``/move`` zapisywały ``added_manual`` — bez plakietki „↻ z …” i z
   zaniżonym wierszem „Przepięcie” w Insights. Rozpoznanie żyje teraz przy
   zakładaniu NOWEGO procesu (``transition_process``).

2. Arkusz screeningu należy do pary, ale tylko do bieżącej próby procesu.
   Osoba odrzucona rok temu, dodana ponownie, nie przechodzi na
   „Zweryfikowany” starym arkuszem, a nowy wiersz etapu go nie dziedziczy
   (portal klienta i generator CV czytają bieżący wiersz). Powrót z
   „Zamkniętych” krótko po zamknięciu (≤ 30 dni) zachowuje arkusz.

Prawdziwy Postgres, baza wspólna i nieczyszczona — każdy test zakłada własny
świat i sprawdza tylko swoje wiersze.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.job import Job, JobStatus, RemotePolicy
from app.models.job_proposal import JobProposal
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.recruitment_process import ProcessStatus, RecruitmentProcess
from app.models.user import UserRole
from app.services import candidate_claim
from app.services.recruitment_process_commands import (
    SCREENING_REOPEN_GRACE,
    open_process,
    screening_window,
    transition_process,
)
from tests.test_board_tasks import _cleanup, _login, _seed_user, _seed_world

SHEET = {"answers": [{"question_id": "q1", "response": "5 lat Kafka"}]}


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


@pytest.fixture
def verified_gate_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "VERIFIED_GATE_ENABLED", True)


# ── Jednostkowe: okno arkusza ────────────────────────────────────────────────


def _proc(status: ProcessStatus, attempt: int, opened: datetime, closed=None):
    return SimpleNamespace(
        status=status, attempt_no=attempt, opened_at=opened, closed_at=closed
    )


def test_screening_window_follows_the_current_attempt() -> None:
    now = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)
    year_ago = now - timedelta(days=365)

    # Brak procesu i pierwsza próba: wszystkie wiersze pary.
    assert screening_window(None, at=now).covers(year_ago)
    first = screening_window(_proc(ProcessStatus.open, 1, year_ago), at=now)
    assert first.counts and first.since is None

    # Druga próba: tylko wiersze od jej początku.
    opened = now - timedelta(days=2)
    second = screening_window(_proc(ProcessStatus.open, 2, opened), at=now)
    assert second.since == opened
    assert second.covers(opened)
    assert not second.covers(year_ago)

    # Zamknięta niedawno: ruch otworzy nową próbę, arkusz idzie z osobą.
    recent = _proc(ProcessStatus.closed, 1, year_ago, now - timedelta(days=10))
    assert screening_window(recent, at=now).covers(year_ago)
    edge = _proc(ProcessStatus.closed, 1, year_ago, now - SCREENING_REOPEN_GRACE)
    assert screening_window(edge, at=now).counts

    # Zamknięta dawno: żaden stary arkusz się nie liczy.
    old = _proc(ProcessStatus.closed, 1, year_ago, now - timedelta(days=300))
    stale = screening_window(old, at=now)
    assert not stale.counts
    assert not stale.covers(now)


# ── Przepięcie rozpoznane przy zakładaniu procesu ───────────────────────────


async def _seed_source_job(world: dict) -> int:
    async with AsyncSessionLocal() as db:
        job = Job(
            title=f"Źródło {uuid.uuid4().hex[:6]}",
            location="Warszawa",
            status=JobStatus.published,
            remote_policy=RemotePolicy.hybrid,
            client_id=world["client_id"],
        )
        db.add(job)
        await db.commit()
        return job.id


async def _seed_reassign_proposal(world: dict, source_job_id: int) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            JobProposal(
                job_id=world["job_id"],
                candidate_id=world["candidate_id"],
                source="reassign",
                status="proposed",
                evidence={"reassign": {"job_id": source_job_id}},
            )
        )
        await db.commit()


async def _latest_process(world: dict) -> RecruitmentProcess:
    async with AsyncSessionLocal() as db:
        proc = await db.scalar(
            select(RecruitmentProcess)
            .where(
                RecruitmentProcess.candidate_id == world["candidate_id"],
                RecruitmentProcess.job_id == world["job_id"],
            )
            .order_by(RecruitmentProcess.attempt_no.desc())
            .limit(1)
        )
    assert proc is not None
    return proc


async def _drop(world: dict, source_job_id: int | None, user_ids: list[int]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(JobProposal).where(JobProposal.candidate_id == world["candidate_id"])
        )
        if source_job_id is not None:
            await db.execute(delete(Job).where(Job.id == source_job_id))
        await db.commit()
    await _cleanup(world, user_ids)


@pytest.mark.asyncio
async def test_manual_add_with_open_reassign_proposal_is_a_reassign() -> None:
    """Dodanie z ekranu innego niż „proposals/bulk” (tu: ``added_manual``,
    jak historia, shortlista, rekomendacje, profil i ``/move``)."""
    world = await _seed_world()
    rec_id, _ = await _seed_user(UserRole.recruiter)
    source_job_id = await _seed_source_job(world)
    try:
        await _seed_reassign_proposal(world, source_job_id)
        async with AsyncSessionLocal() as db:
            await open_process(
                db,
                candidate_id=world["candidate_id"],
                job_id=world["job_id"],
                stage=PipelineStage.new,
                actor_user_id=rec_id,
                entry_source=candidate_claim.ENTRY_ADDED_MANUAL,
                claim_for_user_id=rec_id,
            )
            await db.commit()
        proc = await _latest_process(world)
        assert proc.entry_source == candidate_claim.ENTRY_REASSIGN
        assert proc.reassign_from_job_id == source_job_id
    finally:
        await _drop(world, source_job_id, [rec_id])


@pytest.mark.asyncio
async def test_explicit_sources_and_pairs_without_proposal_stay_as_given() -> None:
    world = await _seed_world()
    other = await _seed_world()
    rec_id, _ = await _seed_user(UserRole.recruiter)
    source_job_id = await _seed_source_job(world)
    try:
        # Integracja z otwartym przepięciem zostaje automatem.
        await _seed_reassign_proposal(world, source_job_id)
        async with AsyncSessionLocal() as db:
            await open_process(
                db,
                candidate_id=world["candidate_id"],
                job_id=world["job_id"],
                stage=PipelineStage.new,
                actor_user_id=rec_id,
                entry_source=candidate_claim.ENTRY_AUTO_MATCH,
            )
            await db.commit()
        proc = await _latest_process(world)
        assert proc.entry_source == candidate_claim.ENTRY_AUTO_MATCH
        assert proc.reassign_from_job_id is None

        # Bez propozycji przepięcia ręczne dodanie zostaje ręcznym.
        async with AsyncSessionLocal() as db:
            await open_process(
                db,
                candidate_id=other["candidate_id"],
                job_id=other["job_id"],
                stage=PipelineStage.new,
                actor_user_id=rec_id,
                entry_source=candidate_claim.ENTRY_ADDED_MANUAL,
            )
            await db.commit()
        other_proc = await _latest_process(other)
        assert other_proc.entry_source == candidate_claim.ENTRY_ADDED_MANUAL
        assert other_proc.reassign_from_job_id is None
    finally:
        await _drop(world, source_job_id, [rec_id])
        await _cleanup(other, [])


# ── Arkusz bieżącej próby ────────────────────────────────────────────────────


async def _closed_attempt_with_sheet(world: dict, actor_id: int, closed_days: int):
    """Pierwsza próba: arkusz w „Screeningu”, potem odrzucenie."""
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        await transition_process(
            db,
            candidate_id=world["candidate_id"],
            job_id=world["job_id"],
            stage=PipelineStage.screening,
            stage_def_id=world["defs"]["screening"],
            actor_user_id=actor_id,
            moved_at=now - timedelta(days=closed_days + 3),
            screening_answers=SHEET,
        )
        await transition_process(
            db,
            candidate_id=world["candidate_id"],
            job_id=world["job_id"],
            stage=PipelineStage.rejected,
            actor_user_id=actor_id,
            moved_at=now - timedelta(days=closed_days),
            ended_by="recruiter",
        )
        await db.commit()


async def _readd(world: dict, actor_id: int) -> CandidateStage:
    async with AsyncSessionLocal() as db:
        stage = await open_process(
            db,
            candidate_id=world["candidate_id"],
            job_id=world["job_id"],
            stage=PipelineStage.new,
            actor_user_id=actor_id,
            entry_source=candidate_claim.ENTRY_ADDED_MANUAL,
        )
        await db.commit()
        return stage


async def _move_to_verified(client: AsyncClient, headers: dict, world: dict):
    return await client.post(
        "/api/pipeline/move",
        headers=headers,
        json={
            "candidate_id": world["candidate_id"],
            "job_id": world["job_id"],
            "stage_def_id": world["defs"]["verified"],
            "expected_rate_value": "140",
            "expected_rate_unit": "hourly",
            "expected_rate_currency": "PLN",
        },
    )


@pytest.mark.asyncio
async def test_sheet_from_a_year_old_attempt_does_not_pass_verified(
    api_client: AsyncClient, verified_gate_on
) -> None:
    world = await _seed_world()
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    rec = await _login(api_client, rec_creds)
    try:
        await _closed_attempt_with_sheet(world, rec_id, closed_days=365)
        new_stage = await _readd(world, rec_id)
        assert new_stage.screening_answers is None

        proc = await _latest_process(world)
        assert proc.attempt_no == 2 and proc.status == ProcessStatus.open

        # Karta nowej próby nie pokazuje arkusza sprzed roku.
        screening = await api_client.get(
            f"/api/pipeline/stages/{new_stage.id}/screening", headers=rec
        )
        assert screening.status_code == 200, screening.text
        assert screening.json()["screening_source_stage_id"] is None

        moved = await _move_to_verified(api_client, rec, world)
        assert moved.status_code == 409, moved.text
        assert moved.json()["detail"]["missing"] == ["screening_sheet"]
    finally:
        await _cleanup(world, [rec_id])


@pytest.mark.asyncio
async def test_return_shortly_after_closing_keeps_the_sheet(
    api_client: AsyncClient, verified_gate_on
) -> None:
    world = await _seed_world()
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    rec = await _login(api_client, rec_creds)
    try:
        await _closed_attempt_with_sheet(world, rec_id, closed_days=10)
        new_stage = await _readd(world, rec_id)
        assert new_stage.screening_answers == SHEET

        moved = await _move_to_verified(api_client, rec, world)
        assert moved.status_code == 200, moved.text

        # Arkusz idzie dalej w ramach nowej próby (zwykłe przejście etapu).
        async with AsyncSessionLocal() as db:
            latest = await db.scalar(
                select(CandidateStage)
                .where(
                    CandidateStage.candidate_id == world["candidate_id"],
                    CandidateStage.job_id == world["job_id"],
                )
                .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
                .limit(1)
            )
        assert latest.stage == PipelineStage.verified
        assert latest.screening_answers == SHEET
    finally:
        await _cleanup(world, [rec_id])
