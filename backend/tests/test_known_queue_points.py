"""„Znamy tę osobę”: punkty kolejki w „Nowych” (decyzja Artura z 02.11.2026)."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.job_autofill_pool import JobAutofillPool
from app.models.note import Note
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.services import known_queue_points as known
from app.services import new_column_autofill as autofill


@pytest.mark.parametrize(
    "jobs, note_days, expected",
    [
        (0, None, (0, 0)),
        (2, None, (6, 0)),
        (0, 30, (0, 8)),
        (0, 31, (0, 2)),
        (0, 90, (0, 2)),
        (0, 91, (0, 0)),
        (1, 5, (6, 8)),
    ],
)
def test_points_for_the_edges_of_each_window(jobs, note_days, expected):
    assert known.points_for(known.KnownPoints(), jobs, note_days) == expected


def test_points_outside_the_allowed_range_are_refused():
    assert known.validation_error(known.KnownPoints()) is None
    assert known.validation_error(known.KnownPoints(client=-1)) is not None
    assert known.validation_error(known.KnownPoints(note_recent=16)) is not None


async def _world() -> dict:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"KQ client {tag}")
        other_client = Client(name=f"KQ other {tag}")
        db.add_all([client, other_client])
        await db.flush()
        job = Job(
            title=f"KQ job {tag}",
            client_id=client.id,
            status=JobStatus.published,
            work_state="searching",
        )
        earlier = Job(
            title=f"KQ earlier {tag}",
            client_id=client.id,
            status=JobStatus.published,
        )
        elsewhere = Job(
            title=f"KQ elsewhere {tag}",
            client_id=other_client.id,
            status=JobStatus.published,
        )
        people = [Candidate(name="Znana", lastname=f"{i}-{tag}") for i in range(5)]
        db.add_all([job, earlier, elsewhere, *people])
        await db.commit()
        return {
            "job": job.id,
            "client": client.id,
            "earlier": earlier.id,
            "elsewhere": elsewhere.id,
            "ids": [p.id for p in people],
        }


async def _stage(cid: int, job_id: int, stage: PipelineStage, **extra) -> None:
    async with AsyncSessionLocal() as db:
        db.add(CandidateStage(candidate_id=cid, job_id=job_id, stage=stage, **extra))
        await db.commit()


async def _note(cid: int, days_ago: int) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            Note(
                candidate_id=cid,
                content="Rozmowa",
                created_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
            )
        )
        await db.commit()


@pytest.mark.asyncio
async def test_facts_count_this_client_and_fresh_notes_only():
    w = await _world()
    familiar, other_client, rejected, stranger, legacy = w["ids"]
    await _stage(familiar, w["earlier"], PipelineStage.verified)
    await _note(familiar, 2)
    await _stage(other_client, w["elsewhere"], PipelineStage.verified)
    await _stage(rejected, w["earlier"], PipelineStage.cv_sent)
    await _stage(rejected, w["earlier"], PipelineStage.rejected, ended_by="client")
    await _note(rejected, 1)
    # Stary wiersz: odrzucenie po wysyłce bez `ended_by` nie zabiera punktów.
    await _stage(legacy, w["earlier"], PipelineStage.cv_sent)
    await _stage(legacy, w["earlier"], PipelineStage.rejected)
    async with AsyncSessionLocal() as db:
        facts = await known.facts_for(
            db,
            job_id=w["job"],
            client_id=w["client"],
            candidate_ids=w["ids"],
            now=datetime.now(timezone.utc),
        )
    assert facts[familiar].points == 14
    assert facts[familiar].verified_at_client == 1
    assert facts[familiar].last_note_days == 2
    # Weryfikacja u innego klienta nie daje punktów, odrzucenie przez tego klienta
    # zabiera też punkty za świeżą notatkę.
    assert set(facts) == {familiar, legacy}
    assert facts[legacy].points == 6


@pytest.mark.asyncio
async def test_saved_points_replace_the_defaults():
    async with AsyncSessionLocal() as db:
        await known.save_points(
            db, known.KnownPoints(client=1, note_recent=2, note_older=3), actor_id=None
        )
        await db.flush()
        assert await known.read_points(db) == known.KnownPoints(1, 2, 3)
        await db.rollback()


@pytest.mark.asyncio
async def test_picks_order_by_score_with_points_and_score_stays_the_score():
    w = await _world()
    familiar, higher, *_ = w["ids"]
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                JobAutofillPool(
                    job_id=w["job"],
                    candidate_id=familiar,
                    score=70,
                    run_id="r",
                    evidence={},
                ),
                JobAutofillPool(
                    job_id=w["job"],
                    candidate_id=higher,
                    score=75,
                    run_id="r",
                    evidence={},
                ),
            ]
        )
        await db.commit()
    await _stage(familiar, w["earlier"], PipelineStage.verified)
    async with AsyncSessionLocal() as db:
        picks = await autofill.ranked_picks(db, w["job"], limit=10)
    assert [p.candidate_id for p in picks] == [familiar, higher]
    assert picks[0].score == 70


@pytest.mark.asyncio
async def test_without_process_ignores_this_recruitment_only():
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Fresh client {tag}")
        db.add(client)
        await db.flush()
        job = Job(title=f"Fresh {tag}", client_id=client.id, status=JobStatus.published)
        other = Job(title=f"Other {tag}", client_id=client.id, status=JobStatus.closed)
        people = [
            Candidate(
                name="Bez", lastname=f"{i}-{tag}", email=f"fresh-{i}-{tag}@example.com"
            )
            for i in range(3)
        ]
        db.add_all([job, other, *people])
        await db.flush()
        here_only, elsewhere, nowhere = (p.id for p in people)
        db.add_all(
            [
                CandidateStage(
                    candidate_id=here_only, job_id=job.id, stage=PipelineStage.new
                ),
                CandidateStage(
                    candidate_id=elsewhere,
                    job_id=other.id,
                    stage=PipelineStage.rejected,
                ),
            ]
        )
        await db.commit()
        fresh = await known.without_process(
            db, job_id=job.id, candidate_ids=[here_only, elsewhere, nowhere]
        )
        assert fresh == {here_only, nowhere}
        assert await known.without_process(db, job_id=job.id, candidate_ids=[]) == set()
