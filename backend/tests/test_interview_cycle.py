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
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token, hash_password
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.notification import Notification, NotificationType
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
    todo_is_mine,
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


# ── Na kogo czeka zadanie (okienko „Rozmowy”, 13.10.2026) ────────────────────


def _owned(ev: EventRef, owner_id: int) -> EventRef:
    return replace(ev, owner_id=owner_id)


def _todos_by_kind(
    pair: PairSnapshot, *, user_id: int = 11, is_dl_view: bool = False
) -> dict[str, dict]:
    todos = compute_todos(
        pair, NOW, call_window_minutes=30, user_id=user_id, is_dl_view=is_dl_view
    )
    return {t["kind"]: t for t in todos}


def test_call_and_debrief_wait_for_the_interview_owner():
    call = PairSnapshot(1, 2, interview=_owned(_iv(NOW - timedelta(minutes=65)), 11))
    assert _todos_by_kind(call)["call_now"]["owner_id"] == 11
    overdue = PairSnapshot(1, 2, interview=_owned(_iv(NOW - timedelta(hours=3)), 11))
    assert _todos_by_kind(overdue)["debrief_overdue"]["owner_id"] == 11


def test_slot_todos_wait_for_the_recruiter_and_the_request_author():
    pick = PairSnapshot(1, 2, slot_request=_req("awaiting_recruiter"))
    assert _todos_by_kind(pick)["slots_pick"]["owner_id"] == 11
    confirm = PairSnapshot(1, 2, slot_request=_req("awaiting_dl", chosen=0))
    assert _todos_by_kind(confirm, user_id=22)["slots_confirm"]["owner_id"] == 22
    missing = PairSnapshot(1, 2, latest_stage="client_interview")
    assert _todos_by_kind(missing, is_dl_view=True)["slots_missing"]["owner_id"] is None


def test_prep_todos_wait_for_the_interview_owner_or_the_prep_organizer():
    upcoming = _owned(_iv(NOW + timedelta(days=2)), 11)
    assert (
        _todos_by_kind(PairSnapshot(1, 2, interview=upcoming))["prep_missing"][
            "owner_id"
        ]
        == 11
    )

    def prep(**fields) -> EventRef:
        base = dict(id=5, start=NOW - timedelta(hours=2), end=None, title="P")
        return EventRef(**{**base, "status": "completed", "owner_id": 33, **fields})

    weak = prep(
        prep_no=1, transcript_status="ready", review_status="ok", review_level="weak"
    )
    with_weak = _todos_by_kind(PairSnapshot(1, 2, preps=[weak], interview=upcoming))
    assert with_weak["prep_weak"]["owner_id"] == 33
    # Prep 2 planuje rekruter (właściciel rozmowy), nie organizator Prepu 1.
    assert with_weak["prep2_missing"]["owner_id"] == 11

    unrecorded = prep(prep_no=1, transcript_status="missing")
    assert (
        _todos_by_kind(PairSnapshot(1, 2, preps=[unrecorded], interview=upcoming))[
            "prep_unrecorded"
        ]["owner_id"]
        == 33
    )

    late = prep(start=NOW + timedelta(days=3), status="scheduled", ordinal=1)
    assert (
        _todos_by_kind(PairSnapshot(1, 2, interview=upcoming, late_preps=[late]))[
            "prep_late"
        ]["owner_id"]
        == 33
    )


