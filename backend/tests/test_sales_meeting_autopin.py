"""Sprzedaż → spotkanie z kalendarza przypina się samo (``meeting_autopin``).

Automat przypina tylko wtedy, gdy nie ma czego wybierać: jedna otwarta szansa
w firmie albo termin przekazania z formularza „Umów spotkanie”. Przypięcie da
się cofnąć i cofnięte nie wraca.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app.core.database import AsyncSessionLocal
from app.services.sales import handoff, meeting_autopin
from app.services.sales.meeting_decisions import OUTLOOK_FIELD
from tests.test_sales_companies_api import _headers, _user
from tests.test_sales_handoff import _booked, _in, _meetings, _mine, _tag
from tests.test_sales_meeting_decisions import (
    ACTIVITIES,
    _activity,
    _client,
    _events,
    _firm,
    _list,
    _opportunity,
    _own_firm,
    _row,
)

MY_DAY = "/api/sales/my-day"


async def _run() -> int:
    async with AsyncSessionLocal() as db:
        pinned = await meeting_autopin.pin_obvious_meetings(
            db, now=datetime.now(timezone.utc)
        )
        await db.commit()
        return pinned


def _soon(hours: int = 2) -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0) + timedelta(hours=hours)


@pytest.mark.asyncio
async def test_single_open_opportunity_gets_the_meeting(app_client) -> None:
    rep = await _user("sales_edit")
    company_id = await _firm()
    opp = await _opportunity(app_client, rep, company_id)
    subject = f"Warsztat {_tag()}"
    meeting = await _activity(
        company_id, subject=subject, when=_soon(), owner_id=rep.id, done=False
    )

    await _run()
    assert (await _row(meeting)).opportunity_id == opp["id"]
    pins = [e for e in await _events(opp["id"]) if e.field == OUTLOOK_FIELD]
    # Przypięcie bez osoby: po tym ekran poznaje „przypięte samo”.
    assert [(e.new_value, e.user_id) for e in pins] == [(str(meeting), None)]

    listed = await _list(app_client, rep, q=subject)
    [row] = listed["items"]
    assert (row["decision"], row["auto_pinned"], row["can_unpin"]) == (
        "linked",
        True,
        True,
    )

    # Da się je odpiąć, a odpięte nie wraca przy następnym przebiegu skrzynki.
    undone = await app_client.delete(
        f"{ACTIVITIES}/{meeting}/pin", headers=_headers(rep)
    )
    assert undone.status_code == 200
    await _run()
    assert (await _row(meeting)).opportunity_id is None
    [row] = (await _list(app_client, rep, q=subject))["items"]
    assert (row["decision"], row["auto_pinned"]) == ("pin", False)


@pytest.mark.asyncio
async def test_manual_pin_is_not_called_automatic(app_client) -> None:
    rep = await _user("sales_edit")
    company_id = await _firm()
    first = await _opportunity(app_client, rep, company_id, "Pierwsza")
    await _opportunity(app_client, rep, company_id, "Druga")
    subject = f"Spotkanie {_tag()}"
    meeting = await _activity(company_id, subject=subject, when=_soon(), done=False)
    resp = await app_client.post(
        f"{ACTIVITIES}/{meeting}/pin",
        json={"opportunity_id": first["id"]},
        headers=_headers(rep),
    )
    assert resp.status_code == 200
    [row] = (await _list(app_client, rep, q=subject))["items"]
    assert (row["decision"], row["auto_pinned"]) == ("linked", False)


@pytest.mark.asyncio
async def test_several_opportunities_stay_a_human_choice(app_client) -> None:
    rep = await _user("sales_edit")
    company_id = await _firm()
    await _opportunity(app_client, rep, company_id, "Pierwsza")
    await _opportunity(app_client, rep, company_id, "Druga")
    meeting = await _activity(company_id, when=_soon(), done=False)
    await _run()
    assert (await _row(meeting)).opportunity_id is None


@pytest.mark.asyncio
async def test_meeting_older_than_the_opportunity_stays_with_the_company(
    app_client,
) -> None:
    rep = await _user("sales_edit")
    company_id = await _firm()
    meeting = await _activity(
        company_id, when=datetime.now(timezone.utc) - timedelta(days=5)
    )
    await _opportunity(app_client, rep, company_id)
    await _run()
    assert (await _row(meeting)).opportunity_id is None


@pytest.mark.asyncio
async def test_client_and_own_company_are_left_to_people(app_client) -> None:
    rep = await _user("sales_edit")
    client_id, _ = await _client()
    client_company = await _firm(client_id=client_id)
    own_company, _ = await _own_firm()
    meetings = []
    for company_id in (client_company, own_company):
        await _opportunity(app_client, rep, company_id)
        meetings.append(await _activity(company_id, when=_soon(), done=False))
    await _run()
    for meeting in meetings:
        assert (await _row(meeting)).opportunity_id is None


@pytest.mark.asyncio
async def test_one_event_at_two_companies_is_ambiguous(app_client) -> None:
    rep = await _user("sales_edit")
    external_id = f"ical-{_tag()}"
    copies = []
    for _ in range(2):
        company_id = await _firm()
        await _opportunity(app_client, rep, company_id)
        copies.append(
            await _activity(
                company_id, when=_soon(), external_id=external_id, done=False
            )
        )
    await _run()
    for copy in copies:
        assert (await _row(copy)).opportunity_id is None


@pytest.mark.asyncio
async def test_non_outlook_and_imported_meetings_are_not_touched(app_client) -> None:
    rep = await _user("sales_edit")
    company_id = await _firm()
    await _opportunity(app_client, rep, company_id)
    manual = await _activity(company_id, source=None, when=_soon(), done=False)
    mail = await _activity(
        company_id, source="msgraph-mail", kind="email", when=_soon(), done=False
    )
    await _run()
    assert (await _row(manual)).opportunity_id is None
    assert (await _row(mail)).opportunity_id is None


@pytest.mark.asyncio
async def test_calendar_meeting_replaces_the_booked_term(app_client) -> None:
    caller = await _user("sales_edit")
    host = await _user("sales_edit")
    when = _in(3, hour=13)
    booked = await _booked(app_client, caller, host, meeting_at=when.isoformat())
    opportunity_id, company_id = booked["opportunity"]["id"], booked["company"]["id"]
    # Druga otwarta szansa w firmie: termin przekazania i tak wskazuje właściwą.
    await _opportunity(app_client, host, company_id, "Inny temat")
    [placeholder] = await _meetings(opportunity_id)
    invite = await _activity(
        company_id,
        subject="Zaproszenie z Outlooka",
        when=when + timedelta(minutes=5),
        owner_id=host.id,
        done=False,
    )
    other_day = await _activity(
        company_id, when=when + timedelta(days=1), owner_id=host.id, done=False
    )

    await _run()
    assert (await _row(invite)).opportunity_id == opportunity_id
    assert (await _row(other_day)).opportunity_id is None
    # Jedno spotkanie to jeden wiersz: wpis terminu z formularza znika.
    assert await _row(placeholder.id) is None
    assert [m.id for m in await _meetings(opportunity_id)] == [invite]

    [row] = (await _mine(app_client, host))["to_me"]
    assert row["from_calendar"] is True
    assert datetime.fromisoformat(row["meeting_at"]) == when + timedelta(minutes=5)
    moved = await app_client.put(
        f"/api/sales/handoffs/{opportunity_id}/term",
        json={"meeting_at": _in(5).isoformat()},
        headers=_headers(host),
    )
    assert moved.status_code == 409
    assert "Outlooku" in moved.json()["detail"]


@pytest.mark.asyncio
async def test_calendar_gives_the_term_to_a_handoff_without_one(app_client) -> None:
    caller = await _user("sales_edit")
    host = await _user("sales_edit")
    booked = await _booked(app_client, caller, host)
    assert booked["phase"] == "no_term"
    when = _soon(hours=30)
    invite = await _activity(
        booked["company"]["id"], when=when, owner_id=host.id, done=False
    )
    await _run()
    [row] = (await _mine(app_client, host))["to_me"]
    assert row["from_calendar"] is True
    assert datetime.fromisoformat(row["meeting_at"]) == when
    assert (await _row(invite)).opportunity_id == booked["opportunity"]["id"]


@pytest.mark.asyncio
async def test_no_show_keeps_the_calendar_row(app_client) -> None:
    caller = await _user("sales_edit")
    host = await _user("sales_edit")
    held = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=30)
    booked = await _booked(app_client, caller, host, meeting_at=held.isoformat())
    invite = await _activity(booked["company"]["id"], when=held, owner_id=host.id)
    await _run()
    resp = await app_client.post(
        f"/api/sales/handoffs/{booked['opportunity']['id']}/verdict",
        json={"kind": "no_show"},
        headers=_headers(host),
    )
    assert resp.status_code == 200, resp.text
    # Wiersz synchronizacji należy do kalendarza: znika, gdy spotkanie odwołasz w Outlooku.
    assert await _row(invite) is not None


@pytest.mark.asyncio
async def test_my_day_marks_auto_pinned_and_offers_an_opportunity(app_client) -> None:
    rep = await _user("sales_edit")
    with_opp = await _firm()
    opp = await _opportunity(app_client, rep, with_opp)
    noon = datetime.now(timezone.utc).replace(microsecond=0)
    pinned = await _activity(with_opp, when=noon, owner_id=rep.id, done=False)
    without = await _firm()
    loose = await _activity(without, when=noon, owner_id=rep.id, done=False)
    manual = await _activity(
        await _firm(), source=None, when=noon, owner_id=rep.id, done=False
    )
    await _run()

    resp = await app_client.get(MY_DAY, headers=_headers(rep))
    assert resp.status_code == 200, resp.text
    rows: dict[int, dict[str, Any]] = {
        row["activity_id"]: row for row in resp.json()["meetings"]
    }
    assert rows[pinned]["auto_pinned"] is True
    assert rows[pinned]["opportunity"]["id"] == opp["id"]
    assert rows[pinned]["can_create_opportunity"] is False
    assert rows[loose]["auto_pinned"] is False
    # Brak szansy: po spotkaniu ekran proponuje „Załóż szansę”.
    assert rows[loose]["can_create_opportunity"] is True
    assert rows[manual]["can_create_opportunity"] is False


def test_adopt_window_is_the_timeline_merge_window() -> None:
    assert handoff.ADOPT_WINDOW == timedelta(minutes=15)
