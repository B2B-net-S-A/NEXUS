"""Minimum porcji rośnie osobno dla każdego (decyzja Artura 08.11.2026).

Kto zrobił swoje minimum, następnego dnia roboczego ma o 10 więcej, do 50.
Baza testowa jest wspólna: wiersz stanu poziomów czyści fixture, a asercje
dotyczą własnych kont.
"""

import uuid
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.core.security import hash_password
from app.models.app_setting import AppSetting
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobPriority, JobStatus
from app.models.job_autofill_pool import JobAutofillPool
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.recruitment_process import RecruitmentProcess
from app.models.user import User, UserRole
from app.services import new_column_autofill as autofill
from app.services import review_batch as rb
from app.services import review_batch_levels as levels
from app.services import review_batch_team as team

_WAW = ZoneInfo("Europe/Warsaw")


# ── Reguła ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("level", "done", "expected"),
    [
        (10, 10, 20),
        (10, 37, 20),
        (40, 40, 50),
        (45, 45, 50),
        (50, 80, 50),
        (10, 9, 10),
        (30, 0, 30),
    ],
)
def test_next_level(level, done, expected):
    assert levels.next_level(level, done) == expected


def test_level_above_the_cap_set_by_hand_stays():
    assert levels.next_level(60, 60) == 60


@pytest.mark.parametrize(
    ("stored", "base", "expected"),
    [({}, 10, 10), ({7: 30}, 10, 30), ({7: 20}, 40, 40), ({8: 30}, 10, 10)],
)
def test_level_of(stored, base, expected):
    assert levels.level_of(stored, 7, base) == expected


def test_previous_business_day_skips_the_weekend():
    monday = datetime(2026, 11, 9).date()
    assert levels.previous_business_day(monday) == datetime(2026, 11, 6).date()


# ── Na bazie ────────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _yesterday() -> datetime:
    day = levels.previous_business_day(business_today())
    return datetime.combine(day, time(12), tzinfo=_WAW).astimezone(timezone.utc)


async def _user() -> int:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"rbl-{tag}@example.com",
            password_hash=hash_password(f"T3st_{tag}!Batch"),
            name=f"RBL {tag}",
            role=UserRole.recruiter,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        return user.id


async def _cards(recruiter: int, count: int, *, opened: datetime) -> dict:
    """Rekrutacja z ``count`` kartami od systemu dla rekrutera, założonymi
    w chwili ``opened``."""
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"RBL client {tag}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"RBL job {tag}",
            client_id=client.id,
            status=JobStatus.published,
            work_state="searching",
            recruiter_id=recruiter,
            priority=JobPriority.medium,
        )
        people = [Candidate(name="P", lastname=f"{i}-{tag}") for i in range(count)]
        db.add_all([job, *people])
        await db.flush()
        db.add_all(
            [
                JobAutofillPool(
                    job_id=job.id,
                    candidate_id=p.id,
                    score=Decimal("90"),
                    run_id="run-rbl",
                    evidence={"matched_must": ["Java"], "missing_must": []},
                )
                for p in people
            ]
        )
        await db.commit()
        job_id = job.id
    async with AsyncSessionLocal() as db:
        added = await autofill.fill_job(db, job_id, now=_now(), batch=True)
        await db.commit()
    async with AsyncSessionLocal() as db:
        for process in await db.scalars(
            select(RecruitmentProcess).where(RecruitmentProcess.job_id == job_id)
        ):
            process.opened_at = opened
        for stage in await db.scalars(
            select(CandidateStage).where(CandidateStage.job_id == job_id)
        ):
            stage.moved_at = opened
        await db.commit()
    return {"job_id": job_id, "ids": added}


async def _move(
    job_id: int, candidate_id: int, stage: PipelineStage, by: int, at: datetime
) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(
                candidate_id=candidate_id,
                job_id=job_id,
                stage=stage,
                moved_by=by,
                moved_at=at,
            )
        )
        await db.commit()


async def _rejected(recruiter: int, count: int, at: datetime) -> None:
    """``count`` decyzji rekrutera w chwili ``at``."""
    world = await _cards(recruiter, count, opened=at - timedelta(hours=2))
    for cid in world["ids"]:
        await _move(world["job_id"], cid, PipelineStage.rejected, recruiter, at)


async def _state(day, users: dict[int, int]) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, levels.LEVELS_KEY)
        value = {"day": day.isoformat(), "users": {str(k): v for k, v in users.items()}}
        if row is None:
            db.add(AppSetting(key=levels.LEVELS_KEY, value=value))
        else:
            row.value = value
        await db.commit()