@pytest.mark.parametrize(
    "kind, owner_id, acting_for, delivery_lead_id, expected",
    [
        ("call_now", 11, {11}, None, True),
        # Delivery Lead w „Moich rekrutacjach” widzi telefon rekrutera, nie dostaje go.
        ("call_now", 11, {22}, 22, False),
        ("call_now", None, {11}, 11, False),
        # Zastępca pracuje za nieobecnego właściciela.
        ("debrief_overdue", 11, {22, 11}, None, True),
        ("slots_pick", None, {11}, None, True),
        ("slots_pick", 99, {11}, None, False),
        ("slots_confirm", 22, {22}, None, True),
        ("slots_confirm", 22, {11}, None, False),
        ("prep_missing", 11, {22}, 22, True),
        ("prep_missing", 11, {11}, 22, True),
        ("prep_missing", 11, {33}, 22, False),
        ("prep2_missing", 11, {11}, 22, True),
        ("prep2_missing", 11, {22}, 22, False),
        ("prep2_missing", None, {22}, 22, True),
        ("prep_late", 33, {33}, None, True),
        ("prep_weak", 33, {11}, 11, False),
        ("prep_unrecorded", 33, {33}, None, True),
        ("slots_missing", None, {22}, 22, True),
        ("slots_missing", None, {22}, None, False),
    ],
)
def test_todo_is_mine(kind, owner_id, acting_for, delivery_lead_id, expected):
    todo = {"kind": kind, "owner_id": owner_id}
    assert todo_is_mine(todo, acting_for, delivery_lead_id=delivery_lead_id) is expected


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

    async def working_owner_id(_db, job):  # nikt nie jest „Poprzednim rekruterem”
        return job.recruiter_id

    async def source_unchanged(_db, *, force=False):
        return False

    monkeypatch.setattr(nt, "_user_is_active", active)
    monkeypatch.setattr(nt, "working_owner_id", working_owner_id)
    # Test bez bazy: przełącznik źródła dostępności odświeża się z bazy co
    # minutę, więc wynik zależał od tego, ile trwały testy przed nim
    # (kolejka 19.10.2026: „'NoneType' object has no attribute 'scalar'”).
    from app.services.hr import availability_local

    monkeypatch.setattr(availability_local, "refresh_source", source_unchanged)
    monkeypatch.setattr(availability_local, "availability_enabled", lambda: False)
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
            phone="+48 500 000 000",
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


async def test_cancelled_interview_from_the_choice_drops_client_reply_todo(
    app_client: AsyncClient,
):
    """Audyt 22.10, F33: rozmowa z wyboru rekrutera odwołana w kalendarzu —
    DL nie ma już „Odpisz klientowi” z tekstem potwierdzającym termin."""
    rec_id, rec_h = await _user(UserRole.recruiter)
    dl_id, dl_h = await _user(UserRole.delivery_lead)
    job_id, cand_id, _client_id = await _job_with_candidate(
        recruiter_id=rec_id, dl_id=dl_id
    )
    created = await app_client.post(
        "/api/interview-cycle/slots",
        headers=dl_h,
        json={
            "candidate_id": cand_id,
            "job_id": job_id,
            "slots": [{"start": _future(3)}],
        },
    )
    assert created.status_code == 201, created.text
    chosen = await app_client.post(
        f"/api/interview-cycle/slots/{created.json()['id']}/choose",
        headers=rec_h,
        json={"index": 0},
    )
    assert chosen.status_code == 200, chosen.text
    body = chosen.json()
    assert body["client_reply_pending"] is True

    def reply_todos(resp) -> list:
        return [
            t
            for t in resp.json()["todos"]
            if t["candidate_id"] == cand_id and t["kind"] == "slots_reply"
        ]

    before = await app_client.get("/api/interview-cycle?scope=mine", headers=dl_h)
    assert reply_todos(before)

    async with AsyncSessionLocal() as db:
        event = await db.get(CalendarEvent, body["event_id"])
        event.status = EventStatus.cancelled
        await db.commit()

    after = await app_client.get("/api/interview-cycle?scope=mine", headers=dl_h)
    assert after.status_code == 200, after.text
    assert reply_todos(after) == []


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
    # 0487 (20.10.2026): wybór rekrutera od razu wpisuje rozmowę do
    # kalendarza, DL tylko odpisuje klientowi.
    body = chosen.json()
    assert body["status"] == "confirmed"
    assert body["client_reply_pending"] is True
    assert body["event_id"] is not None

    # Rekruter nie odpisuje klientowi w imieniu DL-a.
    self_reply = await app_client.post(
        f"/api/interview-cycle/slots/{req['id']}/client-replied", headers=rec_h
    )
    assert self_reply.status_code == 403, self_reply.text

    dl_todos = await app_client.get("/api/interview-cycle?scope=mine", headers=dl_h)
    reply_todo = next(
        t
        for t in dl_todos.json()["todos"]
        if t["candidate_id"] == cand_id and t["kind"] == "slots_reply"
    )
    assert reply_todo["mine"] is True

    replied = await app_client.post(
        f"/api/interview-cycle/slots/{req['id']}/client-replied", headers=dl_h
    )
    assert replied.status_code == 200, replied.text
    assert replied.json()["client_reply_pending"] is False
    assert replied.json()["client_replied_at"] is not None
    dl_todos = await app_client.get("/api/interview-cycle?scope=mine", headers=dl_h)
    assert not any(
        t["kind"] == "slots_reply"
        for t in dl_todos.json()["todos"]
        if t["candidate_id"] == cand_id
    )

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
    # Numer i e-mail w nagłówku panelu rozmowy — do umawiania terminu.
    assert item["candidate_phone"] == "+48 500 000 000"
    assert item["candidate_email"].startswith("cycle-cand-")
    agenda_kinds = {
        a["kind"] for a in overview.json()["agenda"] if a["candidate_id"] == cand_id
    }
    assert {"interview", "call"} <= agenda_kinds

    dl_view = await app_client.get("/api/interview-cycle?scope=jobs", headers=dl_h)
    assert any(i["candidate_id"] == cand_id for i in dl_view.json()["items"])


