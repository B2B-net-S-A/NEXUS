"""Odpowiedź kandydata na prep, zmiany z Outlooka i powiadomienia pary (0453).

Zgłoszenie DL-a (17.10.2026, decyzje D5–D8): NEXUS nie czytał odpowiedzi
kandydata, zmianę z Outlooka widział dopiero po starej godzinie prepu, a DL
nie dowiadywał się, że rekruter założył prep w jego kalendarzu.

Graph podmieniony na poziomie ``teams_prep_graph`` — trasy, pętla odczytu,
zapisy i powiadomienia działają naprawdę.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.notification import Notification, NotificationType
from app.models.prep_meeting import PrepMeeting
from app.models.user import UserRole
from app.services import notification_triggers, prep_attention, prep_responses
from app.services.m365 import teams_prep_graph
from app.services.m365.graph_client import GraphRequestError
from app.services.m365.teams_prep_graph import AttendeeResponse, parse_attendees
from tests.test_prep_editing import EditingGraph, graph  # noqa: F401 — fikstura
from tests.test_prep_meetings_flow import _at, _create, _pair, _user


class ResponseGraph(EditingGraph):
    """Stan per wydarzenie: baza testów jest wspólna w shardzie, a pętla
    czyta WSZYSTKIE nadchodzące prepy — prepy innych testów dostają ``None``
    (pominięte), nie stan i nie 404 tego testu."""

    def __init__(self) -> None:
        super().__init__()
        self.states: dict[str, dict] = {}
        self.missing: set[str] = set()

    async def get_event(self, upn, graph_event_id):
        if graph_event_id in self.missing:
            raise GraphRequestError(404, {"error": "x"})
        return self.states.get(graph_event_id)


@pytest.fixture
def rgraph(monkeypatch, graph):  # noqa: F811 — fikstura z test_prep_editing
    fake = ResponseGraph()
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
    return fake


async def _notes(user_id: int) -> list[Notification]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(Notification)
                    .where(Notification.user_id == user_id)
                    .order_by(Notification.id)
                )
            ).all()
        )


async def _prep2_by_recruiter(app_client, *, hours: float = 48.0):
    """Rekruter zakłada Prep 2 u siebie; DL rekrutacji jest w parze."""
    rec_id, rec_h = await _user(UserRole.recruiter, "Ola Rekruter")
    dl_id, dl_h = await _user(UserRole.delivery_lead, "Kasia Lead")
    job_id, cand_id = await _pair(recruiter_id=rec_id, dl_id=dl_id)
    resp = await _create(
        app_client,
        rec_h,
        candidate_id=cand_id,
        job_id=job_id,
        prep_no=2,
        organizer_user_id=rec_id,
        start=_at(hours),
        end=_at(hours + 0.75),
    )
    assert resp.status_code == 201, resp.text
    event_id = resp.json()["event_id"]
    async with AsyncSessionLocal() as db:
        ev = await db.get(CalendarEvent, event_id)
        cand_email = ev.attendees[0]["address"]
        start, end = ev.start_time, ev.end_time
        gid = ev.external_id
    return {
        "rec": (rec_id, rec_h),
        "dl": (dl_id, dl_h),
        "event_id": event_id,
        "gid": gid,
        "cand_email": cand_email,
        "start": start,
        "end": end,
    }


def _state(ctx, *, response="none", proposed=None, start=None, end=None):
    att = AttendeeResponse(
        email=ctx["cand_email"].lower(),
        response=response,
        time=datetime.now(timezone.utc),
        proposed_start=proposed[0] if proposed else None,
        proposed_end=proposed[1] if proposed else None,
    )
    return {
        "isCancelled": False,
        "start": start or ctx["start"],
        "end": end or ctx["end"],
        "join_url": None,
        "attendees": [att],
    }


async def test_new_prep_waits_for_an_answer_and_dl_hears_it_was_planned(
    app_client: AsyncClient, rgraph: ResponseGraph
):
    ctx = await _prep2_by_recruiter(app_client)
    dl_id, _ = ctx["dl"]
    rec_id, _ = ctx["rec"]
    async with AsyncSessionLocal() as db:
        prep = await db.scalar(
            select(PrepMeeting).where(PrepMeeting.calendar_event_id == ctx["event_id"])
        )
        assert prep.candidate_response == "none"
    dl_notes = await _notes(dl_id)
    assert [n.notification_type for n in dl_notes] == [NotificationType.prep_changed]
    assert dl_notes[0].title.startswith("Prep 2 zaplanowany")
    # Autor nie dostaje nic o własnym ruchu.
    assert await _notes(rec_id) == []


async def test_accepted_answer_reaches_the_whole_pair(
    app_client: AsyncClient, rgraph: ResponseGraph
):
    ctx = await _prep2_by_recruiter(app_client)
    dl_id, _ = ctx["dl"]
    rec_id, _ = ctx["rec"]
    rgraph.states[ctx["gid"]] = _state(ctx, response="accepted")
    async with AsyncSessionLocal() as db:
        stats = await prep_responses.sync_upcoming(db)
    assert stats.responses >= 1
    async with AsyncSessionLocal() as db:
        prep = await db.scalar(
            select(PrepMeeting).where(PrepMeeting.calendar_event_id == ctx["event_id"])
        )
        assert prep.candidate_response == "accepted"
        assert prep.candidate_response_at is not None
    for uid in (dl_id, rec_id):
        types = [n.notification_type for n in await _notes(uid)]
        assert NotificationType.prep_candidate_response in types

    # Ta sama odpowiedź przy kolejnym odczycie — nic nowego.
    async with AsyncSessionLocal() as db:
        await prep_responses.sync_upcoming(db)
    types = [n.notification_type for n in await _notes(dl_id)]
    assert types.count(NotificationType.prep_candidate_response) == 1

    detail = await app_client.get(
        f"/api/interview-cycle/preps/{ctx['event_id']}", headers=ctx["dl"][1]
    )
    assert detail.json()["candidate_response"] == "accepted"


async def test_first_read_of_an_old_prep_is_silent_about_accepting(
    app_client: AsyncClient, rgraph: ResponseGraph
):
    ctx = await _prep2_by_recruiter(app_client)
    dl_id, _ = ctx["dl"]
    async with AsyncSessionLocal() as db:
        prep = await db.scalar(
            select(PrepMeeting).where(PrepMeeting.calendar_event_id == ctx["event_id"])
        )
        prep.candidate_response = None  # prep sprzed 0453
        await db.commit()
    rgraph.states[ctx["gid"]] = _state(ctx, response="accepted")
    async with AsyncSessionLocal() as db:
        await prep_responses.sync_upcoming(db)
    types = [n.notification_type for n in await _notes(dl_id)]
    assert NotificationType.prep_candidate_response not in types


async def test_proposed_time_rings_and_shows_on_the_board(
    app_client: AsyncClient, rgraph: ResponseGraph
):
    from app.services.interview_cycle import interview_badges_for_job

    ctx = await _prep2_by_recruiter(app_client)
    dl_id, _ = ctx["dl"]
    proposed = (ctx["start"] + timedelta(hours=3), ctx["end"] + timedelta(hours=3))
    rgraph.states[ctx["gid"]] = _state(ctx, response="declined", proposed=proposed)
    async with AsyncSessionLocal() as db:
        await prep_responses.sync_upcoming(db)
    notes = [
        n
        for n in await _notes(dl_id)
        if n.notification_type == NotificationType.prep_candidate_declined
    ]
    assert len(notes) == 1 and "proponuje" in notes[0].title
    async with AsyncSessionLocal() as db:
        prep = await db.scalar(
            select(PrepMeeting).where(PrepMeeting.calendar_event_id == ctx["event_id"])
        )
        assert prep.candidate_response == "declined"
        assert prep.proposed_start is not None
        # Rozmowa u klienta za 5 dni — prep jest przed nią, plakietka pary
        # mówi, że kandydat proponuje inny termin.
        db.add(
            CalendarEvent(
                title="Rozmowa u klienta",
                event_type=EventType.client_interview,
                start_time=datetime.now(timezone.utc) + timedelta(days=5),
                end_time=datetime.now(timezone.utc) + timedelta(days=5, hours=1),
                candidate_id=prep.candidate_id,
                job_id=prep.job_id,
                created_by=ctx["dl"][0],
                operational_owner_id=ctx["dl"][0],
            )
        )
        await db.commit()
        badges = await interview_badges_for_job(
            db, job_id=prep.job_id, candidate_ids=[prep.candidate_id]
        )
    badge = badges[prep.candidate_id]
    assert badge["kind"] == "prep_refused"
    assert badge["label"].startswith("Prep 2: kandydat proponuje")


async def test_change_in_outlook_is_seen_within_one_pass(
    app_client: AsyncClient, rgraph: ResponseGraph
):
    ctx = await _prep2_by_recruiter(app_client)
    dl_id, _ = ctx["dl"]
    new_start = ctx["start"] + timedelta(hours=5)
    new_end = ctx["end"] + timedelta(hours=5)
    rgraph.states[ctx["gid"]] = _state(ctx, start=new_start, end=new_end)
    async with AsyncSessionLocal() as db:
        stats = await prep_responses.sync_upcoming(db)
    assert stats.moved == 1
    async with AsyncSessionLocal() as db:
        ev = await db.get(CalendarEvent, ctx["event_id"])
        assert ev.start_time == new_start
    titles = [n.title for n in await _notes(dl_id)]
    assert any(t.startswith("Prep 2 przełożony na") for t in titles)

    rgraph.missing.add(ctx["gid"])
    async with AsyncSessionLocal() as db:
        stats = await prep_responses.sync_upcoming(db)
    assert stats.cancelled == 1
    async with AsyncSessionLocal() as db:
        ev = await db.get(CalendarEvent, ctx["event_id"])
        assert ev.status == EventStatus.cancelled


async def test_no_answer_a_day_before_reminds_once(
    app_client: AsyncClient, rgraph: ResponseGraph
):
    ctx = await _prep2_by_recruiter(app_client, hours=20)
    rec_id, _ = ctx["rec"]
    dl_id, _ = ctx["dl"]
    async with AsyncSessionLocal() as db:
        prep = await db.scalar(
            select(PrepMeeting).where(PrepMeeting.calendar_event_id == ctx["event_id"])
        )
        prep.created_at = datetime.now(timezone.utc) - timedelta(hours=5)
        await db.commit()
    rgraph.states[ctx["gid"]] = _state(ctx, response="none")
    for _ in range(2):
        async with AsyncSessionLocal() as db:
            await prep_responses.sync_upcoming(db)
    reminders = [
        n
        for n in await _notes(rec_id)
        if n.notification_type == NotificationType.prep_no_response
    ]
    assert len(reminders) == 1
    # Przypomnienie idzie do prowadzącego i planującego, nie do całej pary.
    assert not [
        n
        for n in await _notes(dl_id)
        if n.notification_type == NotificationType.prep_no_response
    ]


async def test_dl_move_rings_in_the_recruiter_calendar_and_resets_the_answer(
    app_client: AsyncClient, rgraph: ResponseGraph
):
    ctx = await _prep2_by_recruiter(app_client)
    rec_id, _ = ctx["rec"]
    _dl_id, dl_h = ctx["dl"]
    async with AsyncSessionLocal() as db:
        prep = await db.scalar(
            select(PrepMeeting).where(PrepMeeting.calendar_event_id == ctx["event_id"])
        )
        prep.candidate_response = "accepted"
        await db.commit()
    resp = await app_client.patch(
        f"/api/interview-cycle/preps/{ctx['event_id']}",
        headers=dl_h,
        json={"start": _at(60), "end": _at(60.75)},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["candidate_response"] == "none"
    yours = [
        n
        for n in await _notes(rec_id)
        if n.notification_type == NotificationType.prep_changed_yours
    ]
    assert len(yours) == 1 and yours[0].title.startswith("Twój Prep 2 przełożony")


async def test_planned_then_moved_the_same_day_both_reach_the_dl(
    app_client: AsyncClient, rgraph: ResponseGraph
):
    """``ix_notif_dedup_daily`` nie zna rodzaju encji: oba wpisy to
    ``prep_changed`` tego samego wydarzenia w tym samym dniu — drugi był
    odrzucany, zanim zmiany prepu poszły bez ID encji."""
    ctx = await _prep2_by_recruiter(app_client)
    dl_id, _ = ctx["dl"]
    _rec_id, rec_h = ctx["rec"]
    resp = await app_client.patch(
        f"/api/interview-cycle/preps/{ctx['event_id']}",
        headers=rec_h,
        json={"start": _at(70), "end": _at(70.75)},
    )
    assert resp.status_code == 200, resp.text
    titles = [
        n.title
        for n in await _notes(dl_id)
        if n.notification_type == NotificationType.prep_changed
    ]
    assert any(t.startswith("Prep 2 zaplanowany") for t in titles)
    assert any(t.startswith("Prep 2 przełożony na") for t in titles)


async def test_prep_attention_also_reaches_the_dl(
    app_client: AsyncClient, rgraph: ResponseGraph, monkeypatch
):
    ctx = await _prep2_by_recruiter(app_client)
    rec_id, _ = ctx["rec"]
    dl_id, _ = ctx["dl"]
    async with AsyncSessionLocal() as db:
        prep = await db.scalar(
            select(PrepMeeting).where(PrepMeeting.calendar_event_id == ctx["event_id"])
        )
        item = prep_attention.PrepAttention(
            reason="weak",
            prep_no=2,
            candidate_id=prep.candidate_id,
            job_id=prep.job_id,
            interview_event_id=ctx["event_id"],
            interview_start=datetime.now(timezone.utc) + timedelta(days=2),
            prep_event_id=ctx["event_id"],
            owner_id=rec_id,
            urgent=False,
        )

    async def _items(_db, _now):
        return [item]

    monkeypatch.setattr(prep_attention, "load_prep_attention", _items)
    monkeypatch.setattr(notification_triggers, "_PREP_ATTENTION_LAST_RUN", None)
    async with AsyncSessionLocal() as db:
        await notification_triggers.check_prep_attention(db, datetime.now(timezone.utc))
        await db.commit()
    types = [n.notification_type for n in await _notes(dl_id)]
    assert NotificationType.prep_attention in types


# ── Czyste (bez bazy) ────────────────────────────────────────────────────────


def test_graph_attendees_are_parsed_with_proposal_and_without_zero_date():
    parsed = parse_attendees(
        [
            {
                "emailAddress": {"address": "Kandydat@Example.com"},
                "status": {"response": "declined", "time": "2031-10-01T08:00:00Z"},
                "proposedNewTime": {
                    "start": {
                        "dateTime": "2031-10-03T09:00:00.0000000",
                        "timeZone": "UTC",
                    },
                    "end": {
                        "dateTime": "2031-10-03T09:45:00.0000000",
                        "timeZone": "UTC",
                    },
                },
            },
            {
                "emailAddress": {"address": "rek@example.com"},
                "status": {"response": "none", "time": "0001-01-01T00:00:00Z"},
            },
            {"emailAddress": {}},
            "śmieć",
        ]
    )
    assert [a.email for a in parsed] == ["kandydat@example.com", "rek@example.com"]
    first, second = parsed
    assert first.response == "declined"
    assert first.proposed_start == datetime(2031, 10, 3, 9, 0, tzinfo=timezone.utc)
    assert first.proposed_end == datetime(2031, 10, 3, 9, 45, tzinfo=timezone.utc)
    assert second.time is None and second.proposed_start is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("accepted", "accepted"),
        ("tentativelyAccepted", "tentative"),
        ("declined", "declined"),
        ("notResponded", "none"),
        ("organizer", "none"),
        (None, "none"),
    ],
)
def test_graph_response_maps_to_the_nexus_vocabulary(raw, expected):
    assert prep_responses.normalize_response(raw) == expected
