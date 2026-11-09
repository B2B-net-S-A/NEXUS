"""Podsumowanie spotkania dla klienta i wysyłka z NEXUSA (decyzje Artura 09.11.2026).

Wysyła tylko organizator spotkania albo admin, z własnej skrzynki, nigdy do adresu
z bazy kandydatów. Awaria modelu daje puste pole, a nie błąd. Drugi klik z tym
samym kluczem nie wysyła drugiego maila. Mail ląduje na osi szansy, a oś pokazuje
przy spotkaniu podsumowanie transkryptu. Microsoft Graph jest podmieniony.

Baza testowa jest wspólna dla przebiegu: adresy i nazwy niosą losowy tag.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.m365 import M365Connection
from app.models.sales import SalesActivity, SalesMeetingTranscript, SalesOpportunity
from app.services.m365 import sender as m365_sender
from app.services.m365.graph_client import GraphRequestError
from app.services.sales import meeting_client_mail as service
from app.services.sales import outlook_activities as outlook
from tests.test_sales_companies_api import _headers, _user
from tests.test_sales_meeting_decisions import _activity, _firm, _opportunity, _tag
from tests.test_sales_outlook_sync import _candidate

ACTIVITIES = "/api/sales/activities"


def _draft_url(activity_id: int) -> str:
    return f"{ACTIVITIES}/{activity_id}/client-summary"


def _send_url(activity_id: int) -> str:
    return f"{ACTIVITIES}/{activity_id}/client-summary/send"


async def _mailbox(
    user, *, scopes=("Mail.Send", "Mail.ReadWrite"), active=True
) -> None:
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


async def _meeting(
    organizer,
    company_id: int,
    *,
    attendees: list[dict[str, str]],
    opportunity_id: Optional[int] = None,
    summary: Optional[str] = "Ustalono demo.",
    status: str = "fetched",
) -> tuple[int, str]:
    uid = f"ical-{_tag()}"
    activity_id = await _activity(
        company_id,
        subject="Wdrożenie zespołu",
        external_id=uid,
        owner_id=organizer.id,
        opportunity_id=opportunity_id,
    )
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        db.add(
            SalesMeetingTranscript(
                ical_uid=uid,
                organizer_user_id=organizer.id,
                organizer_upn=organizer.email,
                graph_event_id="g1",
                starts_at=now - timedelta(hours=2),
                ends_at=now - timedelta(hours=1),
                status=status,
                plain_text="Handlowiec: Dziękuję. Klient: Prosimy o demo w piątek.",
                summary=summary,
            )
        )
        db.add(
            CalendarEvent(
                title="Spotkanie",
                event_type=EventType.meeting,
                status=EventStatus.scheduled,
                start_time=now - timedelta(hours=2),
                end_time=now - timedelta(hours=1),
                attendees=attendees,
                m365_ical_uid=uid,
                external_source="m365",
                external_id=f"ev-{_tag()}",
                created_by=organizer.id,
            )
        )
        await db.commit()
    return activity_id, uid


async def _transcript(uid: str) -> SalesMeetingTranscript:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(SalesMeetingTranscript).where(SalesMeetingTranscript.ical_uid == uid)
        )


class _FakeGraph:
    """Szkic i wysyłka; ``fail_on`` = ścieżka, na której Graph odpowiada błędem."""

    calls: list[tuple[str, Any]] = []
    fail_on: Optional[str] = None
    fail_status = 500

    def __init__(self, connection, db, *, sales_ok: bool = False) -> None:
        assert sales_ok is True
        self.connection = connection

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info) -> None:
        return None

    async def post(self, url: str, json=None, **_kwargs):
        type(self).calls.append((url, json))
        if self.fail_on and url.endswith(self.fail_on):
            raise GraphRequestError(type(self).fail_status, "boom")
        if url == "/me/messages":
            return {"id": "msg-1", "internetMessageId": f"<{_tag()}@example.com>"}
        return {}


@pytest.fixture
def graph(monkeypatch):
    _FakeGraph.calls = []
    _FakeGraph.fail_on = None
    _FakeGraph.fail_status = 500
    monkeypatch.setattr(service, "GraphClient", _FakeGraph)

    async def no_signature(_gc, _conn, body):
        return body, ()

    monkeypatch.setattr(m365_sender, "_signature_body", no_signature)
    return _FakeGraph


@pytest.fixture
def model(monkeypatch):
    calls: list[str] = []

    def fake(prompt: str) -> str:
        calls.append(prompt)
        return "Dziękujemy za spotkanie.\nUstalenia:\n- demo w piątek"

    monkeypatch.setattr(service, "_call_model", fake)
    monkeypatch.setattr(
        "app.services.llm_providers.api_key_configured", lambda _model: True
    )
    return calls


def _payload(to: list[str], **extra) -> dict:
    return {
        "subject": "Podsumowanie spotkania",
        "body": "Dziękujemy za spotkanie.",
        "to": to,
        "request_id": str(uuid.uuid4()),
        **extra,
    }


@pytest.mark.asyncio
async def test_draft_offers_outside_attendees_and_blocks_candidates(
    app_client, model
) -> None:
    rep = await _user("sales_edit")
    await _mailbox(rep)
    company_id = await _firm()
    client_address = f"klient-{_tag()}@firma-{_tag()}.pl"
    candidate_address = f"kandydat-{_tag()}@firma-{_tag()}.pl"
    await _candidate(candidate_address)
    activity_id, uid = await _meeting(
        rep,
        company_id,
        attendees=[
            {"address": rep.email, "name": "Ja"},
            {"address": client_address, "name": "Klient"},
            {"address": candidate_address, "name": "Kandydat"},
        ],
    )

    resp = await app_client.get(_draft_url(activity_id), headers=_headers(rep))

    assert resp.status_code == 200, resp.text
    draft = resp.json()
    assert draft["subject"] == "Podsumowanie spotkania: Wdrożenie zespołu"
    assert draft["body"].startswith("Dziękujemy za spotkanie.")
    assert draft["model_failed"] is False
    assert draft["mailbox"] == "ok"
    assert [(r["address"], r["blocked"]) for r in draft["recipients"]] == [
        (client_address, None),
        (candidate_address, "candidate"),
    ]
    # Szkic zostaje przy transkrypcie: ponowne otwarcie okna nie woła modelu.
    assert (await _transcript(uid)).client_summary == draft["body"]
    again = await app_client.get(_draft_url(activity_id), headers=_headers(rep))
    assert again.json()["body"] == draft["body"]
    assert len(model) == 1


@pytest.mark.asyncio
async def test_model_failure_leaves_an_empty_draft_not_an_error(
    app_client, monkeypatch
) -> None:
    rep = await _user("sales_edit")
    await _mailbox(rep, scopes=("Mail.ReadWrite",))
    activity_id, uid = await _meeting(rep, await _firm(), attendees=[])

    def broken(_prompt: str) -> str:
        raise RuntimeError("provider down")

    monkeypatch.setattr(service, "_call_model", broken)
    monkeypatch.setattr(
        "app.services.llm_providers.api_key_configured", lambda _model: True
    )
    resp = await app_client.get(_draft_url(activity_id), headers=_headers(rep))

    assert resp.status_code == 200, resp.text
    assert (resp.json()["body"], resp.json()["model_failed"]) == ("", True)
    assert resp.json()["mailbox"] == "no_send_scope"
    assert (await _transcript(uid)).client_summary is None


@pytest.mark.asyncio
async def test_only_organizer_or_admin_with_sales_edit(app_client, model) -> None:
    rep = await _user("sales_edit")
    colleague = await _user("sales_edit")
    viewer = await _user("sales_view")
    admin = await _user(role="admin")
    activity_id, _uid = await _meeting(rep, await _firm(), attendees=[])

    other = await app_client.get(_draft_url(activity_id), headers=_headers(colleague))
    assert other.status_code == 403
    assert "organizator" in other.json()["detail"]
    read_only = await app_client.get(_draft_url(activity_id), headers=_headers(viewer))
    assert read_only.status_code == 403
    blocked_send = await app_client.post(
        _send_url(activity_id),
        json=_payload(["klient@example.pl"]),
        headers=_headers(viewer),
    )
    assert blocked_send.status_code == 403
    assert (
        await app_client.get(_draft_url(activity_id), headers=_headers(admin))
    ).status_code == 200


@pytest.mark.asyncio
async def test_meeting_without_fetched_transcript_is_404(app_client) -> None:
    rep = await _user("sales_edit")
    activity_id, _uid = await _meeting(
        rep, await _firm(), attendees=[], status="missing"
    )
    resp = await app_client.get(_draft_url(activity_id), headers=_headers(rep))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_send_goes_from_own_mailbox_and_lands_on_the_opportunity(
    app_client, graph
) -> None:
    rep = await _user("sales_edit")
    await _mailbox(rep)
    company_id = await _firm()
    opp = await _opportunity(app_client, rep, company_id)
    client_address = f"klient-{_tag()}@firma-{_tag()}.pl"
    activity_id, uid = await _meeting(
        rep, company_id, attendees=[], opportunity_id=opp["id"]
    )

    resp = await app_client.post(
        _send_url(activity_id),
        json=_payload(
            [client_address.upper(), client_address], body="Linia 1\n<b>2</b>"
        ),
        headers=_headers(rep),
    )

    assert resp.status_code == 200, resp.text
    sent = resp.json()
    assert (sent["kind"], sent["direction"]) == ("email", "out")
    assert sent["opportunity"]["id"] == opp["id"]
    draft_call = next(json for url, json in graph.calls if url == "/me/messages")
    assert draft_call["toRecipients"] == [{"emailAddress": {"address": client_address}}]
    assert draft_call["body"]["content"] == "Linia 1<br>&lt;b&gt;2&lt;/b&gt;"
    assert ("/me/messages/msg-1/send", {}) in graph.calls
    transcript = await _transcript(uid)
    assert transcript.client_mail_sent_at is not None
    async with AsyncSessionLocal() as db:
        row = await db.get(SalesActivity, sent["id"])
        assert row.external_source == "msgraph-mail" and row.external_id
        opportunity = await db.get(SalesOpportunity, opp["id"])
        assert opportunity.last_activity_at >= transcript.client_mail_sent_at

    timeline = await app_client.get(
        f"{ACTIVITIES}/timeline",
        params={"opportunity_id": opp["id"]},
        headers=_headers(rep),
    )
    meeting = next(i for i in timeline.json()["items"] if i["kind"] == "meeting")
    assert meeting["transcript_activity_id"] == activity_id
    assert meeting["transcript_summary"] == "Ustalono demo."
    assert meeting["can_send_client_summary"] is True
    assert meeting["client_mail_sent_at"] is not None
    assert any(i["id"] == sent["id"] for i in timeline.json()["items"])


@pytest.mark.asyncio
async def test_company_meeting_goes_to_the_card_it_was_sent_from(
    app_client, graph
) -> None:
    rep = await _user("sales_edit")
    await _mailbox(rep)
    company_id = await _firm()
    opp = await _opportunity(app_client, rep, company_id)
    stranger = await _opportunity(app_client, rep, await _firm())
    activity_id, _uid = await _meeting(rep, company_id, attendees=[])

    other_card = await app_client.post(
        _send_url(activity_id),
        json=_payload(["a@firma.pl"], opportunity_id=stranger["id"]),
        headers=_headers(rep),
    )
    assert other_card.status_code == 200, other_card.text
    assert other_card.json()["opportunity"] is None

    own_card = await app_client.post(
        _send_url(activity_id),
        json=_payload(["a@firma.pl"], opportunity_id=opp["id"]),
        headers=_headers(rep),
    )
    assert own_card.json()["opportunity"]["id"] == opp["id"]


@pytest.mark.asyncio
async def test_candidate_address_is_refused_even_for_admin(app_client, graph) -> None:
    admin = await _user(role="admin")
    await _mailbox(admin)
    address = f"kandydat-{_tag()}@example.pl"
    await _candidate(address)
    activity_id, uid = await _meeting(admin, await _firm(), attendees=[])

    resp = await app_client.post(
        _send_url(activity_id),
        json=_payload([f" {address.upper()} "]),
        headers=_headers(admin),
    )

    assert resp.status_code == 422
    # Odmowa nie wymienia adresu: wpisywanie nie sprawdza, kto jest w bazie.
    assert address not in resp.json()["detail"]
    assert "kandydatów" in resp.json()["detail"]
    assert graph.calls == []
    assert (await _transcript(uid)).client_mail_request_id is None


@pytest.mark.asyncio
async def test_candidate_check_runs_only_for_the_organizer(app_client, graph) -> None:
    rep = await _user("sales_edit")
    colleague = await _user("sales_edit")
    await _mailbox(colleague)
    address = f"kandydat-{_tag()}@example.pl"
    await _candidate(address)
    activity_id, _uid = await _meeting(rep, await _firm(), attendees=[])

    foreign = await app_client.post(
        _send_url(activity_id), json=_payload([address]), headers=_headers(colleague)
    )
    missing = await app_client.post(
        _send_url(999_999_999), json=_payload([address]), headers=_headers(colleague)
    )

    assert foreign.status_code == 403
    assert missing.status_code == 404
    assert address not in foreign.text + missing.text
    assert graph.calls == []


@pytest.mark.asyncio
async def test_sync_copy_from_sent_items_keeps_the_full_body(app_client, graph) -> None:
    rep = await _user("sales_edit")
    await _mailbox(rep)
    domain = f"{_tag()}.example.pl"
    company_id = await _firm(domain=domain)
    opp = await _opportunity(app_client, rep, company_id)
    activity_id, _uid = await _meeting(
        rep, company_id, attendees=[], opportunity_id=opp["id"]
    )
    body = "Dziękujemy za spotkanie.\nUstalenia:\n- demo w piątek\n" + "x" * 400
    sent = await app_client.post(
        _send_url(activity_id),
        json=_payload([f"klient@{domain}"], body=body),
        headers=_headers(rep),
    )
    assert sent.status_code == 200, sent.text
    async with AsyncSessionLocal() as db:
        internet_id = (await db.get(SalesActivity, sent.json()["id"])).external_id

    async with AsyncSessionLocal() as db:
        await outlook.record(
            db,
            outlook.OutlookItem(
                source=outlook.EMAIL_SOURCE,
                external_id=internet_id,
                owner_user_id=rep.id,
                owner_address=rep.email,
                addresses=[rep.email, f"klient@{domain}"],
                subject="Podsumowanie spotkania",
                preview="Dziękujemy za spotkanie. Ustalenia: - demo",
                occurred_at=datetime.now(timezone.utc),
                direction="out",
            ),
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        rows = (
            await db.scalars(
                select(SalesActivity).where(SalesActivity.external_id == internet_id)
            )
        ).all()
    assert len(rows) == 1
    assert rows[0].body == body
    assert rows[0].opportunity_id == opp["id"]


@pytest.mark.asyncio
async def test_bad_address_missing_mailbox_and_missing_scope(app_client, graph) -> None:
    rep = await _user("sales_edit")
    activity_id, _uid = await _meeting(rep, await _firm(), attendees=[])

    bad = await app_client.post(
        _send_url(activity_id), json=_payload(["nie-adres"]), headers=_headers(rep)
    )
    assert bad.status_code == 422
    no_box = await app_client.post(
        _send_url(activity_id), json=_payload(["a@firma.pl"]), headers=_headers(rep)
    )
    assert no_box.status_code == 409
    assert "Podłącz skrzynkę" in no_box.json()["detail"]

    rep_without_send = await _user("sales_edit")
    await _mailbox(rep_without_send, scopes=("Mail.ReadWrite",))
    own_id, _ = await _meeting(rep_without_send, await _firm(), attendees=[])
    no_scope = await app_client.post(
        _send_url(own_id),
        json=_payload(["a@firma.pl"]),
        headers=_headers(rep_without_send),
    )
    assert no_scope.status_code == 409
    assert "ponownie" in no_scope.json()["detail"]
    assert graph.calls == []


@pytest.mark.asyncio
async def test_second_click_with_the_same_key_does_not_send_twice(
    app_client, graph
) -> None:
    rep = await _user("sales_edit")
    await _mailbox(rep)
    activity_id, _uid = await _meeting(rep, await _firm(), attendees=[])
    payload = _payload(["a@firma.pl"])

    first = await app_client.post(
        _send_url(activity_id), json=payload, headers=_headers(rep)
    )
    second = await app_client.post(
        _send_url(activity_id), json=payload, headers=_headers(rep)
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 409
    assert sum(1 for url, _ in graph.calls if url.endswith("/send")) == 1
    # Nowe okno (nowy klucz) może wysłać ponownie, np. do innej osoby.
    again = await app_client.post(
        _send_url(activity_id), json=_payload(["b@firma.pl"]), headers=_headers(rep)
    )
    assert again.status_code == 200


@pytest.mark.asyncio
async def test_refused_send_frees_the_key_and_unknown_outcome_keeps_it(
    app_client, graph
) -> None:
    rep = await _user("sales_edit")
    await _mailbox(rep)
    activity_id, uid = await _meeting(rep, await _firm(), attendees=[])
    payload = _payload(["a@firma.pl"])

    graph.fail_on, graph.fail_status = "/send", 400
    refused = await app_client.post(
        _send_url(activity_id), json=payload, headers=_headers(rep)
    )
    assert refused.status_code == 502
    assert (await _transcript(uid)).client_mail_request_id is None

    graph.fail_status = 503
    unknown = await app_client.post(
        _send_url(activity_id), json=payload, headers=_headers(rep)
    )
    assert unknown.status_code == 409
    assert "Wysłane" in unknown.json()["detail"]
    row = await _transcript(uid)
    assert row.client_mail_request_id == payload["request_id"]
    assert row.client_mail_sent_at is None
    async with AsyncSessionLocal() as db:
        recorded = await db.scalar(
            select(SalesActivity.id).where(
                SalesActivity.kind == "email",
                SalesActivity.company_id
                == (await db.get(SalesActivity, activity_id)).company_id,
            )
        )
    assert recorded is None


@pytest.mark.asyncio
async def test_timeline_hides_send_from_a_colleague(app_client) -> None:
    rep = await _user("sales_edit")
    colleague = await _user("sales_edit")
    company_id = await _firm()
    opp = await _opportunity(app_client, rep, company_id)
    await _meeting(rep, company_id, attendees=[], opportunity_id=opp["id"])

    resp = await app_client.get(
        f"{ACTIVITIES}/timeline",
        params={"opportunity_id": opp["id"]},
        headers=_headers(colleague),
    )

    meeting = next(i for i in resp.json()["items"] if i["kind"] == "meeting")
    assert meeting["transcript_summary"] == "Ustalono demo."
    assert meeting["can_send_client_summary"] is False


def test_text_to_html_escapes_and_keeps_lines() -> None:
    assert (
        service.text_to_html(" a & b\n<i>c</i>\n")
        == "a &amp; b<br>&lt;i&gt;c&lt;/i&gt;"
    )


def test_normalize_address() -> None:
    assert service.normalize_address(" Ala@Firma.PL ") == "ala@firma.pl"
    for wrong in ("", "ala", "ala@firma", "a b@firma.pl", "a@b.pl, c@d.pl"):
        assert service.normalize_address(wrong) is None


def test_mailbox_state() -> None:
    def conn(scopes, active=True):
        return M365Connection(scopes_granted=scopes, is_active=active)

    assert service.mailbox_state(None) == "missing"
    assert service.mailbox_state(conn(["Mail.Send"], active=False)) == "missing"
    assert service.mailbox_state(conn(["Mail.ReadWrite"])) == "no_send_scope"
    assert (
        service.mailbox_state(conn(["https://graph.microsoft.com/Mail.Send"])) == "ok"
    )
