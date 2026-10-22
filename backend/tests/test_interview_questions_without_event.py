"""Pytania z rozmowy u klienta bez terminu w kalendarzu NEXUSA (20.10.2026).

Na produkcji w 30 dniach 88 z 99 par weszło w „Rozmowę z klientem” bez
wydarzenia ``client_interview``, więc nie dostawały telefonu po rozmowie,
„Uzupełnij debrief” ani bramki przed „Umową” — pytania klienta lądowały
w notatkach. Te testy pilnują:

* zadania ``questions_missing`` (po dobie w etapie, bez rozmowy i bez otwartego
  wniosku o terminy) i jego adresata;
* daty z „Kiedy była rozmowa?” / „Kiedy rozmowa?”;
* bramki przed „Umową” dla pary z etapem rozmowy, ale bez wydarzenia
  (``event_id = None``, ``needs_interview_date``) i jej wyłącznika;
* ``POST /api/interview-cycle/client-interviews`` (termin z okna przesunięcia);
* ``PUT /api/interview-cycle/pairs/{c}/{j}/debrief`` (zakłada odbytą rozmowę
  albo zapisuje pod bieżącą rundą).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import func, select

import app.models  # noqa: F401
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token, hash_password
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.interview_feedback import FeedbackSource, InterviewFeedback
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services.client_interview_entry import (
    held_interview_start,
    validate_planned_start,
)
from app.services.debrief_gate import QUESTIONS_REQUIRED_MESSAGE, missing_debrief
from app.services.interview_cycle import (
    EventRef,
    PairSnapshot,
    SlotRef,
    compute_todos,
    todo_is_mine,
)

NOW = datetime(2031, 6, 10, 12, 0, tzinfo=timezone.utc)
WARSAW = ZoneInfo("Europe/Warsaw")


# ── Czyste reguły ───────────────────────────────────────────────────────────


def _pair(**kw) -> PairSnapshot:
    base = dict(
        latest_stage=PipelineStage.client_interview.value,
        latest_stage_at=NOW - timedelta(hours=25),
        recruiter_id=11,
    )
    base.update(kw)
    return PairSnapshot(1, 2, **base)


def _todos(pair: PairSnapshot, *, user_id: int = 11) -> list[dict]:
    return compute_todos(
        pair, NOW, call_window_minutes=30, user_id=user_id, is_dl_view=False
    )


def _kinds(pair: PairSnapshot) -> list[str]:
    return [t["kind"] for t in _todos(pair)]


def test_questions_missing_after_a_day_in_stage_without_interview():
    todos = [t for t in _todos(_pair()) if t["kind"] == "questions_missing"]
    assert len(todos) == 1
    assert todos[0]["owner_id"] == 11
    assert todos[0]["due"] == NOW - timedelta(hours=1)


def test_questions_missing_waits_a_full_day():
    assert "questions_missing" not in _kinds(
        _pair(latest_stage_at=NOW - timedelta(hours=23, minutes=59))
    )
    assert "questions_missing" in _kinds(
        _pair(latest_stage_at=NOW - timedelta(hours=24))
    )


def test_questions_missing_only_in_client_interview_stage():
    assert "questions_missing" not in _kinds(
        _pair(latest_stage=PipelineStage.cv_sent.value)
    )
    assert "questions_missing" not in _kinds(_pair(latest_stage_at=None))


def test_interview_in_calendar_keeps_the_old_reminders():
    # Para z rozmową w kalendarzu ma telefon i „Debrief zaległy” — nie dubel.
    past = EventRef(
        id=7,
        start=NOW - timedelta(hours=5),
        end=NOW - timedelta(hours=4),
        title="R",
        status="completed",
    )
    kinds = _kinds(_pair(interview=past))
    assert "questions_missing" not in kinds
    assert "debrief_overdue" in kinds


def test_open_slot_request_means_no_interview_yet():
    def req(status: str) -> SlotRef:
        return SlotRef(
            id=3,
            status=status,
            slots=(),
            chosen_index=None,
            respond_by=None,
            recruiter_id=11,
            created_by=22,
            duration_minutes=60,
            note=None,
            event_id=None,
        )

    assert "questions_missing" not in _kinds(
        _pair(slot_request=req("awaiting_recruiter"))
    )
    assert "questions_missing" not in _kinds(_pair(slot_request=req("awaiting_dl")))
    assert "questions_missing" in _kinds(_pair(slot_request=req("cancelled")))


def test_questions_missing_belongs_to_recruiter_else_delivery_lead():
    todo = {"kind": "questions_missing", "owner_id": 11}
    assert todo_is_mine(todo, [11], delivery_lead_id=99)
    assert not todo_is_mine(todo, [99], delivery_lead_id=99)
    orphan = {"kind": "questions_missing", "owner_id": None}
    assert todo_is_mine(orphan, [99], delivery_lead_id=99)
    assert not todo_is_mine(orphan, [11], delivery_lead_id=99)


def test_held_start_defaults_to_nine_business_time():
    now = datetime(2031, 6, 10, 14, 0, tzinfo=WARSAW)
    start = held_interview_start(date(2031, 6, 9), None, now=now)
    assert start == datetime(2031, 6, 9, 9, 0, tzinfo=WARSAW)
    assert start.tzinfo == timezone.utc


def test_held_start_today_before_nine_is_just_now():
    now = datetime(2031, 6, 10, 8, 0, tzinfo=WARSAW)
    start = held_interview_start(date(2031, 6, 10), None, now=now)
    assert start == now - timedelta(minutes=1)


def test_held_start_with_time():
    now = datetime(2031, 6, 10, 18, 0, tzinfo=WARSAW)
    start = held_interview_start(date(2031, 6, 10), time(15, 30), now=now)
    assert start == datetime(2031, 6, 10, 15, 30, tzinfo=WARSAW)


@pytest.mark.parametrize(
    "held_on,held_at",
    [(date(2031, 6, 11), None), (date(2031, 6, 10), time(16, 0))],
)
def test_held_start_refuses_the_future(held_on, held_at):
    now = datetime(2031, 6, 10, 14, 0, tzinfo=WARSAW)
    with pytest.raises(HTTPException) as err:
        held_interview_start(held_on, held_at, now=now)
    assert err.value.status_code == 422


def test_planned_start_window():
    assert validate_planned_start(NOW - timedelta(days=3), now=NOW) == NOW - timedelta(
        days=3
    )
    for bad in (NOW - timedelta(days=31), NOW + timedelta(days=121)):
        with pytest.raises(HTTPException) as err:
            validate_planned_start(bad, now=NOW)
        assert err.value.status_code == 422


# ── Z bazą ──────────────────────────────────────────────────────────────────


async def _user(role: UserRole) -> tuple[int, dict[str, str]]:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"qmiss-{role.value}-{tag}@example.com",
            password_hash=hash_password(f"Qm1ss_{tag}!pw"),
            name=f"Qmiss {role.value} {tag}",
            role=role,
            roles=[role.value],
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        uid = user.id
    token = create_access_token(uid, role.value, roles=[role.value])
    return uid, {"Authorization": f"Bearer {token}"}


async def _stage_pair(
    *, recruiter_id: int | None = None, stage: PipelineStage | None = None
) -> tuple[int, int, int]:
    from app.models.candidate import Candidate, CandidateStatus
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    tag = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"QmissClient-{tag}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"QmissJob-{tag}",
            status=JobStatus.published,
            client_id=client.id,
            recruiter_id=recruiter_id,
        )
        cand = Candidate(
            name="Ola",
            lastname=f"Pytania-{tag}",
            email=f"qmiss-cand-{tag}@example.com",
            status=CandidateStatus.active,
        )
        db.add_all([job, cand])
        await db.flush()
        db.add(
            CandidateStage(
                candidate_id=cand.id,
                job_id=job.id,
                stage=stage or PipelineStage.client_interview,
                moved_by=recruiter_id,
                moved_at=datetime.now(timezone.utc) - timedelta(days=2),
            )
        )
        await db.commit()
        return job.id, cand.id, client.id


async def _interview_count(cand_id: int, job_id: int) -> int:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(func.count(CalendarEvent.id)).where(
                CalendarEvent.candidate_id == cand_id,
                CalendarEvent.job_id == job_id,
                CalendarEvent.event_type == EventType.client_interview,
            )
        )


async def _gate(cand_id: int, job_id: int):
    async with AsyncSessionLocal() as db:
        return await missing_debrief(db, candidate_id=cand_id, job_id=job_id)


async def test_gate_without_event_asks_for_questions():
    job_id, cand_id, _ = await _stage_pair()
    detail = await _gate(cand_id, job_id)
    assert detail is not None
    assert detail["code"] == "DEBRIEF_REQUIRED"
    assert detail["event_id"] is None
    assert detail["needs_interview_date"] is True
    assert detail["interview_pending"] is False
    assert detail["message"] == QUESTIONS_REQUIRED_MESSAGE


async def test_gate_without_event_has_a_switch(monkeypatch):
    job_id, cand_id, _ = await _stage_pair()
    monkeypatch.setattr(settings, "DEBRIEF_GATE_WITHOUT_EVENT", False)
    assert await _gate(cand_id, job_id) is None


async def test_gate_ignores_pairs_that_never_met_the_client():
    job_id, cand_id, _ = await _stage_pair(stage=PipelineStage.cv_sent)
    assert await _gate(cand_id, job_id) is None


async def test_create_client_interview_from_move(app_client: AsyncClient):
    rec_id, rec_h = await _user(UserRole.recruiter)
    job_id, cand_id, client_id = await _stage_pair(recruiter_id=rec_id)
    start = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=2)
    res = await app_client.post(
        "/api/interview-cycle/client-interviews",
        headers=rec_h,
        json={"candidate_id": cand_id, "job_id": job_id, "start": start.isoformat()},
    )
    assert res.status_code == 200, res.text
    event_id = res.json()["event_id"]
    async with AsyncSessionLocal() as db:
        ev = await db.get(CalendarEvent, event_id)
        assert ev.event_type == EventType.client_interview
        assert ev.status == EventStatus.scheduled
        assert ev.operational_owner_id == rec_id
        assert ev.client_id == client_id
        assert ev.end_time - ev.start_time == timedelta(minutes=60)
    # Rozmowa zaplanowana — bramka czeka na nią, a nie na datę.
    detail = await _gate(cand_id, job_id)
    assert detail["event_id"] == event_id
    assert detail["interview_pending"] is True

    again = await app_client.post(
        "/api/interview-cycle/client-interviews",
        headers=rec_h,
        json={"candidate_id": cand_id, "job_id": job_id, "start": start.isoformat()},
    )
    assert again.status_code == 409, again.text
    assert "ma już zaplanowaną rozmowę" in again.text
    assert await _interview_count(cand_id, job_id) == 1


async def test_create_client_interview_needs_the_pair_in_pipeline(
    app_client: AsyncClient,
):
    rec_id, rec_h = await _user(UserRole.recruiter)
    job_id, _cand, _ = await _stage_pair(recruiter_id=rec_id)
    _job2, other_cand, _ = await _stage_pair(recruiter_id=rec_id)
    res = await app_client.post(
        "/api/interview-cycle/client-interviews",
        headers=rec_h,
        json={
            "candidate_id": other_cand,
            "job_id": job_id,
            "start": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        },
    )
    assert res.status_code == 404, res.text


async def test_pair_debrief_creates_held_interview_and_opens_gate(
    app_client: AsyncClient,
):
    rec_id, rec_h = await _user(UserRole.recruiter)
    job_id, cand_id, _ = await _stage_pair(recruiter_id=rec_id)
    url = f"/api/interview-cycle/pairs/{cand_id}/{job_id}/debrief"
    body = {
        "outcome": "good",
        "offer_acceptance": "likely",
        "questions": ["Czym różni się Spring Boot 2 od 3?", "Jak testujesz Kafkę?"],
    }

    no_date = await app_client.put(url, headers=rec_h, json=body)
    assert no_date.status_code == 422, no_date.text
    assert "kiedy była rozmowa" in no_date.text
    assert await _interview_count(cand_id, job_id) == 0

    yesterday = (datetime.now(WARSAW) - timedelta(days=1)).date().isoformat()
    saved = await app_client.put(
        url, headers=rec_h, json={**body, "held_on": yesterday, "held_at": "14:00"}
    )
    assert saved.status_code == 200, saved.text
    out = saved.json()
    assert out["questions"] == body["questions"]
    assert out["questions_saved"] == 2
    assert await _interview_count(cand_id, job_id) == 1
    async with AsyncSessionLocal() as db:
        ev = await db.get(CalendarEvent, out["calendar_event_id"])
        assert ev.status == EventStatus.completed
        assert ev.start_time.astimezone(WARSAW).time() == time(14, 0)
        assert ev.operational_owner_id == rec_id
    assert await _gate(cand_id, job_id) is None

    # Drugi zapis pytań bez rozmowy z tego samego dnia nie zakłada drugiej
    # rozmowy i NIE nadpisuje jej debriefu: 409 z rozmową, którą okno otwiera
    # do poprawy (decyzja Artura 22.10.2026, audyt F27). Dotąd zapis z okna
    # startującego od pustego formularza zastępował pytania, ocenę i ofertę.
    again = await app_client.put(
        url,
        headers=rec_h,
        json={
            **body,
            "outcome": "medium",
            "offer_acceptance": "unknown",
            "questions": ["Jak testujesz Kafkę?"],
            "held_on": yesterday,
        },
    )
    assert again.status_code == 409, again.text
    detail = again.json()["detail"]
    assert detail["code"] == "DEBRIEF_EXISTS"
    assert detail["event_id"] == out["calendar_event_id"]
    assert "ma już zapisany debrief" in detail["message"]
    assert await _interview_count(cand_id, job_id) == 1
    kept = await app_client.get(
        f"/api/interview-cycle/events/{out['calendar_event_id']}/debrief",
        headers=rec_h,
    )
    assert kept.status_code == 200, kept.text
    assert kept.json()["questions"] == body["questions"]
    assert kept.json()["outcome"] == "good"
    assert kept.json()["offer_acceptance"] == "likely"


async def test_pair_debrief_uses_the_held_interview_without_debrief(
    app_client: AsyncClient,
):
    rec_id, rec_h = await _user(UserRole.recruiter)
    job_id, cand_id, client_id = await _stage_pair(recruiter_id=rec_id)
    async with AsyncSessionLocal() as db:
        ev = CalendarEvent(
            title="Rozmowa u klienta",
            event_type=EventType.client_interview,
            start_time=datetime.now(timezone.utc) - timedelta(hours=3),
            end_time=datetime.now(timezone.utc) - timedelta(hours=2),
            status=EventStatus.completed,
            created_by=rec_id,
            operational_owner_id=rec_id,
            candidate_id=cand_id,
            job_id=job_id,
            client_id=client_id,
            attendees=[],
        )
        db.add(ev)
        await db.commit()
        event_id = ev.id
    res = await app_client.put(
        f"/api/interview-cycle/pairs/{cand_id}/{job_id}/debrief",
        headers=rec_h,
        json={
            "outcome": "medium",
            "offer_acceptance": "unknown",
            "no_client_questions": True,
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["calendar_event_id"] == event_id
    assert await _interview_count(cand_id, job_id) == 1
    async with AsyncSessionLocal() as db:
        fb = await db.scalar(
            select(InterviewFeedback).where(
                InterviewFeedback.calendar_event_id == event_id,
                InterviewFeedback.feedback_source == FeedbackSource.candidate_side,
            )
        )
        assert fb.no_client_questions is True


async def test_pair_debrief_refuses_before_the_planned_interview(
    app_client: AsyncClient,
):
    rec_id, rec_h = await _user(UserRole.recruiter)
    job_id, cand_id, _ = await _stage_pair(recruiter_id=rec_id)
    planned = await app_client.post(
        "/api/interview-cycle/client-interviews",
        headers=rec_h,
        json={
            "candidate_id": cand_id,
            "job_id": job_id,
            "start": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        },
    )
    assert planned.status_code == 200, planned.text
    res = await app_client.put(
        f"/api/interview-cycle/pairs/{cand_id}/{job_id}/debrief",
        headers=rec_h,
        json={
            "outcome": "good",
            "offer_acceptance": "yes",
            "questions": ["Pytanie"],
            "held_on": datetime.now(WARSAW).date().isoformat(),
        },
    )
    assert res.status_code == 422, res.text
    assert "jeszcze się nie odbyła" in res.text
    assert await _interview_count(cand_id, job_id) == 1


async def test_pair_debrief_needs_the_pair_in_pipeline(app_client: AsyncClient):
    # Rekrutacje widzą i prowadzą wszystkie role wewnętrzne (23.09.2026),
    # więc granicą jest para w procesie tej rekrutacji, nie zespół.
    rec_id, rec_h = await _user(UserRole.recruiter)
    job_id, _cand, _ = await _stage_pair(recruiter_id=rec_id)
    _job2, other_cand, _ = await _stage_pair(recruiter_id=rec_id)
    res = await app_client.put(
        f"/api/interview-cycle/pairs/{other_cand}/{job_id}/debrief",
        headers=rec_h,
        json={
            "outcome": "good",
            "offer_acceptance": "yes",
            "questions": ["Pytanie"],
            "held_on": datetime.now(WARSAW).date().isoformat(),
        },
    )
    assert res.status_code == 404, res.text
    assert await _interview_count(other_cand, job_id) == 0


async def test_overview_shows_questions_missing_to_the_recruiter(
    app_client: AsyncClient,
):
    rec_id, rec_h = await _user(UserRole.recruiter)
    job_id, cand_id, _ = await _stage_pair(recruiter_id=rec_id)
    res = await app_client.get(
        "/api/interview-cycle", headers=rec_h, params={"scope": "mine"}
    )
    assert res.status_code == 200, res.text
    todos = [
        t
        for t in res.json()["todos"]
        if t["candidate_id"] == cand_id and t["job_id"] == job_id
    ]
    assert [t["kind"] for t in todos] == ["questions_missing"]
    assert todos[0]["mine"] is True


async def test_verifier_sees_questions_missing_moved_by_someone_else(
    app_client: AsyncClient,
):
    # Na produkcji 20.10.2026 5 z 24 zadań nie widział nikt: rekruterem pary był
    # pierwszy weryfikator, a na „Rozmowę u klienta” przesunął kto inny.
    rec_id, rec_h = await _user(UserRole.recruiter)
    dl_id, _ = await _user(UserRole.delivery_lead)
    job_id, cand_id, _ = await _stage_pair(recruiter_id=None)
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(
                candidate_id=cand_id,
                job_id=job_id,
                stage=PipelineStage.verified,
                moved_by=rec_id,
                moved_at=datetime.now(timezone.utc) - timedelta(days=5),
            )
        )
        stage = await db.scalar(
            select(CandidateStage).where(
                CandidateStage.candidate_id == cand_id,
                CandidateStage.stage == PipelineStage.client_interview,
            )
        )
        stage.moved_by = dl_id
        await db.commit()
    res = await app_client.get(
        "/api/interview-cycle", headers=rec_h, params={"scope": "mine"}
    )
    assert res.status_code == 200, res.text
    todos = [
        t
        for t in res.json()["todos"]
        if t["candidate_id"] == cand_id and t["kind"] == "questions_missing"
    ]
    assert len(todos) == 1
    assert todos[0]["mine"] is True
