"""Porcja dnia (07.11.2026) — prawdziwy Postgres.

Kontrakty:

- porcja liczy tylko czekające karty od systemu (osoby dodane przez zespół
  się nie liczą) i bierze osoby od ``MIN_SCORE``;
- rekrutacja bez rekrutera nie dostaje porcji;
- karty dostają właścicieli po równo między rekruterów rekrutacji;
- decyzja dziś = ruch karty od systemu z „Nowych” przez tę osobę;
- „Dodaj kolejnych” dokłada osoby klikającemu;
- dzienny przebieg: drugi tick tego samego dnia nie dokłada nikogo w miejsce
  osób, o których już zdecydowano.

Baza testowa jest wspólna i nieczyszczona: asercje dotyczą własnych wierszy.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.app_setting import AppSetting
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.job_autofill_pool import JobAutofillPool
from app.models.job_collaborator import JobCollaborator
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.recruitment_process import RecruitmentProcess
from app.models.user import User, UserRole
from app.services import new_column_autofill as autofill
from app.services import review_batch as rb

_WARSAW = ZoneInfo("Europe/Warsaw")
# Poniedziałek 09.11.2026, 9:00 w Warszawie.
_WORKDAY = datetime(2026, 11, 9, 9, 0, tzinfo=_WARSAW).astimezone(timezone.utc)


async def _user(role: UserRole = UserRole.recruiter) -> int:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"rb-{tag}@example.com",
            password_hash=hash_password(f"T3st_{tag}!Batch"),
            name=f"RB {tag}",
            role=role,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        return user.id


async def _world(people: int, *, recruiters: list[int]) -> dict:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"RB client {tag}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"RB job {tag}",
            client_id=client.id,
            status=JobStatus.published,
            work_state="searching",
            recruiter_id=recruiters[0] if recruiters else None,
        )
        candidates = [
            Candidate(name="Porcja", lastname=f"{i}-{tag}") for i in range(people)
        ]
        db.add_all([job, *candidates])
        await db.flush()
        for uid in recruiters[1:]:
            db.add(JobCollaborator(job_id=job.id, user_id=uid, source="manual"))
        await db.commit()
        return {"job_id": job.id, "ids": [c.id for c in candidates]}


async def _pool(job_id: int, scores: dict[int, float]) -> None:
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                JobAutofillPool(
                    job_id=job_id,
                    candidate_id=cid,
                    score=Decimal(str(score)),
                    run_id="run-rb",
                    evidence={"matched_must": ["Java"], "missing_must": []},
                )
                for cid, score in scores.items()
            ]
        )
        await db.commit()


async def _fill(job_id: int, **kw) -> list[int]:
    async with AsyncSessionLocal() as db:
        added = await autofill.fill_job(db, job_id, now=_WORKDAY, batch=True, **kw)
        await db.commit()
        return added


async def _owners(job_id: int) -> dict[int, int]:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.scalars(
                select(RecruitmentProcess).where(
                    RecruitmentProcess.job_id == job_id,
                    RecruitmentProcess.entry_source == "system",
                )
            )
        ).all()
        return {p.candidate_id: (p.entry_meta or {}).get(rb.OWNER_KEY) for p in rows}


@pytest.fixture
def small_batch(monkeypatch):
    monkeypatch.setattr(rb, "BATCH_SIZE", 4)
    monkeypatch.setattr(rb.settings, "REVIEW_BATCH_ENABLED", True, raising=False)
    return monkeypatch


async def test_batch_fills_from_min_score_and_splits_between_recruiters(small_batch):
    a, b = await _user(), await _user()
    world = await _world(6, recruiters=[a, b])
    ids = world["ids"]
    await _pool(
        world["job_id"],
        {ids[0]: 80, ids[1]: 78, ids[2]: 75, ids[3]: 70, ids[4]: 66, ids[5]: 60},
    )

    added = await _fill(world["job_id"])

    assert len(added) == 4 and ids[5] not in added  # 60 < 65
    owners = await _owners(world["job_id"])
    assert sorted(list(owners.values()).count(u) for u in (a, b)) == [2, 2]


async def test_team_cards_do_not_count_and_no_recruiter_no_batch(small_batch):
    a = await _user()
    world = await _world(6, recruiters=[a])
    ids = world["ids"]
    await _pool(world["job_id"], {cid: 80 - i for i, cid in enumerate(ids)})
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(
                candidate_id=ids[0],
                job_id=world["job_id"],
                stage=PipelineStage.new,
                moved_by=a,
            )
        )
        await db.commit()

    added = await _fill(world["job_id"])
    assert len(added) == 4 and ids[0] not in added

    lonely = await _world(3, recruiters=[])
    await _pool(lonely["job_id"], {cid: 90 for cid in lonely["ids"]})
    assert await _fill(lonely["job_id"]) == []


async def test_decision_counts_today_and_refill_only_replaces_decided(small_batch):
    a = await _user()
    world = await _world(8, recruiters=[a])
    ids = world["ids"]
    await _pool(world["job_id"], {cid: 90 - i for i, cid in enumerate(ids)})
    first = await _fill(world["job_id"])
    assert len(first) == 4

    async with AsyncSessionLocal() as db:
        assert len(await rb.pending_cards(db, owner_id=a)) == 4
        db.add(
            CandidateStage(
                candidate_id=first[0],
                job_id=world["job_id"],
                stage=PipelineStage.screening,
                moved_by=a,
            )
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        assert await rb.decided_today(db, a, now=_WORKDAY) >= 1
        assert len(await rb.pending_cards(db, owner_id=a)) == 3

    # Następne dopełnienie dokłada tylko w miejsce jednej decyzji.
    second = await _fill(world["job_id"])
    assert len(second) == 1


async def test_add_more_goes_to_clicker(small_batch):
    a, b = await _user(), await _user()
    world = await _world(10, recruiters=[a, b])
    ids = world["ids"]
    await _pool(world["job_id"], {cid: 90 - i for i, cid in enumerate(ids)})
    first = await _fill(world["job_id"])
    more = await _fill(world["job_id"], extra_for=b)
    assert len(more) == 4
    owners = await _owners(world["job_id"])
    assert {owners[c] for c in more} == {b}
    assert {owners[c] for c in first} == {a, b}


async def test_daily_tick_runs_once_per_day(small_batch):
    a = await _user()
    world = await _world(8, recruiters=[a])
    ids = world["ids"]
    await _pool(world["job_id"], {cid: 90 - i for i, cid in enumerate(ids)})

    async def _only_mine(_db):
        return [world["job_id"]]

    small_batch.setattr(autofill, "_jobs_in_work", _only_mine)
    small_batch.setattr(autofill.settings, "NEW_COLUMN_AUTOFILL_ENABLED", True, raising=False)
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, autofill.BATCH_DAY_KEY)
        if row is not None:
            await db.delete(row)
            await db.commit()

    result = await autofill.tick(now=_WORKDAY)
    assert result["pass"] == "batch" and result["filled"] == {world["job_id"]: 4}

    async with AsyncSessionLocal() as db:
        [one] = (await rb.pending_cards(db, job_ids=[world["job_id"]]))[:1]
        db.add(
            CandidateStage(
                candidate_id=one.candidate_id,
                job_id=world["job_id"],
                stage=PipelineStage.rejected,
                moved_by=a,
            )
        )
        await db.commit()

    again = await autofill.tick(now=_WORKDAY)
    assert again["filled"] == {} and again["jobs"] == 0
