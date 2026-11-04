"""Bramka integracji (06.10.2026): bez zgłoszenia do TEJ rekrutacji — propozycja.

Integracja (token OAuth) bez ``auto_match`` zakładała kartę w „Ogłoszeniach”
(scraper 01–05.10: 357 kart). Teraz ``/move`` dla nowej osoby,
``assign-to-job`` i ``proposals/bulk`` zakładają propozycję ``job_board``,
chyba że jest dowód zgłoszenia (formularz, źródło „ogłoszenie”, notatka
z formularza aplikacji). Człowiek dodaje jak dotąd.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.services.integration_intake import candidates_with_application_evidence
from tests.test_pipeline_membership_gate import (
    _seed_candidate,
    _seed_job,
    _seed_recruiter,
)

_INTEGRATION = SimpleNamespace(state=SimpleNamespace(oauth_client_id="scraper"))


async def _source_event(candidate_id: int, job_id: int, channel: str) -> None:
    from app.models.candidate_source_event import CandidateSourceEvent, SourceChannel

    async with AsyncSessionLocal() as db:
        db.add(
            CandidateSourceEvent(
                candidate_id=candidate_id,
                job_id=job_id,
                channel=SourceChannel(channel),
            )
        )
        await db.commit()


async def _application_note(candidate_id: int, job_id: int, author_id: int) -> None:
    from app.models.note import Note, NoteType

    async with AsyncSessionLocal() as db:
        db.add(
            Note(
                content="Odpowiedzi z formularza aplikacji — pracuj.pl",
                note_type=NoteType.general,
                candidate_id=candidate_id,
                job_id=job_id,
                author_id=author_id,
                kind="application_form",
                external_source="system",
            )
        )
        await db.commit()


@pytest.mark.asyncio
async def test_evidence_counts_only_this_job(app_client):
    _, uid = await _seed_recruiter(app_client)
    job_id, _ = await _seed_job()
    other_job, _ = await _seed_job()
    by_source, by_note, by_other_job, by_referral, none = [
        await _seed_candidate() for _ in range(5)
    ]
    await _source_event(by_source, job_id, "posting")
    await _application_note(by_note, job_id, uid)
    await _source_event(by_other_job, other_job, "posting")
    await _source_event(by_referral, job_id, "referral")

    async with AsyncSessionLocal() as db:
        applied = await candidates_with_application_evidence(
            db,
            job_id=job_id,
            candidate_ids=[by_source, by_note, by_other_job, by_referral, none],
        )
    assert applied == {by_source, by_note}


async def _user(uid: int):
    from app.models.user import User

    async with AsyncSessionLocal() as db:
        user = await db.get(User, uid)
        db.expunge(user)
        return user


@pytest.mark.asyncio
async def test_integration_move_of_a_fresh_pair_becomes_a_proposal(app_client):
    from app.api.pipeline import move_candidate
    from app.models.job_proposal import JobProposal
    from app.models.recruitment_pipeline import CandidateStage
    from app.schemas.pipeline import StageMove

    _, uid = await _seed_recruiter(app_client)
    user = await _user(uid)
    job_id, _ = await _seed_job()
    cand = await _seed_candidate()

    async with AsyncSessionLocal() as db:
        resp = await move_candidate(
            data=StageMove(candidate_id=cand, job_id=job_id, stage="new"),
            current_user=user,
            db=db,
            request=_INTEGRATION,
        )
    assert resp.status_code == 202

    async with AsyncSessionLocal() as db:
        assert (
            await db.scalar(
                select(CandidateStage.id).where(
                    CandidateStage.candidate_id == cand,
                    CandidateStage.job_id == job_id,
                )
            )
            is None
        )
        proposal = await db.scalar(
            select(JobProposal).where(
                JobProposal.job_id == job_id, JobProposal.candidate_id == cand
            )
        )
        assert proposal is not None and proposal.source == "job_board"
        assert proposal.score is None


@pytest.mark.asyncio
async def test_integration_move_with_application_adds_a_card(app_client):
    from app.api.pipeline import move_candidate
    from app.schemas.pipeline import StageMove

    _, uid = await _seed_recruiter(app_client)
    user = await _user(uid)
    job_id, _ = await _seed_job()
    cand = await _seed_candidate()
    await _source_event(cand, job_id, "posting")

    async with AsyncSessionLocal() as db:
        resp = await move_candidate(
            data=StageMove(candidate_id=cand, job_id=job_id, stage="new"),
            current_user=user,
            db=db,
            request=_INTEGRATION,
        )
    assert getattr(resp, "status_code", 200) == 200
    assert resp.candidate_id == cand


@pytest.mark.asyncio
async def test_integration_assign_to_job_becomes_a_proposal(app_client):
    from app.api.recommendations import assign_candidate_to_job
    from app.models.job_proposal import JobProposal
    from app.models.recruitment_pipeline import CandidateStage

    _, uid = await _seed_recruiter(app_client)
    user = await _user(uid)
    job_id, _ = await _seed_job()
    cand = await _seed_candidate()

    async with AsyncSessionLocal() as db:
        body = await assign_candidate_to_job(
            request=_INTEGRATION,
            candidate_id=cand,
            job_id=job_id,
            current_user=user,
            db=db,
        )
    assert body["status"] == "proposed" and body["stage_id"] is None
    async with AsyncSessionLocal() as db:
        assert (
            await db.scalar(
                select(CandidateStage.id).where(
                    CandidateStage.candidate_id == cand,
                    CandidateStage.job_id == job_id,
                )
            )
            is None
        )
        assert await db.scalar(
            select(JobProposal.id).where(
                JobProposal.job_id == job_id, JobProposal.candidate_id == cand
            )
        )
