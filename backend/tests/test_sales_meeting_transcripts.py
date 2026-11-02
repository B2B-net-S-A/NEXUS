"""Transkrypty Teams spotkań handlowców (decyzje Artura 02.11.2026).

Kolejka powstaje z synchronizacji tylko dla organizatora, pobieranie nie rusza
historii ani cudzych wystąpień spotkania cyklicznego, a awaria modelu zostawia
sam transkrypt. Microsoft Graph jest podmieniony.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.sales import SalesMeetingTranscript
from app.services.m365 import sync as sync_mod
from app.services.m365 import teams_prep_auth, teams_prep_graph
from app.services.m365.graph_client import GraphRequestError
from app.services.m365.teams_prep_graph import TranscriptRef
from app.services.sales import meeting_transcripts as service
from app.services.sales import outlook_activities as outlook
from tests.test_sales_outlook_sync import (
    SALES_ONLY,
    _company,
    _conn,
    _graph_event,
    _tag,
    _user,
)

VTT = "WEBVTT\n\n00:00:01.000 --> 00:00:04.000\n<v Handlowiec>Dzień dobry</v>\n"


@pytest.fixture(autouse=True)
def _enabled(monkeypatch):
    monkeypatch.setattr(settings, "SALES_TEAMS_TRANSCRIPTS_ENABLED", True)
    monkeypatch.setattr(teams_prep_auth, "credentials_configured", lambda: True)


async def _row(uid: str) -> SalesMeetingTranscript | None:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(SalesMeetingTranscript).where(SalesMeetingTranscript.ical_uid == uid)
        )


async def _sync_meeting(rep, attendee: str, *, start: datetime, organizer: str) -> dict:
    event = _graph_event(attendee, start=start)
    event["organizer"] = {"emailAddress": {"address": organizer}}
    async with AsyncSessionLocal() as db:
        await sync_mod._upsert_event(db, _conn(rep), event, scope=SALES_ONLY)
        await db.commit()
    return event


async def _queued(*, ends_in: timedelta = timedelta(hours=-1), **fields) -> int:
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        row = SalesMeetingTranscript(
            ical_uid=f"ical-{_tag()}",
            organizer_upn="handlowiec@example.com",
            graph_event_id="ev",
            join_url="https://teams.microsoft.com/l/meetup-join/x",
            organizer_aad_id="aad",
            online_meeting_id="meeting",
            starts_at=now + ends_in - timedelta(minutes=45),
            ends_at=now + ends_in,
            next_fetch_at=now - timedelta(minutes=1),
            **fields,
        )
        db.add(row)
        await db.commit()
        return row.id


async def _load(row_id: int) -> SalesMeetingTranscript:
    async with AsyncSessionLocal() as db:
        return await db.get(SalesMeetingTranscript, row_id)


def _graph(monkeypatch, refs=None, error: int | None = None) -> None:
    async def list_transcripts(_user_id: str, _meeting_id: str):
        if error:
            raise GraphRequestError(error, "x")
        return refs or []

    async def transcript_vtt(_user_id: str, _meeting_id: str, _id: str) -> str:
        return VTT

    monkeypatch.setattr(teams_prep_graph, "list_transcripts", list_transcripts)
    monkeypatch.setattr(teams_prep_graph, "transcript_vtt", transcript_vtt)


@pytest.mark.asyncio
async def test_only_organizer_new_meeting_enters_the_queue(monkeypatch) -> None:
    rep = await _user("employee", "sales_view")
    domain = f"teams-{_tag()}.example"
    await _company(f"Firma {domain}", domain)
    client = f"klient@{domain}"
    start = datetime.now(timezone.utc) + timedelta(days=1)

    mine = await _sync_meeting(rep, client, start=start, organizer=rep.email)
    assert (await _row(mine["iCalUId"])).status == "waiting"

    guest = await _sync_meeting(rep, client, start=start, organizer=client)
    assert await _row(guest["iCalUId"]) is None

    old = await _sync_meeting(
        rep, client, start=start - timedelta(days=30), organizer=rep.email
    )
    assert await _row(old["iCalUId"]) is None

    monkeypatch.setattr(settings, "SALES_TEAMS_TRANSCRIPTS_ENABLED", False)
    off = await _sync_meeting(rep, client, start=start, organizer=rep.email)
    assert await _row(off["iCalUId"]) is None


@pytest.mark.asyncio
async def test_cancelled_upcoming_meeting_takes_its_queue_row() -> None:
    rep = await _user("employee", "sales_view")
    domain = f"teams-{_tag()}.example"
    await _company(f"Firma {domain}", domain)
    start = datetime.now(timezone.utc) + timedelta(days=1)
    event = await _sync_meeting(
        rep, f"klient@{domain}", start=start, organizer=rep.email
    )
    async with AsyncSessionLocal() as db:
        await outlook.forget(
            db, outlook.EVENT_SOURCE, event["iCalUId"], upcoming_only=True
        )
        await db.commit()
    assert await _row(event["iCalUId"]) is None


@pytest.mark.asyncio
async def test_join_url_comes_from_organizer_calendar() -> None:
    rep = await _user("employee", "sales_view")
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        online = SalesMeetingTranscript(
            ical_uid=f"ical-{_tag()}",
            organizer_user_id=rep.id,
            organizer_upn=rep.email,
            graph_event_id="online",
            starts_at=now,
            ends_at=now,
            next_fetch_at=now,
        )
        offline = SalesMeetingTranscript(
            ical_uid=f"ical-{_tag()}",
            organizer_user_id=rep.id,
            organizer_upn=rep.email,
            graph_event_id="offline",
            starts_at=now,
            ends_at=now,
            next_fetch_at=now,
        )
        db.add_all([online, offline])
        await db.commit()
        online_id, offline_id = online.id, offline.id

    async def get(path: str, params: dict) -> dict:
        assert "onlineMeeting" in params["$select"]
        if path.endswith("/online"):
            return {"isOrganizer": True, "onlineMeeting": {"joinUrl": "https://t/x"}}
        return {"isOrganizer": True, "onlineMeeting": None}

    async with AsyncSessionLocal() as db:
        await service.resolve_join_urls(db, SimpleNamespace(get=get), rep.id)
    assert (await _load(online_id)).join_url == "https://t/x"
    stopped = await _load(offline_id)
    assert (stopped.status, stopped.next_fetch_at) == ("not_online", None)


@pytest.mark.asyncio
async def test_join_url_failure_does_not_stop_the_mail_sync() -> None:
    rep = await _user("employee", "sales_view")
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        db.add(
            SalesMeetingTranscript(
                ical_uid=f"ical-{_tag()}",
                organizer_user_id=rep.id,
                organizer_upn=rep.email,
                graph_event_id="ev",
                starts_at=now,
                ends_at=now,
                next_fetch_at=now,
            )
        )
        await db.commit()

    async def get(_path: str, params: dict) -> dict:
        raise TimeoutError

    async with AsyncSessionLocal() as db:
        await service.resolve_join_urls(db, SimpleNamespace(get=get), rep.id)


def test_recurring_transcript_belongs_to_its_occurrence() -> None:
    start = datetime(2026, 11, 2, 10, tzinfo=timezone.utc)
    end = start + timedelta(hours=1)
    assert service.within_meeting("2026-11-02T10:05:00Z", start, end)
    assert not service.within_meeting("2026-11-01T10:05:00Z", start, end)
    assert not service.within_meeting("2026-11-09T10:05:00Z", start, end)
    assert service.within_meeting(None, start, end)


@pytest.mark.asyncio
async def test_fetch_stores_text_and_skips_other_occurrences(monkeypatch) -> None:
    row_id = await _queued()
    now = datetime.now(timezone.utc)
    _graph(
        monkeypatch,
        refs=[
            TranscriptRef(
                id="tydzien-temu", created=(now - timedelta(days=7)).isoformat()
            ),
            TranscriptRef(id="to", created=(now - timedelta(minutes=70)).isoformat()),
        ],
    )
    async with AsyncSessionLocal() as db:
        assert await service.fetch_due(db) >= 1
    row = await _load(row_id)
    assert row.status == "fetched"
    assert row.graph_transcript_ids == ["to"]
    assert "Handlowiec: Dzień dobry" in row.plain_text
    assert row.next_fetch_at is None


@pytest.mark.asyncio
async def test_without_transcript_waits_then_gives_up(monkeypatch) -> None:
    fresh = await _queued()
    expired = await _queued(ends_in=timedelta(hours=-49))
    _graph(monkeypatch)
    async with AsyncSessionLocal() as db:
        await service.fetch_due(db)
    waiting = await _load(fresh)
    assert waiting.status == "waiting"
    assert waiting.next_fetch_at is not None
    gone = await _load(expired)
    assert (gone.status, gone.next_fetch_at) == ("missing", None)


@pytest.mark.asyncio
async def test_forbidden_retries_later_and_stops_after_the_window(monkeypatch) -> None:
    fresh = await _queued()
    expired = await _queued(ends_in=timedelta(hours=-49))
    _graph(monkeypatch, error=403)
    async with AsyncSessionLocal() as db:
        await service.fetch_due(db)
    retry = await _load(fresh)
    assert (retry.status, retry.last_error) == ("forbidden", "http_403")
    assert retry.next_fetch_at > datetime.now(timezone.utc) + timedelta(hours=5)
    stopped = await _load(expired)
    assert (stopped.status, stopped.next_fetch_at) == ("forbidden", None)


@pytest.mark.asyncio
async def test_model_failure_keeps_transcript_and_limits_attempts(monkeypatch) -> None:
    from app.services import llm_providers

    row_id = await _queued(status="fetched", plain_text="Handlowiec: Dzień dobry")
    monkeypatch.setattr(llm_providers, "api_key_configured", lambda _model: True)

    def broken(_prompt: str) -> str:
        raise RuntimeError("model")

    monkeypatch.setattr(service, "_call_model", broken)
    for _ in range(service.MAX_SUMMARY_ATTEMPTS + 1):
        async with AsyncSessionLocal() as db:
            await service.summarize_pending(db, limit=500)
    failed = await _load(row_id)
    assert failed.summary is None
    assert failed.plain_text
    assert failed.summary_attempts == service.MAX_SUMMARY_ATTEMPTS

    ok_id = await _queued(status="fetched", plain_text="Handlowiec: Dzień dobry")
    monkeypatch.setattr(service, "_call_model", lambda _prompt: " Ustalono demo. ")
    async with AsyncSessionLocal() as db:
        await service.summarize_pending(db, limit=500)
    assert (await _load(ok_id)).summary == "Ustalono demo."


@pytest.mark.asyncio
async def test_api_shows_transcript_to_sales_view_only(app_client) -> None:
    from tests.test_sales_companies_api import _headers, _user as _sales_user

    rep = await _sales_user("sales_edit")
    outsider = await _sales_user()
    domain = f"teams-{_tag()}.example"
    company_id = await _company(f"Firma {domain}", domain)
    event = await _sync_meeting(
        rep,
        f"klient@{domain}",
        start=datetime.now(timezone.utc) + timedelta(days=1),
        organizer=rep.email,
    )
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(SalesMeetingTranscript).where(
                SalesMeetingTranscript.ical_uid == event["iCalUId"]
            )
        )
        row.status = "fetched"
        row.plain_text = "Handlowiec: Dzień dobry"
        row.summary = "Ustalono demo."
        row.next_fetch_at = None
        await db.commit()

    url = "/api/sales/activities/meetings"
    listed = await app_client.get(
        url,
        params={"q": domain, "has_transcript": "true", "limit": 500},
        headers=_headers(rep),
    )
    assert listed.status_code == 200, listed.text
    [item] = listed.json()["items"]
    assert item["company"]["id"] == company_id
    assert item["transcript_status"] == "fetched"
    assert item["transcript_summary"] == "Ustalono demo."
    assert "plain_text" not in item

    transcript_url = f"/api/sales/activities/{item['id']}/transcript"
    full = await app_client.get(transcript_url, headers=_headers(rep))
    assert full.status_code == 200, full.text
    assert full.json()["plain_text"] == "Handlowiec: Dzień dobry"
    denied = await app_client.get(transcript_url, headers=_headers(outsider))
    assert denied.status_code == 403
    missing = await app_client.get(
        "/api/sales/activities/2147483000/transcript", headers=_headers(rep)
    )
    assert missing.status_code == 404
