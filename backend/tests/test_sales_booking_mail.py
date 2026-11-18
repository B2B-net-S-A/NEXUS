"""Sprzedaż → mail do klienta po „Umów spotkanie” (``/api/sales/handoffs/{id}/booking-mail``).

Prośba osób dzwoniących z 17.11.2026: mail wychodzi ze skrzynki osoby, która umówiła
spotkanie, do klienta z kopią do prowadzącego. Nie wysyła go prowadzący ani ktoś obcy,
nie idzie do adresów z bazy kandydatów ani do osób ze sprzeciwem, drugie kliknięcie
nie wysyła drugiego maila, a odmowa Outlooka zostawia zapisane spotkanie. Graph jest
podstawiony: z testu nic nie wychodzi.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.sales import SalesActivity, SalesContact
from app.services.m365 import sender as m365_sender
from app.services.m365.graph_client import GraphRequestError
from app.services.sales import booking_mail, handoff
from app.services.sales import meeting_client_mail as client_mail
from app.services.sales import outlook_activities as outlook
from tests.test_sales_companies_api import _headers, _user
from tests.test_sales_handoff import _booked, _in, _pair
from tests.test_sales_handoff_invite import _mailbox
from tests.test_sales_meeting_decisions import _events
from tests.test_sales_outlook_sync import _candidate

URL = "/api/sales/handoffs"
CLIENT = "Klient@Firma-Umowiona.example"


def _tag() -> str:
    return uuid.uuid4().hex[:10]


class _FakeGraph:
    """Szkic i wysyłka; ``fail_on`` = ścieżka z błędem, ``fail_with`` = inny wyjątek."""

    calls: list[tuple[str, Any]] = []
    fail_on: Optional[str] = None
    fail_status = 500
    fail_with: Optional[Exception] = None

    def __init__(self, connection, db, *, sales_ok: bool = False) -> None:
        # Skrzynka osoby dzwoniącej bez dostępu do kandydatów musi przejść jawnie.
        assert sales_ok is True
        self.connection = connection

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info) -> None:
        return None

    async def post(self, url: str, json=None, **_kwargs):
        type(self).calls.append((url, json))
        if self.fail_on and url.endswith(self.fail_on):
            if type(self).fail_with is not None:
                raise type(self).fail_with
            raise GraphRequestError(type(self).fail_status, "boom")
        if url == "/me/messages":
            return {"id": "msg-1", "internetMessageId": f"<{_tag()}@example.com>"}
        return {}


@pytest.fixture
def graph(monkeypatch):
    _FakeGraph.calls = []
    _FakeGraph.fail_on = None
    _FakeGraph.fail_status = 500
    _FakeGraph.fail_with = None
    monkeypatch.setattr(client_mail, "GraphClient", _FakeGraph)

    async def no_signature(_gc, _conn, body):
        return body, ()

    monkeypatch.setattr(m365_sender, "_signature_body", no_signature)
    return _FakeGraph


def _body(**overrides: Any) -> dict[str, Any]:
    return {
        "to": [CLIENT],
        "subject": "Potwierdzenie spotkania: 19.11, godz. 10:00",
        "message": "Dzień dobry,\n\ndziękuję za rozmowę. Potwierdzam nasze spotkanie.",
        "request_id": str(uuid.uuid4()),
        **overrides,
    }


async def _send(app_client, user, opportunity_id: int, **overrides: Any):
    return await app_client.post(
        f"{URL}/{opportunity_id}/booking-mail",
        json=_body(**overrides),
        headers=_headers(user),
    )


async def _handoff(app_client):
    caller, host = await _pair()
    booked = await _booked(
        app_client, caller, host, meeting_at=_in(3, hour=10).isoformat()
    )
    return caller, host, booked["opportunity"]["id"]


async def _mails(opportunity_id: int) -> list[SalesActivity]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(SalesActivity).where(
                        SalesActivity.opportunity_id == opportunity_id,
                        SalesActivity.kind == "email",
                    )
                )
            ).all()
        )


@pytest.mark.asyncio
async def test_caller_mails_client_with_host_in_copy(app_client, graph) -> None:
    caller, host, opportunity_id = await _handoff(app_client)
    await _mailbox(caller, scopes=("Mail.Send",))

    form = (await app_client.get(f"{URL}/form", headers=_headers(caller))).json()
    assert form["mailbox"] == "ok"
    assert form["mailbox_address"] == caller.email
    assert {"id": host.id, "name": host.name, "email": host.email} in form["hosts"]

    resp = await _send(app_client, caller, opportunity_id)
    assert resp.status_code == 200, resp.text
    assert resp.json()["to"] == [CLIENT.lower()]
    assert resp.json()["cc"] == [host.email.lower()]

    (draft_url, draft), (send_url, _) = graph.calls
    assert draft_url == "/me/messages"
    assert send_url == "/me/messages/msg-1/send"
    assert draft["subject"] == "Potwierdzenie spotkania: 19.11, godz. 10:00"
    assert [r["emailAddress"]["address"] for r in draft["toRecipients"]] == [
        CLIENT.lower()
    ]
    assert [r["emailAddress"]["address"] for r in draft["ccRecipients"]] == [
        host.email.lower()
    ]
    # Zwykły tekst z okna: wiersze zostają, znaki uciekają.
    assert "Dzień dobry,<br><br>dziękuję" in draft["body"]["content"]

    # Ślad na osi szansy: mail wychodzący z kluczem kopii z Wysłanych.
    [mail] = await _mails(opportunity_id)
    assert mail.direction == "out"
    assert mail.created_by_user_id == caller.id
    assert mail.subject == "Potwierdzenie spotkania: 19.11, godz. 10:00"
    assert mail.external_source == outlook.EMAIL_SOURCE
    assert mail.external_id.endswith("@example.com>")

    steps = [
        (event.field, event.new_value)
        for event in await _events(opportunity_id)
        if event.field == handoff.HISTORY_FIELD
    ]
    assert steps[-1] == (handoff.HISTORY_FIELD, booking_mail.HISTORY_VALUE)
    # W historii nie ma adresów ani tytułu.
    assert "firma-umowiona" not in str(steps)


@pytest.mark.asyncio
async def test_second_click_does_not_send_a_second_mail(app_client, graph) -> None:
    caller, _host, opportunity_id = await _handoff(app_client)
    await _mailbox(caller, scopes=("Mail.Send",))

    first = await _send(app_client, caller, opportunity_id)
    assert first.status_code == 200, first.text
    again = await _send(app_client, caller, opportunity_id)
    assert again.status_code == 409
    assert again.json()["detail"] == booking_mail.SENT_DETAIL
    assert len(graph.calls) == 2  # tylko pierwszy szkic i jego wysyłka


@pytest.mark.asyncio
async def test_only_the_person_who_booked_sends(app_client, graph) -> None:
    _caller, host, opportunity_id = await _handoff(app_client)
    stranger = await _user("sales_edit")
    for user in (host, stranger):
        await _mailbox(user, scopes=("Mail.Send",))
        resp = await _send(app_client, user, opportunity_id)
        assert resp.status_code == 403, resp.text
        assert resp.json()["detail"] == booking_mail.SENDER_DETAIL
    viewer = await _user("sales_view")
    assert (await _send(app_client, viewer, opportunity_id)).status_code == 403
    assert graph.calls == []


@pytest.mark.asyncio
async def test_candidates_and_objections_are_refused_before_graph(
    app_client, graph
) -> None:
    caller, _host, opportunity_id = await _handoff(app_client)
    await _mailbox(caller, scopes=("Mail.Send",))

    candidate = f"kandydat-{_tag()}@example.com"
    await _candidate(candidate)
    resp = await _send(app_client, caller, opportunity_id, to=[candidate])
    assert resp.status_code == 422
    # Odmowa nie wymienia adresu: wpisywanie nie sprawdza, kto jest w bazie.
    assert candidate not in resp.text

    objected = f"sprzeciw-{_tag()}@firma-umowiona.example"
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


@pytest.mark.asyncio
async def test_mailbox_must_be_connected_with_send_consent(app_client, graph) -> None:
    caller, _host, opportunity_id = await _handoff(app_client)
    resp = await _send(app_client, caller, opportunity_id)
    assert resp.status_code == 409
    assert resp.json()["detail"] == booking_mail.NO_MAILBOX_DETAIL

    await _mailbox(caller, scopes=("Calendars.ReadWrite",))
    resp = await _send(app_client, caller, opportunity_id)
    assert resp.status_code == 409
    assert resp.json()["detail"] == booking_mail.NO_SCOPE_DETAIL
    form = (await app_client.get(f"{URL}/form", headers=_headers(caller))).json()
    assert form["mailbox"] == "no_send_scope"
    assert form["mailbox_address"] is None
    assert graph.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        GraphRequestError(403, "denied"),
        # Zapora wyjścia na stagingu i zerwane połączenie: Graph nie widział żądania.
        ConnectionError("staging: połączenie zablokowane"),
    ],
)
async def test_refused_mail_keeps_the_meeting_and_allows_retry(
    app_client, graph, failure
) -> None:
    caller, _host, opportunity_id = await _handoff(app_client)
    await _mailbox(caller, scopes=("Mail.Send",))
    graph.fail_on = "/me/messages"
    graph.fail_with = failure

    resp = await _send(app_client, caller, opportunity_id)
    assert resp.status_code == 502
    assert resp.json()["detail"] == booking_mail.UNDELIVERED_DETAIL
    assert await _mails(opportunity_id) == []
    # Spotkanie zostaje: przekazanie dalej czeka u prowadzącego.
    async with AsyncSessionLocal() as db:
        opportunity = await handoff.lock(db, opportunity_id)
        assert handoff.block(opportunity) is not None
        assert booking_mail.MAIL_KEY not in handoff.block(opportunity)

    graph.fail_on = None
    retry = await _send(app_client, caller, opportunity_id)
    assert retry.status_code == 200, retry.text
    assert len(await _mails(opportunity_id)) == 1


@pytest.mark.asyncio
async def test_unknown_outcome_blocks_retry(app_client, graph) -> None:
    caller, _host, opportunity_id = await _handoff(app_client)
    await _mailbox(caller, scopes=("Mail.Send",))
    graph.fail_on = "/send"  # szkic powstał, wynik wysyłki nieznany

    resp = await _send(app_client, caller, opportunity_id)
    assert resp.status_code == 409
    assert resp.json()["detail"] == booking_mail.UNCERTAIN_DETAIL
    graph.fail_on = None
    again = await _send(app_client, caller, opportunity_id)
    assert again.status_code == 409
    assert again.json()["detail"] == booking_mail.IN_FLIGHT_DETAIL


@pytest.mark.asyncio
async def test_copy_to_host_can_be_left_out(app_client, graph) -> None:
    caller, _host, opportunity_id = await _handoff(app_client)
    await _mailbox(caller, scopes=("Mail.Send",))

    resp = await _send(app_client, caller, opportunity_id, cc_host=False)
    assert resp.status_code == 200, resp.text
    assert resp.json()["cc"] == []
    [(_, draft), _] = graph.calls
    assert "ccRecipients" not in draft


@pytest.mark.asyncio
async def test_bad_address_and_empty_text_are_rejected(app_client, graph) -> None:
    caller, _host, opportunity_id = await _handoff(app_client)
    await _mailbox(caller, scopes=("Mail.Send",))
    assert (
        await _send(app_client, caller, opportunity_id, to=["nie-adres"])
    ).status_code == 422
    assert (
        await _send(app_client, caller, opportunity_id, message="   ")
    ).status_code == 422
    assert (await _send(app_client, caller, opportunity_id, to=[])).status_code == 422
    assert graph.calls == []