async def _roll() -> dict[int, int]:
    async with AsyncSessionLocal() as db:
        result = await levels.roll_levels(db, now=_now())
        await db.commit()
        return result


async def _status(user_id: int) -> rb.BatchStatus:
    async with AsyncSessionLocal() as db:
        return await rb.status_for(db, await db.get(User, user_id), now=_now())


@pytest.fixture
def batch_on(monkeypatch):
    monkeypatch.setattr(rb, "BATCH_SIZE", 40)
    monkeypatch.setattr(rb.settings, "REVIEW_BATCH_ENABLED", True, raising=False)
    return monkeypatch


@pytest.fixture
async def clean_state():
    async with AsyncSessionLocal() as db:
        for key in (levels.LEVELS_KEY, autofill.BATCH_DAY_KEY, rb.SETTING_KEY):
            row = await db.get(AppSetting, key)
            if row is not None:
                await db.delete(row)
        await db.commit()


async def test_first_day_starts_everyone_at_the_base(batch_on, clean_state):
    a = await _user()
    await _rejected(a, 12, _yesterday())
    rolled = await _roll()
    assert a not in rolled
    assert (await _status(a)).minimum == rb.DEFAULT_MINIMUM


async def test_reaching_the_minimum_raises_it_the_next_day(batch_on, clean_state):
    a = await _user()
    await _state(levels.previous_business_day(business_today()), {})
    await _rejected(a, 10, _yesterday())
    rolled = await _roll()
    assert rolled[a] == 20
    assert (await _status(a)).minimum == 20


async def test_one_short_of_the_minimum_keeps_the_level(batch_on, clean_state):
    a = await _user()
    await _state(levels.previous_business_day(business_today()), {a: 20})
    await _rejected(a, 19, _yesterday())
    assert (await _roll())[a] == 20


async def test_open_screenings_do_not_raise_the_minimum(batch_on, clean_state):
    """Dziesięć „Do screeningu” bez domknięcia to jeszcze nie dziesięć decyzji."""
    a = await _user()
    at = _yesterday()
    await _state(levels.previous_business_day(business_today()), {})
    world = await _cards(a, 10, opened=at - timedelta(hours=2))
    for cid in world["ids"]:
        await _move(world["job_id"], cid, PipelineStage.screening, a, at)
    assert a not in await _roll()


async def test_second_roll_the_same_day_changes_nothing(batch_on, clean_state):
    a = await _user()
    await _state(levels.previous_business_day(business_today()), {})
    await _rejected(a, 10, _yesterday())
    await _roll()
    assert (await _roll())[a] == 20


async def test_minimum_stops_at_fifty(batch_on, clean_state):
    a = await _user()
    await _state(levels.previous_business_day(business_today()), {a: 50})
    await _rejected(a, 50, _yesterday())
    assert (await _roll())[a] == 50


async def test_decisions_before_yesterday_do_not_count(batch_on, clean_state):
    a = await _user()
    await _state(levels.previous_business_day(business_today()), {})
    await _rejected(a, 10, _yesterday() - timedelta(days=7))
    assert a not in await _roll()


async def test_person_with_a_few_cards_is_not_blocked_by_a_high_level(
    batch_on, clean_state
):
    """Poziom 40, w porcji 2 karty: wymagane 2, bo nie ma z czego zrobić więcej."""
    a = await _user()
    await _state(business_today(), {a: 40})
    await _cards(a, 2, opened=_now() - timedelta(hours=1))
    status = await _status(a)
    assert status.minimum == 40
    assert status.required == 2


async def test_team_view_reads_each_persons_level(batch_on, clean_state):
    a = await _user()
    await _state(business_today(), {a: 30})
    await _cards(a, 35, opened=_now() - timedelta(hours=1))
    async with AsyncSessionLocal() as db:
        view = await team.team_view(db, now=_now())
    row = next(r for r in view["rows"] if r["user_id"] == a)
    assert row["minimum"] == 30
    assert row["required"] == 30


async def test_first_tick_of_the_day_rolls_the_levels(batch_on, clean_state):
    batch_on.setattr(
        autofill.settings, "NEW_COLUMN_AUTOFILL_ENABLED", True, raising=False
    )

    async def _nothing(_db):
        return []

    batch_on.setattr(autofill, "_jobs_without_batch", _nothing)
    batch_on.setattr(autofill, "_jobs_in_work", _nothing)
    a = await _user()
    await _state(levels.previous_business_day(business_today()), {})
    await _rejected(a, 10, _yesterday())
    await autofill._batch_tick(_now())
    assert (await _status(a)).minimum == 20
