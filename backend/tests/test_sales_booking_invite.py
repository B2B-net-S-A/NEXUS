"""Sprzedaż → zaproszenie Teams od umawiającego (``/api/sales/handoffs/{id}/booking-invite``).

Decyzja Artura z 23.11.2026: osoba, która umówiła spotkanie z kolejki dzwonienia,
wysyła zaproszenie jednym kliknięciem, a spotkanie Teams powstaje w kalendarzu
prowadzącego (organizator), z klientem i umawiającym jako uczestnikami. Wysyła tylko
``booked_by`` albo admin, nie do kandydatów ani osób ze sprzeciwem, raz na przekazanie,
a bez aplikacji w Microsoft 365 trasa odpowiada 409. Graph jest podstawiony.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.sales import SalesActivity, SalesContact
from app.services.m365.graph_client import GraphRequestError
from app.services.sales import booking_invite, booking_mail, handoff, handoff_invite
from app.services.sales import outlook_activities as outlook
from tests.test_sales_companies_api import _headers, _user
from tests.test_sales_handoff import _booked, _in, _pair
from tests.test_sales_meeting_decisions import _events
from tests.test_sales_outlook_sync import _candidate

URL = "/api/sales/handoffs"
CLIENT = "Klient@Firma-Zaproszona-Teams.example"


def _tag() -> str:
    return uuid.uuid4().hex[:10]


class _FakeAppGraph:
    """Graph app-only: ``fail_with`` = wyjątek zamiast utworzonego wydarzenia."""

    calls: list[tuple[str, Any]] = []
    fail_with: Optional[Exception] = None

    def __init__(self, *, token_provider) -> None:
        # Zaproszenie idzie tokenem osobnej rejestracji, nie „Teams Prep” ani poczty.
        assert token_provider is booking_invite.acquire_sales_invite_token

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info) -> None:
        return None

    async def post(self, url: str, json=None, **_kwargs):
        type(self).calls.append((url, json))
        if type(self).fail_with is not None:
            raise type(self).fail_with
        return {
            "id": f"ev-{_tag()}",
            "iCalUId": f"ical-{_tag()}",
            "webLink": "https://outlook.office365.com/owa/?itemid=x",
        }


@pytest.fixture
def graph(monkeypatch):
    _FakeAppGraph.calls = []
    _FakeAppGraph.fail_with = None
    monkeypatch.setattr(booking_invite, "AppGraphClient", _FakeAppGraph)
    monkeypatch.setattr(settings, "SALES_INVITE_CLIENT_ID", "app-id")
    monkeypatch.setattr(settings, "SALES_INVITE_CLIENT_SECRET", "sekret")
    monkeypatch.setattr(settings, "M365_MAIL_TENANT_ID", "tenant-b2b")
    return _FakeAppGraph


def _body(**overrides: Any) -> dict[str, Any]:
    return {
        "to": [CLIENT],
        "subject": "B2Bnetwork × Firma: automatyzacje",
        "message": "Dzień dobry,\n\ndziękuję za rozmowę. Zapraszam na spotkanie w Teams.",
        "request_id": str(uuid.uuid4()),
        **overrides,
    }


async def _send(app_client, user, opportunity_id: int, **overrides: Any):
    return await app_client.post(
        f"{URL}/{opportunity_id}/booking-invite",
        json=_body(**overrides),
        headers=_headers(user),
    )


async def _handoff(app_client):
    caller, host = await _pair()
    booked = await _booked(
        app_client, caller, host, meeting_at=_in(3, hour=10).isoformat()
    )
    return caller, host, booked["opportunity"]["id"]


async def _meetings(opportunity_id: int) -> list[SalesActivity]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(SalesActivity).where(
                        SalesActivity.opportunity_id == opportunity_id,
                        SalesActivity.kind == "meeting",
                    )
                )
            ).all()
        )


async def _invite_block(opportunity_id: int) -> Optional[dict]:
    async with AsyncSessionLocal() as db:
        opportunity = await handoff.lock(db, opportunity_id)
        return (handoff.block(opportunity) or {}).get(handoff_invite.INVITE_KEY)


@pytest.mark.asyncio
async def test_caller_creates_teams_meeting_in_host_calendar(app_client, graph) -> None:
    caller, host, opportunity_id = await _handoff(app_client)

    form = (await app_client.get(f"{URL}/form", headers=_headers(caller))).json()
    assert form["teams_invite"] is True

    resp = await _send(app_client, caller, opportunity_id)
    assert resp.status_code == 200, resp.text
    assert resp.json()["invite_sent_at"] is not None

    [(url, payload)] = graph.calls
    # Kalendarz prowadzącego: on jest organizatorem.
    assert url == f"/users/{host.email.lower()}/events"
    assert payload["isOnlineMeeting"] is True
    assert payload["onlineMeetingProvider"] == "teamsForBusiness"
    assert payload["subject"] == "B2Bnetwork × Firma: automatyzacje"
    assert payload["transactionId"]
    attendees = [item["emailAddress"]["address"] for item in payload["attendees"]]
    assert attendees == [CLIENT.lower(), caller.email.lower()]

    # Na osi szansy spotkanie z Outlooka zamiast wpisu terminu; autorem prowadzący.
    [meeting] = await _meetings(opportunity_id)
    assert meeting.external_source == outlook.EVENT_SOURCE
    assert meeting.external_id.startswith("ical-")
    assert meeting.created_by_user_id == host.id

    invite = await _invite_block(opportunity_id)
    assert invite["by"] == caller.id
    assert invite["attendees"] == 2
    steps = [
        event.new_value
        for event in await _events(opportunity_id)
        if event.field == handoff.HISTORY_FIELD
    ]
    assert steps[-1] == "invited"
    assert "firma-zaproszona" not in str(steps)


@pytest.mark.asyncio
async def test_one_invite_per_handoff_whoever_sends(app_client, graph) -> None:
    caller, host, opportunity_id = await _handoff(app_client)
    assert (await _send(app_client, caller, opportunity_id)).status_code == 200

    again = await _send(app_client, caller, opportunity_id)
    assert again.status_code == 409
    # Prowadzący też nie wyśle drugiego: spotkanie jest już w jego kalendarzu.
    from tests.test_sales_handoff_invite import _body as host_body
    from tests.test_sales_handoff_invite import _mailbox

    await _mailbox(host)
    own = await app_client.post(
        f"{URL}/{opportunity_id}/invite", json=host_body(), headers=_headers(host)
    )
    assert own.status_code == 409
    assert len(graph.calls) == 1


@pytest.mark.asyncio
async def test_only_the_person_who_booked_sends(app_client, graph) -> None:
    _caller, host, opportunity_id = await _handoff(app_client)
    stranger = await _user("sales_edit")
    for user in (host, stranger):
        resp = await _send(app_client, user, opportunity_id)
        assert resp.status_code == 403, resp.text
        assert resp.json()["detail"] == booking_mail.SENDER_DETAIL
    viewer = await _user("sales_view")
    assert (await _send(app_client, viewer, opportunity_id)).status_code == 403
    assert graph.calls == []


@pytest.mark.asyncio
async def test_admin_may_send(app_client, graph) -> None:
    _caller, _host, opportunity_id = await _handoff(app_client)
    admin = await _user(role="admin")
    resp = await _send(app_client, admin, opportunity_id)
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_candidates_and_objections_are_refused_before_graph(
    app_client, graph
) -> None:
    caller, _host, opportunity_id = await _handoff(app_client)

    candidate = f"kandydat-{_tag()}@example.com"
    await _candidate(candidate)
    resp = await _send(app_client, caller, opportunity_id, to=[candidate])
    assert resp.status_code == 422
    assert candidate not in resp.text

    objected = f"sprzeciw-{_tag()}@firma-zaproszona-teams.example"
    async with AsyncSessionLocal() as db:
        db.add(
            SalesContact(
                full_name="Osoba Ze Sprzeciwem",
                email=objected,
                do_not_contact_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
    resp = await _send(app_client, caller, opportunity_id, to=[objected.upper()])
    assert resp.status_code == 409
    assert resp.json()["detail"] == booking_mail.OBJECTION_DETAIL
    assert graph.calls == []
    assert await _invite_block(opportunity_id) is None


@pytest.mark.asyncio
async def test_without_app_credentials_form_stays_with_mail(
    app_client, graph, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "SALES_INVITE_CLIENT_SECRET", "")
    caller, _host, opportunity_id = await _handoff(app_client)

    form = (await app_client.get(f"{URL}/form", headers=_headers(caller))).json()
    assert form["teams_invite"] is False
    resp = await _send(app_client, caller, opportunity_id)
    assert resp.status_code == 409
    assert resp.json()["detail"] == booking_invite.NOT_CONFIGURED_DETAIL
    assert graph.calls == []
    assert await _invite_block(opportunity_id) is None


@pytest.mark.asyncio
async def test_host_mailbox_outside_app_scope_releases_reservation(
    app_client, graph
) -> None:
    caller, _host, opportunity_id = await _handoff(app_client)
    graph.fail_with = GraphRequestError(403, "ErrorAccessDenied")

    resp = await _send(app_client, caller, opportunity_id)
    assert resp.status_code == 409
    assert resp.json()["detail"] == booking_invite.NO_ACCESS_DETAIL
    assert await _invite_block(opportunity_id) is None
    assert all(not m.external_source for m in await _meetings(opportunity_id))

    graph.fail_with = None
    retry = await _send(app_client, caller, opportunity_id)
    assert retry.status_code == 200, retry.text


@pytest.mark.asyncio
async def test_connection_never_made_is_undelivered(app_client, graph) -> None:
    caller, _host, opportunity_id = await _handoff(app_client)
    # Zapora wyjścia na stagingu: Graph nie widział żądania.
    graph.fail_with = httpx.ConnectError("staging: połączenie zablokowane")

    resp = await _send(app_client, caller, opportunity_id)
    assert resp.status_code == 502
    assert resp.json()["detail"] == booking_invite.UNDELIVERED_DETAIL
    assert await _invite_block(opportunity_id) is None


@pytest.mark.asyncio
async def test_unknown_outcome_blocks_retry(app_client, graph) -> None:
    caller, _host, opportunity_id = await _handoff(app_client)
    graph.fail_with = GraphRequestError(503, "unavailable")

    resp = await _send(app_client, caller, opportunity_id)
    assert resp.status_code == 409
    assert resp.json()["detail"] == booking_invite.UNCERTAIN_DETAIL
    graph.fail_with = None
    again = await _send(app_client, caller, opportunity_id)
    assert again.status_code == 409
    assert again.json()["detail"] == handoff_invite.IN_FLIGHT_DETAIL
    assert len(graph.calls) == 1


@pytest.mark.asyncio
async def test_caller_can_stay_off_the_attendee_list(app_client, graph) -> None:
    caller, _host, opportunity_id = await _handoff(app_client)
    resp = await _send(app_client, caller, opportunity_id, include_me=False)
    assert resp.status_code == 200, resp.text
    [(_, payload)] = graph.calls
    attendees = [item["emailAddress"]["address"] for item in payload["attendees"]]
    assert attendees == [CLIENT.lower()]


@pytest.mark.asyncio
async def test_meeting_without_term_cannot_be_invited(app_client, graph) -> None:
    caller, host = await _pair()
    booked = await _booked(app_client, caller, host)
    resp = await _send(app_client, caller, booked["opportunity"]["id"])
    assert resp.status_code == 409
    assert resp.json()["detail"] == handoff.NO_TERM_DETAIL
    assert graph.calls == []


def test_attendees_skip_the_organizer_and_duplicates() -> None:
    assert booking_invite.attendee_list(
        ["a@x.pl", "host@b2b.pl"], "a@x.pl", "host@b2b.pl"
    ) == ["a@x.pl"]
    assert booking_invite.attendee_list(["a@x.pl"], "host@b2b.pl", "host@b2b.pl") == [
        "a@x.pl"
    ]
    assert booking_invite.attendee_list(["a@x.pl"], "me@b2b.pl", "host@b2b.pl") == [
        "a@x.pl",
        "me@b2b.pl",
    ]


@pytest.mark.asyncio
async def test_token_failure_is_undelivered_and_frees_the_reservation(
    app_client, graph, monkeypatch
) -> None:
    """Entra nieosiągalne (MSAL rzuca ``requests``): nic nie wyszło, ponowienie od razu."""

    import requests

    from app.services.m365 import sales_invite_auth
    from app.services.m365.app_graph_client import AppGraphClient

    class _Broken:
        def acquire_token_for_client(self, scopes):
            raise requests.exceptions.ConnectionError("login.microsoftonline.com")

        def remove_tokens_for_client(self) -> None:
            return None

    monkeypatch.setattr(booking_invite, "AppGraphClient", AppGraphClient)
    monkeypatch.setattr(sales_invite_auth, "_msal_app", lambda: _Broken())
    caller, _host, opportunity_id = await _handoff(app_client)

    resp = await _send(app_client, caller, opportunity_id)
    assert resp.status_code == 502, resp.text
    assert resp.json()["detail"] == booking_invite.UNDELIVERED_DETAIL
    assert await _invite_block(opportunity_id) is None


@pytest.mark.asyncio
async def test_staging_egress_block_is_undelivered(app_client, graph) -> None:
    from app.core.staging import StagingEgressBlocked

    caller, _host, opportunity_id = await _handoff(app_client)
    graph.fail_with = StagingEgressBlocked("graph.microsoft.com")
    resp = await _send(app_client, caller, opportunity_id)
    assert resp.status_code == 502, resp.text
    assert await _invite_block(opportunity_id) is None


@pytest.mark.asyncio
async def test_owner_without_sales_edit_gets_no_meeting(app_client, graph) -> None:
    """Opiekun zmieniony po umówieniu na konto bez „Sprzedaż: edycja”: bez spotkania."""

    from app.models.sales import SalesOpportunity

    caller, _host, opportunity_id = await _handoff(app_client)
    outsider = await _user()
    async with AsyncSessionLocal() as db:
        opportunity = await db.get(SalesOpportunity, opportunity_id)
        opportunity.owner_user_id = outsider.id
        await db.commit()

    resp = await _send(app_client, caller, opportunity_id)
    assert resp.status_code == 409
    assert resp.json()["detail"] == booking_invite.NO_HOST_DETAIL
    assert graph.calls == []
    assert await _invite_block(opportunity_id) is None
