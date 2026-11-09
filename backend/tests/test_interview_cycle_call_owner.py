"""Telefon po rozmowie u klienta należy do osoby, która zweryfikowała kandydata.

Zgłoszenie 09.11.2026: rekruterka przypisana do rekrutacji dostawała na ekranie
„Rozmowy u klienta” telefon do kandydata prowadzonego przez kogoś innego,
a osoba, która go zweryfikowała, nie miała zadania jako swojego.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.interview_cycle import (
    EventRef,
    PairSnapshot,
    compute_todos,
    todo_is_mine,
)

NOW = datetime(2031, 6, 10, 12, 0, tzinfo=timezone.utc)
OWNER, VERIFIER, JOB_RECRUITER = 14, 26, 226


def _pair(verifier_id: int | None = VERIFIER) -> PairSnapshot:
    start = NOW - timedelta(minutes=70)
    return PairSnapshot(
        candidate_id=1,
        job_id=2,
        interview=EventRef(
            id=7,
            start=start,
            end=start + timedelta(minutes=60),
            title="R",
            status="completed",
            owner_id=OWNER,
        ),
        latest_stage="client_interview",
        verifier_id=verifier_id,
    )


def _kinds(pair: PairSnapshot, user: int, *, is_dl_view: bool = False) -> dict:
    todos = compute_todos(
        pair,
        NOW,
        call_window_minutes=30,
        user_id=user,
        is_dl_view=is_dl_view,
        acting_for={user},
    )
    return {t["kind"]: t for t in todos}


def test_call_goes_to_the_verifier_not_the_event_owner():
    todo = _kinds(_pair(), VERIFIER)["call_now"]
    assert todo["owner_id"] == VERIFIER
    assert todo_is_mine(todo, {VERIFIER})
    assert not todo_is_mine(todo, {OWNER})


def test_job_recruiter_without_link_to_the_person_gets_no_call():
    assert "call_now" not in _kinds(_pair(), JOB_RECRUITER)


def test_debrief_overdue_follows_the_same_rule():
    pair = _pair()
    late = PairSnapshot(
        **{
            **pair.__dict__,
            "interview": EventRef(
                id=7,
                start=NOW - timedelta(hours=5),
                end=NOW - timedelta(hours=4),
                title="R",
                status="completed",
                owner_id=OWNER,
            ),
        }
    )
    assert _kinds(late, VERIFIER)["debrief_overdue"]["owner_id"] == VERIFIER
    assert "debrief_overdue" not in _kinds(late, JOB_RECRUITER)


def test_without_verifier_call_stays_with_the_event_owner():
    todo = _kinds(_pair(verifier_id=None), OWNER)["call_now"]
    assert todo["owner_id"] == OWNER


def test_event_owner_still_sees_the_call_when_someone_else_verified():
    assert "call_now" in _kinds(_pair(), OWNER)


def test_delivery_lead_view_keeps_every_call_on_screen():
    assert "call_now" in _kinds(_pair(), 999, is_dl_view=True)


# ── Zakres ekranu i dzwonek (Postgres) ──────────────────────────────────────


async def _interview_pair(
    *, job_recruiter: int, owner: int, verifier: int, closed=False
):
    from app.core.database import AsyncSessionLocal
    from app.models.calendar_event import CalendarEvent, EventStatus, EventType
    from app.models.job import Job
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage
    from app.models.recruitment_process import RecruitmentProcess
    from tests.test_prep_meetings_flow import _pair

    job_id, candidate_id = await _pair(recruiter_id=owner, dl_id=owner)
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        (await db.get(Job, job_id)).recruiter_id = job_recruiter
        db.add(
            RecruitmentProcess(
                candidate_id=candidate_id,
                job_id=job_id,
                client_id=(await db.get(Job, job_id)).client_id,
                owner_user_id=owner,
                attempt_no=1,
            )
        )
        db.add(
            CandidateStage(
                job_id=job_id,
                candidate_id=candidate_id,
                stage=PipelineStage.verified,
                moved_by=verifier,
                moved_at=now - timedelta(days=3),
            )
        )
        db.add(
            CandidateStage(
                job_id=job_id,
                candidate_id=candidate_id,
                stage=PipelineStage.rejected
                if closed
                else PipelineStage.client_interview,
                moved_by=owner,
                moved_at=now + timedelta(seconds=1),
            )
        )
        event = CalendarEvent(
            title="Rozmowa",
            event_type=EventType.client_interview,
            status=EventStatus.completed,
            start_time=now - timedelta(minutes=80),
            end_time=now - timedelta(minutes=15),
            candidate_id=candidate_id,
            job_id=job_id,
            created_by=owner,
            operational_owner_id=owner,
        )
        db.add(event)
        await db.commit()
        return job_id, candidate_id, event.id


async def _overview(user_id: int) -> dict:
    from app.core.database import AsyncSessionLocal
    from app.models.user import User
    from app.services.interview_cycle import load_overview

    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)
        return await load_overview(db, user, scope="mine")


async def _people():
    from app.models.user import UserRole
    from tests.test_prep_meetings_flow import _user

    job_rec, _ = await _user(UserRole.recruiter, "Rekruter Przypisany")
    verifier, _ = await _user(UserRole.recruiter, "Rekruter Weryfikujacy")
    owner, _ = await _user(UserRole.delivery_lead, "Lead Wlasciciel")
    return job_rec, verifier, owner


async def test_job_recruiter_does_not_get_someone_elses_pair_on_screen():
    job_rec, verifier, owner = await _people()
    job_id, candidate_id, _ = await _interview_pair(
        job_recruiter=job_rec, owner=owner, verifier=verifier
    )
    theirs = await _overview(job_rec)
    assert all(i["candidate_id"] != candidate_id for i in theirs["items"])

    mine = await _overview(verifier)
    todo = next(t for t in mine["todos"] if t["candidate_id"] == candidate_id)
    assert todo["kind"] == "call_now" and todo["mine"] is True
    assert todo["job_id"] == job_id


async def _pings(user_id: int) -> int:
    from sqlalchemy import func, select

    from app.core.database import AsyncSessionLocal
    from app.models.notification import Notification, NotificationType

    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(func.count()).where(
                Notification.user_id == user_id,
                Notification.notification_type == NotificationType.post_interview_t15,
            )
        )


async def _run_t15() -> None:
    from app.core.database import AsyncSessionLocal
    from app.services.notification_triggers import check_post_interview_t15

    async with AsyncSessionLocal() as db:
        await check_post_interview_t15(db, datetime.now(timezone.utc))
        await db.commit()


async def test_phone_reminder_goes_to_the_verifier():
    job_rec, verifier, owner = await _people()
    await _interview_pair(job_recruiter=job_rec, owner=owner, verifier=verifier)
    await _run_t15()
    assert await _pings(verifier) == 1
    assert await _pings(owner) == 0


async def test_closed_card_gets_no_phone_reminder():
    job_rec, verifier, owner = await _people()
    await _interview_pair(
        job_recruiter=job_rec, owner=owner, verifier=verifier, closed=True
    )
    await _run_t15()
    assert await _pings(verifier) == 0 and await _pings(owner) == 0
