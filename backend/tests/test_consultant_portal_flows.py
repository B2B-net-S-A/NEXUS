"""Portal konsultanta: FAQ, Twoje sprawy, rozmowy, oceny, Jakość. Graph to atrapa.

Dla każdej odmowy osobny test; dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select, update

from app.core.database import AsyncSessionLocal
from app.models.admin_case import AdminCase, AdminCaseComment, AdminCaseMessage
from app.models.consultant_portal import CpLink, CpMeeting, CpRating
from app.models.notification import Notification, NotificationType
from app.models.user import UserRole
from app.services import prep_availability
from app.services.consultant_portal import (
    auth,
    content,
    mailbox,
    meetings,
    portal_mail,
    ratings,
    transcripts,
)
from app.services.m365 import teams_prep_graph
from app.services.m365.graph_client import GraphRequestError
from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING
from tests.care_announcements_seed import (  # noqa: F401  (fixture'y)
    _set_setting,
    care_off,
    care_on,
    divisions_restored,
    headers as staff_headers,
    make_head,
    make_user,
    tag,
)
from tests.consultant_portal_seed import (  # noqa: F401  (fixture'y)
    BASE,
    SESSION,
    STAFF,
    clean_team,
    install_mailer,
    make_meeting,
    make_member,
    make_person,
    portal_all,
    portal_restored,
    session_headers,
)

pytestmark = pytest.mark.asyncio


# ── FAQ ──────────────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("portal_all", "care_on", "clean_team")
async def test_back_office_edits_faq_and_consultant_reads_published(app_client) -> None:
    member = await make_member("care")
    created = await app_client.post(
        f"{STAFF}/faq",
        headers=staff_headers(member),
        json={
            "topic": "invoice",
            "question": f"Do kiedy faktura {tag()}?",
            "answer": "Do piątego dnia miesiąca.",
        },
    )
    assert created.status_code == 201, created.text
    draft = await app_client.post(
        f"{STAFF}/faq",
        headers=staff_headers(member),
        json={
            "topic": "invoice",
            "question": f"Szkic {tag()}",
            "answer": "Jeszcze nie.",
            "published": False,
        },
    )
    person = await make_person()
    portal = await session_headers(app_client, person)
    listed = (await app_client.get(f"{BASE}/faq", headers=portal)).json()["items"]
    ids = {row["id"] for row in listed}
    assert created.json()["id"] in ids
    assert draft.json()["id"] not in ids
    # Zmiana i kasowanie działają, a konsultant widzi stan po nich.
    item_id = created.json()["id"]
    updated = await app_client.put(
        f"{STAFF}/faq/{item_id}",
        headers=staff_headers(member),
        json={
            "topic": "contract",
            "question": "Nowe pytanie",
            "answer": "Nowa odpowiedź.",
            "published": False,
        },
    )
    assert updated.status_code == 200
    listed = (await app_client.get(f"{BASE}/faq", headers=portal)).json()["items"]
    assert item_id not in {row["id"] for row in listed}
    assert (
        await app_client.delete(f"{STAFF}/faq/{item_id}", headers=staff_headers(member))
    ).status_code == 204
    assert (
        await app_client.delete(f"{STAFF}/faq/{item_id}", headers=staff_headers(member))
    ).status_code == 404


@pytest.mark.usefixtures("care_on", "clean_team")
async def test_outsider_cannot_edit_faq(app_client) -> None:
    await make_member("care")
    outsider = await make_user(UserRole.recruiter)
    response = await app_client.get(f"{STAFF}/faq", headers=staff_headers(outsider))
    assert response.status_code == 403


@pytest.mark.usefixtures("care_off")
async def test_staff_routes_are_404_with_module_off(app_client) -> None:
    admin = await make_user(UserRole.admin)
    response = await app_client.get(f"{STAFF}/faq", headers=staff_headers(admin))
    assert response.status_code == 404


# ── Wyłącznik od strony admina ───────────────────────────────────────────────


@pytest.mark.usefixtures("portal_all", "care_off")
async def test_module_off_closes_the_portal_too(app_client, monkeypatch) -> None:
    """Wycofanie to wyłączenie modułu: portal bez niego nie zostaje otwarty dla ludzi z zewnątrz."""

    fake = install_mailer(monkeypatch)
    person = await make_person()
    status_response = await app_client.get(f"{BASE}/status")
    assert status_response.status_code == 404
    link = await app_client.post(f"{BASE}/link", json={"email": person.email})
    assert link.status_code == 404
    async with AsyncSessionLocal() as db:
        outcome = await portal_mail.send(
            db,
            contract_id=person.contract_id,
            to=person.email,
            subject="Temat",
            text="Treść",
        )
        assert outcome is None
        assert (await ratings.run_once(db))["status"] == "disabled"
        assert (await mailbox.run_once(db))["status"] == "disabled"
    assert fake.sent == []


@pytest.mark.usefixtures("portal_all", "care_on")
async def test_switching_off_ends_open_sessions(app_client) -> None:
    person = await make_person()
    session = await session_headers(app_client, person)
    admin = await make_user(UserRole.admin)
    off = await app_client.put(
        f"{STAFF}/settings",
        headers=staff_headers(admin),
        json={"state": "off", "pilot_contract_ids": []},
    )
    assert off.status_code == 200
    back_on = await app_client.put(
        f"{STAFF}/settings",
        headers=staff_headers(admin),
        json={"state": "all", "pilot_contract_ids": []},
    )
    assert back_on.status_code == 200
    me = await app_client.get(f"{BASE}/me", headers=session)
    assert me.status_code == 401


@pytest.mark.usefixtures("portal_restored", "care_on", "clean_team")
async def test_only_admin_flips_the_switch(app_client) -> None:
    member = await make_member("care")
    refused = await app_client.put(
        f"{STAFF}/settings", headers=staff_headers(member), json={"state": "all"}
    )
    assert refused.status_code == 403
    admin = await make_user(UserRole.admin)
    saved = await app_client.put(
        f"{STAFF}/settings",
        headers=staff_headers(admin),
        json={"state": "pilot", "pilot_contract_ids": [5, 7]},
    )
    assert saved.json() == {"state": "pilot", "pilot_contract_ids": [5, 7]}
    wrong = await app_client.put(
        f"{STAFF}/settings", headers=staff_headers(admin), json={"state": "everyone"}
    )
    assert wrong.status_code == 422


# ── Twoje sprawy ─────────────────────────────────────────────────────────────


async def _case(person, *, source, key, area="administration", title="Sprawa") -> int:
    async with AsyncSessionLocal() as db:
        case = AdminCase(
            title=title,
            area=area,
            priority="P2",
            status="new",
            source=source,
            source_key=key,
            contract_id=person.contract_id,
            description="Notatka wewnętrzna: nie pokazywać",
        )
        db.add(case)
        await db.commit()
        return case.id


@pytest.mark.usefixtures("portal_all", "care_on")
async def test_new_request_lands_in_own_cases(app_client) -> None:
    person = await make_person()
    portal = await session_headers(app_client, person)
    created = await app_client.post(
        f"{BASE}/cases",
        headers=portal,
        json={"topic": "invoice", "title": "Faktura po aneksie", "body": "Od kiedy?"},
    )
    assert created.status_code == 201, created.text
    items = (await app_client.get(f"{BASE}/cases", headers=portal)).json()["items"]
    assert [row["title"] for row in items] == ["Faktura po aneksie"]
    async with AsyncSessionLocal() as db:
        case = await db.get(AdminCase, created.json()["id"])
    assert case.source == "portal"
    assert case.source_key.startswith("portal:")
    assert case.contract_id == person.contract_id
    assert "Od kiedy?" in (case.description or "")


@pytest.mark.usefixtures("portal_all")
async def test_new_request_refused_when_cases_module_is_dark(app_client) -> None:
    await _set_setting(
        HR_MODULES_SETTING,
        {**{key: False for key in HR_MODULE_KEYS}, "back_office": True},
    )
    person = await make_person()
    portal = await session_headers(app_client, person)
    response = await app_client.post(
        f"{BASE}/cases",
        headers=portal,
        json={"topic": "invoice", "title": "Temat", "body": "Opis sprawy"},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "cases_off"


@pytest.mark.usefixtures("portal_all", "care_on")
async def test_daily_request_limit(app_client, monkeypatch) -> None:
    monkeypatch.setattr(content, "CASES_PER_DAY", 2)
    person = await make_person()
    portal = await session_headers(app_client, person)
    body = {"topic": "data", "title": "Temat", "body": "Opis sprawy"}
    for _ in range(2):
        response = await app_client.post(f"{BASE}/cases", headers=portal, json=body)
        assert response.status_code == 201
    response = await app_client.post(f"{BASE}/cases", headers=portal, json=body)
    assert response.status_code == 429


@pytest.mark.usefixtures("portal_all")
async def test_consultant_never_sees_other_kinds_of_cases(app_client) -> None:
    person = await make_person()
    other = await make_person()
    marker = tag()
    visible = await _case(person, source="portal", key=f"portal:{marker}", title="Moje")
    # Automaty, negocjacje, ocena niska i cudze: nic z tego nie wychodzi.
    await _case(person, source="contract", key=f"c:{marker}", title="Koniec współpracy")
    await _case(person, source="lifecycle", key=f"l:{marker}", title="Wyjście")
    await _case(
        person,
        source="portal",
        key=f"portal:n-{marker}",
        area="negotiation",
        title="Nowa stawka",
    )
    await _case(person, source="manual", key=None, title="Ręczna notatka")
    await _case(person, source="portal", key=f"inne:{marker}", title="Spoza prefiksu")
    await _case(other, source="portal", key=f"portal:o-{marker}", title="Cudza")
    portal = await session_headers(app_client, person)
    items = (await app_client.get(f"{BASE}/cases", headers=portal)).json()["items"]
    assert [row["id"] for row in items] == [visible]
    assert "Notatka wewnętrzna" not in str(items)
    assert not {"description", "checklist", "comments", "messages"} & set(items[0])


@pytest.mark.usefixtures("portal_all")
async def test_mail_case_visible_only_for_own_message(app_client) -> None:
    person = await make_person()
    marker = tag()
    own = await _case(person, source="mail", key=f"mail:{marker}", title="Mój mail")
    someone = await _case(
        person, source="mail", key=f"mail:x{marker}", title="Mail od kierownika klienta"
    )
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                AdminCaseMessage(
                    case_id=own,
                    graph_message_id=f"g-{marker}",
                    sender_email=person.email.upper(),
                ),
                AdminCaseMessage(
                    case_id=someone,
                    graph_message_id=f"h-{marker}",
                    sender_email="kierownik@example.com",
                ),
            ]
        )
        await db.commit()
    portal = await session_headers(app_client, person)
    items = (await app_client.get(f"{BASE}/cases", headers=portal)).json()["items"]
    assert [row["id"] for row in items] == [own]


def test_who_waits_for_whom() -> None:
    assert content.waiting_label("done", "Ola")["who"] == "done"
    # Wolny tekst „Czeka na” zostaje wewnętrzny: konsultant dostaje stałą etykietę.
    assert content.waiting_label("waiting", "Ola") == {
        "who": "other",
        "label": "Czekamy na odpowiedź",
    }
    assert content.waiting_label("new", None)["who"] == "nobody"
    assert content.waiting_label("in_progress", "Ola") == {
        "who": "us",
        "label": "Po naszej stronie: Ola",
    }


# ── Terminy (czyste) ─────────────────────────────────────────────────────────


NOW = datetime(2026, 11, 2, 8, 0, tzinfo=timezone.utc)  # poniedziałek, 9:00 w Warszawie


def test_unknown_calendar_gives_no_slots() -> None:
    assert meetings.slots_for(now=NOW, busy=None) == []


def test_slots_respect_lead_time_busy_and_booked() -> None:
    busy = [(NOW + timedelta(hours=2), NOW + timedelta(hours=3))]
    booked = [(NOW + timedelta(hours=4), NOW + timedelta(hours=5))]
    slots = meetings.slots_for(now=NOW, busy=busy, booked=booked, limit=50)
    assert slots, "powinny być wolne terminy"
    assert min(slots) >= NOW + meetings.MIN_LEAD
    length = timedelta(minutes=meetings.MEETING_MINUTES)
    for start in slots:
        for block_start, block_end in [*busy, *booked]:
            assert not (start < block_end and block_start < start + length)


def test_slots_skip_weekends_and_stay_in_work_hours() -> None:
    from zoneinfo import ZoneInfo

    friday = datetime(2026, 11, 6, 8, 0, tzinfo=timezone.utc)
    zone = ZoneInfo("Europe/Warsaw")
    for start in meetings.slots_for(now=friday, busy=[], limit=60):
        local = start.astimezone(zone)
        assert local.weekday() < 5
        assert meetings.WORK_START <= local.time() < meetings.WORK_END


# ── Rezerwacja przez atrapę Grapha ───────────────────────────────────────────


class FakeGraph:
    def __init__(self, monkeypatch, *, create_error=None, cancel_error=None) -> None:
        self.created: list[tuple[str, dict]] = []
        self.cancelled: list[str] = []
        self.create_error = create_error
        self.cancel_error = cancel_error
        monkeypatch.setattr(teams_prep_graph, "create_event", self._create)
        monkeypatch.setattr(teams_prep_graph, "cancel_event", self._cancel)

    async def _create(self, upn, payload):
        if self.create_error:
            raise self.create_error
        self.created.append((upn, payload))
        return teams_prep_graph.CreatedPrepEvent(
            graph_event_id=f"event-{len(self.created)}",
            change_key=None,
            join_url="https://teams.example.com/meet/1",
        )

    async def _cancel(self, upn, event_id, comment):
        if self.cancel_error:
            raise self.cancel_error
        self.cancelled.append(event_id)
        return "cancelled"


def _ready(monkeypatch) -> None:
    monkeypatch.setattr(
        meetings.settings, "CONSULTANT_PORTAL_MAILBOX", "wsparcie@example.com"
    )
    monkeypatch.setattr(meetings.prep_meetings, "app_only_ready", lambda: True)

    async def free(emails, *, start, end):
        return {email.lower(): [] for email in emails}

    monkeypatch.setattr(prep_availability, "busy_blocks", free)


async def _first_slot(client, portal, host_id) -> str:
    listed = await client.get(
        f"{BASE}/booking/hosts", params={"topic": "invoice"}, headers=portal
    )
    assert listed.status_code == 200, listed.text
    host = next(row for row in listed.json()["hosts"] if row["id"] == host_id)
    assert host["slots"], host
    return host["slots"][0]


@pytest.mark.usefixtures("portal_all", "care_on", "clean_team")
async def test_booking_refused_without_configuration(app_client, monkeypatch) -> None:
    monkeypatch.setattr(meetings.settings, "CONSULTANT_PORTAL_MAILBOX", "")
    host = await make_member("finance")
    person = await make_person()
    portal = await session_headers(app_client, person)
    listed = await app_client.get(
        f"{BASE}/booking/hosts", params={"topic": "invoice"}, headers=portal
    )
    assert listed.status_code == 200
    assert listed.json()["available"] is False
    assert "chwilowo niedostępna" in listed.json()["message"]
    response = await app_client.post(
        f"{BASE}/meetings",
        headers=portal,
        json={
            "host_user_id": host.id,
            "start": datetime.now(timezone.utc).isoformat(),
            "topic": "invoice",
        },
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "booking_off"


@pytest.mark.usefixtures("portal_all", "care_on", "clean_team")
async def test_booking_goes_to_organizer_and_opens_a_case(
    app_client, monkeypatch
) -> None:
    _ready(monkeypatch)
    graph = FakeGraph(monkeypatch)
    host = await make_member("finance")
    person = await make_person()
    portal = await session_headers(app_client, person)
    slot = await _first_slot(app_client, portal, host.id)
    response = await app_client.post(
        f"{BASE}/meetings",
        headers=portal,
        json={
            "host_user_id": host.id,
            "start": slot,
            "topic": "invoice",
            "reason": "Od kiedy nowa stawka?",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "booked"
    upn, payload = graph.created[0]
    assert upn == "wsparcie@example.com"
    attendees = {a["emailAddress"]["address"] for a in payload["attendees"]}
    assert attendees == {host.email, person.email}
    assert payload["isOnlineMeeting"] is True
    assert "transactionId" in payload
    async with AsyncSessionLocal() as db:
        meeting = await db.get(CpMeeting, response.json()["id"])
        case = await db.get(AdminCase, meeting.case_id)
    assert case.source == "portal" and case.contract_id == person.contract_id
    assert meeting.next_fetch_at is not None
    listed = (await app_client.get(f"{BASE}/meetings", headers=portal)).json()["items"]
    assert listed[0]["join_url"] == "https://teams.example.com/meet/1"
    assert not {"transcript_text", "summary", "action_items"} & set(listed[0])


@pytest.mark.usefixtures("portal_all", "care_on", "clean_team")
async def test_same_slot_cannot_be_booked_twice(app_client, monkeypatch) -> None:
    _ready(monkeypatch)
    FakeGraph(monkeypatch)
    host = await make_member("finance")
    first = await make_person()
    second = await make_person()
    slot = await _first_slot(
        app_client, await session_headers(app_client, first), host.id
    )
    body = {"host_user_id": host.id, "start": slot, "topic": "invoice"}
    ok = await app_client.post(
        f"{BASE}/meetings",
        headers=await session_headers(app_client, first),
        json=body,
    )
    assert ok.status_code == 201
    taken = await app_client.post(
        f"{BASE}/meetings",
        headers=await session_headers(app_client, second),
        json=body,
    )
    assert taken.status_code == 409
    assert taken.json()["detail"]["code"] in ("slot_invalid", "slot_taken")


@pytest.mark.usefixtures("portal_all")
async def test_unique_index_closes_the_race(app_client) -> None:
    """Ostatnia linia obrony: dwa wiersze na ten sam termin osoby padają w bazie."""
    from sqlalchemy.exc import IntegrityError

    host = await make_user(UserRole.recruiter)
    person = await make_person()
    start_in = timedelta(days=3)
    await make_meeting(person, host, start_in=start_in, status="pending")
    start = await _start_of_latest(person)
    async with AsyncSessionLocal() as db:
        db.add(
            CpMeeting(
                contract_id=person.contract_id,
                host_user_id=host.id,
                topic="invoice",
                start_at=start,
                end_at=start + timedelta(minutes=20),
                status="booked",
                client_request_id=tag() * 3,
            )
        )
        with pytest.raises(IntegrityError):
            await db.commit()


async def _start_of_latest(person):
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(CpMeeting.start_at).where(
                CpMeeting.contract_id == person.contract_id
            )
        )


@pytest.mark.usefixtures("portal_all", "care_on", "clean_team")
async def test_booking_refuses_outsider_host_and_invented_slot(
    app_client, monkeypatch
) -> None:
    _ready(monkeypatch)
    FakeGraph(monkeypatch)
    host = await make_member("finance")
    outsider = await make_user(UserRole.recruiter)
    person = await make_person()
    portal = await session_headers(app_client, person)
    slot = await _first_slot(app_client, portal, host.id)
    bad_host = await app_client.post(
        f"{BASE}/meetings",
        headers=portal,
        json={"host_user_id": outsider.id, "start": slot, "topic": "invoice"},
    )
    assert bad_host.status_code == 422
    assert bad_host.json()["detail"]["code"] == "host_invalid"
    # Północ: poza godzinami pracy, a więc poza listą.
    midnight = (datetime.now(timezone.utc) + timedelta(days=2)).replace(
        hour=23, minute=0, second=0, microsecond=0
    )
    bad_slot = await app_client.post(
        f"{BASE}/meetings",
        headers=portal,
        json={
            "host_user_id": host.id,
            "start": midnight.isoformat(),
            "topic": "invoice",
        },
    )
    assert bad_slot.status_code == 409
    assert bad_slot.json()["detail"]["code"] == "slot_invalid"


@pytest.mark.usefixtures("portal_all", "care_on", "clean_team")
async def test_upcoming_meetings_are_limited(app_client, monkeypatch) -> None:
    _ready(monkeypatch)
    FakeGraph(monkeypatch)
    host = await make_member("finance")
    person = await make_person()
    for days in (2, 3, 4):
        await make_meeting(person, host, start_in=timedelta(days=days))
    portal = await session_headers(app_client, person)
    response = await app_client.post(
        f"{BASE}/meetings",
        headers=portal,
        json={
            "host_user_id": host.id,
            "start": datetime.now(timezone.utc).isoformat(),
            "topic": "invoice",
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "too_many"


@pytest.mark.usefixtures("portal_all", "care_on", "clean_team")
async def test_graph_failure_frees_the_slot_and_says_so_plainly(
    app_client, monkeypatch
) -> None:
    _ready(monkeypatch)
    graph = FakeGraph(
        monkeypatch, create_error=GraphRequestError(403, {"error": "tajny szczegół"})
    )
    host = await make_member("finance")
    person = await make_person()
    portal = await session_headers(app_client, person)
    slot = await _first_slot(app_client, portal, host.id)
    response = await app_client.post(
        f"{BASE}/meetings",
        headers=portal,
        json={"host_user_id": host.id, "start": slot, "topic": "invoice"},
    )
    assert response.status_code == 503
    assert "tajny" not in response.text
    assert "403" not in response.text
    async with AsyncSessionLocal() as db:
        statuses = (
            await db.scalars(
                select(CpMeeting.status).where(
                    CpMeeting.contract_id == person.contract_id
                )
            )
        ).all()
    assert statuses == ["failed"]
    # Ten sam termin znów jest do wzięcia.
    graph.create_error = None
    again = await app_client.post(
        f"{BASE}/meetings",
        headers=portal,
        json={"host_user_id": host.id, "start": slot, "topic": "invoice"},
    )
    assert again.status_code == 201, again.text


@pytest.mark.usefixtures("portal_all", "care_on", "clean_team")
async def test_cancel_paths(app_client, monkeypatch) -> None:
    graph = FakeGraph(monkeypatch)
    host = await make_member("finance")
    person = await make_person()
    other = await make_person()
    portal = await session_headers(app_client, person)
    future = await make_meeting(
        person, host, start_in=timedelta(days=2), graph_event_id="ev-1"
    )
    past = await make_meeting(person, host, start_in=timedelta(days=-2))
    foreign = await make_meeting(other, host, start_in=timedelta(days=5))
    assert (
        await app_client.post(f"{BASE}/meetings/{foreign}/cancel", headers=portal)
    ).status_code == 404
    assert (
        await app_client.post(f"{BASE}/meetings/{past}/cancel", headers=portal)
    ).status_code == 409
    done = await app_client.post(f"{BASE}/meetings/{future}/cancel", headers=portal)
    assert done.status_code == 200
    assert graph.cancelled == ["ev-1"]
    assert (
        await app_client.post(f"{BASE}/meetings/{future}/cancel", headers=portal)
    ).status_code == 409


@pytest.mark.usefixtures("portal_all", "care_on", "clean_team")
async def test_failed_cancel_keeps_the_meeting(app_client, monkeypatch) -> None:
    FakeGraph(monkeypatch, cancel_error=GraphRequestError(500, {}))
    host = await make_member("finance")
    person = await make_person()
    portal = await session_headers(app_client, person)
    future = await make_meeting(
        person, host, start_in=timedelta(days=2), graph_event_id="ev-2"
    )
    response = await app_client.post(f"{BASE}/meetings/{future}/cancel", headers=portal)
    assert response.status_code == 503
    async with AsyncSessionLocal() as db:
        assert (await db.get(CpMeeting, future)).status == "booked"


# ── Transkrypt i podsumowanie ────────────────────────────────────────────────


_VTT = """WEBVTT

