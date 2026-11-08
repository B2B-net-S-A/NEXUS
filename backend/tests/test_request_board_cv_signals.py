"""Daily: „Bez CV od N dni rob.” (B4) i nowe profile z 7 dni (B6), audyt 08.11.2026.

Czyste reguły dni roboczych i treści dzwonka oraz definicje z bazą: kiedy P1
dostaje pigułkę i dzwonek, a kiedy nie, i co jest „nowym profilem”.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today, local_day_start_utc
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.candidate_source_event import CandidateSourceEvent, SourceChannel
from app.models.client import Client
from app.models.job import Job, JobPriority, JobStatus, RemotePolicy
from app.models.notification import Notification, NotificationType
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services import job_idle
from app.services.job_idle import (
    P1_NO_CV_STAGE,
    _Line,
    business_days_without_cv,
    is_p1_searching,
    p1_notice_text,
)
from app.services.new_profiles import new_profiles_by_job, window_start

# Piątek 06.11.2026, 12:00 czasu polskiego.
FRIDAY = datetime(2026, 11, 6, 11, 0, tzinfo=timezone.utc)


def _utc(day: int, month: int = 11) -> datetime:
    return datetime(2026, month, day, 11, 0, tzinfo=timezone.utc)


def test_counts_working_days_after_the_last_cv() -> None:
    # 30.10 (pt) → 06.11 (pt): pn, wt, śr, czw, pt = 5.
    assert business_days_without_cv((_utc(30, 10), None), FRIDAY) == 5
    assert business_days_without_cv((_utc(2), None), FRIDAY) == 4


def test_public_holiday_is_not_a_working_day() -> None:
    # 11.11 (śr) to święto: 10.11 (wt) → 13.11 (pt) to czw i pt.
    assert business_days_without_cv((_utc(10), None), _utc(13)) == 2


def test_later_of_cv_and_opening_starts_the_count() -> None:
    assert business_days_without_cv((_utc(30, 10), _utc(5)), FRIDAY) == 1


def test_no_known_moment_means_no_count() -> None:
    assert business_days_without_cv((None, None), FRIDAY) == 0


def test_only_p1_still_searching_counts() -> None:
    assert is_p1_searching(JobPriority.high, "searching", None) is True
    assert is_p1_searching(JobPriority.medium, "searching", None) is False
    assert is_p1_searching(JobPriority.urgent, "client_silent", None) is False
    assert is_p1_searching(JobPriority.urgent, "searching", FRIDAY) is False


def test_notice_lists_longest_silence_first_and_links_the_daily() -> None:
    lines = [
        _Line(1, "Java", "Bank", 2, 5, "ostatnie CV 30.10"),
        _Line(2, "QA", None, 2, 9, "bez CV od otwarcia"),
    ]
    title, message, link = p1_notice_text(lines)
    assert title == "P1 bez CV: 2 rekrutacje"
    assert message.index("QA") < message.index("Java")
    assert "NEXUS niczego nie zamknie" in message
    assert link == "/jobs/daily"
    assert p1_notice_text(lines[:1])[2] == "/jobs/1"


async def _job(**kw) -> int:
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Sygnały {uuid.uuid4().hex[:8]}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"Sygnał {uuid.uuid4().hex[:6]}",
            description="x",
            status=JobStatus.published,
            work_state="searching",
            client_id=client.id,
            remote_policy=RemotePolicy.remote,
            priority=JobPriority.high,
            **kw,
        )
        db.add(job)
        await db.commit()
        return job.id


async def _user(role: UserRole = UserRole.delivery_lead) -> int:
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"sygnal-{unique}@example.com",
            name=f"Sygnał {unique}",
            password_hash="x",
            role=role,
            roles=[role.value],
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        return user.id


async def _candidate(created_at: datetime, **kw) -> int:
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name="Profil",
            lastname=uuid.uuid4().hex[:8],
            email=f"profil-{unique}@example.com",
            created_at=created_at,
            **kw,
        )
        db.add(candidate)
        await db.commit()
        return candidate.id


async def _stage(
    candidate_id: int,
    job_id: int,
    stage: PipelineStage,
    at: datetime,
    moved_by: int | None,
) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(
                candidate_id=candidate_id,
                job_id=job_id,
                stage=stage,
                moved_at=at,
                moved_by=moved_by,
            )
        )
        await db.commit()


async def _sweep(job_id: int, now: datetime) -> dict[str, int]:
    async with AsyncSessionLocal() as db:
        counts = await job_idle.run_idle_sweep(
            db, effects=None, now=now, only_job_ids=[job_id]
        )
        await db.commit()
    return counts


async def _bells(user_id: int) -> list[Notification]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(Notification).where(
                        Notification.user_id == user_id,
                        Notification.notification_type
                        == NotificationType.request_review_needed,
                    )
                )
            ).all()
        )


@pytest.mark.asyncio
async def test_p1_without_cv_rings_the_lead_once_and_closes_nothing() -> None:
    lead = await _user()
    now = datetime.now(timezone.utc)
    job_id = await _job(delivery_lead_id=lead, opened_at=now - timedelta(days=30))
    candidate = await _candidate(now - timedelta(days=30))
    # 11 dni kalendarzowych, więc na pewno ≥ 5 dni roboczych w każdym miesiącu.
    await _stage(
        candidate, job_id, PipelineStage.cv_sent, now - timedelta(days=11), lead
    )

    counts = await _sweep(job_id, now)

    assert counts[P1_NO_CV_STAGE] == 1
    assert counts["closed"] == 0
    bells = await _bells(lead)
    assert len(bells) == 1
    assert bells[0].related_entity_type == "job"
    assert "NEXUS niczego nie zamknie" in bells[0].message
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        assert job.status == JobStatus.published
    # Ten sam cykl ciszy nie dzwoni drugi raz, także następnego dnia.
    again = await _sweep(job_id, now + timedelta(days=1))
    assert again[P1_NO_CV_STAGE] == 0


@pytest.mark.asyncio
async def test_new_cv_starts_a_new_silence_cycle() -> None:
    lead = await _user()
    now = datetime.now(timezone.utc)
    job_id = await _job(delivery_lead_id=lead, opened_at=now - timedelta(days=60))
    candidate = await _candidate(now - timedelta(days=60))
    await _stage(
        candidate, job_id, PipelineStage.cv_sent, now - timedelta(days=30), lead
    )
    assert (await _sweep(job_id, now - timedelta(days=20)))[P1_NO_CV_STAGE] == 1

    await _stage(
        candidate, job_id, PipelineStage.cv_sent, now - timedelta(days=11), lead
    )

    assert (await _sweep(job_id, now))[P1_NO_CV_STAGE] == 1
    async with AsyncSessionLocal() as db:
        markers = (
            await db.scalars(
                select(Activity).where(
                    Activity.entity_type == "job",
                    Activity.entity_id == job_id,
                    Activity.action == job_idle.MARKER_ACTION,
                )
            )
        ).all()
    assert len([m for m in markers if m.details["stage"] == P1_NO_CV_STAGE]) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [{"priority": JobPriority.medium}, {"champion_found_at": "now"}],
    ids=["p2", "champion"],
)
async def test_no_bell_outside_p1_searching(changes: dict) -> None:
    lead = await _user()
    now = datetime.now(timezone.utc)
    job_id = await _job(delivery_lead_id=lead, opened_at=now - timedelta(days=30))
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        for field, value in changes.items():
            setattr(job, field, now if value == "now" else value)
        await db.commit()

    assert (await _sweep(job_id, now))[P1_NO_CV_STAGE] == 0
    assert await _bells(lead) == []


@pytest.mark.asyncio
async def test_still_going_postpones_the_bell() -> None:
    lead = await _user()
    now = datetime.now(timezone.utc)
    job_id = await _job(
        delivery_lead_id=lead,
        opened_at=now - timedelta(days=30),
        idle_snoozed_at=now - timedelta(hours=1),
    )

    assert (await _sweep(job_id, now))[P1_NO_CV_STAGE] == 0


# ── Definicja „nowego profilu” ───────────────────────────────────────────────


def test_window_is_today_and_six_days_before() -> None:
    today = business_today()
    assert window_start(today) == local_day_start_utc(today - timedelta(days=6))


async def _counts(job_id: int) -> tuple[int, int]:
    async with AsyncSessionLocal() as db:
        found = await new_profiles_by_job(db, [job_id])
    entry = found.get(job_id)
    return (entry.added, entry.reached_cv) if entry else (0, 0)


@pytest.mark.asyncio
async def test_new_profile_added_by_a_person_counts_and_reaches_cv() -> None:
    adder = await _user(UserRole.recruiter)
    job_id = await _job()
    now = datetime.now(timezone.utc)
    fresh = await _candidate(now - timedelta(hours=5))
    await _stage(fresh, job_id, PipelineStage.new, now - timedelta(hours=4), adder)
    await _stage(fresh, job_id, PipelineStage.cv_sent, now - timedelta(hours=1), adder)
    no_cv = await _candidate(now - timedelta(hours=5))
    await _stage(no_cv, job_id, PipelineStage.new, now - timedelta(hours=4), adder)

    assert await _counts(job_id) == (2, 1)


@pytest.mark.asyncio
async def test_old_profile_from_the_base_is_not_new() -> None:
    adder = await _user(UserRole.recruiter)
    job_id = await _job()
    now = datetime.now(timezone.utc)
    old = await _candidate(now - timedelta(days=30))
    await _stage(old, job_id, PipelineStage.new, now - timedelta(hours=4), adder)

    assert await _counts(job_id) == (0, 0)


@pytest.mark.asyncio
async def test_system_card_is_not_a_new_profile() -> None:
    job_id = await _job()
    now = datetime.now(timezone.utc)
    fresh = await _candidate(now - timedelta(hours=5))
    await _stage(fresh, job_id, PipelineStage.new, now - timedelta(hours=4), None)

    assert await _counts(job_id) == (0, 0)


@pytest.mark.asyncio
async def test_card_older_than_the_window_is_not_counted() -> None:
    adder = await _user(UserRole.recruiter)
    job_id = await _job()
    now = datetime.now(timezone.utc)
    fresh = await _candidate(now - timedelta(days=9))
    await _stage(fresh, job_id, PipelineStage.new, now - timedelta(days=8), adder)
    # Późniejszy ruch nie odmładza karty: liczy się pierwsze dodanie.
    await _stage(fresh, job_id, PipelineStage.cv_sent, now - timedelta(hours=1), adder)

    assert await _counts(job_id) == (0, 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["pracuj", "jjit", "referral"])
async def test_portal_and_referral_sources_are_not_new_profiles(source: str) -> None:
    adder = await _user(UserRole.recruiter)
    job_id = await _job()
    now = datetime.now(timezone.utc)
    candidate = await _candidate(now - timedelta(hours=5), source=source)
    await _stage(candidate, job_id, PipelineStage.new, now - timedelta(hours=4), adder)

    assert await _counts(job_id) == (0, 0)


@pytest.mark.asyncio
async def test_card_from_a_job_posting_is_not_a_new_profile() -> None:
    adder = await _user(UserRole.recruiter)
    job_id = await _job()
    now = datetime.now(timezone.utc)
    candidate = await _candidate(now - timedelta(hours=5))
    await _stage(
        candidate, job_id, PipelineStage.posting, now - timedelta(hours=4), adder
    )

    assert await _counts(job_id) == (0, 0)


@pytest.mark.asyncio
async def test_referral_event_excludes_the_profile() -> None:
    adder = await _user(UserRole.recruiter)
    job_id = await _job()
    now = datetime.now(timezone.utc)
    candidate = await _candidate(now - timedelta(hours=5))
    await _stage(candidate, job_id, PipelineStage.new, now - timedelta(hours=4), adder)
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateSourceEvent(
                candidate_id=candidate,
                channel=SourceChannel.referral,
                captured_at=now - timedelta(days=200),
            )
        )
        await db.commit()

    assert await _counts(job_id) == (0, 0)
