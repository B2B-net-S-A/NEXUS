"""Jednorazowe wycofanie kart od systemu ponad budżetem (25.10.2026) — Postgres.

Kontrakty:

- plan bierze tylko nietknięte karty od systemu (jeden wiersz etapu bez
  osoby, bez „Dzwonię”, bez decyzji, bez notatki pary) ze znaną stawką ponad
  ``BUDGET_HARD_OVER`` nad budżetem;
- wykonanie zdejmuje kartę drogą „Usuń z rekrutacji” (archiwum
  ``candidate_stage_removals`` bez autora, proces ``voided``), dopisuje wpis
  „Praca w tle” i nie wraca: silnik tej osoby więcej nie dodaje.

Baza testowa jest wspólna i nieczyszczona: asercje dotyczą własnych wierszy.
"""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.candidate_stage_removal import CandidateStageRemoval
from app.models.job import Job
from app.models.note import Note
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.recruitment_process import ProcessStatus, RecruitmentProcess
from app.services import autofill_withdraw
from app.services import new_column_autofill as autofill
from tests.test_new_column_autofill import _WORKDAY, _fill, _pool, _user, _world


async def _system_cards(monkeypatch, people: int) -> dict:
    monkeypatch.setattr(autofill, "TARGET", people)
    world = await _world(people)
    await _pool(world["job_id"], {cid: 90 - i for i, cid in enumerate(world["ids"])})
    assert await _fill(world["job_id"]) == world["ids"]
    return world


async def _rates(job_id: int, budget: float, rates: dict[int, float]) -> None:
    async with AsyncSessionLocal() as db:
        (await db.get(Job, job_id)).rate_budget_hourly = Decimal(str(budget))
        for cid, rate in rates.items():
            candidate = await db.get(Candidate, cid)
            candidate.rate_from_hourly = Decimal(str(rate))
            candidate.rate_from_computed_at = datetime.now(timezone.utc)
        await db.commit()


async def test_plan_takes_only_untouched_system_cards_far_above_budget(monkeypatch):
    world = await _system_cards(monkeypatch, 6)
    job_id = world["job_id"]
    far, slight, moved, noted, called, fits = world["ids"]
    recruiter = await _user()
    await _rates(
        job_id,
        100,
        {far: 140, slight: 120, moved: 200, noted: 200, called: 200, fits: 90},
    )
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(
                candidate_id=moved,
                job_id=job_id,
                stage=PipelineStage.screening,
                moved_by=recruiter,
            )
        )
        db.add(
            Note(
                candidate_id=noted,
                job_id=job_id,
                content="Dzwoniłam, oddzwoni.",
                author_id=recruiter,
            )
        )
        process = await db.scalar(
            select(RecruitmentProcess).where(
                RecruitmentProcess.job_id == job_id,
                RecruitmentProcess.candidate_id == called,
            )
        )
        process.entry_meta = {
            **process.entry_meta,
            "decided_at": "2026-10-23T10:00:00+00:00",
        }
        await db.commit()

    async with AsyncSessionLocal() as db:
        pairs = await autofill_withdraw.plan(db, job_ids=[job_id])
    assert pairs == [(far, job_id)]


async def test_apply_removes_the_card_archives_it_and_it_does_not_come_back(
    monkeypatch,
):
    world = await _system_cards(monkeypatch, 2)
    job_id = world["job_id"]
    far, fits = world["ids"]
    await _rates(job_id, 100, {far: 140, fits: 90})

    async with AsyncSessionLocal() as db:
        pairs = await autofill_withdraw.plan(db, job_ids=[job_id])
        withdrawn = await autofill_withdraw.apply(db, pairs)
        await db.commit()
    assert withdrawn == [(far, job_id)]

    async with AsyncSessionLocal() as db:
        stages = (
            await db.scalars(
                select(CandidateStage).where(
                    CandidateStage.job_id == job_id, CandidateStage.candidate_id == far
                )
            )
        ).all()
        assert stages == []
        process = await db.scalar(
            select(RecruitmentProcess).where(
                RecruitmentProcess.job_id == job_id,
                RecruitmentProcess.candidate_id == far,
            )
        )
        assert process.status == ProcessStatus.voided
        [removal] = (
            await db.scalars(
                select(CandidateStageRemoval).where(
                    CandidateStageRemoval.job_id == job_id,
                    CandidateStageRemoval.candidate_id == far,
                )
            )
        ).all()
        assert removal.removed_by is None
        assert removal.reason == autofill_withdraw.REMOVAL_REASON
        assert removal.stage_count == 1
        [event] = (
            await db.scalars(
                select(Activity).where(
                    Activity.entity_type == "job_automation",
                    Activity.entity_id == job_id,
                    Activity.action == autofill_withdraw.ACTION,
                )
            )
        ).all()
        assert event.details["count"] == 1 and event.details["candidate_ids"] == [far]

    # Miejsce się zwolniło, ale ta osoba nie wraca.
    async with AsyncSessionLocal() as db:
        assert await autofill.fill_job(db, job_id, now=_WORKDAY) == []


async def test_apply_skips_a_card_someone_touched_after_the_plan(monkeypatch):
    world = await _system_cards(monkeypatch, 1)
    job_id = world["job_id"]
    [far] = world["ids"]
    await _rates(job_id, 100, {far: 140})
    async with AsyncSessionLocal() as db:
        pairs = await autofill_withdraw.plan(db, job_ids=[job_id])
    recruiter = await _user()
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(
                candidate_id=far,
                job_id=job_id,
                stage=PipelineStage.screening,
                moved_by=recruiter,
            )
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        assert await autofill_withdraw.apply(db, pairs) == []
        await db.commit()


async def test_a_saved_screening_or_scorecard_counts_as_touched(monkeypatch):
    """Arkusz screeningu, scorecard i ocena zapisują się na tym samym wierszu
    etapu bez ruchu karty — a archiwum ich nie przechowuje, więc takiej karty
    system nie zdejmuje."""
    world = await _system_cards(monkeypatch, 4)
    job_id = world["job_id"]
    screened, scored, rated, untouched = world["ids"]
    await _rates(job_id, 100, {cid: 140 for cid in world["ids"]})
    async with AsyncSessionLocal() as db:
        stages = {
            s.candidate_id: s
            for s in (
                await db.scalars(
                    select(CandidateStage).where(CandidateStage.job_id == job_id)
                )
            ).all()
        }
        stages[screened].screening_answers = {
            "answers": [{"question_id": "q1", "value": "tak"}]
        }
        stages[scored].scorecard_answers = {"technical": 4}
        stages[rated].rating = 3
        await db.commit()

    async with AsyncSessionLocal() as db:
        assert await autofill_withdraw.plan(db, job_ids=[job_id]) == [
            (untouched, job_id)
        ]
