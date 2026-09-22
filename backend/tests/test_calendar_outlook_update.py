"""Zmiana terminu wydarzenia z Outlooka z poziomu NEXUSA (0338, „oba kierunki”).

Do 0338 każda zmiana terminu wydarzenia z Outlooka dawała 409 — kalendarz
NEXUSA był tylko do oglądania. Teraz termin, tytuł, miejsce i opis idą
PATCH-em do Outlooka organizatora (twórcy wiersza), a lokalny zapis dopiero
po sukcesie. Każda odmowa zostawia wiersz nietknięty.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token, hash_password
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.m365 import M365Connection
from app.models.user import User, UserRole
from app.services.m365 import calendar as m365_calendar
from app.services.m365.graph_client import GraphRequestError

_START = datetime(2039, 2, 7, 9, 0, tzinfo=timezone.utc)


async def _owner_with_event(*, connected: bool = True) -> tuple[dict, int]:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"upd-{tag}@example.com",
            password_hash=hash_password(f"Upd4te_{tag}!pw"),
            name=f"Upd {tag}",
            role=UserRole.recruiter,
            roles=["recruiter"],
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.flush()
        if connected:
            db.add(
                M365Connection(
                    user_id=user.id,
                    tenant_id="t",
                    mailbox_upn=f"upd-{tag}@example.com",
                    access_token_ct="a",
                    refresh_token_ct="r",
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                    is_active=True,
                )
            )
        ev = CalendarEvent(
            title="Prep z kandydatem",
            event_type=EventType.prep_call,
            start_time=_START,
            end_time=_START + timedelta(minutes=30),
            status=EventStatus.scheduled,
            created_by=user.id,
            external_source="microsoft365",
            external_id=f"graph-{tag}",
            m365_change_key="ck-1",
            attendees=[],
        )
        db.add(ev)
        await db.commit()
        headers = {
            "Authorization": "Bearer "
            + create_access_token(user.id, "recruiter", roles=["recruiter"])
        }
        return headers, ev.id


def test_update_payload_uses_local_business_time():
    payload = m365_calendar.build_update_payload(
        title="Nowy",
        start=datetime(2039, 2, 7, 9, 0, tzinfo=timezone.utc),
        end=datetime(2039, 2, 7, 9, 30, tzinfo=timezone.utc),
        set_location=True,
        location=None,
    )
    assert payload["subject"] == "Nowy"
    # Luty = CET (UTC+1), czas bez przesunięcia + nazwa strefy.
    assert payload["start"]["dateTime"] == "2039-02-07T10:00:00"
    assert payload["start"]["timeZone"] == "Europe/Warsaw"
    assert payload["location"] == {"displayName": ""}
    assert "body" not in payload


async def test_moving_outlook_event_pushes_to_graph_first(
    app_client: AsyncClient, monkeypatch
):
    headers, event_id = await _owner_with_event()
    calls: list[tuple[str, dict]] = []

    async def fake_update(db, conn, graph_id, payload):
        calls.append((graph_id, payload))
        return "ck-2"

    monkeypatch.setattr(m365_calendar, "update_graph_event", fake_update)
    new_start = _START + timedelta(hours=2)
    resp = await app_client.patch(
        f"/api/calendar/events/{event_id}",
        headers=headers,
        json={
            "start_time": new_start.isoformat(),
            "end_time": (new_start + timedelta(minutes=30)).isoformat(),
        },
    )
    assert resp.status_code == 200, resp.text
    assert len(calls) == 1
    assert calls[0][1]["start"]["dateTime"] == "2039-02-07T12:00:00"
    async with AsyncSessionLocal() as db:
        ev = await db.get(CalendarEvent, event_id)
        assert ev.start_time == new_start
        assert ev.m365_change_key == "ck-2"


async def test_graph_refusal_leaves_event_untouched(
    app_client: AsyncClient, monkeypatch
):
    headers, event_id = await _owner_with_event()

    async def refuse(db, conn, graph_id, payload):
        raise GraphRequestError(403, "not organizer")

    monkeypatch.setattr(m365_calendar, "update_graph_event", refuse)
    resp = await app_client.patch(
        f"/api/calendar/events/{event_id}",
        headers=headers,
        json={"title": "Zmieniony"},
    )
    assert resp.status_code == 409, resp.text
    assert "organizuje je ktoś inny" in resp.json()["detail"]
    async with AsyncSessionLocal() as db:
        ev = await db.get(CalendarEvent, event_id)
        assert ev.title == "Prep z kandydatem"


async def test_attendees_still_belong_to_outlook(app_client: AsyncClient):
    headers, event_id = await _owner_with_event()
    resp = await app_client.patch(
        f"/api/calendar/events/{event_id}",
        headers=headers,
        json={"attendees": ["x@example.com"]},
    )
    assert resp.status_code == 409, resp.text
