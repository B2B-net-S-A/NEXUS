"""Umówiony telefon na screening (decyzja Artura 03.11.2026, wariant A).

Trzy rzeczy, których nie widać z ekranu: termin trzyma osobę dłużej niż 12 h,
termin gaśnie sam, gdy osoba poszła dalej, i nieodbyty telefon nie udaje
kontaktu w follow-upie.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, update

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.calendar_event import (
    BOOKED_CALL_LOCATION,
    CalendarEvent,
    EventStatus,
    EventType,
    is_booked_call,
)
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus, RemotePolicy
from app.models.job_collaborator import JobCollaborator
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.recruitment_process import RecruitmentProcess
from app.models.user import User, UserRole
from app.services import screening_calls as svc
from app.services.notification_topics import enrich_realtime_event

pytestmark = pytest.mark.asyncio


# ── czyste reguły ─────────────────────────────────────────────────────────


NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)


async def test_hold_never_shorter_than_a_normal_claim() -> None:
    assert svc.hold_until(NOW + timedelta(hours=1), NOW) == NOW + timedelta(hours=12)


async def test_hold_lasts_two_hours_after_the_call() -> None:
    start = NOW + timedelta(days=2)
    assert svc.hold_until(start, NOW) == start + timedelta(hours=2)


async def test_hold_is_capped_at_seven_days() -> None:
    assert svc.hold_until(NOW + timedelta(days=30), NOW) == NOW + timedelta(days=7)


async def test_outlook_subject_has_first_name_and_initial_only() -> None:
    assert (
        svc.outlook_subject(SimpleNamespace(name="Anna", lastname="Nowak"))
        == "Telefon: Anna N."
    )
    assert (
        svc.outlook_subject(SimpleNamespace(name=None, lastname=None))
        == "Telefon do kandydata"
    )


async def test_is_booked_call_needs_the_marker_and_an_owner() -> None:
    def event(**kw):
        base = {
            "event_type": EventType.screening,
            "location": BOOKED_CALL_LOCATION,
            "operational_owner_id": 1,
        }
        return SimpleNamespace(**{**base, **kw})

    assert is_booked_call(event())
    assert not is_booked_call(event(location="Teams"))
    assert not is_booked_call(event(event_type=EventType.interview))
    assert not is_booked_call(event(operational_owner_id=None))


async def test_force_toast_makes_only_this_reminder_pop_up() -> None:
    frame = {
        "type": "notification",
        "data": {"notification_type": "interview_scheduled"},
    }
    assert enrich_realtime_event(frame)["data"]["toast"] is False
    frame["data"]["force_toast"] = True
    assert enrich_realtime_event(frame)["data"]["toast"] is True


# ── API ───────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def api_client():
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as c:
        yield c


async def _seed_user(role: UserRole) -> tuple[int, str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"call-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Cl"
    async with AsyncSessionLocal() as db:
        u = User(
            email=email,
            password_hash=hash_password(password),
            name=f"Call {role.value} {unique}",
            role=role,
            is_active=True,
        )
        db.add(u)
        await db.commit()
        return u.id, email, password


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _seed_job(owner_id: int, others: tuple[int, ...] = ()) -> int:
    unique = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        cli = Client(name=f"CallClient-{unique}")
        db.add(cli)
        await db.flush()
        job = Job(
            title=f"Call Job {unique}",
            location="Warszawa",
            status=JobStatus.published,
            remote_policy=RemotePolicy.hybrid,
            client_id=cli.id,
            recruiter_id=owner_id,
        )
        db.add(job)
        await db.flush()
        for uid in others:
            db.add(JobCollaborator(job_id=job.id, user_id=uid, added_by=owner_id))
        await db.commit()
        return job.id


async def _seed_candidate() -> int:
    unique = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Telefon",
            lastname=f"Osoba{unique}",
            email=f"call-{unique}@example.com",
        )
        db.add(cand)
        await db.commit()
        return cand.id


async def _add(client, headers, job_id: int, candidate_id: int) -> None:
    resp = await client.post(
        f"/api/jobs/{job_id}/proposals/bulk",
        headers=headers,
        json={
            "candidate_ids": [candidate_id],
            "initial_stage_legacy": "new",
            "source": "manual_search",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["added"] == [candidate_id], resp.text


async def _process(candidate_id: int, job_id: int) -> RecruitmentProcess:
    async with AsyncSessionLocal() as db:
        proc = await db.scalar(
            select(RecruitmentProcess)
            .where(
                RecruitmentProcess.candidate_id == candidate_id,
                RecruitmentProcess.job_id == job_id,
            )
            .order_by(RecruitmentProcess.attempt_no.desc())
            .limit(1)
        )
    assert proc is not None
    return proc


async def _event(event_id: int) -> CalendarEvent:
    async with AsyncSessionLocal() as db:
        event = await db.get(CalendarEvent, event_id)
    assert event is not None
    return event


async def _cleanup(candidate_id: int, job_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(CalendarEvent).where(CalendarEvent.candidate_id == candidate_id)
        )
        await db.execute(
            delete(CandidateStage).where(CandidateStage.candidate_id == candidate_id)
        )
        await db.execute(delete(Candidate).where(Candidate.id == candidate_id))
        await db.execute(delete(Job).where(Job.id == job_id))
        await db.commit()


def _body(candidate_id: int, job_id: int, start: datetime, **extra) -> dict:
    return {
        "candidate_id": candidate_id,
        "job_id": job_id,
        "start": start.isoformat(),
        "client_request_id": uuid.uuid4().hex,
        **extra,
    }


def _in(**delta) -> datetime:
    return datetime.now(timezone.utc) + timedelta(**delta)


async def test_booking_makes_a_phone_event_and_holds_the_person(api_client):
    owner_id, email, pw = await _seed_user(UserRole.recruiter)
    job_id = await _seed_job(owner_id)
    cand_id = await _seed_candidate()
    h = await _login(api_client, email, pw)
    try:
        await _add(api_client, h, job_id, cand_id)
        start = _in(days=2)
        resp = await api_client.post(
            "/api/screening-calls",
            headers=h,
            json=_body(cand_id, job_id, start, note="  w pociągu  "),
        )
        assert resp.status_code == 201, resp.text
        out = resp.json()
        # Rekruter bez połączenia M365 dostaje termin w NEXUSIE i informację.
        assert out["outlook"] == "not_connected"
        assert out["note"] == "w pociągu"

        event = await _event(out["event_id"])
        assert is_booked_call(event)
        assert event.operational_owner_id == owner_id
        assert event.reminder_minutes == 15
        assert event.attendees == []
        assert event.end_time - event.start_time == timedelta(minutes=15)

        proc = await _process(cand_id, job_id)
        assert proc.claimed_by_user_id == owner_id
        assert abs(proc.claimed_until - (start + timedelta(hours=2))) < timedelta(
            seconds=1
        )

        second = await api_client.post(
            "/api/screening-calls", headers=h, json=_body(cand_id, job_id, _in(days=3))
        )
        assert second.status_code == 409, second.text
    finally:
        await _cleanup(cand_id, job_id)


@pytest.mark.parametrize(
    ("delta", "status"),
    [({"minutes": -5}, 422), ({"days": 61}, 422)],
)
async def test_start_must_be_soon_enough_and_in_the_future(api_client, delta, status):
    owner_id, email, pw = await _seed_user(UserRole.recruiter)
    job_id = await _seed_job(owner_id)
    cand_id = await _seed_candidate()
    h = await _login(api_client, email, pw)
    try:
        await _add(api_client, h, job_id, cand_id)
        resp = await api_client.post(
            "/api/screening-calls", headers=h, json=_body(cand_id, job_id, _in(**delta))
        )
        assert resp.status_code == status, resp.text
    finally:
        await _cleanup(cand_id, job_id)


async def test_someone_elses_claim_blocks_booking(api_client):
    owner_id, owner_email, owner_pw = await _seed_user(UserRole.recruiter)
    other_id, other_email, other_pw = await _seed_user(UserRole.recruiter)
    dl_id, dl_email, dl_pw = await _seed_user(UserRole.delivery_lead)
    job_id = await _seed_job(owner_id, others=(other_id, dl_id))
    cand_id = await _seed_candidate()
    owner_h = await _login(api_client, owner_email, owner_pw)
    other_h = await _login(api_client, other_email, other_pw)
    dl_h = await _login(api_client, dl_email, dl_pw)
    try:
        await _add(api_client, owner_h, job_id, cand_id)
        body = _body(cand_id, job_id, _in(days=1))
        recruiter = await api_client.post(
            "/api/screening-calls", headers=other_h, json=body
        )
        assert recruiter.status_code == 423, recruiter.text
        # Delivery Lead przejmuje przyciskiem „Przejmij”, nie po cichu terminem.
        lead = await api_client.post("/api/screening-calls", headers=dl_h, json=body)
        assert lead.status_code == 409, lead.text
    finally:
        await _cleanup(cand_id, job_id)


async def test_person_past_screening_cannot_be_booked(api_client):
    owner_id, email, pw = await _seed_user(UserRole.recruiter)
    job_id = await _seed_job(owner_id)
    cand_id = await _seed_candidate()
    h = await _login(api_client, email, pw)
    try:
        await _add(api_client, h, job_id, cand_id)
        async with AsyncSessionLocal() as db:
            db.add(
                CandidateStage(
                    candidate_id=cand_id,
                    job_id=job_id,
                    stage=PipelineStage.cv_sent,
                    moved_by=owner_id,
                )
            )
            await db.commit()
        resp = await api_client.post(
            "/api/screening-calls", headers=h, json=_body(cand_id, job_id, _in(days=1))
        )
        assert resp.status_code == 409, resp.text
    finally:
        await _cleanup(cand_id, job_id)


async def test_only_owner_or_lead_moves_a_call_and_moving_rearms_reminder(api_client):
    owner_id, owner_email, owner_pw = await _seed_user(UserRole.recruiter)
    other_id, other_email, other_pw = await _seed_user(UserRole.recruiter)
    job_id = await _seed_job(owner_id, others=(other_id,))
    cand_id = await _seed_candidate()
    owner_h = await _login(api_client, owner_email, owner_pw)
    other_h = await _login(api_client, other_email, other_pw)
    try:
        await _add(api_client, owner_h, job_id, cand_id)
        booked = await api_client.post(
            "/api/screening-calls",
            headers=owner_h,
            json=_body(cand_id, job_id, _in(days=1), note="stara"),
        )
        event_id = booked.json()["event_id"]
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(CalendarEvent)
                .where(CalendarEvent.id == event_id)
                .values(reminder_sent_at=datetime.now(timezone.utc))
            )
            await db.commit()

        new_start = _in(days=4)
        denied = await api_client.put(
            f"/api/screening-calls/{event_id}",
            headers=other_h,
            json={"start": new_start.isoformat()},
        )
        assert denied.status_code == 403, denied.text

        moved = await api_client.put(
            f"/api/screening-calls/{event_id}",
            headers=owner_h,
            json={"start": new_start.isoformat()},
        )
        assert moved.status_code == 200, moved.text
        event = await _event(event_id)
        assert event.reminder_sent_at is None
        # Przełożenie bez pola `note` zostawia to, co powiedział kandydat.
        assert event.description == "stara"
        proc = await _process(cand_id, job_id)
        assert abs(proc.claimed_until - (new_start + timedelta(hours=2))) < timedelta(
            seconds=1
        )

        cancelled = await api_client.post(
            f"/api/screening-calls/{event_id}/cancel", headers=owner_h
        )
        assert cancelled.status_code == 200, cancelled.text
        assert (await _event(event_id)).status == EventStatus.cancelled
        again = await api_client.post(
            f"/api/screening-calls/{event_id}/cancel", headers=owner_h
        )
        assert again.status_code == 409, again.text
    finally:
        await _cleanup(cand_id, job_id)


async def test_board_and_tasks_show_the_call(api_client):
    owner_id, email, pw = await _seed_user(UserRole.recruiter)
    job_id = await _seed_job(owner_id)
    cand_id = await _seed_candidate()
    h = await _login(api_client, email, pw)
    try:
        await _add(api_client, h, job_id, cand_id)
        booked = await api_client.post(
            "/api/screening-calls",
            headers=h,
            json=_body(cand_id, job_id, _in(days=1), note="po 16"),
        )
        event_id = booked.json()["event_id"]

        tasks = await api_client.get("/api/board-tasks", headers=h)
        assert tasks.status_code == 200, tasks.text
        rows = tasks.json()["booked_calls"]
        assert [r["event_id"] for r in rows] == [event_id]
        assert rows[0]["note"] == "po 16"
        # Bez drugiej prośby o decyzję w „Twoich blokadach”.
        assert cand_id not in {
            r["candidate_id"] for r in tasks.json()["flow"]["claimed"]
        }

        board = await api_client.get(f"/api/pipeline/kanban/{job_id}", headers=h)
        assert board.status_code == 200, board.text
        assert f'"event_id":{event_id}' in board.text.replace(" ", "")
    finally:
        await _cleanup(cand_id, job_id)


# ── pętla: termin gaśnie sam ──────────────────────────────────────────────


async def _book_directly(api_client) -> tuple[int, int, int, int]:
    owner_id, email, pw = await _seed_user(UserRole.recruiter)
    job_id = await _seed_job(owner_id)
    cand_id = await _seed_candidate()
    h = await _login(api_client, email, pw)
    await _add(api_client, h, job_id, cand_id)
    booked = await api_client.post(
        "/api/screening-calls", headers=h, json=_body(cand_id, job_id, _in(days=1))
    )
    assert booked.status_code == 201, booked.text
    return owner_id, job_id, cand_id, booked.json()["event_id"]


async def test_reconcile_leaves_a_call_in_the_entry_columns(api_client):
    _, job_id, cand_id, event_id = await _book_directly(api_client)
    try:
        async with AsyncSessionLocal() as db:
            await svc.reconcile(db)
        assert (await _event(event_id)).status == EventStatus.scheduled
    finally:
        await _cleanup(cand_id, job_id)


async def test_reconcile_completes_a_call_when_the_person_moved_on(api_client):
    owner_id, job_id, cand_id, event_id = await _book_directly(api_client)
    try:
        async with AsyncSessionLocal() as db:
            db.add(
                CandidateStage(
                    candidate_id=cand_id,
                    job_id=job_id,
                    stage=PipelineStage.cv_sent,
                    moved_by=owner_id,
                )
            )
            await db.commit()
        async with AsyncSessionLocal() as db:
            await svc.reconcile(db)
        assert (await _event(event_id)).status == EventStatus.completed
    finally:
        await _cleanup(cand_id, job_id)


async def test_reconcile_cancels_a_call_when_the_recruitment_closed(api_client):
    _, job_id, cand_id, event_id = await _book_directly(api_client)
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(Job).where(Job.id == job_id).values(status=JobStatus.closed)
            )
            await db.commit()
        async with AsyncSessionLocal() as db:
            await svc.reconcile(db)
        assert (await _event(event_id)).status == EventStatus.cancelled
    finally:
        await _cleanup(cand_id, job_id)


async def test_saved_screening_completes_the_call(api_client):
    _, job_id, cand_id, event_id = await _book_directly(api_client)
    try:
        async with AsyncSessionLocal() as db:
            await svc.complete_for_pair(db, candidate_id=cand_id, job_id=job_id)
            await db.commit()
        assert (await _event(event_id)).status == EventStatus.completed
    finally:
        await _cleanup(cand_id, job_id)


# ── Outlook ───────────────────────────────────────────────────────────────


async def _with_outlook_copy(event_id: int, status: EventStatus) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(CalendarEvent)
            .where(CalendarEvent.id == event_id)
            .values(
                status=status,
                external_source="microsoft365",
                external_id=f"graph-{event_id}",
            )
        )
        await db.commit()


async def test_clean_outlook_unlinks_the_copy_after_cancelling(api_client, monkeypatch):
    _, job_id, cand_id, event_id = await _book_directly(api_client)
    conn = SimpleNamespace(user_id=1)
    cancel = AsyncMock(return_value="deleted")
    monkeypatch.setattr(svc, "_active_connection", AsyncMock(return_value=conn))
    monkeypatch.setattr(svc, "cancel_graph_event", cancel)
    try:
        await _with_outlook_copy(event_id, EventStatus.cancelled)
        async with AsyncSessionLocal() as db:
            assert await svc.clean_outlook(db, datetime.now(timezone.utc)) >= 1
        assert cancel.await_args.args[2] == f"graph-{event_id}"
        event = await _event(event_id)
        assert event.external_id is None
        assert event.external_source is None
    finally:
        await _cleanup(cand_id, job_id)


async def test_clean_outlook_keeps_the_copy_when_graph_fails(api_client, monkeypatch):
    _, job_id, cand_id, event_id = await _book_directly(api_client)
    monkeypatch.setattr(
        svc, "_active_connection", AsyncMock(return_value=SimpleNamespace(user_id=1))
    )
    monkeypatch.setattr(
        svc, "cancel_graph_event", AsyncMock(side_effect=RuntimeError("503"))
    )
    try:
        await _with_outlook_copy(event_id, EventStatus.completed)
        async with AsyncSessionLocal() as db:
            await svc.clean_outlook(db, datetime.now(timezone.utc))
        # Następny przebieg pętli spróbuje jeszcze raz.
        assert (await _event(event_id)).external_id == f"graph-{event_id}"
    finally:
        await _cleanup(cand_id, job_id)


async def test_outlook_entry_has_no_attendees_and_no_teams(api_client, monkeypatch):
    _, job_id, cand_id, event_id = await _book_directly(api_client)
    sent: dict = {}

    class FakeGraph:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def post(self, _url, json):
            sent.update(json)
            return {"id": "graph-new", "changeKey": "ck"}

    monkeypatch.setattr(svc, "GraphClient", FakeGraph)
    monkeypatch.setattr(
        svc, "_active_connection", AsyncMock(return_value=SimpleNamespace(user_id=1))
    )
    try:
        async with AsyncSessionLocal() as db:
            event = await db.get(CalendarEvent, event_id)
            result = await svc.add_to_outlook(
                db,
                event=event,
                candidate_id=cand_id,
                client_request_id="x" * 20,
            )
        assert result == "added"
        assert sent["attendees"] == []
        assert "isOnlineMeeting" not in sent
        # Nazwisko nie wychodzi poza NEXUS; tytuł w NEXUSIE zostaje pełny.
        assert "Osoba" not in sent["subject"]
        stored = await _event(event_id)
        assert stored.external_id == "graph-new"
        assert stored.title.startswith("Telefon: Telefon Osoba")
    finally:
        await _cleanup(cand_id, job_id)


async def test_outlook_failure_does_not_lose_the_call(api_client, monkeypatch):
    _, job_id, cand_id, event_id = await _book_directly(api_client)

    class BrokenGraph:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            raise RuntimeError("503")

        async def __aexit__(self, *_exc):
            return False

    monkeypatch.setattr(svc, "GraphClient", BrokenGraph)
    monkeypatch.setattr(
        svc, "_active_connection", AsyncMock(return_value=SimpleNamespace(user_id=1))
    )
    try:
        async with AsyncSessionLocal() as db:
            event = await db.get(CalendarEvent, event_id)
            result = await svc.add_to_outlook(
                db,
                event=event,
                candidate_id=cand_id,
                client_request_id="y" * 20,
            )
        assert result == "failed"
        stored = await _event(event_id)
        assert stored.status == EventStatus.scheduled
        assert stored.external_id is None
    finally:
        await _cleanup(cand_id, job_id)


# ── wpływ na inne funkcje ─────────────────────────────────────────────────


async def test_outlook_change_does_not_touch_a_booked_call() -> None:
    from app.services.m365 import sync

    class OneRowDb:
        async def scalar(self, _statement):
            return event

    start = datetime.now(timezone.utc) + timedelta(days=2)
    event = CalendarEvent(
        id=1,
        title="Telefon: Anna Nowak",
        event_type=EventType.screening,
        status=EventStatus.scheduled,
        location=BOOKED_CALL_LOCATION,
        start_time=start,
        end_time=start + timedelta(minutes=15),
        operational_owner_id=5,
        external_source="microsoft365",
        external_id="G1",
        m365_change_key="ck1",
    )
    await sync._upsert_event(
        OneRowDb(), SimpleNamespace(id=1, user_id=5), {"id": "G1", "changeKey": "ck2"}
    )
    assert event.title == "Telefon: Anna Nowak"
    assert event.m365_change_key == "ck2"

    await sync._upsert_event(
        OneRowDb(),
        SimpleNamespace(id=1, user_id=5),
        {"id": "G1", "@removed": {"reason": "deleted"}},
    )
    # Usunięta blokada nie odwołuje telefonu w NEXUSIE.
    assert event.status == EventStatus.scheduled
    assert event.external_id is None


async def test_call_that_never_happened_is_not_a_followup_contact(api_client):
    from app.services import candidate_followups

    owner_id, job_id, cand_id, event_id = await _book_directly(api_client)
    past = datetime.now(timezone.utc) - timedelta(hours=3)
    now = datetime.now(timezone.utc)
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(CalendarEvent)
                .where(CalendarEvent.id == event_id)
                .values(start_time=past, end_time=past + timedelta(minutes=15))
            )
            await db.commit()
        async with AsyncSessionLocal() as db:
            contacts = await candidate_followups._last_contacts(db, [cand_id], now=now)
        assert cand_id not in contacts

        async with AsyncSessionLocal() as db:
            await svc.complete_for_pair(db, candidate_id=cand_id, job_id=job_id)
            await db.commit()
        async with AsyncSessionLocal() as db:
            contacts = await candidate_followups._last_contacts(db, [cand_id], now=now)
        assert cand_id in contacts
    finally:
        await _cleanup(cand_id, job_id)


async def test_erasing_the_candidate_cancels_the_call_for_the_outlook_sweep(api_client):
    from app.services.followup_meetings import erase_candidate_meetings

    _, job_id, cand_id, event_id = await _book_directly(api_client)
    try:
        async with AsyncSessionLocal() as db:
            candidate = await db.get(Candidate, cand_id)
            await erase_candidate_meetings(db, candidate)
            await db.commit()
        event = await _event(event_id)
        assert event.status == EventStatus.cancelled
        assert "Osoba" not in event.title
    finally:
        await _cleanup(cand_id, job_id)


async def test_reminder_opens_the_panel_and_pops_up(api_client, monkeypatch):
    from app.api import calendar as calendar_api
    from app.api import ws as ws_manager
    from app.models.notification import Notification

    owner_id, job_id, cand_id, event_id = await _book_directly(api_client)
    frames: list[dict] = []

    async def capture(_user_id, frame):
        frames.append(frame)

    monkeypatch.setattr(ws_manager, "notify_user", capture)
    try:
        await calendar_api._dispatch_reminder(event_id)
        async with AsyncSessionLocal() as db:
            notif = await db.scalar(
                select(Notification)
                .where(Notification.user_id == owner_id)
                .order_by(Notification.id.desc())
                .limit(1)
            )
        assert notif is not None
        assert notif.link == f"/jobs/{job_id}?candidate={cand_id}"
        assert notif.title.startswith("Telefon: Telefon Osoba")
        assert notif.message.startswith("Za ")
        assert frames[0]["data"]["force_toast"] is True
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(Notification).where(Notification.user_id == owner_id)
            )
            await db.commit()
        await _cleanup(cand_id, job_id)