async def test_dl_replaces_open_slots_and_stale_choice_is_refused(
    app_client: AsyncClient,
):
    """Zgłoszenie 30.10.2026: otwartych terminów nie dało się zmienić ani
    anulować z ekranu, a nowe kończyły się samym 409."""
    rec_id, rec_h = await _user(UserRole.recruiter)
    dl_id, dl_h = await _user(UserRole.delivery_lead)
    other_dl_id, other_dl_h = await _user(UserRole.delivery_lead)
    job_id, cand_id, _ = await _job_with_candidate(recruiter_id=rec_id, dl_id=dl_id)
    other_job_id, other_cand_id, _ = await _job_with_candidate(
        recruiter_id=rec_id, dl_id=other_dl_id
    )
    base = {"candidate_id": cand_id, "job_id": job_id}

    first = await app_client.post(
        "/api/interview-cycle/slots",
        headers=dl_h,
        json={**base, "slots": [{"start": _future(2)}, {"start": _future(3)}]},
    )
    assert first.status_code == 201, first.text
    first_id = first.json()["id"]

    # 409 mówi, który wniosek stoi na drodze — okno proponuje jego zastąpienie.
    dup = await app_client.post(
        "/api/interview-cycle/slots",
        headers=dl_h,
        json={**base, "slots": [{"start": _future(4)}]},
    )
    assert dup.status_code == 409, dup.text
    detail = dup.json()["detail"]
    assert detail["code"] == "SLOTS_ALREADY_OPEN"
    assert detail["open_request_id"] == first_id

    # Wniosek innej pary nie zostaje zastąpiony przez pomyłkę.
    foreign = await app_client.post(
        "/api/interview-cycle/slots",
        headers=other_dl_h,
        json={
            "candidate_id": other_cand_id,
            "job_id": other_job_id,
            "slots": [{"start": _future(4)}],
            "replaces_request_id": first_id,
        },
    )
    assert foreign.status_code == 422, foreign.text

    # Rekruter nie zmienia terminów od klienta.
    by_recruiter = await app_client.post(
        "/api/interview-cycle/slots",
        headers=rec_h,
        json={
            **base,
            "slots": [{"start": _future(4)}],
            "replaces_request_id": first_id,
        },
    )
    assert by_recruiter.status_code == 403, by_recruiter.text

    replaced = await app_client.post(
        "/api/interview-cycle/slots",
        headers=dl_h,
        json={
            **base,
            "slots": [{"start": _future(4)}, {"start": _future(5)}],
            "replaces_request_id": first_id,
        },
    )
    assert replaced.status_code == 201, replaced.text
    new = replaced.json()
    assert new["id"] != first_id
    assert new["status"] == "awaiting_recruiter"
    assert new["recruiter_id"] == rec_id

    # Rekruter z oknem otwartym na starej liście nie wybierze indeksem nowego
    # terminu — wybór od razu wpisuje rozmowę do kalendarza.
    stale = await app_client.post(
        f"/api/interview-cycle/slots/{first_id}/choose",
        headers=rec_h,
        json={"index": 0},
    )
    assert stale.status_code == 409, stale.text

    mine = await app_client.get("/api/interview-cycle?scope=mine", headers=rec_h)
    pair = next(i for i in mine.json()["items"] if i["candidate_id"] == cand_id)
    assert pair["slot_request"]["id"] == new["id"]

    # Dwa razy tego samego nie da się zastąpić.
    again = await app_client.post(
        "/api/interview-cycle/slots",
        headers=dl_h,
        json={
            **base,
            "slots": [{"start": _future(6)}],
            "replaces_request_id": first_id,
        },
    )
    assert again.status_code == 409, again.text

    # Termin już wybrany i wpisany do kalendarza zmienia „Klient wybrał inny
    # termin”, nie zastąpienie wniosku.
    chosen = await app_client.post(
        f"/api/interview-cycle/slots/{new['id']}/choose",
        headers=rec_h,
        json={"index": 0},
    )
    assert chosen.json()["status"] == "confirmed", chosen.text
    after_confirm = await app_client.post(
        "/api/interview-cycle/slots",
        headers=dl_h,
        json={
            **base,
            "slots": [{"start": _future(6)}],
            "replaces_request_id": new["id"],
        },
    )
    assert after_confirm.status_code == 409, after_confirm.text


