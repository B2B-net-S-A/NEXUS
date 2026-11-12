"""Sprzedaż → przekazanie spotkania i werdykt (``/api/sales/handoffs``).

Cała ścieżka dwóch ról: dzwoniący umawia, prowadzący widzi, potwierdza i daje
werdykt, dzwoniący widzi werdykt i swoje liczby. Do tego ścieżki odmowy: brak
„Sprzedaż: edycja”, cudza szansa, firma, która jest klientem NEXUSA.

Baza testowa jest wspólna dla przebiegu: nazwy niosą losowy tag, a każdy test
ma własne konta, więc listy i liczby jednej osoby są policzalne.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import DEFAULT_TZ, business_date, business_today
from app.models.calendar_event import CalendarEvent
from app.models.m365 import M365Connection
from app.models.sales import (
    SalesActivity,
    SalesCompany,
    SalesCompanyContact,
    SalesContact,
    SalesOpportunity,
    SalesOpportunityContact,
)
from app.services.sales import handoff, handoff_invite, handoff_state, meeting_autopin
from tests.test_sales_companies_api import _headers, _user
from tests.test_sales_meeting_decisions import (
    _activity,
    _client,
    _events,
    _firm,
    _opp_row,
    _own_firm,
)
from tests.test_sales_opportunities_api import _stages

URL = "/api/sales/handoffs"
OPPS = "/api/sales/opportunities"
WARSAW = ZoneInfo(DEFAULT_TZ)


def _tag() -> str:
    return uuid.uuid4().hex[:10]


def _in(days: int, hour: int = 11) -> datetime:
    """Chwila za ``days`` dni o pełnej godzinie czasu firmy."""

    day = datetime.now(WARSAW).date() + timedelta(days=days)
    return datetime(day.year, day.month, day.day, hour, tzinfo=WARSAW)


async def _pair() -> tuple[Any, Any]:
    """Osoba, która umawia, i prowadzący: oboje z „Sprzedaż: edycja”."""

    return await _user("sales_edit"), await _user("sales_edit")


async def _book(app_client, user, **body: Any):
    return await app_client.post(URL, json=body, headers=_headers(user))


async def _booked(app_client, caller, host, **body: Any) -> dict:
    body.setdefault("new_company", {"name": f"Firma Przekazana {_tag()}"})
    resp = await _book(app_client, caller, host_user_id=host.id, **body)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _mine(app_client, user) -> dict:
    resp = await app_client.get(URL, headers=_headers(user))
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _verdict(app_client, user, opportunity_id: int, **body: Any):
    return await app_client.post(
        f"{URL}/{opportunity_id}/verdict", json=body, headers=_headers(user)
    )


async def _tasks(opportunity_id: int) -> list[SalesActivity]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(SalesActivity)
                    .where(
                        SalesActivity.opportunity_id == opportunity_id,
                        SalesActivity.kind == "task",
                    )
                    .order_by(SalesActivity.id)
                )
            ).all()
        )


async def _meetings(opportunity_id: int) -> list[SalesActivity]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(SalesActivity)
                    .where(
                        SalesActivity.opportunity_id == opportunity_id,
                        SalesActivity.kind == "meeting",
                    )
                    .order_by(SalesActivity.id)
                )
            ).all()
        )


async def _company_row(company_id: int) -> SalesCompany:
    async with AsyncSessionLocal() as db:
        return await db.get(SalesCompany, company_id)


async def _person(company_id: int, name: str = "Osoba Testowa", **fields: Any) -> int:
    async with AsyncSessionLocal() as db:
        contact = SalesContact(full_name=name, company_id=company_id, **fields)
        db.add(contact)
        await db.flush()
        db.add(
            SalesCompanyContact(
                company_id=company_id, contact_id=contact.id, is_primary=True
            )
        )
        await db.commit()
        return contact.id


# ── Umówienie spotkania ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_booking_needs_sales_edit(app_client) -> None:
    viewer = await _user("sales_view")
    host = await _user("sales_edit")
    resp = await _book(
        app_client, viewer, new_company={"name": "Firma"}, host_user_id=host.id
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "permission_denied"
    assert (await app_client.get(URL, headers=_headers(viewer))).status_code == 200
    assert (
        await app_client.get(f"{URL}/form", headers=_headers(viewer))
    ).status_code == 403
    stranger = await _user()
    assert (await app_client.get(URL, headers=_headers(stranger))).status_code == 403


@pytest.mark.asyncio
async def test_booking_creates_opportunity_for_the_host(app_client) -> None:
    caller, host = await _pair()
    stages = await _stages(app_client, caller)
    name = f"Firma Nowa {_tag()}"
    when = _in(3)
    booked = await _booked(
        app_client,
        caller,
        host,
        new_company={"name": name},
        new_contact={
            "full_name": "Anna Przykładowa",
            "title": "Kierownik IT",
            "email": "Anna.Przykladowa@firma-nowa.example",
            "phone": "600 100 200",
        },
        meeting_at=when.isoformat(),
        duration_minutes=45,
        service="Automatyzacje",
        problem="Raporty składane ręcznie",
        decision_maker="Kierownik IT z dyrektorem finansowym",
        timing="Budżet zamykają w grudniu",
    )
    assert booked["company"]["name"] == name
    assert booked["host"]["id"] == host.id
    assert booked["booked_by"]["id"] == caller.id
    assert booked["stage_key"] == "qualifying-meeting"
    assert booked["phase"] == "upcoming"
    assert booked["contact"]["name"] == "Anna Przykładowa"
    assert booked["problem"] == "Raporty składane ręcznie"
    assert datetime.fromisoformat(booked["meeting_at"]) == when

    opp = await _opp_row(booked["opportunity"]["id"])
    assert (opp.owner_user_id, opp.created_by_user_id) == (host.id, caller.id)
    assert opp.stage_id == stages["qualifying-meeting"]
    assert opp.status == "open"
    assert opp.source == handoff.HANDOFF_SOURCE
    assert opp.title == "Automatyzacje: spotkanie kwalifikujące"
    assert opp.primary_contact_id == booked["contact"]["id"]

    company = await _company_row(booked["company"]["id"])
    # Domena z adresu e-mail osoby: bez niej nie działa dopasowanie poczty.
    assert company.domain == "firma-nowa.example"
    async with AsyncSessionLocal() as db:
        link = await db.scalar(
            select(SalesCompanyContact).where(
                SalesCompanyContact.company_id == company.id,
                SalesCompanyContact.contact_id == opp.primary_contact_id,
            )
        )
        assert link is not None and link.is_primary
        assert await db.get(SalesOpportunityContact, (opp.id, opp.primary_contact_id))

    [meeting] = await _meetings(opp.id)
    assert meeting.occurred_at == when
    assert meeting.duration_minutes == 45
    assert meeting.done_at is None
    assert meeting.created_by_user_id == host.id

    fields = [(event.field, event.new_value) for event in await _events(opp.id)]
    assert ("stage_id", str(stages["qualifying-meeting"])) in fields
    assert (handoff.HISTORY_FIELD, "booked") in fields

    for_host = await _mine(app_client, host)
    assert [row["opportunity"]["id"] for row in for_host["to_me"]] == [opp.id]
    assert for_host["booked_by_me"] == [] and for_host["weeks"] == []
    for_caller = await _mine(app_client, caller)
    assert for_caller["to_me"] == []
    assert [row["opportunity"]["id"] for row in for_caller["booked_by_me"]] == [opp.id]
    assert for_caller["weeks"][0] | {"week_start": None} == {
        "week_start": None,
        "booked": 1,
        "held": 0,
        "qualified": 0,
    }


@pytest.mark.asyncio
async def test_missing_fields_never_stop_the_save(app_client) -> None:
    caller, host = await _pair()
    booked = await _booked(app_client, caller, host)
    assert booked["phase"] == "no_term"
    assert booked["meeting_at"] is None and booked["contact"] is None
    assert booked["opportunity"]["name"] == "Spotkanie kwalifikujące"
    assert await _meetings(booked["opportunity"]["id"]) == []


@pytest.mark.asyncio
async def test_company_and_host_are_the_only_required_fields(app_client) -> None:
    caller, host = await _pair()
    assert (await _book(app_client, caller, host_user_id=host.id)).status_code == 422
    assert (
        await _book(app_client, caller, new_company={"name": "Firma"})
    ).status_code == 422
    both = await _book(
        app_client,
        caller,
        host_user_id=host.id,
        company_id=1,
        new_company={"name": "Firma"},
    )
    assert both.status_code == 422


@pytest.mark.asyncio
async def test_client_of_nexus_is_refused_with_its_delivery_lead(app_client) -> None:
    caller, host = await _pair()
    lead = await _user(role="delivery_lead")
    client_id, client_name = await _client(lead_ids=(lead.id,))
    linked = await _firm(client_id=client_id)
    resp = await _book(app_client, caller, company_id=linked, host_user_id=host.id)
    assert resp.status_code == 409
    assert client_name in resp.json()["detail"]
    assert lead.name in resp.json()["detail"]

    # Nowa karta o nazwie klienta też nie powstaje.
    by_name = await _book(
        app_client, caller, new_company={"name": client_name}, host_user_id=host.id
    )
    assert by_name.status_code == 409
    assert lead.name in by_name.json()["detail"]
    async with AsyncSessionLocal() as db:
        cards = await db.scalars(
            select(SalesCompany.id).where(SalesCompany.name == client_name)
        )
        assert cards.all() == []
    assert (await _mine(app_client, host))["to_me"] == []


@pytest.mark.asyncio
async def test_own_company_gets_no_opportunity(app_client) -> None:
    caller, host = await _pair()
    own_id, _ = await _own_firm()
    resp = await _book(app_client, caller, company_id=own_id, host_user_id=host.id)
    assert resp.status_code == 409
    assert "nasza firma" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_same_name_card_warns_and_can_be_overridden(app_client) -> None:
    caller, host = await _pair()
    name = f"Firma Zdublowana {_tag()}"
    existing = await _firm(name)
    resp = await _book(
        app_client,
        caller,
        new_company={"name": f"{name} sp. z o.o."},
        host_user_id=host.id,
    )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["code"] == "sales_company_duplicate"
    assert [item["id"] for item in detail["duplicates"]] == [existing]

    forced = await _book(
        app_client,
        caller,
        new_company={"name": name, "allow_duplicate": True},
        host_user_id=host.id,
    )
    assert forced.status_code == 201
    assert forced.json()["company"]["id"] != existing


@pytest.mark.asyncio
async def test_host_must_be_an_active_sales_account(app_client) -> None:
    caller = await _user("sales_edit")
    viewer = await _user("sales_view")
    resp = await _book(
        app_client, caller, new_company={"name": "Firma"}, host_user_id=viewer.id
    )
    assert resp.status_code == 422
    assert "Prowadzący" in resp.json()["detail"]
    missing = await _book(
        app_client, caller, new_company={"name": "Firma"}, host_user_id=10**9
    )
    assert missing.status_code == 422


@pytest.mark.asyncio
async def test_person_from_another_company_is_refused(app_client) -> None:
    caller, host = await _pair()
    company_id = await _firm()
    foreign = await _person(await _firm())
    resp = await _book(
        app_client,
        caller,
        company_id=company_id,
        contact_id=foreign,
        host_user_id=host.id,
    )
    assert resp.status_code == 422
    assert "nie należy" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_known_person_is_reused_and_only_gaps_are_filled(app_client) -> None:
    caller, host = await _pair()
    company_id = await _firm()
    known = await _person(company_id, "Jan Znany", title="Dyrektor IT")
    booked = await _booked(
        app_client,
        caller,
        host,
        new_company=None,
        company_id=company_id,
        new_contact={
            "full_name": "jan znany",
            "title": "Inne stanowisko",
            "email": "jan@firma-znana.example",
        },
    )
    assert booked["contact"]["id"] == known
    assert booked["contact"]["title"] == "Dyrektor IT"
    assert booked["contact"]["email"] == "jan@firma-znana.example"


@pytest.mark.asyncio
async def test_domain_is_a_hint_and_never_overwrites(app_client) -> None:
    caller, host = await _pair()
    with_domain = await _firm(domain="stara-domena.example")
    await _booked(
        app_client,
        caller,
        host,
        new_company=None,
        company_id=with_domain,
        company_domain="nowa-domena.example",
    )
    assert (await _company_row(with_domain)).domain == "stara-domena.example"

    without = await _firm()
    await _booked(
        app_client,
        caller,
        host,
        new_company=None,
        company_id=without,
        company_domain="https://www.Uzupelniona.example/kontakt",
    )
    assert (await _company_row(without)).domain == "uzupelniona.example"

    # Darmowa skrzynka nie wskazuje firmy.
    free_mail = await _booked(
        app_client,
        caller,
        host,
        new_contact={"full_name": "Osoba Prywatna", "email": "osoba@gmail.com"},
    )
    assert (await _company_row(free_mail["company"]["id"])).domain is None


@pytest.mark.asyncio
async def test_own_lead_is_handed_over_and_becomes_a_meeting(app_client) -> None:
    caller, host = await _pair()
    stages = await _stages(app_client, caller)
    company_id = await _firm()
    created = await app_client.post(
        OPPS,
        json={"company_id": company_id, "title": "Spotkanie wstępne"},
        headers=_headers(caller),
    )
    opportunity_id = created.json()["id"]
    assert created.json()["stage"]["key"] == "lead"

    booked = await _booked(
        app_client,
        caller,
        host,
        new_company=None,
        opportunity_id=opportunity_id,
        meeting_at=_in(2).isoformat(),
    )
    assert booked["opportunity"] == {"id": opportunity_id, "name": "Spotkanie wstępne"}
    opp = await _opp_row(opportunity_id)
    assert opp.owner_user_id == host.id
    assert opp.created_by_user_id == caller.id
    assert opp.stage_id == stages["qualifying-meeting"]
    changed = {event.field for event in await _events(opportunity_id)}
    assert {"owner_user_id", "stage_id", handoff.HISTORY_FIELD} <= changed


@pytest.mark.asyncio
async def test_someone_elses_opportunity_cannot_be_handed_over(app_client) -> None:
    caller, host = await _pair()
    owner = await _user("sales_edit")
    company_id = await _firm()
    created = await app_client.post(
        OPPS, json={"company_id": company_id, "title": "Cudza"}, headers=_headers(owner)
    )
    opportunity_id = created.json()["id"]
    resp = await _book(
        app_client, caller, opportunity_id=opportunity_id, host_user_id=host.id
    )
    assert resp.status_code == 403
    assert "nie Twoja szansa" in resp.json()["detail"]
    opp = await _opp_row(opportunity_id)
    assert opp.owner_user_id == owner.id
    assert handoff_state.block(opp) is None


@pytest.mark.asyncio
async def test_form_suggests_the_host_used_last_time(app_client) -> None:
    caller, host = await _pair()
    await _booked(app_client, caller, host)
    resp = await app_client.get(f"{URL}/form", headers=_headers(caller))
    assert resp.status_code == 200
    body = resp.json()
    assert body["default_host_id"] == host.id
    ids = {item["id"] for item in body["hosts"]}
    assert {caller.id, host.id} <= ids
    viewer = await _user("sales_view")
    assert viewer.id not in ids


# ── Termin i potwierdzenie ────────────────────────────────────────────────


def test_phase_follows_the_term_and_the_business_calendar() -> None:
    monday = datetime(2026, 11, 16, 10, 0, tzinfo=WARSAW)
    friday = datetime(2026, 11, 13, 9, 0, tzinfo=WARSAW)
    thursday = datetime(2026, 11, 12, 9, 0, tzinfo=WARSAW)
    assert handoff_state.phase_of(None, None, friday) == "no_term"
    assert handoff_state.phase_of(monday, None, thursday) == "upcoming"
    # Poniedziałkowe spotkanie potwierdza się w piątek, nie w niedzielę.
    assert handoff_state.phase_of(monday, None, friday) == "confirm"
    assert handoff_state.phase_of(monday, friday, friday) == "upcoming"
    assert (
        handoff_state.phase_of(monday, None, monday + timedelta(minutes=1)) == "verdict"
    )
    # 11.11 to święto: środowe spotkanie 12.11 potwierdza się we wtorek 10.11.
    wednesday = datetime(2026, 11, 12, 10, 0, tzinfo=WARSAW)
    assert handoff_state.previous_business_day(wednesday.date()) == date(2026, 11, 10)
    assert handoff_state.next_business_day(date(2026, 11, 10)) == date(2026, 11, 12)


@pytest.mark.asyncio
async def test_term_is_set_by_the_caller_and_resets_confirmation(app_client) -> None:
    caller, host = await _pair()
    booked = await _booked(app_client, caller, host)
    opportunity_id = booked["opportunity"]["id"]
    no_term = await app_client.post(
        f"{URL}/{opportunity_id}/confirm", headers=_headers(host)
    )
    assert no_term.status_code == 409

    tomorrow = _in(1)
    resp = await app_client.put(
        f"{URL}/{opportunity_id}/term",
        json={"meeting_at": tomorrow.isoformat(), "duration_minutes": 60},
        headers=_headers(caller),
    )
    assert resp.status_code == 200, resp.text
    assert datetime.fromisoformat(resp.json()["meeting_at"]) == tomorrow
    [meeting] = await _meetings(opportunity_id)
    assert (meeting.occurred_at, meeting.duration_minutes) == (tomorrow, 60)

    confirmed = await app_client.post(
        f"{URL}/{opportunity_id}/confirm", headers=_headers(host)
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["confirmed_at"] is not None
    assert confirmed.json()["phase"] == "upcoming"

    moved = await app_client.put(
        f"{URL}/{opportunity_id}/term",
        json={"meeting_at": _in(4).isoformat()},
        headers=_headers(host),
    )
    assert moved.json()["confirmed_at"] is None
    assert len(await _meetings(opportunity_id)) == 1

    cleared = await app_client.put(
        f"{URL}/{opportunity_id}/term", json={}, headers=_headers(host)
    )
    assert cleared.json()["phase"] == "no_term"
    assert await _meetings(opportunity_id) == []


@pytest.mark.asyncio
async def test_stranger_cannot_touch_the_term(app_client) -> None:
    caller, host = await _pair()
    stranger = await _user("sales_edit")
    viewer = await _user("sales_view")
    booked = await _booked(app_client, caller, host, meeting_at=_in(1).isoformat())
    opportunity_id = booked["opportunity"]["id"]
    body = {"meeting_at": _in(5).isoformat()}
    resp = await app_client.put(
        f"{URL}/{opportunity_id}/term", json=body, headers=_headers(stranger)
    )
    assert resp.status_code == 403
    assert (
        await app_client.post(
            f"{URL}/{opportunity_id}/confirm", headers=_headers(stranger)
        )
    ).status_code == 403
    assert (
        await app_client.put(
            f"{URL}/{opportunity_id}/term", json=body, headers=_headers(viewer)
        )
    ).status_code == 403


@pytest.mark.asyncio
async def test_two_meetings_at_the_same_hour_are_flagged(app_client) -> None:
    caller, host = await _pair()
    when = _in(2, hour=13)
    await _booked(app_client, caller, host, meeting_at=when.isoformat())
    await _booked(
        app_client,
        caller,
        host,
        meeting_at=(when + timedelta(minutes=15)).isoformat(),
    )
    await _booked(app_client, caller, host, meeting_at=_in(2, hour=15).isoformat())
    rows = (await _mine(app_client, host))["to_me"]
    assert [row["clash"] for row in rows] == [True, True, False]


@pytest.mark.asyncio
async def test_host_busy_shows_hours_without_titles(app_client) -> None:
    caller, host = await _pair()
    day = _in(6).date()
    when = _in(6, hour=10)
    await _booked(app_client, caller, host, meeting_at=when.isoformat())
    params = {"host_id": host.id, "day": day.isoformat()}

    resp = await app_client.get(
        f"{URL}/host-busy", params=params, headers=_headers(caller)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Bez połączonej skrzynki widać tylko spotkania zapisane w Sprzedaży.
    assert body["calendar"] == "unavailable"
    assert [datetime.fromisoformat(span["start"]) for span in body["busy"]] == [when]
    assert set(body["busy"][0]) == {"start", "end"}

    async with AsyncSessionLocal() as db:
        db.add(
            M365Connection(
                user_id=host.id,
                tenant_id="t",
                mailbox_upn=host.email,
                access_token_ct="a",
                refresh_token_ct="r",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                scopes_granted=["Calendars.ReadWrite"],
                is_active=True,
            )
        )
        db.add_all(
            [
                CalendarEvent(
                    created_by=host.id,
                    title="Tytuł, którego nikt nie zobaczy",
                    start_time=_in(6, hour=14),
                    end_time=_in(6, hour=15),
                ),
                CalendarEvent(
                    created_by=host.id,
                    title="Całodniowe przypomnienie",
                    start_time=_in(6, hour=0),
                    end_time=_in(7, hour=0),
                    all_day=True,
                ),
                CalendarEvent(
                    created_by=caller.id,
                    title="Cudzy kalendarz",
                    start_time=_in(6, hour=8),
                    end_time=_in(6, hour=9),
                ),
            ]
        )
        await db.commit()
    resp = await app_client.get(
        f"{URL}/host-busy", params=params, headers=_headers(caller)
    )
    body = resp.json()
    assert body["calendar"] == "ok"
    assert [
        datetime.fromisoformat(span["start"]).astimezone(WARSAW).hour
        for span in body["busy"]
    ] == [10, 14]
    assert "Tytuł" not in resp.text


@pytest.mark.asyncio
async def test_host_busy_is_not_a_peek_into_any_calendar(app_client) -> None:
    caller = await _user("sales_edit")
    recruiter = await _user()
    viewer = await _user("sales_view")
    day = business_today().isoformat()
    resp = await app_client.get(
        f"{URL}/host-busy",
        params={"host_id": recruiter.id, "day": day},
        headers=_headers(caller),
    )
    assert resp.status_code == 422
    resp = await app_client.get(
        f"{URL}/host-busy",
        params={"host_id": caller.id, "day": day},
        headers=_headers(viewer),
    )
    assert resp.status_code == 403


# ── Werdykt ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_qualified_moves_the_opportunity_and_reaches_the_caller(
    app_client,
) -> None:
    caller, host = await _pair()
    stages = await _stages(app_client, caller)
    held = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=2)
    booked = await _booked(app_client, caller, host, meeting_at=held.isoformat())
    opportunity_id = booked["opportunity"]["id"]
    assert booked["phase"] == "verdict"

    resp = await _verdict(app_client, host, opportunity_id, kind="qualified")
    assert resp.status_code == 200, resp.text
    assert resp.json()["verdict"] == "qualified"
    assert resp.json()["phase"] == "done"
    opp = await _opp_row(opportunity_id)
    assert opp.stage_id == stages["qualified"]
    assert opp.qualified_at is not None and opp.status == "open"
    assert opp.last_activity_at == held
    [meeting] = await _meetings(opportunity_id)
    assert meeting.done_at == held

    assert (await _mine(app_client, host))["to_me"] == []
    mine = await _mine(app_client, caller)
    [row] = mine["booked_by_me"]
    assert (row["opportunity"]["id"], row["verdict"]) == (opportunity_id, "qualified")
    assert (mine["weeks"][0]["booked"], mine["weeks"][0]["held"]) == (1, 1)
    assert mine["weeks"][0]["qualified"] == 1
    assert (
        mine["weeks"][0]["week_start"]
        == (
            business_date(datetime.now(timezone.utc))
            - timedelta(days=business_date(datetime.now(timezone.utc)).weekday())
        ).isoformat()
    )

    again = await _verdict(app_client, host, opportunity_id, kind="not_now")
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_verdict_belongs_to_the_host(app_client) -> None:
    caller, host = await _pair()
    stranger = await _user("sales_edit")
    viewer = await _user("sales_view")
    booked = await _booked(app_client, caller, host)
    opportunity_id = booked["opportunity"]["id"]
    for user in (caller, stranger):
        resp = await _verdict(app_client, user, opportunity_id, kind="qualified")
        assert resp.status_code == 403
        assert "Werdykt daje" in resp.json()["detail"]
    denied = await _verdict(app_client, viewer, opportunity_id, kind="qualified")
    assert denied.json()["detail"]["code"] == "permission_denied"
    assert handoff_state.block(await _opp_row(opportunity_id))["verdict"] is None


@pytest.mark.asyncio
async def test_opportunity_without_handoff_has_no_verdict(app_client) -> None:
    owner = await _user("sales_edit")
    created = await app_client.post(
        OPPS,
        json={"company_id": await _firm(), "title": "Zwykła"},
        headers=_headers(owner),
    )
    opportunity_id = created.json()["id"]
    resp = await _verdict(app_client, owner, opportunity_id, kind="qualified")
    assert resp.status_code == 409
    plain = await app_client.get(
        f"{URL}/by-opportunity/{opportunity_id}", headers=_headers(owner)
    )
    assert plain.status_code == 200 and plain.json() is None
    missing = await _verdict(app_client, owner, 10**9, kind="qualified")
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_not_now_comes_back_on_a_date(app_client) -> None:
    caller, host = await _pair()
    stages = await _stages(app_client, caller)
    booked = await _booked(app_client, caller, host)
    opportunity_id = booked["opportunity"]["id"]
    back = business_today() + timedelta(days=45)
    resp = await _verdict(
        app_client,
        host,
        opportunity_id,
        kind="not_now",
        return_on=back.isoformat(),
        reason="budżet od stycznia",
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["return_on"] == back.isoformat()
    opp = await _opp_row(opportunity_id)
    assert opp.stage_id == stages["qualifying-meeting"] and opp.status == "open"
    assert opp.keep_open_until == back
    [task] = await _tasks(opportunity_id)
    assert task.assignee_user_id == host.id
    assert business_date(task.due_at) == back
    assert "budżet od stycznia" in task.subject
    # Odbyte spotkanie bez terminu też zostawia ślad.
    [meeting] = await _meetings(opportunity_id)
    assert meeting.done_at is not None
    week = (await _mine(app_client, caller))["weeks"][0]
    assert (week["held"], week["qualified"]) == (1, 0)


@pytest.mark.asyncio
async def test_not_now_without_a_date_returns_in_a_month(app_client) -> None:
    caller, host = await _pair()
    booked = await _booked(app_client, caller, host)
    resp = await _verdict(app_client, host, booked["opportunity"]["id"], kind="not_now")
    expected = business_date(datetime.now(timezone.utc)) + timedelta(
        days=handoff.NOT_NOW_DEFAULT_DAYS
    )
    assert resp.json()["return_on"] == expected.isoformat()


@pytest.mark.asyncio
async def test_not_a_fit_closes_with_a_reason(app_client) -> None:
    caller, host = await _pair()
    stages = await _stages(app_client, caller)
    booked = await _booked(app_client, caller, host)
    opportunity_id = booked["opportunity"]["id"]
    resp = await _verdict(
        app_client, host, opportunity_id, kind="not_a_fit", reason="  Za mała firma "
    )
    assert resp.status_code == 200, resp.text
    opp = await _opp_row(opportunity_id)
    assert opp.status == "lost" and opp.lost_at is not None
    assert opp.stage_id == stages["not-qualified"]
    assert opp.lost_reason == "Za mała firma"
    [row] = (await _mine(app_client, caller))["booked_by_me"]
    assert (row["verdict"], row["verdict_reason"]) == ("not_a_fit", "Za mała firma")


@pytest.mark.asyncio
async def test_no_show_returns_to_the_caller_as_a_task(app_client) -> None:
    caller, host = await _pair()
    held = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=1)
    booked = await _booked(app_client, caller, host, meeting_at=held.isoformat())
    opportunity_id = booked["opportunity"]["id"]

    resp = await _verdict(app_client, host, opportunity_id, kind="no_show")
    assert resp.status_code == 200, resp.text
    opp = await _opp_row(opportunity_id)
    assert opp.status == "open" and opp.owner_user_id == host.id
    # Spotkanie, które się nie odbyło, nie zostaje jako odbyte.
    assert await _meetings(opportunity_id) == []
    assert opp.last_activity_at is None
    [task] = await _tasks(opportunity_id)
    assert task.assignee_user_id == caller.id
    assert task.due_at > datetime.now(timezone.utc)
    mine = await _mine(app_client, caller)
    assert mine["booked_by_me"][0]["verdict"] == "no_show"
    assert (mine["weeks"][0]["booked"], mine["weeks"][0]["held"]) == (1, 0)
    assert (await _mine(app_client, host))["to_me"] == []

    # Dzwoniący umawia ponownie tę samą szansę; prowadzącego nie zmienia.
    other_host = await _user("sales_edit")
    swapped = await _book(
        app_client, caller, opportunity_id=opportunity_id, host_user_id=other_host.id
    )
    assert swapped.status_code == 403
    again = _in(3)
    rebooked = await _book(
        app_client,
        caller,
        opportunity_id=opportunity_id,
        host_user_id=host.id,
        meeting_at=again.isoformat(),
    )
    assert rebooked.status_code == 201, rebooked.text
    assert rebooked.json()["verdict"] is None
    assert rebooked.json()["booked_by"]["id"] == caller.id
    [row] = (await _mine(app_client, host))["to_me"]
    assert datetime.fromisoformat(row["meeting_at"]) == again
    assert (await _mine(app_client, caller))["weeks"][0]["booked"] == 2


@pytest.mark.asyncio
async def test_caller_cannot_erase_a_verdict_by_rebooking(app_client) -> None:
    caller, host = await _pair()
    booked = await _booked(app_client, caller, host)
    opportunity_id = booked["opportunity"]["id"]
    await _verdict(app_client, host, opportunity_id, kind="qualified")

    resp = await _book(
        app_client, caller, opportunity_id=opportunity_id, host_user_id=host.id
    )
    assert resp.status_code == 409
    kept = handoff_state.block(await _opp_row(opportunity_id))["verdict"]
    assert kept["kind"] == "qualified"
    # Prowadzący może umówić kolejne spotkanie na swojej szansie.
    again = await _book(
        app_client, host, opportunity_id=opportunity_id, host_user_id=host.id
    )
    assert again.status_code == 201, again.text


@pytest.mark.asyncio
async def test_caller_rebooks_after_not_now(app_client) -> None:
    caller, host = await _pair()
    booked = await _booked(app_client, caller, host)
    opportunity_id = booked["opportunity"]["id"]
    await _verdict(app_client, host, opportunity_id, kind="not_now")
    resp = await _book(
        app_client,
        caller,
        opportunity_id=opportunity_id,
        host_user_id=host.id,
        meeting_at=_in(20).isoformat(),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["phase"] == "upcoming"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["no_show", "not_now"])
async def test_rebooking_after_a_calendar_meeting_starts_a_new_term(
    app_client, kind: str
) -> None:
    """Audyt 12.11 (S5): po werdykcie stare spotkanie z Outlooka trzymało termin.

    Karta pokazywała starą datę i od razu prosiła o werdykt, a zmiana terminu,
    zaproszenie i przejęcie nowego spotkania z kalendarza dostawały 409.
    """

    caller, host = await _pair()
    held = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=30)
    booked = await _booked(app_client, caller, host, meeting_at=held.isoformat())
    opportunity_id = booked["opportunity"]["id"]
    company_id = booked["company"]["id"]
    old = await _activity(company_id, when=held, owner_id=host.id)
    async with AsyncSessionLocal() as db:
        await meeting_autopin.pin_obvious_meetings(db, now=datetime.now(timezone.utc))
        await db.commit()
    [row] = (await _mine(app_client, host))["to_me"]
    assert row["from_calendar"] is True
    resp = await _verdict(app_client, host, opportunity_id, kind=kind)
    assert resp.status_code == 200, resp.text

    again = _in(4)
    rebooked = await _book(
        app_client,
        caller,
        opportunity_id=opportunity_id,
        host_user_id=host.id,
        meeting_at=again.isoformat(),
    )
    assert rebooked.status_code == 201, rebooked.text
    [row] = (await _mine(app_client, host))["to_me"]
    assert (row["from_calendar"], row["phase"]) == (False, "upcoming")
    assert datetime.fromisoformat(row["meeting_at"]) == again
    # Stare spotkanie zostaje na osi szansy obok nowego wpisu terminu.
    meetings = await _meetings(opportunity_id)
    assert old in [m.id for m in meetings] and len(meetings) == 2

    moved = _in(5)
    term = await app_client.put(
        f"{URL}/{opportunity_id}/term",
        json={"meeting_at": moved.isoformat()},
        headers=_headers(caller),
    )
    assert term.status_code == 200, term.text
    async with AsyncSessionLocal() as db:
        opp = await db.get(SalesOpportunity, opportunity_id)
        meeting_at, _ = await handoff_invite.reserve(
            db,
            opp,
            handoff_invite.InviteRequest(
                subject="Spotkanie", to=["klient@example.com"], request_id=uuid.uuid4()
            ),
            now=datetime.now(timezone.utc),
        )
        assert meeting_at == moved
        await db.rollback()

    # Nowe spotkanie z Outlooka w nowym terminie zostaje przejęte.
    invite = await _activity(company_id, when=moved, owner_id=host.id, done=False)
    async with AsyncSessionLocal() as db:
        opp = await db.get(SalesOpportunity, opportunity_id)
        activity = await db.get(SalesActivity, invite)
        activity.opportunity_id = opportunity_id
        assert await handoff.adopt_calendar_meeting(db, opp, activity) is True
        await db.commit()
    [row] = (await _mine(app_client, host))["to_me"]
    assert row["from_calendar"] is True


@pytest.mark.asyncio
async def test_closed_opportunity_takes_no_verdict(app_client) -> None:
    caller, host = await _pair()
    stages = await _stages(app_client, caller)
    booked = await _booked(app_client, caller, host)
    opportunity_id = booked["opportunity"]["id"]
    moved = await app_client.post(
        f"{OPPS}/{opportunity_id}/move",
        json={"stage_id": stages["lost"], "lost_reason": "Zamknięta z tablicy"},
        headers=_headers(host),
    )
    assert moved.status_code == 200
    resp = await _verdict(app_client, host, opportunity_id, kind="qualified")
    assert resp.status_code == 409
    assert (await _mine(app_client, host))["to_me"] == []


@pytest.mark.asyncio
async def test_hosts_own_booking_is_listed_once(app_client) -> None:
    host = await _user("sales_edit")
    booked = await _booked(app_client, host, host, meeting_at=_in(2).isoformat())
    mine = await _mine(app_client, host)
    assert [row["opportunity"]["id"] for row in mine["to_me"]] == [
        booked["opportunity"]["id"]
    ]
    assert mine["booked_by_me"] == []
    assert mine["weeks"][0]["booked"] == 1


@pytest.mark.asyncio
async def test_opportunity_card_reads_the_handoff(app_client) -> None:
    caller, host = await _pair()
    viewer = await _user("sales_view")
    booked = await _booked(app_client, caller, host, problem="Ręczne raporty")
    resp = await app_client.get(
        f"{URL}/by-opportunity/{booked['opportunity']['id']}", headers=_headers(viewer)
    )
    assert resp.status_code == 200
    assert resp.json()["problem"] == "Ręczne raporty"
    assert resp.json()["booked_by"]["id"] == caller.id


def test_request_models_reject_unknown_fields() -> None:
    with pytest.raises(ValueError):
        handoff.BookRequest(host_user_id=1, company_id=1, owner_user_id=2)
    with pytest.raises(ValueError):
        handoff.VerdictRequest(kind="won")
    naive = handoff_state.to_utc(datetime(2026, 11, 12, 13, 0))
    assert naive == datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)


def _block(**fields: Any) -> dict[str, Any]:
    return {"custom_fields": {handoff_state.HANDOFF_KEY: fields}}


def test_planned_term_ignores_settled_handoffs() -> None:
    when = "2026-11-12T12:00:00+00:00"
    pending = SalesOpportunity(**_block(meeting_at=when, verdict=None))
    settled = SalesOpportunity(**_block(meeting_at=when, verdict={"kind": "no_show"}))
    plain = SalesOpportunity(custom_fields={"atlas": {}})
    assert handoff.planned_term(pending) == datetime.fromisoformat(when)
    assert handoff.planned_term(settled) is None
    assert handoff.planned_term(plain) is None
    broken: Optional[dict] = handoff_state.block(
        SalesOpportunity(custom_fields={"handoff": 1})
    )
    assert broken is None
