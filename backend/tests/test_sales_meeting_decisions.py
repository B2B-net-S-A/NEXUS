"""Sprzedaż → Spotkania: decyzja przy wierszu (przypnij, załóż szansę, klient NEXUSA).

Przypięcie dotyczy tylko aktywności z Outlooka, tylko otwartej szansy tej samej
firmy i da się je cofnąć. Synchronizacja (``record``, ``forget``) nie może go
zepsuć. Firma, która jest klientem NEXUSA, nie dostaje nowej szansy: idzie do
swojego Delivery Leada (decyzja z 22.10.2026).

Baza testowa jest wspólna dla przebiegu: tematy i nazwy niosą losowy tag.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Optional

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import DEFAULT_TZ, business_today
from app.models.calendar_event import CalendarEvent
from app.models.client import Client
from app.models.client_directory import ClientAlias
from app.models.sales import (
    SalesActivity,
    SalesCompany,
    SalesCompanyContact,
    SalesContact,
    SalesMeetingTranscript,
    SalesOpportunity,
    SalesOpportunityContact,
    SalesOpportunityEvent,
)
from app.models.team_structure import DeliveryLeadClientAssignment
from app.services.company_names import normalize_company_name
from app.services.m365 import sync as sync_mod
from app.services.m365.access import MailboxScope
from app.services.sales import outlook_activities as outlook
from app.services.sales.meeting_decisions import clean_meeting_title
from tests.test_sales_companies_api import _headers, _user
from tests.test_sales_opportunities_api import _stages

ACTIVITIES = "/api/sales/activities"
MEETINGS = f"{ACTIVITIES}/meetings"
OPPS = "/api/sales/opportunities"
EVENT = outlook.EVENT_SOURCE
MAIL = outlook.EMAIL_SOURCE


def _tag() -> str:
    return uuid.uuid4().hex[:10]


def _ago(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


async def _firm(
    name: Optional[str] = None,
    *,
    domain: Optional[str] = None,
    client_id: Optional[int] = None,
) -> int:
    label = name or f"Firma Spotkań {_tag()}"
    async with AsyncSessionLocal() as db:
        company = SalesCompany(
            name=label,
            normalized_name=normalize_company_name(label) or label.lower(),
            domain=domain,
            client_id=client_id,
        )
        db.add(company)
        await db.commit()
        return company.id


async def _opportunity(app_client, rep, company_id: int, title: str = "Szansa") -> dict:
    resp = await app_client.post(
        OPPS, json={"company_id": company_id, "title": title}, headers=_headers(rep)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _set_last_activity(opportunity_id: int, when: datetime) -> None:
    async with AsyncSessionLocal() as db:
        opp = await db.get(SalesOpportunity, opportunity_id)
        opp.last_activity_at = when
        await db.commit()


async def _activity(
    company_id: Optional[int],
    *,
    subject: str = "Spotkanie",
    source: Optional[str] = EVENT,
    kind: str = "meeting",
    when: Optional[datetime] = None,
    external_id: Optional[str] = None,
    owner_id: Optional[int] = None,
    contact_id: Optional[int] = None,
    opportunity_id: Optional[int] = None,
    done: bool = True,
) -> int:
    moment = when or _ago(3)
    async with AsyncSessionLocal() as db:
        activity = SalesActivity(
            company_id=company_id,
            contact_id=contact_id,
            opportunity_id=opportunity_id,
            kind=kind,
            subject=subject,
            body="Podgląd treści",
            occurred_at=moment,
            done_at=moment if done else None,
            created_by_user_id=owner_id,
            external_source=source,
            external_id=external_id or (f"ext-{_tag()}" if source else None),
            web_link="https://outlook.office365.com/calendar/item/x"
            if source
            else None,
        )
        db.add(activity)
        await db.commit()
        return activity.id


async def _row(activity_id: int) -> Optional[SalesActivity]:
    async with AsyncSessionLocal() as db:
        return await db.get(SalesActivity, activity_id)


async def _opp_row(opportunity_id: int) -> SalesOpportunity:
    async with AsyncSessionLocal() as db:
        return await db.get(SalesOpportunity, opportunity_id)


async def _events(opportunity_id: int) -> list[SalesOpportunityEvent]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(SalesOpportunityEvent)
                    .where(SalesOpportunityEvent.opportunity_id == opportunity_id)
                    .order_by(SalesOpportunityEvent.id)
                )
            ).all()
        )


async def _pin(app_client, user, activity_id: int, opportunity_id: int):
    return await app_client.post(
        f"{ACTIVITIES}/{activity_id}/pin",
        json={"opportunity_id": opportunity_id},
        headers=_headers(user),
    )


async def _client(
    name: Optional[str] = None,
    *,
    lead_ids: tuple[int, ...] = (),
    alias: Optional[str] = None,
    head: bool = True,
) -> tuple[int, str]:
    label = name or f"Klient Nexusa {_tag()}"
    async with AsyncSessionLocal() as db:
        client = Client(name=label)
        db.add(client)
        await db.flush()
        if alias:
            db.add(
                ClientAlias(
                    client_id=client.id,
                    alias=alias,
                    normalized_alias=normalize_company_name(alias),
                    source_system="test",
                )
            )
        for lead_id in lead_ids:
            db.add(
                DeliveryLeadClientAssignment(
                    delivery_lead_user_id=lead_id, client_id=client.id, is_head=head
                )
            )
        await db.commit()
        return client.id, label


async def _history(app_client, user, opportunity_id: int) -> list[dict]:
    resp = await app_client.get(
        f"{OPPS}/{opportunity_id}/history", headers=_headers(user)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _set_held(activity_id: int, when: datetime) -> None:
    """Czas minął, a synchronizacja o tym spotkaniu nie wie (delta go nie odda)."""

    async with AsyncSessionLocal() as db:
        row = await db.get(SalesActivity, activity_id)
        row.occurred_at = when
        await db.commit()


async def _own_firm() -> tuple[int, int]:
    """Nasza spółka: karta sprzedaży i widoczny klient o tej samej nazwie."""

    name = "B2B.net S.A."
    async with AsyncSessionLocal() as db:
        client = Client(name=name)
        db.add(client)
        await db.commit()
        client_id = client.id
    return await _firm(name), client_id


async def _list(app_client, user, **params: Any) -> dict:
    resp = await app_client.get(MEETINGS, params=params, headers=_headers(user))
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── Przypięcie ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pin_links_meeting_touches_opportunity_and_undo_restores_it(
    app_client,
) -> None:
    rep = await _user("sales_edit")
    company_id = await _firm()
    opp = await _opportunity(app_client, rep, company_id, "Migracja")
    earlier = _ago(40)
    await _set_last_activity(opp["id"], earlier)
    held = _ago(5)
    activity_id = await _activity(company_id, subject="Warsztat", when=held)

    pinned = await _pin(app_client, rep, activity_id, opp["id"])
    assert pinned.status_code == 200, pinned.text
    assert pinned.json()["opportunity"]["id"] == opp["id"]
    assert (await _row(activity_id)).opportunity_id == opp["id"]
    touched = await _opp_row(opp["id"])
    assert touched.last_activity_at == held

    fields = [(e.field, e.old_value, e.new_value) for e in await _events(opp["id"])]
    assert ("outlook_activity", None, str(activity_id)) in fields
    shown = await _history(app_client, rep, opp["id"])
    assert any(
        e["field"] == "outlook_activity" and e["new_label"] == "Warsztat" for e in shown
    )

    again = await _pin(app_client, rep, activity_id, opp["id"])
    assert again.status_code == 200
    assert len(await _events(opp["id"])) == len(fields)

    undone = await app_client.delete(
        f"{ACTIVITIES}/{activity_id}/pin", headers=_headers(rep)
    )
    assert undone.status_code == 200, undone.text
    assert undone.json()["opportunity"] is None
    assert (await _row(activity_id)).opportunity_id is None
    assert (await _opp_row(opp["id"])).last_activity_at == earlier
    after = [(e.field, e.old_value, e.new_value) for e in await _events(opp["id"])]
    assert ("outlook_activity", str(activity_id), None) in after


@pytest.mark.asyncio
async def test_undo_keeps_a_fresher_trace_of_work(app_client) -> None:
    rep = await _user("sales_edit")
    company_id = await _firm()
    opp = await _opportunity(app_client, rep, company_id)
    await _set_last_activity(opp["id"], _ago(60))
    older = await _activity(company_id, when=_ago(20))
    newer = await _activity(company_id, when=_ago(2))
    assert (await _pin(app_client, rep, older, opp["id"])).status_code == 200
    assert (await _pin(app_client, rep, newer, opp["id"])).status_code == 200

    # Cofnięcie starszego niczego nie zmienia: ostatni ślad to nowsze spotkanie.
    newer_at = (await _opp_row(opp["id"])).last_activity_at
    await app_client.delete(f"{ACTIVITIES}/{older}/pin", headers=_headers(rep))
    assert (await _opp_row(opp["id"])).last_activity_at == newer_at

    # Odwrotna kolejność: po nowszym zostaje data sprzed przypięć.
    assert (await _pin(app_client, rep, older, opp["id"])).status_code == 200
    await app_client.delete(f"{ACTIVITIES}/{newer}/pin", headers=_headers(rep))
    assert (await _opp_row(opp["id"])).last_activity_at == (await _row(older)).done_at


@pytest.mark.asyncio
async def test_pin_never_moves_last_activity_back_and_mail_can_be_pinned(
    app_client,
) -> None:
    rep = await _user("sales_edit")
    company_id = await _firm()
    opp = await _opportunity(app_client, rep, company_id)
    fresh = _ago(1)
    await _set_last_activity(opp["id"], fresh)
    mail_id = await _activity(company_id, source=MAIL, kind="email", when=_ago(30))

    assert (await _pin(app_client, rep, mail_id, opp["id"])).status_code == 200
    assert (await _opp_row(opp["id"])).last_activity_at == fresh


@pytest.mark.asyncio
async def test_future_meeting_is_pinned_without_claiming_work_already_done(
    app_client,
) -> None:
    rep = await _user("sales_edit")
    company_id = await _firm()
    opp = await _opportunity(app_client, rep, company_id)
    before = (await _opp_row(opp["id"])).last_activity_at
    upcoming = await _activity(company_id, when=_ago(-3), done=False)

    assert (await _pin(app_client, rep, upcoming, opp["id"])).status_code == 200
    assert (await _row(upcoming)).opportunity_id == opp["id"]
    assert (await _opp_row(opp["id"])).last_activity_at == before


@pytest.mark.asyncio
async def test_pin_refusals(app_client) -> None:
    rep = await _user("sales_edit")
    viewer = await _user("sales_view")
    outsider = await _user()
    company_id = await _firm()
    other_company = await _firm()
    opp = await _opportunity(app_client, rep, company_id)
    foreign = await _opportunity(app_client, rep, other_company)
    stages = await _stages(app_client, rep)
    closed = await _opportunity(app_client, rep, company_id, "Przegrana")
    moved = await app_client.post(
        f"{OPPS}/{closed['id']}/move",
        json={"stage_id": stages["lost"], "lost_reason": "Cena"},
        headers=_headers(rep),
    )
    assert moved.status_code == 200, moved.text
    archived = await _opportunity(app_client, rep, company_id, "W archiwum")
    async with AsyncSessionLocal() as db:
        row = await db.get(SalesOpportunity, archived["id"])
        row.archived_at = datetime.now(timezone.utc)
        await db.commit()
    activity_id = await _activity(company_id)
    manual_id = await _activity(company_id, source=None)

    assert (await _pin(app_client, viewer, activity_id, opp["id"])).status_code == 403
    assert (await _pin(app_client, outsider, activity_id, opp["id"])).status_code == 403
    assert (await _pin(app_client, rep, 999_999_999, opp["id"])).status_code == 404
    assert (await _pin(app_client, rep, activity_id, 999_999_999)).status_code == 422
    assert (await _pin(app_client, rep, activity_id, foreign["id"])).status_code == 422
    assert (await _pin(app_client, rep, activity_id, archived["id"])).status_code == 422
    assert (await _pin(app_client, rep, activity_id, closed["id"])).status_code == 409
    assert (await _pin(app_client, rep, manual_id, opp["id"])).status_code == 422
    assert (await _row(activity_id)).opportunity_id is None

    second = await _opportunity(app_client, rep, company_id, "Druga")
    assert (await _pin(app_client, rep, activity_id, opp["id"])).status_code == 200
    taken = await _pin(app_client, rep, activity_id, second["id"])
    assert taken.status_code == 409
    assert (await _row(activity_id)).opportunity_id == opp["id"]

    forbidden = await app_client.delete(
        f"{ACTIVITIES}/{activity_id}/pin", headers=_headers(viewer)
    )
    assert forbidden.status_code == 403
    assert (await _row(activity_id)).opportunity_id == opp["id"]


# ── Synchronizacja a przypięcie ──────────────────────────────────────────


def _item(external_id: str, domain: str, owner_id: int, **fields: Any):
    defaults: dict[str, Any] = {
        "source": EVENT,
        "external_id": external_id,
        "owner_user_id": owner_id,
        "owner_address": "handlowiec@b2bnet.example",
        "addresses": [f"osoba@{domain}"],
        "subject": "Nowy temat z Outlooka",
        "preview": "Nowy podgląd",
        "occurred_at": _ago(1),
    }
    return outlook.OutlookItem(**{**defaults, **fields})


@pytest.mark.asyncio
async def test_resync_refreshes_meeting_but_keeps_the_pin(app_client) -> None:
    rep = await _user("sales_edit")
    domain = f"{_tag()}.example.pl"
    company_id = await _firm(domain=domain)
    opp = await _opportunity(app_client, rep, company_id)
    external_id = f"ical-{_tag()}"
    activity_id = await _activity(company_id, external_id=external_id)
    assert (await _pin(app_client, rep, activity_id, opp["id"])).status_code == 200

    async with AsyncSessionLocal() as db:
        assert await outlook.record(db, _item(external_id, domain, rep.id)) == 1
        await db.commit()

    row = await _row(activity_id)
    assert row.subject == "Nowy temat z Outlooka"
    assert row.opportunity_id == opp["id"]


@pytest.mark.asyncio
async def test_private_mark_scrubs_pinned_row_and_keeps_the_pin(app_client) -> None:
    rep = await _user("sales_edit")
    domain = f"{_tag()}.example.pl"
    company_id = await _firm(domain=domain)
    opp = await _opportunity(app_client, rep, company_id)
    external_id = f"ical-{_tag()}"
    pinned_id = await _activity(company_id, external_id=external_id, subject="Poufne")
    other_company = await _firm()
    unpinned_id = await _activity(other_company, external_id=external_id)
    assert (await _pin(app_client, rep, pinned_id, opp["id"])).status_code == 200
    touched = (await _opp_row(opp["id"])).last_activity_at
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        db.add(
            SalesMeetingTranscript(
                ical_uid=external_id,
                organizer_upn="handlowiec@example.com",
                graph_event_id="g1",
                starts_at=now,
                ends_at=now,
                status="fetched",
                plain_text="Poufna rozmowa",
            )
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        await outlook.forget(db, EVENT, external_id, upcoming_only=False)
        await db.commit()

    row = await _row(pinned_id)
    assert row is not None and row.opportunity_id == opp["id"]
    assert "Poufne" not in (row.subject or "")
    assert (row.body, row.web_link) == (None, None)
    assert await _row(unpinned_id) is None
    assert (await _opp_row(opp["id"])).last_activity_at == touched
    async with AsyncSessionLocal() as db:
        transcript = await db.scalar(
            select(SalesMeetingTranscript).where(
                SalesMeetingTranscript.ical_uid == external_id
            )
        )
    assert transcript is None

    # Historia szansy nie trzyma tematu: prywatne nie wraca tą drogą.
    stored = await _events(opp["id"])
    assert not any("Poufne" in (e.new_value or "") for e in stored)
    assert not any("Poufne" in (e.old_value or "") for e in stored)
    shown = await _history(app_client, rep, opp["id"])
    assert "Poufne" not in str(shown)
    pinned_event = next(e for e in shown if e["field"] == "outlook_activity")
    assert pinned_event["new_label"] == outlook.PRIVATE_SUBJECTS[EVENT]

    # Zdjęcie znacznika w Outlooku wraca przez ``record`` do tego samego wiersza.
    async with AsyncSessionLocal() as db:
        await outlook.record(db, _item(external_id, domain, rep.id))
        await db.commit()
    back = await _row(pinned_id)
    assert (back.subject, back.opportunity_id) == ("Nowy temat z Outlooka", opp["id"])


@pytest.mark.asyncio
async def test_undo_scrubs_the_subject_from_history_too(app_client) -> None:
    rep = await _user("sales_edit")
    company_id = await _firm()
    opp = await _opportunity(app_client, rep, company_id)
    external_id = f"ical-{_tag()}"
    activity_id = await _activity(company_id, external_id=external_id, subject="Poufne")
    assert (await _pin(app_client, rep, activity_id, opp["id"])).status_code == 200
    await app_client.delete(f"{ACTIVITIES}/{activity_id}/pin", headers=_headers(rep))

    # Już nieprzypięte: ``forget`` kasuje wiersz, historia zostaje bez tematu.
    async with AsyncSessionLocal() as db:
        await outlook.forget(db, EVENT, external_id, upcoming_only=False)
        await db.commit()

    assert await _row(activity_id) is None
    shown = await _history(app_client, rep, opp["id"])
    assert "Poufne" not in str(shown)
    assert [
        (e["old_label"], e["new_label"])
        for e in shown
        if e["field"] == "outlook_activity"
    ] == [(None, None), (None, None)]


@pytest.mark.asyncio
async def test_meeting_without_subject_has_a_label_in_history(app_client) -> None:
    rep = await _user("sales_edit")
    company_id = await _firm()
    opp = await _opportunity(app_client, rep, company_id)
    activity_id = await _activity(company_id, subject="")
    async with AsyncSessionLocal() as db:
        row = await db.get(SalesActivity, activity_id)
        row.subject = None
        await db.commit()
    assert (await _pin(app_client, rep, activity_id, opp["id"])).status_code == 200

    shown = await _history(app_client, rep, opp["id"])
    event = next(e for e in shown if e["field"] == "outlook_activity")
    assert (event["new_value"], event["new_label"]) == (str(activity_id), "bez tematu")


# ── Spotkanie, które się odbyło po przypięciu ────────────────────────────


async def _pinned_future(app_client, rep, *, domain: Optional[str] = None):
    company_id = await _firm(domain=domain)
    opp = await _opportunity(app_client, rep, company_id)
    earlier = _ago(40)
    await _set_last_activity(opp["id"], earlier)
    external_id = f"ical-{_tag()}"
    activity_id = await _activity(
        company_id, external_id=external_id, when=_ago(-3), done=False
    )
    assert (await _pin(app_client, rep, activity_id, opp["id"])).status_code == 200
    assert (await _opp_row(opp["id"])).last_activity_at == earlier
    return opp, activity_id, external_id, earlier


async def _settle() -> int:
    async with AsyncSessionLocal() as db:
        settled = await outlook.settle_pinned_meetings(db)
        await db.commit()
    return settled


@pytest.mark.asyncio
async def test_resync_after_the_meeting_moves_the_opportunity(app_client) -> None:
    rep = await _user("sales_edit")
    domain = f"{_tag()}.example.pl"
    opp, activity_id, external_id, _ = await _pinned_future(
        app_client, rep, domain=domain
    )
    held = _ago(1)

    async with AsyncSessionLocal() as db:
        await outlook.record(db, _item(external_id, domain, rep.id, occurred_at=held))
        await db.commit()

    assert (await _row(activity_id)).done_at == held
    assert (await _opp_row(opp["id"])).last_activity_at == held
    changes = [e for e in await _events(opp["id"]) if e.field == "last_activity_at"]
    assert len(changes) == 1 and changes[0].user_id is None

    # Kolejna synchronizacja tego samego nie dopisuje historii po raz drugi.
    async with AsyncSessionLocal() as db:
        await outlook.record(db, _item(external_id, domain, rep.id, occurred_at=held))
        await db.commit()
    again = [e for e in await _events(opp["id"]) if e.field == "last_activity_at"]
    assert len(again) == 1


@pytest.mark.asyncio
async def test_meeting_that_simply_passed_moves_the_opportunity(app_client) -> None:
    rep = await _user("sales_edit")
    opp, activity_id, _, earlier = await _pinned_future(app_client, rep)
    held = _ago(1)
    await _set_held(activity_id, held)

    assert await _settle() >= 1
    assert (await _row(activity_id)).done_at == held
    assert (await _opp_row(opp["id"])).last_activity_at == held

    await _settle()
    changes = [e for e in await _events(opp["id"]) if e.field == "last_activity_at"]
    assert len(changes) == 1

    # Cofnięcie przypięcia po odbyciu oddaje datę sprzed spotkania.
    await app_client.delete(f"{ACTIVITIES}/{activity_id}/pin", headers=_headers(rep))
    assert (await _opp_row(opp["id"])).last_activity_at == earlier


@pytest.mark.parametrize(
    ("sales", "expected_done"),
    [(True, True), (False, False)],
    ids=["skrzynka-sprzedazy", "skrzynka-bez-sprzedazy"],
)
@pytest.mark.asyncio
async def test_mailbox_sync_settles_what_the_delta_will_not_return(
    app_client, monkeypatch, sales: bool, expected_done: bool
) -> None:
    rep = await _user("sales_edit")
    _, activity_id, _, _ = await _pinned_future(app_client, rep)
    await _set_held(activity_id, _ago(1))

    class _Graph:
        def __init__(self, *args: Any, **kwargs: Any) -> None: ...

        async def __aenter__(self) -> "_Graph":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

    async def _nothing(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(sync_mod, "GraphClient", _Graph)
    monkeypatch.setattr(sync_mod, "_sync_messages", _nothing)
    monkeypatch.setattr(sync_mod, "_sync_events", _nothing)
    monkeypatch.setattr(sync_mod, "_sales_catch_up", _nothing)
    monkeypatch.setattr(sync_mod.sales_transcripts, "resolve_join_urls", _nothing)
    conn = SimpleNamespace(
        id=20_000_000 + rep.id,
        user_id=rep.id,
        mailbox_upn=rep.email,
        last_sync_status=None,
        last_error=None,
        last_sync_at=None,
    )
    scope = MailboxScope(candidates=not sales, sales=sales)

    async with AsyncSessionLocal() as db:
        result = await sync_mod._sync_connection_locked(
            db, conn, sync_mod.SyncResult(connection_id=conn.id), scope=scope
        )

    assert result.errors == 0
    assert ((await _row(activity_id)).done_at is not None) is expected_done


@pytest.mark.asyncio
async def test_settling_leaves_the_rest_alone(app_client) -> None:
    rep = await _user("sales_edit")
    opp, future_id, _, earlier = await _pinned_future(app_client, rep)
    company_id = await _firm()
    bare = await _activity(company_id, when=_ago(2), done=False)
    second = await _opportunity(app_client, rep, company_id)
    fresher = _ago(1)
    await _set_last_activity(second["id"], fresher)
    pinned_older = await _activity(company_id, when=_ago(-2), done=False)
    assert (await _pin(app_client, rep, pinned_older, second["id"])).status_code == 200
    older = _ago(10)
    await _set_held(pinned_older, older)

    await _settle()

    assert (await _row(future_id)).done_at is None
    assert (await _opp_row(opp["id"])).last_activity_at == earlier
    assert (await _row(bare)).done_at is None
    # Spotkanie starsze niż ostatnia aktywność nie cofa daty.
    assert (await _row(pinned_older)).done_at == older
    assert (await _opp_row(second["id"])).last_activity_at == fresher


@pytest.mark.asyncio
async def test_cancelled_meeting_goes_and_leaves_the_opportunity_alone(
    app_client,
) -> None:
    rep = await _user("sales_edit")
    company_id = await _firm()
    opp = await _opportunity(app_client, rep, company_id)
    stamp = _ago(10)
    await _set_last_activity(opp["id"], stamp)
    upcoming_uid = f"ical-{_tag()}"
    past_uid = f"ical-{_tag()}"
    upcoming = await _activity(
        company_id, external_id=upcoming_uid, when=_ago(-2), done=False
    )
    past = await _activity(company_id, external_id=past_uid, when=_ago(4))
    for activity_id in (upcoming, past):
        assert (await _pin(app_client, rep, activity_id, opp["id"])).status_code == 200
    expected = (await _opp_row(opp["id"])).last_activity_at

    async with AsyncSessionLocal() as db:
        await outlook.forget(db, EVENT, upcoming_uid, upcoming_only=True)
        await outlook.forget(db, EVENT, past_uid, upcoming_only=True)
        await db.commit()

    assert await _row(upcoming) is None
    assert (await _row(past)).opportunity_id == opp["id"]
    survivor = await _opp_row(opp["id"])
    assert (survivor.status, survivor.last_activity_at) == ("open", expected)


# ── Szansa ze spotkania ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("subject", "expected"),
    [
        ("[ELEVATE] Firma Testowa S.A. x B2Bnetwork", "Firma Testowa S.A."),
        ("[onsite] [ELEVATE] Firma x B2B Network", "Firma"),
        ("Firma Testowa × b2bnetwork", "Firma Testowa"),
        ("Spotkanie: Firma --> B2BNETWORK", "Spotkanie: Firma"),
        ("Firma vs B2BNetwork", "Firma"),
        ("B2Bnetwork x Firma Testowa", "Firma Testowa"),
        ("Grupa B2Bnet SA x Firma_warsztat", "Firma_warsztat"),
        ("Grupa B2Bnet SA [Cloud] x Firma", "Firma"),
        ("Synchro w temacie umowy", "Synchro w temacie umowy"),
        ("Firma xB2Bnetwork plan", "Firma xB2Bnetwork plan"),
        ("[ELEVATE]", ""),
        (None, ""),
    ],
)
def test_clean_meeting_title(subject: Optional[str], expected: str) -> None:
    assert clean_meeting_title(subject) == expected


async def _create_from(app_client, user, activity_id: int, **payload: Any):
    body = {"title": "Nowa szansa", "service_line": "bodyleasing", **payload}
    return await app_client.post(
        f"{OPPS}/from-activity/{activity_id}", json=body, headers=_headers(user)
    )


@pytest.mark.asyncio
async def test_create_from_meeting_pins_it_and_writes_history(app_client) -> None:
    rep = await _user("sales_edit")
    company_id = await _firm()
    async with AsyncSessionLocal() as db:
        contact = SalesContact(full_name="Osoba Testowa", company_id=company_id)
        db.add(contact)
        await db.commit()
        contact_id = contact.id
    held = _ago(2)
    activity_id = await _activity(company_id, when=held, contact_id=contact_id)

    created = await _create_from(
        app_client,
        rep,
        activity_id,
        title="  Szansa ze spotkania  ",
        service_line="subscription",
        contact_ids=[contact_id],
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert (body["title"], body["service_line"], body["owner"]["id"]) == (
        "Szansa ze spotkania",
        "subscription",
        rep.id,
    )
    assert body["company"]["id"] == company_id
    assert (await _row(activity_id)).opportunity_id == body["id"]

    row = await _opp_row(body["id"])
    assert (row.last_activity_at, row.primary_contact_id, row.status) == (
        held,
        contact_id,
        "open",
    )
    async with AsyncSessionLocal() as db:
        linked = await db.scalar(
            select(SalesOpportunityContact.contact_id).where(
                SalesOpportunityContact.opportunity_id == body["id"]
            )
        )
    assert linked == contact_id
    kinds = [(e.kind, e.field) for e in await _events(body["id"])]
    assert ("created", "stage_id") in kinds
    assert ("updated", "outlook_activity") in kinds

    twice = await _create_from(app_client, rep, activity_id)
    assert twice.status_code == 409


@pytest.mark.asyncio
async def test_create_from_meeting_refusals(app_client) -> None:
    rep = await _user("sales_edit")
    viewer = await _user("sales_view")
    company_id = await _firm()
    other = await _firm()
    meeting = await _activity(company_id)
    mail = await _activity(company_id, source=MAIL, kind="email")
    manual = await _activity(company_id, source=None)
    async with AsyncSessionLocal() as db:
        stranger = SalesContact(full_name="Ktoś Inny", company_id=other)
        db.add(stranger)
        await db.commit()
        stranger_id = stranger.id

    assert (await _create_from(app_client, viewer, meeting)).status_code == 403
    no_service = await app_client.post(
        f"{OPPS}/from-activity/{meeting}",
        json={"title": "Bez usługi"},
        headers=_headers(rep),
    )
    assert no_service.status_code == 422
    blank = await _create_from(app_client, rep, meeting, title="   ")
    assert blank.status_code == 422
    assert (await _create_from(app_client, rep, mail)).status_code == 422
    assert (await _create_from(app_client, rep, manual)).status_code == 422
    assert (await _create_from(app_client, rep, 999_999_999)).status_code == 404
    foreign = await _create_from(app_client, rep, meeting, contact_ids=[stranger_id])
    assert foreign.status_code == 422
    assert (await _row(meeting)).opportunity_id is None


@pytest.mark.asyncio
async def test_client_gate_names_the_delivery_lead(app_client) -> None:
    rep = await _user("sales_edit")
    lead = await _user(role="delivery_lead")
    backup = await _user(role="delivery_lead")
    client_id, _ = await _client(lead_ids=(lead.id,))
    async with AsyncSessionLocal() as db:
        db.add(
            DeliveryLeadClientAssignment(
                delivery_lead_user_id=backup.id, client_id=client_id, is_head=False
            )
        )
        await db.commit()
    linked = await _firm(client_id=client_id)
    activity_id = await _activity(linked)

    refused = await _create_from(app_client, rep, activity_id)
    assert refused.status_code == 409
    assert lead.name in str(refused.json()["detail"])
    assert backup.name not in str(refused.json()["detail"])
    assert (await _row(activity_id)).opportunity_id is None


@pytest.mark.asyncio
async def test_client_gate_recognises_name_and_alias(app_client) -> None:
    rep = await _user("sales_edit")
    lead = await _user(role="delivery_lead")
    tag = _tag()
    _, name = await _client(f"Bocian Bank {tag}", lead_ids=(lead.id,))
    await _client(f"Nazwa Główna {tag}", lead_ids=(lead.id,), alias=f"Żuraw {tag}")
    by_name = await _firm(f"BOCIAN BANK {tag} S.A.")
    by_alias = await _firm(f"Żuraw {tag} sp. z o.o.")

    for company_id in (by_name, by_alias):
        refused = await _create_from(app_client, rep, await _activity(company_id))
        assert refused.status_code == 409, refused.text
        assert lead.name in str(refused.json()["detail"])


@pytest.mark.asyncio
async def test_client_without_active_lead_goes_to_the_head(app_client) -> None:
    rep = await _user("sales_edit")
    gone = await _user(role="delivery_lead")
    async with AsyncSessionLocal() as db:
        row = await db.get(type(gone), gone.id)
        row.is_active = False
        await db.commit()
    client_id, _ = await _client(lead_ids=(gone.id,))
    company_id = await _firm(client_id=client_id)

    refused = await _create_from(app_client, rep, await _activity(company_id))
    assert refused.status_code == 409
    detail = str(refused.json()["detail"])
    assert "zgłoś do Heada" in detail
    assert gone.name not in detail


@pytest.mark.asyncio
async def test_hidden_client_does_not_block_a_new_opportunity(app_client) -> None:
    rep = await _user("sales_edit")
    tag = _tag()
    async with AsyncSessionLocal() as db:
        db.add(Client(name=f"Ukryty Bank {tag}", hidden=True))
        await db.commit()
    company_id = await _firm(f"Ukryty Bank {tag}")
    created = await _create_from(app_client, rep, await _activity(company_id))
    assert created.status_code == 201, created.text


@pytest.mark.asyncio
async def test_draft_prefers_meeting_attendees_and_falls_back_to_company_people(
    app_client,
) -> None:
    rep = await _user("sales_edit")
    viewer = await _user("sales_view")
    company_id = await _firm()
    tag = _tag()
    async with AsyncSessionLocal() as db:
        met = SalesContact(
            full_name="Bywalec Spotkań",
            title="CTO",
            email=f"bywalec-{tag}@example.pl",
            company_id=company_id,
        )
        absent = SalesContact(full_name="Nieobecna Osoba", company_id=company_id)
        linked = SalesContact(full_name="Osoba Powiązana", company_id=None)
        gone = SalesContact(
            full_name="Osoba Zarchiwizowana",
            company_id=company_id,
            archived_at=datetime.now(timezone.utc),
        )
        db.add_all([met, absent, linked, gone])
        await db.flush()
        db.add(SalesCompanyContact(company_id=company_id, contact_id=linked.id))
        uid = f"ical-{tag}"
        db.add(
            CalendarEvent(
                created_by=rep.id,
                title="Spotkanie",
                start_time=_ago(1),
                end_time=_ago(1),
                m365_ical_uid=uid,
                attendees=[{"address": met.email, "name": "x"}],
            )
        )
        await db.commit()
    with_people = await _activity(
        company_id,
        subject="[ELEVATE] Firma Testowa x B2Bnetwork",
        external_id=uid,
    )
    nobody_firm = await _activity(company_id, subject="[ELEVATE]")

    draft = await app_client.get(
        f"{ACTIVITIES}/{with_people}/opportunity-draft", headers=_headers(viewer)
    )
    assert draft.status_code == 200, draft.text
    body = draft.json()
    assert body["suggested_title"] == "Firma Testowa"
    assert body["attendees_known"] is True
    assert [p["name"] for p in body["people"] if p["attended"]] == ["Bywalec Spotkań"]

    fallback = (
        await app_client.get(
            f"{ACTIVITIES}/{nobody_firm}/opportunity-draft", headers=_headers(viewer)
        )
    ).json()
    assert fallback["attendees_known"] is False
    assert fallback["suggested_title"] == fallback["company"]["name"]
    names = {p["name"] for p in fallback["people"]}
    assert {"Bywalec Spotkań", "Nieobecna Osoba", "Osoba Powiązana"} <= names
    assert "Osoba Zarchiwizowana" not in names
    assert not any(p["attended"] for p in fallback["people"])


# ── Lista ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_each_row_says_what_to_do_next(app_client) -> None:
    rep = await _user("sales_edit")
    lead = await _user(role="delivery_lead")
    tag = _tag()
    empty = await _firm()
    one = await _firm()
    two = await _firm()
    client_id, client_name = await _client(lead_ids=(lead.id,))
    served = await _firm(client_id=client_id)
    orphan_client, _ = await _client()
    orphan = await _firm(client_id=orphan_client)
    single = await _opportunity(app_client, rep, one, "Jedyna")
    await _opportunity(app_client, rep, two, "Mniejsza")
    bigger = await _opportunity(app_client, rep, two, "Większa")
    await _opportunity(app_client, rep, served, "U klienta")
    async with AsyncSessionLocal() as db:
        row = await db.get(SalesOpportunity, bigger["id"])
        row.value = 1000
        await db.commit()

    ids = {
        "create": await _activity(empty, subject=f"{tag} zalozyc"),
        "pin": await _activity(one, subject=f"{tag} przypiac"),
        "choose": await _activity(two, subject=f"{tag} wybrac"),
        "client": await _activity(served, subject=f"{tag} klient"),
        "orphan": await _activity(orphan, subject=f"{tag} sierota"),
        "manual": await _activity(empty, subject=f"{tag} reczne", source=None),
    }
    linked_id = await _activity(
        one, subject=f"{tag} przypiete", opportunity_id=single["id"]
    )
    atlas_linked = await _activity(
        one, subject=f"{tag} fireflies", source="fireflies", opportunity_id=single["id"]
    )

    listing = await _list(app_client, rep, q=tag)
    by_id = {item["id"]: item for item in listing["items"]}
    decision = {key: by_id[value]["decision"] for key, value in ids.items()}
    assert decision == {
        "create": "create",
        "pin": "pin",
        "choose": "choose",
        "client": "client",
        "orphan": "client",
        "manual": "company_only",
    }
    assert [o["title"] for o in by_id[ids["choose"]]["open_opportunities"]] == [
        "Większa",
        "Mniejsza",
    ]
    option = by_id[ids["pin"]]["open_opportunities"][0]
    assert option["id"] == single["id"] and option["stage_name"]
    assert by_id[ids["client"]]["client_name"] == client_name
    assert by_id[ids["client"]]["delivery_lead"] == lead.name
    assert by_id[ids["orphan"]]["delivery_lead"] is None
    assert by_id[linked_id]["decision"] == "linked"
    assert by_id[linked_id]["can_unpin"] is True
    assert by_id[atlas_linked]["can_unpin"] is False


@pytest.mark.asyncio
async def test_list_orders_soon_first_and_far_future_last(app_client) -> None:
    rep = await _user("sales_edit")
    tag = _tag()
    company_id = await _firm()
    today_noon = datetime.now(timezone.utc)
    ids = {
        "far": await _activity(company_id, subject=f"{tag} far", when=_ago(-300)),
        "old": await _activity(company_id, subject=f"{tag} old", when=_ago(30)),
        "recent": await _activity(company_id, subject=f"{tag} recent", when=_ago(2)),
        "in3": await _activity(company_id, subject=f"{tag} in3", when=_ago(-3)),
        "in6": await _activity(company_id, subject=f"{tag} in6", when=_ago(-6)),
        "now": await _activity(company_id, subject=f"{tag} now", when=today_noon),
    }
    listing = await _list(app_client, rep, q=tag)
    order = [item["id"] for item in listing["items"]]
    assert order == [
        ids["now"],
        ids["in3"],
        ids["in6"],
        ids["recent"],
        ids["old"],
        ids["far"],
    ]
    timing = {item["id"]: item["timing"] for item in listing["items"]}
    assert (timing[ids["now"]], timing[ids["old"]], timing[ids["far"]]) == (
        "soon",
        "past",
        "later",
    )


@pytest.mark.asyncio
async def test_same_meeting_is_one_row_and_pinned_copy_wins(app_client) -> None:
    rep = await _user("sales_edit")
    tag = _tag()
    first = await _firm()
    second = await _firm()
    opp = await _opportunity(app_client, rep, second)
    uid = f"ical-{tag}"
    first_row = await _activity(first, subject=f"{tag} a", external_id=uid)
    second_row = await _activity(second, subject=f"{tag} a", external_id=uid)

    # Firma z otwartą szansą bierze wiersz, bo tam jest co zrobić.
    listing = await _list(app_client, rep, q=tag)
    assert listing["total"] == 1
    assert [item["id"] for item in listing["items"]] == [second_row]

    assert (await _pin(app_client, rep, second_row, opp["id"])).status_code == 200
    pinned = await _list(app_client, rep, q=tag)
    assert [item["id"] for item in pinned["items"]] == [second_row]
    assert pinned["items"][0]["decision"] == "linked"
    assert first_row != second_row
    # Spotkanie już rozstrzygnięte nie wraca do kolejki przy drugiej firmie.
    assert (await _list(app_client, rep, q=tag, queue="create"))["total"] == 0


@pytest.mark.asyncio
async def test_client_copy_does_not_hide_a_prospect_without_opportunity(
    app_client,
) -> None:
    rep = await _user("sales_edit")
    tag = _tag()
    client_id, _ = await _client()
    served = await _firm(client_id=client_id)
    prospect = await _firm()
    uid = f"ical-{tag}"
    await _activity(served, subject=f"{tag} a", external_id=uid)
    prospect_row = await _activity(prospect, subject=f"{tag} a", external_id=uid)

    listing = await _list(app_client, rep, q=tag)
    assert [(i["id"], i["decision"]) for i in listing["items"]] == [
        (prospect_row, "create")
    ]
    assert listing["counts"]["create"] == 1


@pytest.mark.asyncio
async def test_own_company_is_not_a_client_to_report(app_client) -> None:
    rep = await _user("sales_edit")
    tag = _tag()
    own, _ = await _own_firm()
    meeting = await _activity(own, subject=f"{tag} wewnętrzne")

    listing = await _list(app_client, rep, q=tag)
    item = listing["items"][0]
    assert (item["id"], item["decision"]) == (meeting, "internal")
    assert (item["client_name"], item["delivery_lead"]) == (None, None)
    assert listing["counts"] == {"pin": 0, "create": 0, "upcoming": 0}

    refused = await _create_from(app_client, rep, meeting)
    assert refused.status_code == 409
    detail = str(refused.json()["detail"])
    assert "nasza" in detail.lower() and "Heada" not in detail
    assert (await _row(meeting)).opportunity_id is None


@pytest.mark.asyncio
async def test_own_company_copy_gives_way_to_the_real_counterparty(app_client) -> None:
    rep = await _user("sales_edit")
    tag = _tag()
    own, _ = await _own_firm()
    prospect = await _firm()
    uid = f"ical-{tag}"
    await _activity(own, subject=f"{tag} a", external_id=uid)
    prospect_row = await _activity(prospect, subject=f"{tag} a", external_id=uid)

    listing = await _list(app_client, rep, q=tag)
    assert [(i["id"], i["decision"]) for i in listing["items"]] == [
        (prospect_row, "create")
    ]


@pytest.mark.asyncio
async def test_atlas_recording_and_calendar_event_are_one_row(app_client) -> None:
    rep = await _user("sales_edit")
    tag = _tag()
    company_id = await _firm()
    opp = await _opportunity(app_client, rep, company_id)
    held = _ago(6)
    recording = await _activity(
        company_id,
        subject=f"{tag} Nagranie",
        source="fireflies",
        when=held,
        opportunity_id=opp["id"],
    )
    await _activity(company_id, subject=f"{tag} nagranie", when=held)
    other_hour = await _activity(
        company_id, subject=f"{tag} Nagranie", when=held - timedelta(hours=2)
    )

    listing = await _list(app_client, rep, q=tag)
    assert [item["id"] for item in listing["items"]] == [recording, other_hour]
    assert listing["items"][0]["decision"] == "linked"
    assert listing["counts"]["pin"] == 1


@pytest.mark.asyncio
async def test_filters_and_counts(app_client) -> None:
    rep = await _user("sales_edit")
    colleague = await _user("sales_edit")
    tag = _tag()
    empty = await _firm()
    with_opp = await _firm()
    await _opportunity(app_client, rep, with_opp)

    mine_past = await _activity(
        empty, subject=f"{tag} moje stare", owner_id=rep.id, when=_ago(4)
    )
    mine_soon = await _activity(
        with_opp, subject=f"{tag} moje nowe", owner_id=rep.id, when=_ago(-2)
    )
    theirs = await _activity(
        empty, subject=f"{tag} cudze", owner_id=colleague.id, when=_ago(-1)
    )

    everything = await _list(app_client, rep, q=tag)
    assert everything["total"] == 3
    assert everything["counts"] == {"pin": 1, "create": 2, "upcoming": 2}

    mine = await _list(app_client, rep, q=tag, mine=True)
    assert {item["id"] for item in mine["items"]} == {mine_past, mine_soon}
    assert mine["counts"] == {"pin": 1, "create": 1, "upcoming": 1}

    create = await _list(app_client, rep, q=tag, queue="create")
    assert {item["id"] for item in create["items"]} == {mine_past, theirs}
    assert create["counts"]["upcoming"] == 1

    pin = await _list(app_client, rep, q=tag, queue="pin")
    assert [item["id"] for item in pin["items"]] == [mine_soon]

    future = await _list(app_client, rep, q=tag, upcoming=True)
    assert {item["id"] for item in future["items"]} == {mine_soon, theirs}
    assert future["counts"] == {"pin": 1, "create": 1, "upcoming": 2}

    # Dotychczasowe filtry zostają: zakres dat i przypisanie.
    today = business_today()
    dated = await _list(
        app_client,
        rep,
        q=tag,
        date_from=(today + timedelta(days=1)).isoformat(),
        date_to=(today + timedelta(days=2)).isoformat(),
    )
    assert {item["id"] for item in dated["items"]} <= {mine_soon, theirs}
    assert dated["total"] >= 1
    company_only = await _list(app_client, rep, q=tag, linked="company")
    assert company_only["total"] == 3
    assert (await _list(app_client, rep, q=tag, linked="opportunity"))["total"] == 0
    assert DEFAULT_TZ == "Europe/Warsaw"


@pytest.mark.asyncio
async def test_list_needs_sales_view(app_client) -> None:
    outsider = await _user()
    resp = await app_client.get(MEETINGS, headers=_headers(outsider))
    assert resp.status_code == 403