00:00:00.000 --> 00:00:05.000
<v Konsultant>Pytam o fakturę po aneksie.</v>

00:00:05.000 --> 00:00:09.000
<v Prowadząca>Wystaw ze starą stawką, różnica korektą.</v>
"""


def _graph_transcripts(monkeypatch, *, refs=("t1",), vtt=_VTT, error=None) -> None:
    async def resolve(upn):
        return "aad-1"

    async def find(user_id, join_url):
        return "online-1"

    async def listing(user_id, meeting_id):
        if error:
            raise error
        return [teams_prep_graph.TranscriptRef(id=ref, created=None) for ref in refs]

    async def content_of(user_id, meeting_id, ref_id):
        return vtt

    monkeypatch.setattr(teams_prep_graph, "resolve_user_id", resolve)
    monkeypatch.setattr(teams_prep_graph, "find_online_meeting", find)
    monkeypatch.setattr(teams_prep_graph, "list_transcripts", listing)
    monkeypatch.setattr(teams_prep_graph, "transcript_vtt", content_of)


async def _process(meeting_id, now=None):
    async with AsyncSessionLocal() as db:
        meeting = await db.get(CpMeeting, meeting_id)
        outcome = await transcripts.process_meeting(
            db, meeting, now=now or datetime.now(timezone.utc)
        )
        await db.commit()
        return outcome


async def test_transcript_is_stored_as_text(monkeypatch) -> None:
    _graph_transcripts(monkeypatch)
    person = await make_person()
    meeting_id = await make_meeting(person, None, join_url="https://x.example.com/1")
    assert await _process(meeting_id) == "fetched"
    async with AsyncSessionLocal() as db:
        meeting = await db.get(CpMeeting, meeting_id)
    assert "Pytam o fakturę" in meeting.transcript_text
    assert meeting.transcript_status == "fetched"
    assert meeting.next_fetch_at is None


async def test_no_transcript_waits_then_gives_up(monkeypatch) -> None:
    _graph_transcripts(monkeypatch, refs=())
    person = await make_person()
    meeting_id = await make_meeting(person, None, join_url="https://x.example.com/1")
    assert await _process(meeting_id) == "waiting"
    late = datetime.now(timezone.utc) + timedelta(days=5)
    assert await _process(meeting_id, now=late) == "missing"
    async with AsyncSessionLocal() as db:
        meeting = await db.get(CpMeeting, meeting_id)
    assert meeting.transcript_status == "missing"
    assert meeting.summary_status == "skipped"


async def test_forbidden_is_a_state_not_a_crash(monkeypatch) -> None:
    _graph_transcripts(monkeypatch, error=GraphRequestError(403, {"secret": "x"}))
    person = await make_person()
    meeting_id = await make_meeting(person, None, join_url="https://x.example.com/1")
    assert await _process(meeting_id) == "forbidden"
    async with AsyncSessionLocal() as db:
        meeting = await db.get(CpMeeting, meeting_id)
    assert meeting.last_error == "http_403"
    assert meeting.next_fetch_at is not None


async def test_empty_transcript_is_missing_without_a_summary(monkeypatch) -> None:
    _graph_transcripts(monkeypatch, vtt="WEBVTT\n\n")
    person = await make_person()
    meeting_id = await make_meeting(person, None, join_url="https://x.example.com/1")
    assert await _process(meeting_id) == "missing"


def test_summary_parser_accepts_only_the_expected_shape() -> None:
    summary, items = transcripts.parse_summary(
        '```json\n{"summary": "Ustalono korektę.", "action_items": '
        '[{"who": "Ola", "what": "Wysłać mail"}, {"what": ""}, "śmieć"]}\n```'
    )
    assert summary == "Ustalono korektę."
    assert items == [{"who": "Ola", "what": "Wysłać mail"}]
    assert transcripts.parse_summary("nie json") == (None, [])
    assert transcripts.parse_summary('{"summary": ""}') == (None, [])
    assert transcripts.parse_summary("[1, 2]") == (None, [])


async def _meeting_with_case(person, host, **fields) -> tuple[int, int]:
    case_id = await _case(person, source="portal", key=f"portal:{tag()}")
    return (
        await make_meeting(
            person,
            host,
            case_id=case_id,
            transcript_text="Konsultant: pytanie. Prowadząca: odpowiedź.",
            transcript_status="fetched",
            **fields,
        ),
        case_id,
    )


async def _comments(case_id) -> list[str]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(AdminCaseComment.body).where(
                        AdminCaseComment.case_id == case_id
                    )
                )
            ).all()
        )


async def test_summary_goes_to_the_case(monkeypatch) -> None:
    monkeypatch.setattr(
        transcripts, "_call_model", lambda *a: '{"summary": "Ustalono."}'
    )
    monkeypatch.setattr(
        "app.services.llm_providers.api_key_configured", lambda model: True
    )
    person = await make_person()
    meeting_id, case_id = await _meeting_with_case(person, None)
    async with AsyncSessionLocal() as db:
        assert await transcripts.summarize(db, meeting_id) == "done"
    assert any("Ustalono." in body for body in await _comments(case_id))


async def test_model_failure_blocks_nothing(monkeypatch) -> None:
    def boom(*args):
        raise RuntimeError("awaria dostawcy")

    monkeypatch.setattr(transcripts, "_call_model", boom)
    monkeypatch.setattr(
        "app.services.llm_providers.api_key_configured", lambda model: True
    )
    person = await make_person()
    meeting_id, case_id = await _meeting_with_case(person, None)
    async with AsyncSessionLocal() as db:
        assert await transcripts.summarize(db, meeting_id) == "failed"
    async with AsyncSessionLocal() as db:
        meeting = await db.get(CpMeeting, meeting_id)
    assert meeting.summary_status == "failed"
    assert meeting.transcript_text
    assert await _comments(case_id) == []


async def test_old_transcripts_are_purged() -> None:
    person = await make_person()
    meeting_id = await make_meeting(
        person,
        None,
        start_in=timedelta(days=-(transcripts.TRANSCRIPT_RETENTION.days + 2)),
        transcript_text="Stara rozmowa",
        summary="Stare podsumowanie",
    )
    async with AsyncSessionLocal() as db:
        await transcripts.purge_expired(db, now=datetime.now(timezone.utc))
    async with AsyncSessionLocal() as db:
        meeting = await db.get(CpMeeting, meeting_id)
    assert meeting.transcript_text is None
    assert meeting.summary is None
    assert meeting.transcript_purged_at is not None


@pytest.mark.usefixtures("portal_restored")
async def test_transcript_loop_does_nothing_with_portal_off() -> None:
    from tests.consultant_portal_seed import set_portal

    await set_portal("off")
    async with AsyncSessionLocal() as db:
        assert await transcripts.run_once(db) == {"status": "disabled"}


# ── Rozmowy dla back office'u ────────────────────────────────────────────────


@pytest.mark.usefixtures("care_on", "clean_team", "divisions_restored")
async def test_talks_visibility_and_rating_hidden_from_host(app_client) -> None:
    head = await make_head()
    host = await make_member("finance", name="Prowadząca")
    colleague = await make_member("finance", name="Koleżanka")
    person = await make_person()
    meeting_id = await make_meeting(
        person,
        host,
        transcript_text="Treść rozmowy",
        summary="Podsumowanie",
        transcript_status="fetched",
    )
    async with AsyncSessionLocal() as db:
        db.add(
            CpRating(
                meeting_id=meeting_id,
                contract_id=person.contract_id,
                host_user_id=host.id,
                score=2,
                comment="Komentarz o prowadzącej",
                followup_status="open",
            )
        )
        await db.commit()

    # Prowadząca widzi rozmowę i transkrypt, ale nie widzi oceny.
    own = await app_client.get(
        f"{STAFF}/meetings/{meeting_id}", headers=staff_headers(host)
    )
    assert own.status_code == 200
    assert own.json()["transcript"] == "Treść rozmowy"
    assert own.json()["rating"] is None
    assert "Komentarz o prowadzącej" not in own.text
    listed = await app_client.get(f"{STAFF}/meetings", headers=staff_headers(host))
    assert "Komentarz o prowadzącej" not in listed.text

    # Inna osoba z zespołu tej rozmowy nie widzi wcale.
    other = await app_client.get(
        f"{STAFF}/meetings/{meeting_id}", headers=staff_headers(colleague)
    )
    assert other.status_code == 404
    other_list = await app_client.get(
        f"{STAFF}/meetings", headers=staff_headers(colleague)
    )
    assert meeting_id not in {row["id"] for row in other_list.json()["items"]}

    # Kierownik widzi ocenę.
    lead = await app_client.get(
        f"{STAFF}/meetings/{meeting_id}", headers=staff_headers(head)
    )
    assert lead.json()["rating"]["comment"] == "Komentarz o prowadzącej"


@pytest.mark.usefixtures("care_on", "clean_team", "divisions_restored")
async def test_lead_who_hosted_does_not_see_own_rating(app_client) -> None:
    head = await make_head()
    person = await make_person()
    meeting_id = await make_meeting(person, head)
    comment = f"O kierowniku {tag()}"
    async with AsyncSessionLocal() as db:
        db.add(
            CpRating(
                meeting_id=meeting_id,
                contract_id=person.contract_id,
                host_user_id=head.id,
                score=1,
                comment=comment,
                followup_status="open",
            )
        )
        await db.commit()
    detail = await app_client.get(
        f"{STAFF}/meetings/{meeting_id}", headers=staff_headers(head)
    )
    assert detail.json()["rating"] is None
    quality = await app_client.get(f"{STAFF}/quality", headers=staff_headers(head))
    assert comment not in quality.text
    assert head.id not in {row["user_id"] for row in quality.json()["people"]}


@pytest.mark.usefixtures("care_on", "clean_team", "divisions_restored")
async def test_quality_totals_do_not_reveal_the_viewers_own_rating(app_client) -> None:
    """Sumy liczą te same wiersze co lista: różnica nie może odsłonić oceny oglądającego."""

    head = await make_head()
    host = await make_member("finance")
    person = await make_person()
    when = datetime.now(timezone.utc)
    await _rating_row(person, head, score=1, when=when)
    await _rating_row(person, host, score=5, when=when)
    report = (
        await app_client.get(f"{STAFF}/quality", headers=staff_headers(head))
    ).json()
    people = report["people"]
    assert report["rated"] == sum(row["rated"] for row in people)
    expected = (
        sum(row["average"] * row["rated"] for row in people if row["rated"])
        / report["rated"]
    )
    # Średnie w wierszach są zaokrąglone do dwóch miejsc.
    assert report["average"] == pytest.approx(expected, abs=0.02)
    assert report["average"] <= 5


@pytest.mark.usefixtures("care_on", "clean_team", "divisions_restored")
async def test_case_owner_sees_the_talk(app_client) -> None:
    owner = await make_member("care", name="Opiekun")
    host = await make_member("finance")
    person = await make_person()
    case_id = await _case(person, source="portal", key=f"portal:{tag()}")
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(AdminCase)
            .where(AdminCase.id == case_id)
            .values(assignee_user_id=owner.id)
        )
        await db.commit()
    meeting_id = await make_meeting(person, host, case_id=case_id)
    response = await app_client.get(
        f"{STAFF}/meetings/{meeting_id}", headers=staff_headers(owner)
    )
    assert response.status_code == 200


# ── Oceny ────────────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("portal_all", "care_on", "clean_team", "divisions_restored")
async def test_low_rating_opens_a_task_for_the_lead(app_client) -> None:
    head = await make_head()
    host = await make_member("finance")
    person = await make_person()
    meeting_id = await make_meeting(person, host)
    portal = await session_headers(app_client, person)
    rated = await app_client.post(
        f"{BASE}/meetings/{meeting_id}/rating",
        headers=portal,
        json={"score": 1, "resolved": False, "comment": "Nikt nie oddzwonił"},
    )
    assert rated.status_code == 201, rated.text
    async with AsyncSessionLocal() as db:
        rating = await db.scalar(
            select(CpRating).where(CpRating.meeting_id == meeting_id)
        )
        bells = (
            await db.scalars(
                select(Notification.user_id).where(
                    Notification.notification_type
                    == NotificationType.portal_low_rating,
                    Notification.related_entity_id == rating.id,
                )
            )
        ).all()
    assert rating.followup_status == "open"
    assert rating.followup_due_on is not None
    assert head.id in bells
    assert host.id not in bells
    quality = await app_client.get(f"{STAFF}/quality", headers=staff_headers(head))
    assert quality.status_code == 200
    tasks = [row for row in quality.json()["tasks"] if row["id"] == rating.id]
    assert tasks[0]["comment"] == "Nikt nie oddzwonił"
    closed = await app_client.post(
        f"{STAFF}/quality/tasks/{rating.id}/close",
        headers=staff_headers(head),
        json={"note": "Oddzwoniłem"},
    )
    assert closed.json()["followup_status"] == "done"
    again = await app_client.post(
        f"{STAFF}/quality/tasks/{rating.id}/close",
        headers=staff_headers(head),
        json={},
    )
    assert again.status_code == 409


@pytest.mark.usefixtures("portal_all", "care_on", "clean_team", "divisions_restored")
async def test_rated_person_cannot_reach_quality_or_close_tasks(app_client) -> None:
    await make_head()
    host = await make_member("finance")
    assert (
        await app_client.get(f"{STAFF}/quality", headers=staff_headers(host))
    ).status_code == 403
    assert (
        await app_client.post(
            f"{STAFF}/quality/tasks/1/close", headers=staff_headers(host), json={}
        )
    ).status_code == 403


@pytest.mark.usefixtures("portal_all")
async def test_good_rating_opens_no_task(app_client) -> None:
    person = await make_person()
    meeting_id = await make_meeting(person, None)
    portal = await session_headers(app_client, person)
    await app_client.post(
        f"{BASE}/meetings/{meeting_id}/rating", headers=portal, json={"score": 5}
    )
    async with AsyncSessionLocal() as db:
        rating = await db.scalar(
            select(CpRating).where(CpRating.meeting_id == meeting_id)
        )
    assert rating.followup_status == "none"
    assert rating.followup_due_on is None


@pytest.mark.usefixtures("portal_all")
async def test_rating_refusals(app_client) -> None:
    person = await make_person()
    other = await make_person()
    portal = await session_headers(app_client, person)
    future = await make_meeting(person, None, start_in=timedelta(days=2))
    foreign = await make_meeting(other, None)
    done = await make_meeting(person, None)
    cancelled = await make_meeting(person, None, status="cancelled")
    assert (
        await app_client.post(
            f"{BASE}/meetings/{future}/rating", headers=portal, json={"score": 4}
        )
    ).status_code == 409
    assert (
        await app_client.post(
            f"{BASE}/meetings/{foreign}/rating", headers=portal, json={"score": 4}
        )
    ).status_code == 404
    assert (
        await app_client.post(
            f"{BASE}/meetings/{cancelled}/rating", headers=portal, json={"score": 4}
        )
    ).status_code == 409
    assert (
        await app_client.post(
            f"{BASE}/meetings/{done}/rating", headers=portal, json={"score": 9}
        )
    ).status_code == 422
    first = await app_client.post(
        f"{BASE}/meetings/{done}/rating", headers=portal, json={"score": 4}
    )
    assert first.status_code == 201
    second = await app_client.post(
        f"{BASE}/meetings/{done}/rating", headers=portal, json={"score": 1}
    )
    assert second.status_code == 409


async def _rating_token(person, meeting_id, *, used=False, expired=False) -> str:
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        raw = await auth.rating_link(
            db,
            contract_id=person.contract_id,
            meeting_id=meeting_id,
            email=person.email,
            now=now,
        )
        if used or expired:
            await db.execute(
                update(CpLink)
                .where(CpLink.token_hash == auth.token_hash(raw))
                .values(
                    used_at=now if used else None,
                    expires_at=now - timedelta(minutes=1) if expired else now,
                )
            )
        await db.commit()
    return raw


@pytest.mark.usefixtures("portal_all")
async def test_rating_by_link_without_session(app_client) -> None:
    person = await make_person()
    meeting_id = await make_meeting(person, None)
    raw = await _rating_token(person, meeting_id)
    form = await app_client.post(f"{BASE}/rating-form", json={"token": raw})
    assert form.status_code == 200
    assert form.json()["topic_label"] == "Faktury i płatności"
    assert not {"email", "contract_id", "comment"} & set(form.json())
    sent = await app_client.post(f"{BASE}/rating", json={"token": raw, "score": 4})
    assert sent.status_code == 201
    # Link jest jednorazowy.
    assert (
        await app_client.post(f"{BASE}/rating-form", json={"token": raw})
    ).status_code == 404
    assert (
        await app_client.post(f"{BASE}/rating", json={"token": raw, "score": 1})
    ).status_code == 404


@pytest.mark.usefixtures("portal_all")
async def test_rating_link_refusals_look_the_same(app_client) -> None:
    person = await make_person()
    meeting_id = await make_meeting(person, None)
    expired = await _rating_token(person, meeting_id, expired=True)
    used = await _rating_token(person, meeting_id, used=True)
    answers = [
        await app_client.post(f"{BASE}/rating-form", json={"token": token})
        for token in (expired, used, "z" * 43, "z" * 200)
    ]
    assert {answer.status_code for answer in answers} == {404}
    assert len({answer.text for answer in answers}) == 1


@pytest.mark.usefixtures("portal_all")
async def test_rating_requests_go_once_and_only_after_the_talk(monkeypatch) -> None:
    mailer = install_mailer(monkeypatch)
    person = await make_person()
    done = await make_meeting(person, None, start_in=timedelta(hours=-1))
    upcoming = await make_meeting(person, None, start_in=timedelta(days=1))
    cancelled = await make_meeting(
        person, None, start_in=timedelta(hours=-1), status="cancelled"
    )
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        await ratings.send_requests(db, now=now)
    mine = [mail for mail in mailer.sent if mail["to"] == person.email]
    assert len(mine) == 1
    assert "/konsultant/ocena#" in mine[0]["text"]
    async with AsyncSessionLocal() as db:
        assert (await db.get(CpMeeting, done)).rating_requested_at is not None
        assert (await db.get(CpMeeting, upcoming)).rating_requested_at is None
        assert (await db.get(CpMeeting, cancelled)).rating_requested_at is None
        await ratings.send_requests(db, now=now)
    assert len([m for m in mailer.sent if m["to"] == person.email]) == 1


@pytest.mark.usefixtures("portal_restored")
async def test_rating_request_blocked_when_portal_is_off(monkeypatch) -> None:
    from tests.consultant_portal_seed import set_portal

    mailer = install_mailer(monkeypatch)
    await set_portal("off")
    person = await make_person()
    await make_meeting(person, None, start_in=timedelta(hours=-1))
    async with AsyncSessionLocal() as db:
        result = await ratings.send_requests(db, now=datetime.now(timezone.utc))
    assert result == {"sent": 0}
    assert mailer.sent == []


@pytest.mark.usefixtures("portal_restored")
async def test_rating_request_skips_contracts_outside_the_pilot(monkeypatch) -> None:
    from tests.consultant_portal_seed import set_portal

    mailer = install_mailer(monkeypatch)
    inside = await make_person()
    outside = await make_person()
    await set_portal("pilot", [inside.contract_id])
    await make_meeting(inside, None, start_in=timedelta(hours=-1))
    await make_meeting(outside, None, start_in=timedelta(hours=-1))
    async with AsyncSessionLocal() as db:
        await ratings.send_requests(db, now=datetime.now(timezone.utc))
    assert {mail["to"] for mail in mailer.sent} == {inside.email}


# ── Przegląd miesięczny ──────────────────────────────────────────────────────


async def _rating_row(person, host, *, score, when) -> None:
    # Unikat (osoba, początek): każda ocena ma własny termin rozmowy.
    meeting_id = await make_meeting(
        person, host, start_in=timedelta(hours=-2, seconds=-uuid4().int % 86_400)
    )
    async with AsyncSessionLocal() as db:
        db.add(
            CpRating(
                meeting_id=meeting_id,
                contract_id=person.contract_id,
                host_user_id=host.id,
                score=score,
                resolved=True,
                comment="Pojedynczy komentarz",
                followup_status="open" if score <= 2 else "none",
                created_at=when,
            )
        )
        await db.commit()


def test_previous_month_crosses_the_year() -> None:
    assert ratings.previous_month(date(2026, 1, 15)) == (2025, 12)
    assert ratings.previous_month(date(2026, 11, 2)) == (2026, 10)


@pytest.mark.usefixtures("care_on", "clean_team")
async def test_my_review_is_aggregated_and_hidden_below_the_minimum(app_client) -> None:
    host = await make_member("finance")
    person = await make_person()
    today = ratings.business_today()
    year, month = ratings.previous_month(today)
    when = ratings._month_bounds(year, month)[0] + timedelta(days=2)
    await _rating_row(person, host, score=2, when=when)
    await _rating_row(person, host, score=4, when=when)
    few = await app_client.get(
        f"{STAFF}/quality/my-review", headers=staff_headers(host)
    )
    assert few.status_code == 200
    assert few.json()["enough"] is False
    assert few.json()["average"] is None
    assert few.json()["rated"] is None
    await _rating_row(person, host, score=3, when=when)
    enough = await app_client.get(
        f"{STAFF}/quality/my-review", headers=staff_headers(host)
    )
    assert enough.json()["enough"] is True
    assert enough.json()["average"] == 3.0
    assert enough.json()["rated"] == 3
    assert "Pojedynczy komentarz" not in enough.text
    assert not {"comment", "comments", "tasks", "ratings"} & set(enough.json())


@pytest.mark.usefixtures("portal_all", "care_on", "clean_team")
async def test_monthly_notice_only_on_the_first_and_once(monkeypatch) -> None:
    host = await make_member("finance")
    person = await make_person()
    # Rezerwacja przebiegu zostaje w bazie testowej: każdy bieg ma własny miesiąc.
    year = 2100 + uuid4().int % 7000
    first_of_month = date(year, 7, 1)
    start, _end = ratings._month_bounds(year, 6)
    for score in (3, 4, 5):
        await _rating_row(person, host, score=score, when=start + timedelta(days=2))
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(ratings, "business_today", lambda: date(year, 7, 2))
    async with AsyncSessionLocal() as db:
        assert await ratings.notify_monthly_reviews(db, now=now) == {"notified": 0}
    monkeypatch.setattr(ratings, "business_today", lambda: first_of_month)
    async with AsyncSessionLocal() as db:
        first = await ratings.notify_monthly_reviews(db, now=now)
    async with AsyncSessionLocal() as db:
        second = await ratings.notify_monthly_reviews(db, now=now)
    assert first["notified"] >= 1
    assert second == {"notified": 0}