async def test_jobs_scope_includes_the_callers_own_pairs_from_other_jobs(
    app_client: AsyncClient,
):
    """Zgłoszenie 02.10.2026: DL wpisał terminy od klienta, dzwonek dostała
    rekruterka kandydata, która NIE jest w zespole tej rekrutacji. Jej ekran
    startuje w „Moje rekrutacje” (ma też rolę TAC), a ten zakres pary nie
    zawierał — tablica była pusta, a link z dzwonka mówił „nie ma w Twoim
    zakresie”. „Moje rekrutacje” zawierają też własne pary."""
    job_rec_id, _ = await _user(UserRole.recruiter)
    dl_id, dl_h = await _user(UserRole.delivery_lead)
    outsider_id, outsider_h = await _user(UserRole.recruiter)
    _, stranger_h = await _user(UserRole.recruiter)
    job_id, cand_id, _ = await _job_with_candidate(recruiter_id=job_rec_id, dl_id=dl_id)

    created = await app_client.post(
        "/api/interview-cycle/slots",
        headers=dl_h,
        json={
            "candidate_id": cand_id,
            "job_id": job_id,
            "slots": [{"start": _future(4)}, {"start": _future(3)}],
            "recruiter_id": outsider_id,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["recruiter_id"] == outsider_id

    jobs = await app_client.get("/api/interview-cycle?scope=jobs", headers=outsider_h)
    assert jobs.status_code == 200, jobs.text
    item = next((i for i in jobs.json()["items"] if i["candidate_id"] == cand_id), None)
    assert item is not None, "własny wniosek o terminy zniknął z „Moich rekrutacji”"
    kinds = [t["kind"] for t in jobs.json()["todos"] if t["candidate_id"] == cand_id]
    assert "slots_pick" in kinds
    # Okno prepu zna najwcześniejszy termin, który jeszcze czeka na wybór.
    assert item["tentative_interview_at"].startswith(_future(3)[:13])

    # Osoba bez żadnego związku z parą nadal jej w swoim zakresie nie ma.
    other = await app_client.get("/api/interview-cycle?scope=jobs", headers=stranger_h)
    assert all(i["candidate_id"] != cand_id for i in other.json()["items"])


async def test_overview_marks_whose_todo_it_is(app_client: AsyncClient):
    """Okienko „Rozmowy” (13.10.2026): Delivery Lead w „Moich rekrutacjach”
    widzi wybór terminu rekrutera, ale nie jako swoje zadanie."""
    rec_id, rec_h = await _user(UserRole.recruiter)
    dl_id, dl_h = await _user(UserRole.delivery_lead)
    job_id, cand_id, _ = await _job_with_candidate(recruiter_id=rec_id, dl_id=dl_id)
    created = await app_client.post(
        "/api/interview-cycle/slots",
        headers=dl_h,
        json={
            "candidate_id": cand_id,
            "job_id": job_id,
            "slots": [{"start": _future(4)}],
            "recruiter_id": rec_id,
        },
    )
    assert created.status_code == 201, created.text

    def pick(resp) -> dict:
        assert resp.status_code == 200, resp.text
        return next(
            t
            for t in resp.json()["todos"]
            if t["candidate_id"] == cand_id and t["kind"] == "slots_pick"
        )

    mine = await app_client.get("/api/interview-cycle?scope=mine", headers=rec_h)
    assert pick(mine)["mine"] is True
    # Wskazanie wykonawcy jest wewnętrzne — odpowiedź niesie tylko flagę.
    assert "owner_id" not in pick(mine)
    jobs = await app_client.get("/api/interview-cycle?scope=jobs", headers=dl_h)
    assert pick(jobs)["mine"] is False


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
    # Okno potwierdzenia pokazuje DL rozmowy, które termin może przełożyć:
    # tylko przyszłą, nieodbytą — nie tę, która się odbyła.
    listed = await app_client.get(
        f"/api/interview-cycle/slots/{second['id']}/replaceable", headers=dl_h
    )
    assert listed.status_code == 200, listed.text
    assert [row["id"] for row in listed.json()] == [one.json()["event_id"]]
    two = await app_client.post(
        f"/api/interview-cycle/slots/{second['id']}/confirm",
        headers=dl_h,
        json={
            "index": 0,
            "add_to_outlook": False,
            "supersedes_event_id": one.json()["event_id"],
        },
    )
    assert two.status_code == 200, two.text
    assert two.json()["cancelled_event_id"] == one.json()["event_id"]
    # Rozmowa była tylko w NEXUSIE — w Outlooku nie było czego zdejmować.
    assert two.json()["superseded_outlook"] == "none"

    async with AsyncSessionLocal() as db:
        old = await db.get(CalendarEvent, one.json()["event_id"])
        new = await db.get(CalendarEvent, two.json()["event_id"])
        past = await db.get(CalendarEvent, held)
        assert old.status == EventStatus.cancelled
        assert new.status == EventStatus.scheduled
        # Rozmowa, która się odbyła, zostaje w historii.
        assert past.status == EventStatus.completed


async def test_next_round_without_rescheduling_keeps_both_interviews(
    app_client: AsyncClient,
):
    """Decyzja Artura 26.09.2026: bez jawnego „to przełożenie” nic nie jest
    odwoływane — klient bywa, że umawia dwie rundy naraz."""
    rec_id, _ = await _user(UserRole.recruiter)
    dl_id, dl_h = await _user(UserRole.delivery_lead)
    job_id, cand_id, _ = await _job_with_candidate(recruiter_id=rec_id, dl_id=dl_id)
    first = await _slot_request(app_client, dl_h, cand_id, job_id, days=2)
    one = await app_client.post(
        f"/api/interview-cycle/slots/{first['id']}/confirm",
        headers=dl_h,
        json={"index": 0, "add_to_outlook": False},
    )
    assert one.status_code == 200, one.text
    second = await _slot_request(app_client, dl_h, cand_id, job_id, days=5)
    two = await app_client.post(
        f"/api/interview-cycle/slots/{second['id']}/confirm",
        headers=dl_h,
        json={"index": 0, "add_to_outlook": False},
    )
    assert two.status_code == 200, two.text
    assert two.json()["cancelled_event_id"] is None
    assert two.json()["superseded_outlook"] is None
    async with AsyncSessionLocal() as db:
        for key in (one, two):
            event = await db.get(CalendarEvent, key.json()["event_id"])
            assert event.status == EventStatus.scheduled


async def test_superseding_a_foreign_interview_is_refused(app_client: AsyncClient):
    rec_id, _ = await _user(UserRole.recruiter)
    dl_id, dl_h = await _user(UserRole.delivery_lead)
    job_id, cand_id, _ = await _job_with_candidate(recruiter_id=rec_id, dl_id=dl_id)
    other_job, other_cand, _ = await _job_with_candidate(
        recruiter_id=rec_id, dl_id=dl_id
    )
    foreign = await _slot_request(app_client, dl_h, other_cand, other_job, days=2)
    foreign_ok = await app_client.post(
        f"/api/interview-cycle/slots/{foreign['id']}/confirm",
        headers=dl_h,
        json={"index": 0, "add_to_outlook": False},
    )
    assert foreign_ok.status_code == 200, foreign_ok.text
    mine = await _slot_request(app_client, dl_h, cand_id, job_id, days=5)
    refused = await app_client.post(
        f"/api/interview-cycle/slots/{mine['id']}/confirm",
        headers=dl_h,
        json={
            "index": 0,
            "add_to_outlook": False,
            "supersedes_event_id": foreign_ok.json()["event_id"],
        },
    )
    assert refused.status_code == 422, refused.text
    async with AsyncSessionLocal() as db:
        event = await db.get(CalendarEvent, foreign_ok.json()["event_id"])
        assert event.status == EventStatus.scheduled


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


# ── 0487: wybór rekrutera = rozmowa w kalendarzu, DL odpisuje klientowi ─────


async def _two_slot_request(app_client, dl_h, cand_id, job_id) -> dict:
    created = await app_client.post(
        "/api/interview-cycle/slots",
        headers=dl_h,
        json={
            "candidate_id": cand_id,
            "job_id": job_id,
            "slots": [{"start": _future(3)}, {"start": _future(4)}],
        },
    )
    assert created.status_code == 201, created.text
    return created.json()


async def test_dl_picking_the_slot_notifies_the_recruiter(app_client: AsyncClient):
    """DL wybrał termin sam — rozmowa jest w kalendarzu rekrutera, więc
    rekruter dostaje powiadomienie, jak po potwierdzeniu."""
    rec_id, _ = await _user(UserRole.recruiter)
    dl_id, dl_h = await _user(UserRole.delivery_lead)
    job_id, cand_id, _ = await _job_with_candidate(recruiter_id=rec_id, dl_id=dl_id)
    req = await _two_slot_request(app_client, dl_h, cand_id, job_id)
    chosen = await app_client.post(
        f"/api/interview-cycle/slots/{req['id']}/choose",
        headers=dl_h,
        json={"index": 0},
    )
    assert chosen.status_code == 200, chosen.text
    assert chosen.json()["status"] == "confirmed"
    assert chosen.json()["outlook"] in ("not_requested", "skipped", "failed", "added")
    async with AsyncSessionLocal() as db:
        recipients = set(
            (
                await db.execute(
                    select(Notification.user_id).where(
                        Notification.notification_type
                        == NotificationType.interview_slot_confirmed,
                        Notification.related_entity_id == req["id"],
                    )
                )
            ).scalars()
        )
    assert rec_id in recipients


async def test_choice_waits_for_dl_when_the_switch_is_off(
    app_client: AsyncClient, monkeypatch
):
    from app.core.config import settings

    monkeypatch.setattr(settings, "SLOT_CHOICE_CONFIRMS", False)
    rec_id, rec_h = await _user(UserRole.recruiter)
    dl_id, dl_h = await _user(UserRole.delivery_lead)
    job_id, cand_id, _ = await _job_with_candidate(recruiter_id=rec_id, dl_id=dl_id)
    req = await _two_slot_request(app_client, dl_h, cand_id, job_id)
    chosen = await app_client.post(
        f"/api/interview-cycle/slots/{req['id']}/choose",
        headers=rec_h,
        json={"index": 0},
    )
    assert chosen.status_code == 200, chosen.text
    assert chosen.json()["status"] == "awaiting_dl"
    assert chosen.json()["event_id"] is None
    confirmed = await app_client.post(
        f"/api/interview-cycle/slots/{req['id']}/confirm",
        headers=dl_h,
        json={"add_to_outlook": False},
    )
    assert confirmed.status_code == 200, confirmed.text
    # DL potwierdził u klienta — nie ma zadania „Odpisz klientowi”.
    assert confirmed.json()["request"]["client_reply_pending"] is False


async def test_choice_next_to_a_planned_interview_still_waits_for_dl(
    app_client: AsyncClient,
):
    """Nowy termin przy zaplanowanej rozmowie może być przełożeniem — o tym
    decyduje DL w oknie potwierdzenia (reguła 26.09.2026)."""
    rec_id, rec_h = await _user(UserRole.recruiter)
    dl_id, dl_h = await _user(UserRole.delivery_lead)
    job_id, cand_id, _ = await _job_with_candidate(recruiter_id=rec_id, dl_id=dl_id)
    first = await _slot_request(app_client, dl_h, cand_id, job_id, days=2)
    one = await app_client.post(
        f"/api/interview-cycle/slots/{first['id']}/confirm",
        headers=dl_h,
        json={"index": 0, "add_to_outlook": False},
    )
    assert one.status_code == 200, one.text
    second = await _slot_request(app_client, dl_h, cand_id, job_id, days=5)
    chosen = await app_client.post(
        f"/api/interview-cycle/slots/{second['id']}/choose",
        headers=rec_h,
        json={"index": 0},
    )
    assert chosen.status_code == 200, chosen.text
    assert chosen.json()["status"] == "awaiting_dl"


async def test_client_picked_another_slot_moves_the_interview(
    app_client: AsyncClient,
):
    rec_id, rec_h = await _user(UserRole.recruiter)
    dl_id, dl_h = await _user(UserRole.delivery_lead)
    job_id, cand_id, _ = await _job_with_candidate(recruiter_id=rec_id, dl_id=dl_id)
    req = await _two_slot_request(app_client, dl_h, cand_id, job_id)
    chosen = await app_client.post(
        f"/api/interview-cycle/slots/{req['id']}/choose",
        headers=rec_h,
        json={"index": 0},
    )
    assert chosen.status_code == 200, chosen.text
    first_event = chosen.json()["event_id"]

    by_recruiter = await app_client.post(
        f"/api/interview-cycle/slots/{req['id']}/change",
        headers=rec_h,
        json={"index": 1},
    )
    assert by_recruiter.status_code == 403, by_recruiter.text
    same = await app_client.post(
        f"/api/interview-cycle/slots/{req['id']}/change",
        headers=dl_h,
        json={"index": 0},
    )
    assert same.status_code == 422, same.text

    changed = await app_client.post(
        f"/api/interview-cycle/slots/{req['id']}/change",
        headers=dl_h,
        json={"index": 1},
    )
    assert changed.status_code == 200, changed.text
    body = changed.json()
    assert body["cancelled_event_id"] == first_event
    assert body["request"]["chosen_index"] == 1
    # Zmiana przyszła od klienta — odpowiedź do klienta jest odhaczona.
    assert body["request"]["client_reply_pending"] is False
    async with AsyncSessionLocal() as db:
        old = await db.get(CalendarEvent, first_event)
        new = await db.get(CalendarEvent, body["event_id"])
        assert old.status == EventStatus.cancelled
        assert new.status == EventStatus.scheduled
        assert new.operational_owner_id == rec_id
        assert new.start_time.isoformat().startswith(_future(4)[:13])


async def test_every_change_of_the_slot_reaches_the_recruiter(
    app_client: AsyncClient,
):
    """Audyt 22.10, F100: „Klient zmienił termin” nie ginie w dziennym
    dedupie dzwonka po wcześniejszym dzwonku o tym samym wniosku."""
    rec_id, rec_h = await _user(UserRole.recruiter)
    dl_id, dl_h = await _user(UserRole.delivery_lead)
    job_id, cand_id, _ = await _job_with_candidate(recruiter_id=rec_id, dl_id=dl_id)
    req = await _two_slot_request(app_client, dl_h, cand_id, job_id)
    chosen = await app_client.post(
        f"/api/interview-cycle/slots/{req['id']}/choose",
        headers=rec_h,
        json={"index": 0},
    )
    assert chosen.status_code == 200, chosen.text
    for index in (1, 0):
        changed = await app_client.post(
            f"/api/interview-cycle/slots/{req['id']}/change",
            headers=dl_h,
            json={"index": index},
        )
        assert changed.status_code == 200, changed.text
    async with AsyncSessionLocal() as db:
        titles = (
            await db.scalars(
                select(Notification.title).where(
                    Notification.user_id == rec_id,
                    Notification.notification_type
                    == NotificationType.interview_slot_confirmed,
                )
            )
        ).all()
    assert titles == ["Klient zmienił termin rozmowy"] * 2


async def _move_slot_to_the_past(request_id: int, index: int) -> None:
    """Termin wniosku cofnięty na now − 2 h (wniosek sprzed kilku dni)."""
    from app.models.client_interview_slot_request import ClientInterviewSlotRequest

    past = datetime.now(timezone.utc) - timedelta(hours=2)
    async with AsyncSessionLocal() as db:
        req = await db.get(ClientInterviewSlotRequest, request_id)
        slots = [dict(s) for s in req.slots]
        slots[index] = {
            "start": past.isoformat(),
            "end": (past + timedelta(hours=1)).isoformat(),
        }
        req.slots = slots
        await db.commit()


async def test_choosing_a_slot_that_already_passed_is_refused(
    app_client: AsyncClient,
):
    """Audyt 21.10.2026: wybór od 0487 od razu zakłada rozmowę i blokadę
    w Outlooku — minionego terminu nie wolno wybrać."""
    rec_id, rec_h = await _user(UserRole.recruiter)
    dl_id, dl_h = await _user(UserRole.delivery_lead)
    job_id, cand_id, _ = await _job_with_candidate(recruiter_id=rec_id, dl_id=dl_id)
    req = await _two_slot_request(app_client, dl_h, cand_id, job_id)
    await _move_slot_to_the_past(req["id"], 0)
    chosen = await app_client.post(
        f"/api/interview-cycle/slots/{req['id']}/choose",
        headers=rec_h,
        json={"index": 0},
    )
    assert chosen.status_code == 422, chosen.text
    assert "minął" in chosen.json()["detail"]
    async with AsyncSessionLocal() as db:
        events = (
            await db.execute(
                select(CalendarEvent.id).where(
                    CalendarEvent.candidate_id == cand_id,
                    CalendarEvent.job_id == job_id,
                )
            )
        ).all()
    assert events == []


async def test_changing_to_a_slot_that_already_passed_keeps_the_interview(
    app_client: AsyncClient,
):
    rec_id, rec_h = await _user(UserRole.recruiter)
    dl_id, dl_h = await _user(UserRole.delivery_lead)
    job_id, cand_id, _ = await _job_with_candidate(recruiter_id=rec_id, dl_id=dl_id)
    req = await _two_slot_request(app_client, dl_h, cand_id, job_id)
    chosen = await app_client.post(
        f"/api/interview-cycle/slots/{req['id']}/choose",
        headers=rec_h,
        json={"index": 1},
    )
    assert chosen.status_code == 200, chosen.text
    event_id = chosen.json()["event_id"]
    await _move_slot_to_the_past(req["id"], 0)
    changed = await app_client.post(
        f"/api/interview-cycle/slots/{req['id']}/change",
        headers=dl_h,
        json={"index": 0},
    )
    assert changed.status_code == 422, changed.text
    async with AsyncSessionLocal() as db:
        event = await db.get(CalendarEvent, event_id)
        assert event.status == EventStatus.scheduled
