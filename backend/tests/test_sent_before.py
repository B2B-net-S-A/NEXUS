"""„Wysłany wcześniej” w silniku „Nowych” i porcji (Z1 i Z3, 20.11.2026) —
prawdziwy Postgres.

Kontrakty:

- osoba wysłana do klienta w innej rekrutacji w ostatnim roku to fakt
  z liczbą rekrutacji i ostatnią wysyłką; wysyłka starsza niż rok i wysyłka
  w tej samej rekrutacji się nie liczą;
- kolejka dostaje za nią ``SENT_POINTS``;
- budżet ponad 15% i miasto dalej niż 100 km od biura jej nie wycinają, tylko
  dają ostrzeżenie; osoba bez wysyłki dalej odpada;
- przy progu porcji (65%) wchodzi od 65% jak inni (od 22.11.2026) i ma
  ``sent_before`` w migawce.

Baza testowa jest wspólna i nieczyszczona: asercje dotyczą własnych wierszy.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.job_autofill_pool import JobAutofillPool
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.recruitment_process import RecruitmentProcess
from app.services import known_queue_points as known
from app.services import new_column_autofill as autofill
from app.services import sent_before

_WARSAW = ZoneInfo("Europe/Warsaw")
_WORKDAY = datetime(2026, 11, 9, 9, 0, tzinfo=_WARSAW).astimezone(timezone.utc)


async def _world(people: int) -> dict:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"SB client {tag}")
        other = Client(name=f"SB other {tag}")
        db.add_all([client, other])
        await db.flush()
        job = Job(
            title=f"SB job {tag}",
            client_id=client.id,
            status=JobStatus.published,
            work_state="searching",
        )
        earlier = Job(
            title=f"SB earlier {tag}", client_id=other.id, status=JobStatus.published
        )
        candidates = [
            Candidate(name="Wysłany", lastname=f"{i}-{tag}") for i in range(people)
        ]
        db.add_all([job, earlier, *candidates])
        await db.commit()
        return {
            "job_id": job.id,
            "earlier_id": earlier.id,
            "earlier_title": earlier.title,
            "ids": [c.id for c in candidates],
        }


async def _sent(cid: int, job_id: int, *, days_ago: int) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(
                candidate_id=cid,
                job_id=job_id,
                stage=PipelineStage.cv_sent,
                moved_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
            )
        )
        await db.commit()


async def _pool(job_id: int, scores: dict[int, float]) -> None:
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                JobAutofillPool(
                    job_id=job_id,
                    candidate_id=cid,
                    score=Decimal(str(score)),
                    run_id="run-sb",
                    evidence={"matched_must": ["Java"], "missing_must": []},
                )
                for cid, score in scores.items()
            ]
        )
        await db.commit()


async def test_facts_count_other_recruitments_in_the_last_year():
    world = await _world(3)
    recent, old, same = world["ids"]
    await _sent(recent, world["earlier_id"], days_ago=7)
    await _sent(old, world["earlier_id"], days_ago=400)
    await _sent(same, world["job_id"], days_ago=3)
    async with AsyncSessionLocal() as db:
        facts = await sent_before.facts_for(
            db,
            job_id=world["job_id"],
            candidate_ids=world["ids"],
            now=datetime.now(timezone.utc),
        )
    assert set(facts) == {recent}
    assert facts[recent].count == 1
    assert facts[recent].last_days == 7
    assert facts[recent].last_job_title == world["earlier_title"]


async def test_queue_points_for_a_person_sent_elsewhere():
    world = await _world(2)
    sent, fresh = world["ids"]
    await _sent(sent, world["earlier_id"], days_ago=30)
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, world["job_id"])
        facts = await known.facts_for(
            db,
            job_id=job.id,
            client_id=job.client_id,
            candidate_ids=[sent, fresh],
            now=datetime.now(timezone.utc),
        )
    assert facts[sent].sent_elsewhere == 1
    assert facts[sent].sent_points == known.SENT_POINTS
    assert facts[sent].points == known.SENT_POINTS
    assert fresh not in facts


async def test_budget_and_distance_do_not_cut_a_person_sent_before(monkeypatch):
    """Z3: 20 z 42 osób, które reguły wycięły, a zespół i tak wysłał
    (09–19.11), było już wcześniej wysyłanych."""
    monkeypatch.setattr(autofill, "TARGET", 4)
    world = await _world(4)
    pricey_sent, pricey, far_sent, far = world["ids"]
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, world["job_id"])
        job.rate_budget_hourly = Decimal("100")
        job.onsite_days_per_week = 1
        job.location = "Warszawa"
        now = datetime.now(timezone.utc)
        for cid in (pricey_sent, pricey):
            person = await db.get(Candidate, cid)
            person.rate_from_hourly = Decimal("140")
            person.rate_from_computed_at = now
        (await db.get(Candidate, far_sent)).city = "Kraków"
        (await db.get(Candidate, far)).city = "Kraków"
        await db.commit()
    for cid in (pricey_sent, far_sent):
        await _sent(cid, world["earlier_id"], days_ago=20)
    await _pool(world["job_id"], {pricey_sent: 90, pricey: 89, far_sent: 88, far: 87})

    async with AsyncSessionLocal() as db:
        added = await autofill.fill_job(db, world["job_id"], now=_WORKDAY)
        await db.commit()

    assert set(added) == {pricey_sent, far_sent}
    async with AsyncSessionLocal() as db:
        metas = {
            p.candidate_id: p.entry_meta
            for p in (
                await db.scalars(
                    select(RecruitmentProcess).where(
                        RecruitmentProcess.job_id == world["job_id"]
                    )
                )
            ).all()
        }
    assert [c["key"] for c in metas[pricey_sent]["cautions"]] == ["budget"]
    assert [c["key"] for c in metas[far_sent]["cautions"]] == ["office_city"]
    assert metas[far_sent]["cautions"][0]["km"] > autofill.OFFICE_FAR_KM
    assert metas[pricey_sent]["sent_before"] is True


async def test_batch_threshold_is_the_same_for_a_sent_person():
    """R3, 22.11.2026: przy progu porcji 65% osoba wysłana wcześniej wchodzi
    od 65% jak inni (60–64% dawało 0 CV z 40 decyzji), ale z flagą."""
    world = await _world(3)
    sent, below, weak_sent = world["ids"]
    await _sent(sent, world["earlier_id"], days_ago=10)
    await _sent(weak_sent, world["earlier_id"], days_ago=10)
    await _pool(world["job_id"], {sent: 66, below: 60, weak_sent: 62})

    async with AsyncSessionLocal() as db:
        picks = await autofill.ranked_picks(
            db, world["job_id"], limit=10, min_score=65.0
        )

    assert [p.candidate_id for p in picks] == [sent]
    assert picks[0].sent_before is True


async def _pool_rows(job_id: int) -> dict[int, tuple[float, bool]]:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(
                    JobAutofillPool.candidate_id,
                    JobAutofillPool.score,
                    JobAutofillPool.evidence,
                ).where(JobAutofillPool.job_id == job_id)
            )
        ).all()
    return {
        int(cid): (float(score), sent_before.is_sent_before(evidence))
        for cid, score, evidence in rows
    }


async def test_new_cv_does_not_trim_people_sent_before_from_the_pool(monkeypatch):
    """22.11.2026: dopisanie nowego CV przycinało pulę do 150 według wyniku
    i wycinało dołożonych „wysłanych wcześniej” (27 z 33 pilnych pul miało ich
    0). Przycinanie liczy miejsca tylko wśród zwykłej puli, a nowy wynik osoby
    dołożonej nie zdejmuje z niej flagi."""
    from app.services import auto_full_review
    from app.services import auto_match_service as ams

    monkeypatch.setattr(auto_full_review, "AUTOFILL_POOL_SIZE", 3)
    world = await _world(6)
    a, b, c, extra, again, newcomer = world["ids"]
    await _pool(world["job_id"], {a: 80, b: 75, c: 70})
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                JobAutofillPool(
                    job_id=world["job_id"],
                    candidate_id=cid,
                    score=Decimal(str(score)),
                    run_id="run-sb",
                    evidence={
                        "matched_must": [],
                        "missing_must": [],
                        sent_before.EVIDENCE_KEY: True,
                    },
                )
                for cid, score in ((extra, 55), (again, 52))
            ]
        )
        await db.commit()

    scored = [
        ams.Scored(
            candidate_id=newcomer,
            job_id=world["job_id"],
            score=90.0,
            matching_must=("Java",),
            gap_must=(),
            penalties=(),
        ),
        ams.Scored(
            candidate_id=again,
            job_id=world["job_id"],
            score=71.0,
            matching_must=("Java",),
            gap_must=(),
            penalties=(),
        ),
    ]
    async with AsyncSessionLocal() as db:
        await ams._write_pool(db, scored=scored, revision="r2", run_id="run-cv")
        await db.commit()

    pool = await _pool_rows(world["job_id"])
    regular = {cid for cid, (_s, flag) in pool.items() if not flag}
    assert regular == {newcomer, a, b}
    assert pool[extra] == (55.0, True)
    assert pool[again] == (71.0, True)


async def test_new_cv_does_not_trim_fresh_cv_extras_from_the_pool(monkeypatch):
    """Audyt R3, 24.11.2026: dodatki „świeże CV” (``fresh_cv``, #3794) też
    są ponad pulą 150 — nie obniżają poprzeczki, nie wypadają przy cięciu,
    a nowy wynik osoby dołożonej nie zdejmuje z niej flagi."""
    from app.services import auto_full_review
    from app.services import auto_match_service as ams

    monkeypatch.setattr(auto_full_review, "AUTOFILL_POOL_SIZE", 3)
    world = await _world(6)
    a, b, c, extra, again, newcomer = world["ids"]
    await _pool(world["job_id"], {a: 80, b: 75, c: 70})
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                JobAutofillPool(
                    job_id=world["job_id"],
                    candidate_id=cid,
                    score=Decimal(str(score)),
                    run_id="run-fresh",
                    evidence={
                        "matched_must": [],
                        "missing_must": [],
                        auto_full_review.FRESH_EVIDENCE_KEY: True,
                    },
                )
                for cid, score in ((extra, 69), (again, 68))
            ]
        )
        await db.commit()

    scored = [
        ams.Scored(
            candidate_id=newcomer,
            job_id=world["job_id"],
            score=90.0,
            matching_must=("Java",),
            gap_must=(),
            penalties=(),
        ),
        ams.Scored(
            candidate_id=again,
            job_id=world["job_id"],
            score=71.0,
            matching_must=("Java",),
            gap_must=(),
            penalties=(),
        ),
    ]
    async with AsyncSessionLocal() as db:
        await ams._write_pool(db, scored=scored, revision="r2", run_id="run-cv")
        await db.commit()

    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(
                    JobAutofillPool.candidate_id,
                    JobAutofillPool.score,
                    JobAutofillPool.evidence,
                ).where(JobAutofillPool.job_id == world["job_id"])
            )
        ).all()
    pool = {
        int(cid): (float(score), auto_full_review.is_fresh_extra(evidence))
        for cid, score, evidence in rows
    }
    regular = {cid for cid, (_s, flag) in pool.items() if not flag}
    assert regular == {newcomer, a, b}
    assert pool[extra] == (69.0, True)
    assert pool[again] == (71.0, True)
