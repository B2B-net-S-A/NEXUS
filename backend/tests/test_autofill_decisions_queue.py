"""Kolejka decyzji o osobach od systemu i poranny dzwonek (23.10.2026).

Kontrakty:

- do „Czeka na Ciebie” trafia osoba od systemu z „Nowych” po 2 dniach
  roboczych bez decyzji — nie osoba po „Dzwonię”, nie osoba od człowieka,
  nie osoba w rekrutacji bez rekrutera;
- Rekruter dostaje jeden dzwonek dziennie z liczbą osób i rekrutacjami,
  drugi tick tego dnia nic nie wysyła.

Baza testowa jest wspólna: asercje dotyczą własnych rekrutacji i odbiorców.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select, text

import app.models  # noqa: F401
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.scheduling import is_business_day
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.job_autofill_pool import JobAutofillPool
from app.models.notification import Notification, NotificationType
from app.models.recruitment_process import RecruitmentProcess
from app.models.user import User, UserRole
from app.services import autofill_decisions as decisions
from app.services import autofill_decisions_bell as bell
from app.services import board_flow
from app.services import new_column_autofill as autofill


def _workday_morning(days_ahead: int) -> datetime:
    """Dzień roboczy co najmniej ``days_ahead`` dni od dziś, 9:00 w Warszawie."""
    zone = ZoneInfo(settings.BUSINESS_TZ)
    day = datetime.now(zone).date() + timedelta(days=days_ahead)
    while not is_business_day(datetime.combine(day, time(12), tzinfo=zone)):
        day += timedelta(days=1)
    return datetime.combine(day, time(9, 1), tzinfo=zone)


async def _recruiter() -> User:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"adq-{tag}@example.com",
            password_hash=hash_password(f"T3st_{tag}!Q"),
            name=f"ADQ {tag}",
            role=UserRole.recruiter,
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


async def _job_with_people(recruiter_id: int | None, people: int) -> dict:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"ADQ client {tag}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"ADQ job {tag}",
            client_id=client.id,
            status=JobStatus.published,
            work_state="searching",
            recruiter_id=recruiter_id,
        )
        candidates = [
            Candidate(name="Kolejka", lastname=f"{i}-{tag}") for i in range(people)
        ]
        db.add_all([job, *candidates])
        await db.flush()
        db.add_all(
            [
                JobAutofillPool(
                    job_id=job.id,
                    candidate_id=c.id,
                    score=Decimal(str(90 - i)),
                    run_id="run-adq",
                    evidence={"matched_must": [], "missing_must": []},
                )
                for i, c in enumerate(candidates)
            ]
        )
        await db.commit()
        return {"job_id": job.id, "ids": [c.id for c in candidates]}


async def _fill(job_id: int, target: int, monkeypatch) -> list[int]:
    monkeypatch.setattr(autofill, "TARGET", target)
    async with AsyncSessionLocal() as db:
        added = await autofill.fill_job(db, job_id, now=datetime.now(timezone.utc))
        await db.commit()
        return added


async def test_only_undecided_system_people_with_a_recruiter_are_due(monkeypatch):
    recruiter = await _recruiter()
    world = await _job_with_people(recruiter.id, 2)
    waiting, called = world["ids"]
    assert await _fill(world["job_id"], 2, monkeypatch) == [waiting, called]
    async with AsyncSessionLocal() as db:
        process = await db.scalar(
            select(RecruitmentProcess).where(
                RecruitmentProcess.job_id == world["job_id"],
                RecruitmentProcess.candidate_id == called,
            )
        )
        decisions.record_call(process, recruiter.id, datetime.now(timezone.utc))
        await db.commit()
    orphan = await _job_with_people(None, 1)
    await _fill(orphan["job_id"], 1, monkeypatch)

    later = _workday_morning(7)
    async with AsyncSessionLocal() as db:
        due = await decisions.due_decisions(
            db, [world["job_id"], orphan["job_id"]], later
        )
        # Dziś nikt jeszcze nie czeka 2 dni.
        assert (
            await decisions.due_decisions(
                db, [world["job_id"]], datetime.now(timezone.utc)
            )
            == []
        )
    assert [(d.job_id, d.candidate_id) for d in due] == [(world["job_id"], waiting)]
    assert due[0].score == 90 and due[0].waiting_days >= decisions.DECISION_DAYS

    async with AsyncSessionLocal() as db:
        block = await board_flow.load_flow(db, recruiter, now=later)
    rows = [r for r in block.autofill_decisions if r.job_id == world["job_id"]]
    assert [r.candidate_id for r in rows] == [waiting]
    assert rows[0].candidate_name.startswith("Kolejka")


async def test_morning_bell_goes_once_a_day_to_the_recruiter(monkeypatch):
    recruiter = await _recruiter()
    world = await _job_with_people(recruiter.id, 3)
    await _fill(world["job_id"], 3, monkeypatch)
    later = _workday_morning(7)
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("DELETE FROM app_settings WHERE key = :k"), {"k": bell.STATE_KEY}
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        assert await bell.send_decision_bells(db, later) >= 1
        await db.commit()
        assert await bell.send_decision_bells(db, later) == 0
    async with AsyncSessionLocal() as db:
        [note] = (
            await db.scalars(
                select(Notification).where(Notification.user_id == recruiter.id)
            )
        ).all()
    assert note.notification_type == NotificationType.autofill_decisions_due
    assert note.title == "3 osoby od systemu czekają na Twoją decyzję"
    assert "(3)" in note.message and "„Dzwonię”" in note.message
    assert note.link == bell.LINK


def test_bell_texts():
    assert bell.bell_title(1) == "1 osoba od systemu czeka na Twoją decyzję"
    assert bell.bell_title(12) == "12 osób od systemu czeka na Twoją decyzję"
    message = bell.bell_message([("A", 3), ("B", 2), ("C", 1), ("D", 1), ("E", 1)])
    assert message.startswith("A (3), B (2), C (1) i 2 inne rekrutacje.")
    assert bell.bell_message([("A", 1)]).startswith("A (1). Zadzwoń")


async def test_no_bell_outside_working_hours():
    zone = ZoneInfo(settings.BUSINESS_TZ)
    evening = datetime.combine(_workday_morning(1).date(), time(18), tzinfo=zone)
    async with AsyncSessionLocal() as db:
        assert await bell.send_decision_bells(db, evening) == 0
