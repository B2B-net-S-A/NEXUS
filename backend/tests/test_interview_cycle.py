"""Cykl rozmowy u klienta (0338): kroki, sloty DL ↔ rekruter, debrief.

Kalendarz na produkcji był kopią Outlooka (10 wydarzeń założonych w NEXUSIE
w całej historii, 0 feedbacków). Zespół planuje wyłącznie prep i drugi prep
i musi znać termin rozmowy kandydata u klienta, żeby zadzwonić ≤30 min po
niej. Te testy pilnują tego cyklu:

* czyste ``compute_steps``/``compute_todos`` — który krok jest bieżący, kiedy
  „zadzwoń teraz”, kiedy debrief jest zaległy;
* pełny przepływ HTTP: DL dodaje terminy → rekruter wybiera → DL potwierdza
  → wydarzenie ``client_interview`` z właścicielem = rekruter;
* debrief: feedback strony kandydata, pytania do banku klienta i prep-kitu.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token, hash_password
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.interview_feedback import FeedbackSource, InterviewFeedback
from app.models.interview_question import (
    InterviewQuestion,
    InterviewQuestionSource,
    JobQuestion,
)
from app.models.user import User, UserRole
from app.services.interview_cycle import (
    DebriefRef,
    EventRef,
    PairSnapshot,
    SlotRef,
    compute_steps,
    compute_todos,
    current_step_key,
)

NOW = datetime(2031, 6, 10, 12, 0, tzinfo=timezone.utc)


# ── Czyste kroki ─────────────────────────────────────────────────────────────


def _states(steps: list[dict]) -> dict[str, str]:
    return {s["key"]: s["state"] for s in steps}


def _iv(start: datetime, minutes: int = 60) -> EventRef:
    return EventRef(
        id=7,
        start=start,
        end=start + timedelta(minutes=minutes),
        title="R",
        status="scheduled",
    )


def _req(status: str, *, chosen: int | None = None, respond_by=None) -> SlotRef:
    return SlotRef(
        id=3,
        status=status,
        slots=(
            {"start": "2031-06-12T08:00:00+00:00", "end": "2031-06-12T09:00:00+00:00"},
            {"start": "2031-06-13T08:00:00+00:00", "end": "2031-06-13T09:00:00+00:00"},
        ),
        chosen_index=chosen,
        respond_by=respond_by,
        recruiter_id=11,
        created_by=22,
        duration_minutes=60,
        note=None,
        event_id=None,
    )


def test_empty_pair_starts_at_slots():
    steps = compute_steps(PairSnapshot(1, 2), NOW, call_window_minutes=30)
    assert [s["key"] for s in steps] == [
        "slots",
        "choice",
        "prep",
        "prep2",
        "interview",
        "call",
        "debrief",
    ]
    assert current_step_key(steps) == "slots"


def test_awaiting_recruiter_marks_choice_and_overdue_after_deadline():
    pair = PairSnapshot(1, 2, slot_request=_req("awaiting_recruiter"))
    assert (
        _states(compute_steps(pair, NOW, call_window_minutes=30))["choice"] == "current"
    )
    late = PairSnapshot(
        1,
        2,
        slot_request=_req("awaiting_recruiter", respond_by=NOW - timedelta(hours=1)),
    )
    assert (
        _states(compute_steps(late, NOW, call_window_minutes=30))["choice"] == "overdue"
    )


def test_awaiting_dl_is_waiting_not_done():
    pair = PairSnapshot(1, 2, slot_request=_req("awaiting_dl", chosen=1))
    steps = compute_steps(pair, NOW, call_window_minutes=30)
    assert _states(steps)["choice"] == "waiting"
    assert current_step_key(steps) == "choice"


def test_call_is_current_inside_window_and_overdue_after():
    ended = PairSnapshot(1, 2, interview=_iv(NOW - timedelta(minutes=70)))
    assert (
        _states(compute_steps(ended, NOW, call_window_minutes=30))["call"] == "current"
    )
    late = PairSnapshot(1, 2, interview=_iv(NOW - timedelta(minutes=100)))
    s = _states(compute_steps(late, NOW, call_window_minutes=30))
    assert s["call"] == "overdue" and s["debrief"] == "overdue"
    # Pominięte prepy nie blokują — po rozmowie już się nie wydarzą.
    assert s["prep"] == "skipped" and s["prep2"] == "skipped"


def test_debrief_closes_call_and_debrief():
    pair = PairSnapshot(
        1,
        2,
        interview=_iv(NOW - timedelta(hours=5)),
        debrief=DebriefRef(1, 5, "yes", None, None, None),
    )
    s = _states(compute_steps(pair, NOW, call_window_minutes=30))
    assert s["call"] == "done" and s["debrief"] == "done"


def test_call_and_debrief_wait_until_the_interview_starts():
    # Prep i prep 2 zrobione, rozmowa jutro: nic nie jest „bieżące” (karta nie
    # proponuje „Zapisz debrief”), a debrief zapisany przed rozmową nie zamyka
    # kroków (test na produkcji 23.09.2026).
    preps = [
        EventRef(
            id=3, start=NOW - timedelta(days=2), end=None, title="P", status="completed"
        ),
        EventRef(
            id=4,
            start=NOW - timedelta(hours=3),
            end=None,
            title="P2",
            status="completed",
        ),
    ]
    pair = PairSnapshot(
        1,
        2,
        preps=preps,
        interview=_iv(NOW + timedelta(days=1)),
        debrief=DebriefRef(1, 5, "yes", None, None, "Kafka?"),
    )
    steps = compute_steps(pair, NOW, call_window_minutes=30)
    s = _states(steps)
    assert s["interview"] == "scheduled"
    assert s["call"] == "todo" and s["debrief"] == "todo"
    assert current_step_key(steps) == "interview"
    # Rozmowa trwa — debrief już można zapisać, telefon jest bieżący.
    during = PairSnapshot(1, 2, preps=preps, interview=_iv(NOW - timedelta(minutes=10)))
    assert (
        _states(compute_steps(during, NOW, call_window_minutes=30))["call"] == "current"
    )


def test_upcoming_interview_without_prep_asks_for_prep():
    pair = PairSnapshot(1, 2, interview=_iv(NOW + timedelta(days=2)))
    todos = compute_todos(
        pair, NOW, call_window_minutes=30, user_id=11, is_dl_view=False
    )
    assert [t["kind"] for t in todos] == ["prep_missing"]


def test_call_now_is_top_priority_todo():
    pair = PairSnapshot(1, 2, interview=_iv(NOW - timedelta(minutes=65)))
    todos = compute_todos(
        pair, NOW, call_window_minutes=30, user_id=11, is_dl_view=False
    )
    assert todos[0]["kind"] == "call_now"
    assert todos[0]["due"] == NOW - timedelta(minutes=5) + timedelta(minutes=30)


def test_pick_goes_to_recruiter_confirm_goes_to_dl():
    pick = PairSnapshot(1, 2, slot_request=_req("awaiting_recruiter"))
    assert [
        t["kind"]
        for t in compute_todos(
            pick, NOW, call_window_minutes=30, user_id=11, is_dl_view=False
        )
    ] == ["slots_pick"]
    # Inny rekruter nie dostaje cudzego wyboru.
    assert (
        compute_todos(pick, NOW, call_window_minutes=30, user_id=99, is_dl_view=False)
        == []
    )
    confirm = PairSnapshot(1, 2, slot_request=_req("awaiting_dl", chosen=0))
    assert [
        t["kind"]
        for t in compute_todos(
            confirm, NOW, call_window_minutes=30, user_id=22, is_dl_view=False
        )
    ] == ["slots_confirm"]


def test_dl_view_flags_client_interview_stage_without_slots():
    pair = PairSnapshot(1, 2, latest_stage="client_interview")
    assert [
        t["kind"]
        for t in compute_todos(
            pair, NOW, call_window_minutes=30, user_id=22, is_dl_view=True
        )
    ] == ["slots_missing"]


# ── Wyzwalacze po rozmowie ───────────────────────────────────────────────────


async def test_client_interview_reminder_goes_to_event_owner_on_candidate_side(
    monkeypatch,
):
    from app.services import notification_triggers as nt

    ev = CalendarEvent(
        event_type=EventType.client_interview, operational_owner_id=11, created_by=22
    )
    assert nt._post_interview_side(ev, None) is False

    class _Job:
        recruiter_id = 33
        delivery_lead_id = 44

    async def active(db, user_id):
        return True

    monkeypatch.setattr(nt, "_user_is_active", active)
    assert await nt._post_interview_recipients(None, ev, _Job(), client_side=False) == [
        11
    ]


def test_client_interview_reminder_links_to_debrief_not_generic_feedback():
    from app.services.notification_triggers import _post_interview_link

    ev = CalendarEvent(
        id=5, event_type=EventType.client_interview, candidate_id=1, job_id=2
    )
    assert _post_interview_link(ev) == "/calendar?cycle=1-2&debrief=5"
    other = CalendarEvent(
        id=6, event_type=EventType.interview, candidate_id=1, job_id=2
    )
    assert _post_interview_link(other) == "/calendar?event=6&action=feedback"


# ── HTTP ─────────────────────────────────────────────────────────────────────


async def _user(role: UserRole) -> tuple[int, dict[str, str]]:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"cycle-{role.value}-{tag}@example.com",
            password_hash=hash_password(f"Cyc1e_{tag}!pw"),
            name=f"Cycle {role.value} {tag}",
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


async def _job_with_candidate(*, recruiter_id: int, dl_id: int) -> tuple[int, int, int]:
    from app.models.candidate import Candidate, CandidateStatus
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    tag = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"CycleClient-{tag}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"CycleJob-{tag}",
            status=JobStatus.published,
            client_id=client.id,
            recruiter_id=recruiter_id,
            delivery_lead_id=dl_id,
        )
        cand = Candidate(
            name="Anna",
            lastname=f"Cykl-{tag}",
            email=f"cycle-cand-{tag}@example.com",
            status=CandidateStatus.active,
        )
        db.add_all([job, cand])
        await db.flush()
        db.add(
            CandidateStage(
                candidate_id=cand.id,
                job_id=job.id,
                stage=PipelineStage.client_interview,
                moved_by=recruiter_id,
            )
        )
        await db.commit()
        return job.id, cand.id, client.id


def _future(days: int, hour: int = 9) -> str:
    base = datetime.now(timezone.utc) + timedelta(days=days)
    return base.replace(hour=hour, minute=0, second=0, microsecond=0).isoformat()


async def test_full_slot_flow_creates_client_interview_for_recruiter(
    app_client: AsyncClient,
):
    rec_id, rec_h = await _user(UserRole.recruiter)
    dl_id, dl_h = await _user(UserRole.delivery_lead)
    job_id, cand_id, client_id = await _job_with_candidate(
        recruiter_id=rec_id, dl_id=dl_id
    )

    created = await app_client.post(
        "/api/interview-cycle/slots",
        headers=dl_h,
        json={
            "candidate_id": cand_id,
            "job_id": job_id,
            "slots": [{"start": _future(3)}, {"start": _future(2)}],
            "duration_minutes": 45,
            "note": "Klient prosi o kamerkę",
        },
    )
    assert created.status_code == 201, created.text
    req = created.json()
    assert req["status"] == "awaiting_recruiter"
    assert req["recruiter_id"] == rec_id
    # Posortowane chronologicznie, koniec = start + czas trwania.
    starts = [s["start"] for s in req["slots"]]
    assert starts == sorted(starts)

    # Drugi otwarty wniosek na tę samą parę = 409.
    dup = await app_client.post(
        "/api/interview-cycle/slots",
        headers=dl_h,
        json={
            "candidate_id": cand_id,
            "job_id": job_id,
            "slots": [{"start": _future(4)}],
        },
    )
    assert dup.status_code == 409, dup.text

    mine = await app_client.get("/api/interview-cycle?scope=mine", headers=rec_h)
    assert mine.status_code == 200, mine.text
    kinds = [t["kind"] for t in mine.json()["todos"] if t["candidate_id"] == cand_id]
    assert "slots_pick" in kinds

    chosen = await app_client.post(
        f"/api/interview-cycle/slots/{req['id']}/choose",
        headers=rec_h,
        json={"index": 1},
    )
    assert chosen.status_code == 200, chosen.text
    assert chosen.json()["status"] == "awaiting_dl"

    # Rekruter nie potwierdza klientowi — to przekazanie należy do DL.
    self_confirm = await app_client.post(
        f"/api/interview-cycle/slots/{req['id']}/confirm",
        headers=rec_h,
        json={"add_to_outlook": False},
    )
    assert self_confirm.status_code == 403, self_confirm.text

    confirmed = await app_client.post(
        f"/api/interview-cycle/slots/{req['id']}/confirm",
        headers=dl_h,
        json={"add_to_outlook": False},
    )
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["request"]["status"] == "confirmed"
    assert body["outlook"] == "not_requested"

    async with AsyncSessionLocal() as db:
        event = await db.get(CalendarEvent, body["event_id"])
        assert event.event_type == EventType.client_interview
        assert event.operational_owner_id == rec_id
        assert (event.candidate_id, event.job_id, event.client_id) == (
            cand_id,
            job_id,
            client_id,
        )
        assert event.start_time.isoformat().startswith(_future(3)[:13])

    # Ponowne potwierdzenie = 409, nie druga rozmowa.
    again = await app_client.post(
        f"/api/interview-cycle/slots/{req['id']}/confirm",
        headers=dl_h,
        json={"add_to_outlook": False},
    )
    assert again.status_code == 409

    overview = await app_client.get("/api/interview-cycle?scope=mine", headers=rec_h)
    item = next(i for i in overview.json()["items"] if i["candidate_id"] == cand_id)
    states = {s["key"]: s["state"] for s in item["steps"]}
    assert states["interview"] == "scheduled"
    assert states["choice"] == "done"
    assert item["candidate_name"].startswith("Anna Cykl-")
    agenda_kinds = {
        a["kind"] for a in overview.json()["agenda"] if a["candidate_id"] == cand_id
    }
    assert {"interview", "call"} <= agenda_kinds

    dl_view = await app_client.get("/api/interview-cycle?scope=jobs", headers=dl_h)
    assert any(i["candidate_id"] == cand_id for i in dl_view.json()["items"])


async def test_slots_require_dl_role_and_pipeline_pair(app_client: AsyncClient):
    rec_id, rec_h = await _user(UserRole.recruiter)
    dl_id, dl_h = await _user(UserRole.delivery_lead)
    job_id, cand_id, _ = await _job_with_candidate(recruiter_id=rec_id, dl_id=dl_id)

    by_recruiter = await app_client.post(
        "/api/interview-cycle/slots",
        headers=rec_h,
        json={
            "candidate_id": cand_id,
            "job_id": job_id,
            "slots": [{"start": _future(2)}],
        },
    )
    assert by_recruiter.status_code == 403, by_recruiter.text

    _, other_cand, _ = await _job_with_candidate(recruiter_id=rec_id, dl_id=dl_id)
    not_in_job = await app_client.post(
        "/api/interview-cycle/slots",
        headers=dl_h,
        json={
            "candidate_id": other_cand,
            "job_id": job_id,
            "slots": [{"start": _future(2)}],
        },
    )
    assert not_in_job.status_code == 422, not_in_job.text

    past = await app_client.post(
        "/api/interview-cycle/slots",
        headers=dl_h,
        json={
            "candidate_id": cand_id,
            "job_id": job_id,
            "slots": [
                {"start": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()}
            ],
        },
    )
    assert past.status_code == 422, past.text


async def test_all_scope_is_oversight_only(app_client: AsyncClient):
    _, rec_h = await _user(UserRole.recruiter)
    resp = await app_client.get("/api/interview-cycle?scope=all", headers=rec_h)
    assert resp.status_code == 403


async def _client_interview(
    *, owner_id: int, cand_id: int, job_id: int, client_id: int, ended_min_ago: int
) -> int:
    end = datetime.now(timezone.utc) - timedelta(minutes=ended_min_ago)
    async with AsyncSessionLocal() as db:
        ev = CalendarEvent(
            title="Rozmowa u klienta",
            event_type=EventType.client_interview,
            start_time=end - timedelta(hours=1),
            end_time=end,
            status=EventStatus.completed,
            created_by=owner_id,
            operational_owner_id=owner_id,
            candidate_id=cand_id,
            job_id=job_id,
            client_id=client_id,
            needs_attention=True,
            attendees=[],
        )
        db.add(ev)
        await db.commit()
        return ev.id


async def test_debrief_saves_feedback_and_client_questions(app_client: AsyncClient):
    rec_id, rec_h = await _user(UserRole.recruiter)
    dl_id, _ = await _user(UserRole.delivery_lead)
    job_id, cand_id, client_id = await _job_with_candidate(
        recruiter_id=rec_id, dl_id=dl_id
    )
    event_id = await _client_interview(
        owner_id=rec_id,
        cand_id=cand_id,
        job_id=job_id,
        client_id=client_id,
        ended_min_ago=10,
    )

    overview = await app_client.get("/api/interview-cycle?scope=mine", headers=rec_h)
    todo = [t for t in overview.json()["todos"] if t["candidate_id"] == cand_id]
    assert todo and todo[0]["kind"] == "call_now"

    payload = {
        "outcome": "good",
        "candidate_comment": "Mocna rozmowa techniczna",
        "questions": [
            "Transakcje w Spring — propagacja",
            "  transakcje w spring — propagacja ",
            "Doświadczenie z Kafką",
        ],
        "offer_acceptance": "likely",
        "acceptance_condition": "Min. 190 zł/h",
    }
    saved = await app_client.put(
        f"/api/interview-cycle/events/{event_id}/debrief", headers=rec_h, json=payload
    )
    assert saved.status_code == 200, saved.text
    out = saved.json()
    assert out["outcome"] == "good"
    assert out["questions"] == [
        "Transakcje w Spring — propagacja",
        "Doświadczenie z Kafką",
    ]
    assert out["questions_saved"] == 2

    # Poprawka debriefu = ten sam wiersz, bez duplikatu pytań.
    payload["offer_acceptance"] = "yes"
    again = await app_client.put(
        f"/api/interview-cycle/events/{event_id}/debrief", headers=rec_h, json=payload
    )
    assert again.status_code == 200, again.text
    assert again.json()["id"] == out["id"]
    assert again.json()["questions_saved"] == 0

    async with AsyncSessionLocal() as db:
        fbs = (
            (
                await db.execute(
                    select(InterviewFeedback).where(
                        InterviewFeedback.calendar_event_id == event_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(fbs) == 1
        assert fbs[0].feedback_source == FeedbackSource.candidate_side
        assert fbs[0].offer_acceptance == "yes"
        assert fbs[0].overall_impression == 5
        questions = (
            (
                await db.execute(
                    select(InterviewQuestion).where(
                        InterviewQuestion.client_id == client_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert {q.source for q in questions} == {InterviewQuestionSource.client_debrief}
        assert len(questions) == 2
        pins = (
            (await db.execute(select(JobQuestion).where(JobQuestion.job_id == job_id)))
            .scalars()
            .all()
        )
        assert len(pins) == 2
        event = await db.get(CalendarEvent, event_id)
        assert event.needs_attention is False

    listed = await app_client.get(
        f"/api/interview-cycle/client-questions?job_id={job_id}", headers=rec_h
    )
    assert listed.status_code == 200, listed.text
    assert {q["text"] for q in listed.json()} == {
        "Transakcje w Spring — propagacja",
        "Doświadczenie z Kafką",
    }

    fetched = await app_client.get(
        f"/api/interview-cycle/events/{event_id}/debrief", headers=rec_h
    )
    assert fetched.json()["offer_acceptance"] == "yes"

    after = await app_client.get("/api/interview-cycle?scope=mine", headers=rec_h)
    item = next(i for i in after.json()["items"] if i["candidate_id"] == cand_id)
    states = {s["key"]: s["state"] for s in item["steps"]}
    assert states["debrief"] == "done"


async def test_delivery_lead_of_the_job_saves_debrief_for_someone_elses_interview(
    app_client: AsyncClient,
):
    """Audyt 25.09.2026: DL rekrutacji, który nie jest właścicielem ani
    uczestnikiem rozmowy, dostawał 404 — a bramka debriefu przed „Umową”
    zatrzymywała go bez wyjścia. Rekrutacje widzą wszyscy (23.09.2026)."""
    rec_id, _ = await _user(UserRole.recruiter)
    dl_id, dl_h = await _user(UserRole.delivery_lead)
    job_id, cand_id, client_id = await _job_with_candidate(
        recruiter_id=rec_id, dl_id=dl_id
    )
    event_id = await _client_interview(
        owner_id=rec_id,
        cand_id=cand_id,
        job_id=job_id,
        client_id=client_id,
        ended_min_ago=15,
    )
    event = await app_client.get(
        f"/api/interview-cycle/events/{event_id}", headers=dl_h
    )
    assert event.status_code == 200, event.text
    saved = await app_client.put(
        f"/api/interview-cycle/events/{event_id}/debrief",
        headers=dl_h,
        json={
            "outcome": "good",
            "offer_acceptance": "likely",
            "no_client_questions": True,
        },
    )
    assert saved.status_code == 200, saved.text
    fetched = await app_client.get(
        f"/api/interview-cycle/events/{event_id}/debrief", headers=dl_h
    )
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["offer_acceptance"] == "likely"


async def test_slot_request_recruiter_must_be_an_active_team_member(
    app_client: AsyncClient,
):
    """Audyt 25.09.2026: nieistniejący `recruiter_id` kończył się błędem klucza
    obcego braną za „otwarte terminy" (409), a dowolne konto dostawało wybór
    terminu i blokadę w Outlooku. Teraz 422 po polsku, zanim coś się zapisze."""
    rec_id, _ = await _user(UserRole.recruiter)
    dl_id, dl_h = await _user(UserRole.delivery_lead)
    job_id, cand_id, _ = await _job_with_candidate(recruiter_id=rec_id, dl_id=dl_id)
    inactive_id, _ = await _user(UserRole.recruiter)
    trainee_id, _ = await _user(UserRole.trainee)
    async with AsyncSessionLocal() as db:
        inactive = await db.get(User, inactive_id)
        inactive.is_active = False
        await db.commit()

    for bad in (2_000_000_000, inactive_id, trainee_id):
        resp = await app_client.post(
            "/api/interview-cycle/slots",
            headers=dl_h,
            json={
                "candidate_id": cand_id,
                "job_id": job_id,
                "slots": [{"start": _future(2)}],
                "recruiter_id": bad,
            },
        )
        assert resp.status_code == 422, resp.text
        assert "zespołu rekrutacji" in resp.json()["detail"]

    ok = await app_client.post(
        "/api/interview-cycle/slots",
        headers=dl_h,
        json={
            "candidate_id": cand_id,
            "job_id": job_id,
            "slots": [{"start": _future(2)}],
            "recruiter_id": rec_id,
        },
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["recruiter_id"] == rec_id


async def test_default_slot_recruiter_skips_an_inactive_first_verifier(
    app_client: AsyncClient,
):
    """Runda 2 audytu 25.09.2026: podpowiadany rekruter wniosku (właściciel
    procesu → pierwszy weryfikator → rekruter rekrutacji) nie przechodził
    reguły jawnego wyboru — wniosek dostawał np. ktoś, kto odszedł z firmy."""
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    rec_id, _ = await _user(UserRole.recruiter)
    dl_id, dl_h = await _user(UserRole.delivery_lead)
    gone_id, _ = await _user(UserRole.recruiter)
    job_id, cand_id, _ = await _job_with_candidate(recruiter_id=rec_id, dl_id=dl_id)
    async with AsyncSessionLocal() as db:
        gone = await db.get(User, gone_id)
        gone.is_active = False
        db.add(
            CandidateStage(
                candidate_id=cand_id,
                job_id=job_id,
                stage=PipelineStage.verified,
                moved_by=gone_id,
                moved_at=datetime.now(timezone.utc) - timedelta(days=10),
            )
        )
        await db.commit()

    resp = await app_client.post(
        "/api/interview-cycle/slots",
        headers=dl_h,
        json={
            "candidate_id": cand_id,
            "job_id": job_id,
            "slots": [{"start": _future(2)}],
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["recruiter_id"] == rec_id


async def test_prep_kit_includes_client_debrief_questions_from_other_jobs(
    app_client: AsyncClient,
):
    from app.models.job import Job
    from app.services.question_suggestions import suggest_questions_for_prep

    rec_id, rec_h = await _user(UserRole.recruiter)
    dl_id, _ = await _user(UserRole.delivery_lead)
    job_id, cand_id, client_id = await _job_with_candidate(
        recruiter_id=rec_id, dl_id=dl_id
    )
    event_id = await _client_interview(
        owner_id=rec_id,
        cand_id=cand_id,
        job_id=job_id,
        client_id=client_id,
        ended_min_ago=40,
    )
    resp = await app_client.put(
        f"/api/interview-cycle/events/{event_id}/debrief",
        headers=rec_h,
        json={
            "outcome": "medium",
            "questions": ["Jak pracujesz z niejasnymi wymaganiami?"],
            "offer_acceptance": "unknown",
        },
    )
    assert resp.status_code == 200, resp.text

    async with AsyncSessionLocal() as db:
        other = Job(title="Inna rola", client_id=client_id, recruiter_id=rec_id)
        db.add(other)
        await db.commit()
        await db.refresh(other)
        result = await suggest_questions_for_prep(db, other, target_count=3)
    tiers = {q.text: q.source_tier for q in result.questions}
    assert tiers.get("Jak pracujesz z niejasnymi wymaganiami?") == "client_debrief"


async def test_debrief_only_for_client_interview(app_client: AsyncClient):
    rec_id, rec_h = await _user(UserRole.recruiter)
    async with AsyncSessionLocal() as db:
        ev = CalendarEvent(
            title="Spotkanie",
            event_type=EventType.meeting,
            start_time=datetime.now(timezone.utc),
            status=EventStatus.scheduled,
            created_by=rec_id,
            attendees=[],
        )
        db.add(ev)
        await db.commit()
        event_id = ev.id
    resp = await app_client.put(
        f"/api/interview-cycle/events/{event_id}/debrief",
        headers=rec_h,
        json={
            "outcome": "good",
            "offer_acceptance": "yes",
            "no_client_questions": True,
        },
    )
    assert resp.status_code == 422, resp.text
    assert "rozmową kandydata u klienta" in resp.text


# ── Lustro migracji ──────────────────────────────────────────────────────────


def test_migration_is_mirrored_in_entrypoint():
    import re
    from pathlib import Path

    backend = Path(__file__).resolve().parents[1]
    entry = re.sub(r"\s+", " ", (backend / "entrypoint.sh").read_text())
    migration = (
        backend / "alembic/versions/0338_client_interview_cycle.py"
    ).read_text()
    for needle in (
        "ADD VALUE IF NOT EXISTS 'client_interview'",
        "ADD VALUE IF NOT EXISTS 'client_debrief'",
        "ADD VALUE IF NOT EXISTS 'interview_slots_requested'",
        "ADD VALUE IF NOT EXISTS 'interview_slot_chosen'",
        "ADD VALUE IF NOT EXISTS 'interview_slot_confirmed'",
        "ADD VALUE IF NOT EXISTS 'interview_debrief_saved'",
        "CREATE TABLE IF NOT EXISTS client_interview_slot_requests",
        "ADD COLUMN IF NOT EXISTS offer_acceptance",
        "ADD COLUMN IF NOT EXISTS acceptance_condition",
        "WHERE status IN ('awaiting_recruiter', 'awaiting_dl')",
    ):
        assert needle in entry, needle
    for name in set(re.findall(r'"((?:uq|ck|ix)_[a-z_]+)"', migration)):
        assert name in entry, name
    enum_block = migration.split("_ENUM_VALUES = (", 1)[1].split(")\n\n", 1)[0]
    for value in re.findall(r'\("\w+", "(\w+)"\)', enum_block):
        assert f"ADD VALUE IF NOT EXISTS '{value}'" in entry, value


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (5, "good"),
        (4, "good"),
        (3, "medium"),
        (1, "bad"),
        (None, None),
    ],
)
def test_outcome_mapping_round_trips(value, expected):
    from app.api.interview_cycle import _outcome_from_impression

    assert _outcome_from_impression(value) == expected


# ── Potwierdzenie terminu (runda 6 audytu, IC-1 / IC-3) ──────────────────────


async def _slot_request(app_client, dl_h, cand_id, job_id, days=3) -> dict:
    created = await app_client.post(
        "/api/interview-cycle/slots",
        headers=dl_h,
        json={
            "candidate_id": cand_id,
            "job_id": job_id,
            "slots": [{"start": _future(days)}],
        },
    )
    assert created.status_code == 201, created.text
    return created.json()


async def test_confirming_a_new_date_cancels_the_unheld_previous_interview(
    app_client: AsyncClient,
):
    """Klient przełożył rozmowę: stara, nieodbyta rozmowa nie może dawać
    telefonów T+15/T+45 ani zabierać prepów nowej rundzie."""
    rec_id, _ = await _user(UserRole.recruiter)
    dl_id, dl_h = await _user(UserRole.delivery_lead)
    job_id, cand_id, client_id = await _job_with_candidate(
        recruiter_id=rec_id, dl_id=dl_id
    )
    first = await _slot_request(app_client, dl_h, cand_id, job_id, days=2)
    one = await app_client.post(
        f"/api/interview-cycle/slots/{first['id']}/confirm",
        headers=dl_h,
        json={"index": 0, "add_to_outlook": False},
    )
    assert one.status_code == 200, one.text
    held = await _client_interview(
        owner_id=rec_id,
        cand_id=cand_id,
        job_id=job_id,
        client_id=client_id,
        ended_min_ago=60 * 24,
    )

    second = await _slot_request(app_client, dl_h, cand_id, job_id, days=5)
    two = await app_client.post(
        f"/api/interview-cycle/slots/{second['id']}/confirm",
        headers=dl_h,
        json={"index": 0, "add_to_outlook": False},
    )
    assert two.status_code == 200, two.text

    async with AsyncSessionLocal() as db:
        old = await db.get(CalendarEvent, one.json()["event_id"])
        new = await db.get(CalendarEvent, two.json()["event_id"])
        past = await db.get(CalendarEvent, held)
        assert old.status == EventStatus.cancelled
        assert new.status == EventStatus.scheduled
        # Rozmowa, która się odbyła, zostaje w historii.
        assert past.status == EventStatus.completed


async def test_confirm_skips_a_recruiter_who_left_before_confirmation(
    app_client: AsyncClient,
):
    rec_id, _ = await _user(UserRole.recruiter)
    dl_id, dl_h = await _user(UserRole.delivery_lead)
    job_id, cand_id, _ = await _job_with_candidate(recruiter_id=rec_id, dl_id=dl_id)
    req = await _slot_request(app_client, dl_h, cand_id, job_id)
    assert req["recruiter_id"] == rec_id
    async with AsyncSessionLocal() as db:
        gone = await db.get(User, rec_id)
        gone.is_active = False
        await db.commit()

    confirmed = await app_client.post(
        f"/api/interview-cycle/slots/{req['id']}/confirm",
        headers=dl_h,
        json={"index": 0, "add_to_outlook": False},
    )
    assert confirmed.status_code == 200, confirmed.text
    async with AsyncSessionLocal() as db:
        event = await db.get(CalendarEvent, confirmed.json()["event_id"])
        # Nikogo innego z dostępem nie ma — rozmowa zostaje u potwierdzającego.
        assert event.operational_owner_id == dl_id
        assert event.created_by == dl_id
