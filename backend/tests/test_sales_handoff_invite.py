"""Sprzedaż → zaproszenie na przekazane spotkanie (``/api/sales/handoffs/{id}/invite``).

Zaproszenie wysyła prowadzący, ze swojej skrzynki i po swoim kliknięciu. Nie wysyła go
osoba, która umówiła spotkanie, ani administrator; nie idzie do adresów z bazy
kandydatów; drugie kliknięcie nie tworzy drugiego spotkania. Graph jest podstawiony.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import pytest

from app.core.database import AsyncSessionLocal
from app.models.m365 import M365Connection
from app.services.m365.graph_client import GraphRequestError
from app.services.sales import handoff, handoff_invite, handoff_state
from app.services.sales import outlook_activities as outlook
from tests.test_sales_companies_api import _headers, _user
from tests.test_sales_handoff import _booked, _in, _meetings, _mine, _pair
from tests.test_sales_meeting_decisions import _events, _opp_row
from tests.test_sales_outlook_sync import _candidate

URL = "/api/sales/handoffs"


def _tag() -> str:
    return uuid.uuid4().hex[:10]


class _FakeGraph:
    """Kalendarz Graph: ``fail_status`` = odpowiedź błędem zamiast wydarzenia."""

    calls: list[tuple[str, Any]] = []
    fail_status: Optional[int] = None

    def __init__(self, connection, db, *, sales_ok: bool = False) -> None:
        # Skrzynka handlowca bez dostępu do kandydatów musi przejść jawnie.
        assert sales_ok is True
        self.connection = connection

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info) -> None:
        return None

    async def post(self, url: str, json=None, **_kwargs):
        type(self).calls.append((url, json))
        if type(self).fail_status is not None:
            raise GraphRequestError(type(self).fail_status, "boom")
        return {
            "id": f"evt-{_tag()}",
            "iCalUId": f"ical-{_tag()}",
            "webLink": "https://outlook.example/calendar/item",
        }


@pytest.fixture
def graph(monkeypatch):
    _FakeGraph.calls = []
    _FakeGraph.fail_status = None
    monkeypatch.setattr(handoff_invite, "GraphClient", _FakeGraph)
    return _FakeGraph


async def _mailbox(user, *, scopes=("Calendars.ReadWrite",), active=True) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            M365Connection(
                user_id=user.id,
                tenant_id="t",
                mailbox_upn=user.email,
                access_token_ct="a",
                refresh_token_ct="r",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                scopes_granted=list(scopes),
                is_active=active,
            )
        )
        await db.commit()


def _body(**overrides: Any) -> dict[str, Any]:
    return {
        "subject": "Spotkanie: automatyzacje",
        "to": ["Klient@Firma-Zaproszona.example"],
        "message": "Dzień dobry,\nprzesyłam zaproszenie.",
        "request_id": str(uuid.uuid4()),
        **overrides,
    }


async def _send(app_client, user, opportunity_id: int, **overrides: Any):
    return await app_client.post(
        f"{URL}/{opportunity_id}/invite",
        json=_body(**overrides),
        headers=_headers(user),
    )


async def _handoff(app_client, *, days: Optional[int] = 3, **fields: Any):
    caller, host = await _pair()
    if days is not None:
        fields["meeting_at"] = _in(days, hour=13).isoformat()
    booked = await _booked(app_client, caller, host, **fields)
    return caller, host, booked["opportunity"]["id"], booked


@pytest.mark.asyncio
async def test_host_sends_a_teams_invitation_from_own_mailbox(
    app_client, graph
) -> None:
    caller, host, opportunity_id, booked = await _handoff(
        app_client, duration_minutes=45
    )
    await _mailbox(host)
    [placeholder] = await _meetings(opportunity_id)

    resp = await _send(app_client, host, opportunity_id)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["invite_sent_at"] is not None
    assert body["from_calendar"] is True

    [(url, event)] = graph.calls
    assert url == "/me/events"
    assert event["subject"] == "Spotkanie: automatyzacje"
    assert [a["emailAddress"]["address"] for a in event["attendees"]] == [
        "klient@firma-zaproszona.example"
    ]
    assert event["isOnlineMeeting"] is True
    assert event["onlineMeetingProvider"] == "teamsForBusiness"
    assert event["transactionId"].startswith("nexus-")
    assert "przesyłam zaproszenie" in event["body"]["content"]
    start = datetime.fromisoformat(event["start"]["dateTime"])
    end = datetime.fromisoformat(event["end"]["dateTime"])
    assert end - start == timedelta(minutes=45)

    # Jedno spotkanie to jeden wiersz: wpis terminu zastąpiło spotkanie z Outlooka.
    [meeting] = await _meetings(opportunity_id)
    assert meeting.id != placeholder.id
    assert meeting.external_source == outlook.EVENT_SOURCE
    assert meeting.created_by_user_id == host.id
    assert meeting.occurred_at == datetime.fromisoformat(booked["meeting_at"])

    steps = [
        (event.field, event.new_value, event.old_value)
        for event in await _events(opportunity_id)
        if event.field == handoff.HISTORY_FIELD
    ]
    assert steps[-1] == (handoff.HISTORY_FIELD, "invited", None)
    # W historii nie ma adresów ani tematu zaproszenia.
    assert "firma-zaproszona" not in str(steps)

    # Termin jest teraz w kalendarzu: zmienia się go w Outlooku.
    moved = await app_client.put(
        f"{URL}/{opportunity_id}/term",
        json={"meeting_at": _in(5).isoformat()},
        headers=_headers(host),
    )
    assert moved.status_code == 409
    [row] = (await _mine(app_client, caller))["booked_by_me"]
    assert row["invite_sent_at"] is not None


@pytest.mark.asyncio
async def test_only_the_host_sends_the_invitation(app_client, graph) -> None:
    caller, host, opportunity_id, _ = await _handoff(app_client)
    stranger = await _user("sales_edit")
    admin = await _user(role="admin")
    viewer = await _user("sales_view")
    for user in (caller, stranger, admin):
        await _mailbox(user)
        resp = await _send(app_client, user, opportunity_id)
        assert resp.status_code == 403, resp.text
        assert "prowadzący" in resp.json()["detail"]
        draft = await app_client.get(
            f"{URL}/{opportunity_id}/invite", headers=_headers(user)
        )
        assert draft.status_code == 403
    denied = await _send(app_client, viewer, opportunity_id)
    assert denied.json()["detail"]["code"] == "permission_denied"
    assert graph.calls == []


@pytest.mark.asyncio
async def test_invitation_needs_a_connected_calendar(app_client, graph) -> None:
    _, host, opportunity_id, _ = await _handoff(app_client)
    missing = await _send(app_client, host, opportunity_id)
    assert missing.status_code == 409
    assert "Podłącz skrzynkę" in missing.json()["detail"]

    _, mail_only, second_id, _ = await _handoff(app_client)
    await _mailbox(mail_only, scopes=("Mail.Send",))
    no_scope = await _send(app_client, mail_only, second_id)
    assert no_scope.status_code == 409
    assert "kalendarz" in no_scope.json()["detail"]

    _, inactive, third_id, _ = await _handoff(app_client)
    await _mailbox(inactive, active=False)
    assert (await _send(app_client, inactive, third_id)).status_code == 409
    assert graph.calls == []


@pytest.mark.asyncio
async def test_candidates_are_never_invited_from_sales(app_client, graph) -> None:
    _, host, opportunity_id, _ = await _handoff(app_client)
    await _mailbox(host)
    address = f"kandydat-{_tag()}@example.com"
    await _candidate(address)
    resp = await _send(
        app_client, host, opportunity_id, to=["klient@firma.example", address]
    )
    assert resp.status_code == 422
    # Odmowa nie wymienia adresu: wpisywanie nie sprawdza, kto jest w bazie.
    assert address not in resp.text
    assert graph.calls == []
    opp = await _opp_row(opportunity_id)
    assert handoff_state.invite_sent_at(handoff_state.block(opp)) is None


@pytest.mark.asyncio
async def test_bad_address_and_empty_subject_are_refused(app_client, graph) -> None:
    _, host, opportunity_id, _ = await _handoff(app_client)
    await _mailbox(host)
    bad = await _send(app_client, host, opportunity_id, to=["to nie adres"])
    assert bad.status_code == 422
    blank = await _send(app_client, host, opportunity_id, subject="   ")
    assert blank.status_code == 422
    nobody = await _send(app_client, host, opportunity_id, to=[])
    assert nobody.status_code == 422
    assert graph.calls == []


@pytest.mark.asyncio
async def test_invitation_needs_a_future_term(app_client, graph) -> None:
    _, host, no_term_id, _ = await _handoff(app_client, days=None)
    await _mailbox(host)
    assert (await _send(app_client, host, no_term_id)).status_code == 409

    past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    _, late, past_id, _ = await _handoff(app_client, days=None, meeting_at=past)
    await _mailbox(late)
    resp = await _send(app_client, late, past_id)
    assert resp.status_code == 409
    assert "minął" in resp.json()["detail"]
    assert graph.calls == []


@pytest.mark.asyncio
async def test_second_click_does_not_send_a_second_invitation(
    app_client, graph
) -> None:
    _, host, opportunity_id, _ = await _handoff(app_client)
    await _mailbox(host)
    assert (await _send(app_client, host, opportunity_id)).status_code == 200
    again = await _send(app_client, host, opportunity_id)
    assert again.status_code == 409
    assert len(graph.calls) == 1
    assert len(await _meetings(opportunity_id)) == 1


@pytest.mark.asyncio
async def test_refused_by_outlook_can_be_retried(app_client, graph) -> None:
    _, host, opportunity_id, _ = await _handoff(app_client)
    await _mailbox(host)
    request_id = str(uuid.uuid4())
    graph.fail_status = 400
    refused = await _send(app_client, host, opportunity_id, request_id=request_id)
    assert refused.status_code == 502
    assert "Nic nie wyszło" in refused.json()["detail"]
    opp = await _opp_row(opportunity_id)
    assert handoff_invite.INVITE_KEY not in handoff_state.block(opp)

    graph.fail_status = None
    retried = await _send(app_client, host, opportunity_id, request_id=request_id)
    assert retried.status_code == 200, retried.text


@pytest.mark.asyncio
async def test_lost_answer_keeps_the_key_and_asks_to_check(app_client, graph) -> None:
    _, host, opportunity_id, _ = await _handoff(app_client)
    await _mailbox(host)
    request_id = str(uuid.uuid4())
    graph.fail_status = 503
    unsure = await _send(app_client, host, opportunity_id, request_id=request_id)
    assert unsure.status_code == 409
    assert "Sprawdź kalendarz" in unsure.json()["detail"]
    # Ten sam klucz nie wyśle drugi raz, a wpis terminu z formularza zostaje.
    graph.fail_status = None
    same = await _send(app_client, host, opportunity_id, request_id=request_id)
    assert same.status_code == 409
    assert len(graph.calls) == 1
    [meeting] = await _meetings(opportunity_id)
    assert meeting.external_source is None


@pytest.mark.asyncio
async def test_draft_tells_the_mailbox_state_and_proposes_the_contact(
    app_client, graph
) -> None:
    address = f"osoba-{_tag()}@firma-z-oknem.example"
    _, host, opportunity_id, _ = await _handoff(
        app_client,
        service="Automatyzacje",
        new_contact={"full_name": "Anna Przykładowa", "email": address},
    )
    url = f"{URL}/{opportunity_id}/invite"
    first = (await app_client.get(url, headers=_headers(host))).json()
    assert first["mailbox"] == "missing"
    assert first["subject"] == "Spotkanie: Automatyzacje"
    assert first["recipients"] == [
        {"address": address, "name": "Anna Przykładowa", "blocked": None}
    ]
    assert first["sent_at"] is None and first["duration_minutes"] == 30

    await _mailbox(host)
    await _candidate(address)
    second = (await app_client.get(url, headers=_headers(host))).json()
    assert second["mailbox"] == "ok"
    assert second["recipients"][0]["blocked"] == "candidate"
    assert graph.calls == []


@pytest.mark.asyncio
async def test_calendar_sync_merges_with_the_sent_invitation(app_client, graph) -> None:
    domain = f"zaproszona-{_tag()}.example"
    _, host, opportunity_id, booked = await _handoff(
        app_client,
        new_company={"name": f"Firma {domain}", "domain": domain},
    )
    await _mailbox(host)
    sent = await _send(app_client, host, opportunity_id, to=[f"klient@{domain}"])
    assert sent.status_code == 200, sent.text
    [meeting] = await _meetings(opportunity_id)

    # Kopia z synchronizacji kalendarza ma ten sam iCalUId: skleja się, nie dubluje.
    async with AsyncSessionLocal() as db:
        await outlook.record(
            db,
            outlook.OutlookItem(
                source=outlook.EVENT_SOURCE,
                external_id=meeting.external_id,
                owner_user_id=host.id,
                owner_address=host.email,
                addresses=[f"klient@{domain}"],
                subject="Spotkanie: automatyzacje",
                preview=None,
                occurred_at=meeting.occurred_at,
                duration_minutes=30,
            ),
        )
        await db.commit()
    [after] = await _meetings(opportunity_id)
    assert after.id == meeting.id
    assert after.opportunity_id == opportunity_id
    assert booked["company"]["id"] == after.company_id
