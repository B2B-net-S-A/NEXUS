"""Zmiana i odwołanie prepu przez ludzi pary, zaproszeni spoza zespołu (17.10.2026).

Zgłoszenie DL-a i decyzje D1–D4: do tej daty prep zmieniał tylko właściciel
wydarzenia, czyli prowadzący. Rekruter, który założył Prep 1 w kalendarzu
DL-a, dostawał 404 na „Szczegóły” i 403 na zmianę terminu, a lista
zaproszonych przyjmowała wyłącznie zespół rekrutacji.

Graph jest podmieniony na poziomie ``teams_prep_graph`` — reszta (trasy,
bramki, zapisy) działa naprawdę, jak w ``test_prep_meetings_flow``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.calendar_event import CalendarEvent, EventStatus
from app.models.prep_meeting import PrepMeeting
from app.models.user import User, UserRole
from app.services import prep_availability, prep_meetings
from app.services.m365 import teams_prep_auth, teams_prep_graph
from app.services.m365.graph_client import GraphRequestError
from tests.test_prep_meetings_flow import FakeGraph, _at, _create, _pair, _user


class EditingGraph(FakeGraph):
    def __init__(self) -> None:
        super().__init__()
        self.updated: list[tuple[str, str, dict]] = []
        self.cancelled: list[tuple[str, str, str]] = []
        self.fail_cancel_for: str | None = None

    async def update_event(self, upn, graph_event_id, payload):
        self.updated.append((upn, graph_event_id, payload))
        return "ck2"

    async def cancel_event(self, upn, graph_event_id, comment):
        if self.fail_cancel_for and upn == self.fail_cancel_for:
            raise GraphRequestError(500, {"error": "x"})
        self.cancelled.append((upn, graph_event_id, comment))
        return "cancelled"


@pytest.fixture
def graph(monkeypatch):
    fake = EditingGraph()
    for name in (
        "create_event",
        "resolve_user_id",
        "find_online_meeting",
        "enable_auto_transcription",
        "get_event",
        "update_event",
        "cancel_event",
    ):
        monkeypatch.setattr(teams_prep_graph, name, getattr(fake, name))
    monkeypatch.setattr(prep_availability, "busy_blocks", fake.busy_blocks)
    monkeypatch.setattr(settings, "TEAMS_PREP_APP_ONLY_ENABLED", True)
    monkeypatch.setattr(teams_prep_auth, "credentials_configured", lambda: True)
    return fake


async def _prep1_by_recruiter(app_client, *, hours: float = 48.0):
    """Rekruter zakłada Prep 1 w kalendarzu Delivery Leada."""
    rec_id, rec_h = await _user(UserRole.recruiter, "Ola Rekruter")
    dl_id, dl_h = await _user(UserRole.delivery_lead, "Kasia Lead")
    job_id, cand_id = await _pair(recruiter_id=rec_id, dl_id=dl_id)
    resp = await _create(
        app_client,
        rec_h,
        candidate_id=cand_id,
        job_id=job_id,
        prep_no=1,
        organizer_user_id=dl_id,
        start=_at(hours),
        end=_at(hours + 0.75),
        client_request_id="edit-1",
    )
    assert resp.status_code == 201, resp.text
    return {
        "rec": (rec_id, rec_h),
        "dl": (dl_id, dl_h),
        "job_id": job_id,
        "cand_id": cand_id,
        "event_id": resp.json()["event_id"],
    }


async def test_recruiter_moves_prep_that_lives_in_the_dl_calendar(
    app_client: AsyncClient, graph: EditingGraph
):
    ctx = await _prep1_by_recruiter(app_client)
    rec_id, rec_h = ctx["rec"]
    dl_id, _ = ctx["dl"]
    event_id = ctx["event_id"]

    detail = await app_client.get(
        f"/api/interview-cycle/preps/{event_id}", headers=rec_h
    )
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["can_edit"] is True
    assert body["organizer"]["id"] == dl_id
    assert body["scheduled_by"]["id"] == rec_id

    new_start = _at(72)
    resp = await app_client.patch(
        f"/api/interview-cycle/preps/{event_id}",
        headers=rec_h,
        json={"start": new_start, "end": _at(72.75)},
    )
    assert resp.status_code == 200, resp.text
    upn, _gid, payload = graph.updated[-1]
    # Zmiana idzie do kalendarza prowadzącego, nie planującego.
    assert upn.startswith("prep-delivery_lead-")
    assert set(payload) == {"start", "end"}
    async with AsyncSessionLocal() as db:
        ev = await db.get(CalendarEvent, event_id)
        assert ev.start_time == datetime.fromisoformat(new_start)
        assert ev.m365_change_key == "ck2"


async def test_person_outside_the_pair_cannot_change_or_cancel(
    app_client: AsyncClient, graph: EditingGraph
):
    ctx = await _prep1_by_recruiter(app_client)
    _other_id, other_h = await _user(UserRole.recruiter, "Inny Rekruter")
    event_id = ctx["event_id"]

    detail = await app_client.get(
        f"/api/interview-cycle/preps/{event_id}", headers=other_h
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["can_edit"] is False

    moved = await app_client.patch(
        f"/api/interview-cycle/preps/{event_id}",
        headers=other_h,
        json={"start": _at(80), "end": _at(81)},
    )
    assert moved.status_code == 403, moved.text
    cancelled = await app_client.post(
        f"/api/interview-cycle/preps/{event_id}/cancel", headers=other_h, json={}
    )
    assert cancelled.status_code == 403, cancelled.text
    assert graph.updated == [] and graph.cancelled == []


async def test_anyone_in_nexus_and_any_address_can_be_invited(
    app_client: AsyncClient, graph: EditingGraph
):
    rec_id, rec_h = await _user(UserRole.recruiter, "Ola Rekruter")
    dl_id, _ = await _user(UserRole.delivery_lead, "Kasia Lead")
    stranger_id, _ = await _user(UserRole.delivery_lead, "Inny Lead")
    job_id, cand_id = await _pair(recruiter_id=rec_id, dl_id=dl_id)

    opts = await app_client.get(
        f"/api/interview-cycle/preps/options?candidate_id={cand_id}&job_id={job_id}",
        headers=rec_h,
    )
    people = {p["id"]: p for p in opts.json()["people"]}
    assert people[stranger_id]["in_team"] is False
    assert people[dl_id]["in_team"] is True

    resp = await _create(
        app_client,
        rec_h,
        candidate_id=cand_id,
        job_id=job_id,
        prep_no=2,
        organizer_user_id=rec_id,
        start=_at(30),
        end=_at(30.75),
        attendee_user_ids=[stranger_id],
        attendee_emails=["Ekspert@Partner.example.com"],
    )
    assert resp.status_code == 201, resp.text
    _upn, payload = graph.created[-1]
    addresses = [a["emailAddress"]["address"] for a in payload["attendees"]]
    assert addresses[0].startswith("prep-cand-")
    assert any(a.startswith("prep-delivery_lead-") for a in addresses)
    assert any(a.lower() == "ekspert@partner.example.com" for a in addresses)

    attendees = resp.json()["attendees"]
    by_user = {a["user_id"]: a for a in attendees}
    assert stranger_id in by_user
    assert by_user[None]["email"].lower() == "ekspert@partner.example.com"


async def test_invalid_address_is_rejected(
    app_client: AsyncClient, graph: EditingGraph
):
    rec_id, rec_h = await _user(UserRole.recruiter, "Ola Rekruter")
    dl_id, _ = await _user(UserRole.delivery_lead, "Kasia Lead")
    job_id, cand_id = await _pair(recruiter_id=rec_id, dl_id=dl_id)
    resp = await _create(
        app_client,
        rec_h,
        candidate_id=cand_id,
        job_id=job_id,
        prep_no=2,
        organizer_user_id=rec_id,
        start=_at(30),
        end=_at(30.75),
        attendee_emails=["to-nie-jest-adres"],
    )
    assert resp.status_code == 422
    assert graph.created == []


async def test_dl_of_the_job_changes_who_is_invited_to_the_recruiter_prep(
    app_client: AsyncClient, graph: EditingGraph
):
    rec_id, rec_h = await _user(UserRole.recruiter, "Ola Rekruter")
    dl_id, dl_h = await _user(UserRole.delivery_lead, "Kasia Lead")
    job_id, cand_id = await _pair(recruiter_id=rec_id, dl_id=dl_id)
    created = await _create(
        app_client,
        rec_h,
        candidate_id=cand_id,
        job_id=job_id,
        prep_no=2,
        organizer_user_id=rec_id,
        start=_at(30),
        end=_at(30.75),
    )
    event_id = created.json()["event_id"]

    resp = await app_client.patch(
        f"/api/interview-cycle/preps/{event_id}",
        headers=dl_h,
        json={"attendee_user_ids": [dl_id], "attendee_emails": ["gosc@example.org"]},
    )
    assert resp.status_code == 200, resp.text
    upn, _gid, payload = graph.updated[-1]
    assert upn.startswith("prep-recruiter-")
    assert set(payload) == {"attendees"}
    addresses = [a["emailAddress"]["address"] for a in payload["attendees"]]
    assert addresses[0].startswith("prep-cand-")
    assert addresses[1:] == [
        a for a in addresses[1:] if not a.startswith("prep-recruiter-")
    ]
    assert "gosc@example.org" in addresses
    async with AsyncSessionLocal() as db:
        ev = await db.get(CalendarEvent, event_id)
        assert {a["address"] for a in ev.attendees} == set(addresses)

    # Ta sama lista drugi raz = nic do Outlooka.
    again = await app_client.patch(
        f"/api/interview-cycle/preps/{event_id}",
        headers=dl_h,
        json={"attendee_user_ids": [dl_id], "attendee_emails": ["gosc@example.org"]},
    )
    assert again.status_code == 200
    assert len(graph.updated) == 1


async def test_recruiter_cancels_and_can_plan_the_prep_again(
    app_client: AsyncClient, graph: EditingGraph
):
    ctx = await _prep1_by_recruiter(app_client)
    _rec_id, rec_h = ctx["rec"]
    dl_id, _ = ctx["dl"]
    event_id = ctx["event_id"]

    resp = await app_client.post(
        f"/api/interview-cycle/preps/{event_id}/cancel",
        headers=rec_h,
        json={"comment": "Kandydat poprosił o inny termin."},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "cancelled"
    upn, _gid, comment = graph.cancelled[-1]
    assert upn.startswith("prep-delivery_lead-")
    assert comment == "Kandydat poprosił o inny termin."

    again = await app_client.post(
        f"/api/interview-cycle/preps/{event_id}/cancel", headers=rec_h, json={}
    )
    assert again.status_code == 200
    assert len(graph.cancelled) == 1

    moved = await app_client.patch(
        f"/api/interview-cycle/preps/{event_id}",
        headers=rec_h,
        json={"start": _at(80), "end": _at(81)},
    )
    assert moved.status_code == 409

    replanned = await _create(
        app_client,
        rec_h,
        candidate_id=ctx["cand_id"],
        job_id=ctx["job_id"],
        prep_no=1,
        organizer_user_id=dl_id,
        start=_at(50),
        end=_at(50.75),
    )
    assert replanned.status_code == 201, replanned.text


async def test_new_organizer_gets_a_new_meeting_and_the_old_one_is_cancelled(
    app_client: AsyncClient, graph: EditingGraph
):
    ctx = await _prep1_by_recruiter(app_client)
    rec_id, rec_h = ctx["rec"]
    event_id = ctx["event_id"]

    resp = await app_client.patch(
        f"/api/interview-cycle/preps/{event_id}",
        headers=rec_h,
        json={"organizer_user_id": rec_id, "client_request_id": "swap-1"},
    )
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["event_id"] != event_id
    assert out["organizer"]["id"] == rec_id
    new_upn, _payload = graph.created[-1]
    assert new_upn.startswith("prep-recruiter-")
    old_upn, _gid, comment = graph.cancelled[-1]
    assert old_upn.startswith("prep-delivery_lead-")
    assert "Prep poprowadzi Ola Rekruter" in comment

    async with AsyncSessionLocal() as db:
        old = await db.get(CalendarEvent, event_id)
        assert old.status == EventStatus.cancelled
        old_prep = await db.scalar(
            select(PrepMeeting).where(PrepMeeting.calendar_event_id == event_id)
        )
        assert old_prep.transcript_status == "cancelled"


async def test_failed_cancel_of_the_old_meeting_changes_nothing(
    app_client: AsyncClient, graph: EditingGraph
):
    ctx = await _prep1_by_recruiter(app_client)
    rec_id, rec_h = ctx["rec"]
    event_id = ctx["event_id"]
    async with AsyncSessionLocal() as db:
        dl = await db.get(User, ctx["dl"][0])
        graph.fail_cancel_for = dl.email

    resp = await app_client.patch(
        f"/api/interview-cycle/preps/{event_id}",
        headers=rec_h,
        json={"organizer_user_id": rec_id},
    )
    assert resp.status_code == 502, resp.text
    # Nowe spotkanie zostało odwołane, żeby kandydat nie miał dwóch.
    undo_upn, _gid, _comment = graph.cancelled[-1]
    assert undo_upn.startswith("prep-recruiter-")
    async with AsyncSessionLocal() as db:
        old = await db.get(CalendarEvent, event_id)
        assert old.status == EventStatus.scheduled
        preps = (
            await db.scalars(
                select(PrepMeeting).where(
                    PrepMeeting.candidate_id == ctx["cand_id"],
                    PrepMeeting.job_id == ctx["job_id"],
                )
            )
        ).all()
        assert [p.calendar_event_id for p in preps] == [event_id]


async def test_prep_that_already_happened_cannot_be_changed(
    app_client: AsyncClient, graph: EditingGraph
):
    ctx = await _prep1_by_recruiter(app_client, hours=-2)
    _rec_id, rec_h = ctx["rec"]
    resp = await app_client.patch(
        f"/api/interview-cycle/preps/{ctx['event_id']}",
        headers=rec_h,
        json={"start": _at(24), "end": _at(25)},
    )
    assert resp.status_code == 409, resp.text
    assert graph.updated == []


# ── Czyste reguły (bez bazy) ─────────────────────────────────────────────────


def _person(uid: int, email: str, role: UserRole = UserRole.recruiter) -> User:
    return User(id=uid, email=email, name=f"Osoba {uid}", role=role, roles=[role.value])


def test_attendee_list_puts_candidate_first_and_skips_organizer_and_repeats():
    out = prep_meetings.attendee_emails(
        candidate_email="kandydat@example.com",
        organizer_email="Lead@Example.com",
        users=[_person(1, "lead@example.com"), _person(2, "rek@example.com")],
        emails=["REK@example.com", " gosc@example.org ", "kandydat@EXAMPLE.com"],
    )
    assert out == ["kandydat@example.com", "rek@example.com", "gosc@example.org"]


@pytest.mark.parametrize(
    ("role", "uid", "expected"),
    [
        (UserRole.recruiter, 7, True),
        (UserRole.recruiter, 8, False),
        (UserRole.delivery_lead, 8, False),
        (UserRole.head_of_recruitment, 8, True),
        (UserRole.admin, 8, True),
    ],
)
def test_only_people_of_the_pair_and_oversight_can_edit(role, uid, expected):
    assert (
        prep_meetings.user_can_edit_prep(_person(uid, "x@example.com", role), {7, 9})
        is expected
    )


def test_closed_prep_is_refused():
    now = datetime.now(timezone.utc)
    cancelled = CalendarEvent(
        start_time=now + timedelta(hours=2),
        end_time=now + timedelta(hours=3),
        status=EventStatus.cancelled,
    )
    past = CalendarEvent(
        start_time=now - timedelta(hours=2),
        end_time=now - timedelta(hours=1),
        status=EventStatus.scheduled,
    )
    ahead = CalendarEvent(
        start_time=now + timedelta(hours=2),
        end_time=now + timedelta(hours=3),
        status=EventStatus.scheduled,
    )
    for event in (cancelled, past):
        with pytest.raises(Exception) as err:
            prep_meetings.ensure_prep_open(event, now)
        assert getattr(err.value, "status_code", None) == 409
    prep_meetings.ensure_prep_open(ahead, now)
