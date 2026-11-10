"""Podsumowanie spotkania dla klienta i wysyłka z NEXUSA (decyzje Artura 09.11.2026).

Szkic pisze model F46 z transkryptu Teams, w tonie do klienta: ustalenia i następne
kroki, bez stawek, kandydatów i spraw wewnętrznych. Handlowiec czyta go i poprawia
w oknie, więc awaria modelu zostawia puste pole do napisania ręcznie, a nie błąd.

Wysyła organizator spotkania (transkrypt jest tylko jego) albo admin, ze swojej
skrzynki przez Graph. Skrzynka handlowca bez dostępu do kandydatów przechodzi tu
z ``sales_ok=True``, dlatego ta ścieżka nie wysyła do adresów z bazy kandydatów:
bramka kandydatów zostaje taka jak w ``m365/sender.py``.
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional, Sequence

from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.models.ai_feature import AIFeatureKey
from app.models.calendar_event import CalendarEvent
from app.models.candidate import Candidate
from app.models.m365 import M365Connection
from app.models.sales import SalesActivity, SalesMeetingTranscript, SalesOpportunity
from app.services.ai_quota import ai_feature
from app.services.llm_prompts import SALES_MEETING_CLIENT_SUMMARY
from app.services.m365 import matcher
from app.services.m365 import sender as m365_sender
from app.services.m365.graph_client import GraphClient, GraphRequestError
from app.services.sales.meeting_decisions import clean_meeting_title
from app.services.sales.outlook_activities import EMAIL_SOURCE, EVENT_SOURCE

logger = logging.getLogger(__name__)

FEATURE = AIFeatureKey.sales_meeting_client_summary
MAX_TRANSCRIPT_CHARS = 200_000
MAX_RECIPIENTS = 20
SUBJECT_PREFIX = "Podsumowanie spotkania"
SEND_SCOPE = "mail.send"
_ADDRESS = re.compile(r"^[^@\s<>,;\"']+@[^@\s<>,;\"']+\.[^@\s<>,;\"']+$")


@dataclass(frozen=True)
class Meeting:
    activity: SalesActivity
    transcript: SalesMeetingTranscript


@dataclass(frozen=True)
class Recipient:
    address: str
    name: Optional[str]
    #: ``candidate`` — adres z bazy kandydatów; tej ścieżce nie wolno do niego pisać.
    blocked: Optional[str] = None


class Undelivered(RuntimeError):
    """Mail na pewno nie wyszedł (brak szkicu albo odmowa Graph 4xx)."""


class Uncertain(RuntimeError):
    """Szkic powstał, a wynik wysyłki jest nieznany: mail mógł wyjść."""


async def load(
    db: AsyncSession, activity_id: int, *, lock: bool = False
) -> Optional[Meeting]:
    """Spotkanie z Outlooka z pobranym transkryptem; ``lock`` blokuje wiersz transkryptu."""

    query = (
        select(SalesActivity, SalesMeetingTranscript)
        .join(
            SalesMeetingTranscript,
            and_(
                SalesActivity.external_source == EVENT_SOURCE,
                SalesActivity.external_id == SalesMeetingTranscript.ical_uid,
            ),
        )
        .where(
            SalesActivity.id == activity_id,
            SalesActivity.kind == "meeting",
            SalesMeetingTranscript.status == "fetched",
        )
    )
    if lock:
        query = query.with_for_update(of=SalesMeetingTranscript)
    row = (await db.execute(query)).first()
    return Meeting(activity=row[0], transcript=row[1]) if row else None


def may_send(user_id: int, transcript: SalesMeetingTranscript, *, admin: bool) -> bool:
    """Organizator spotkania (jego skrzynka ma transkrypt) albo admin."""

    return admin or transcript.organizer_user_id == user_id


def default_subject(activity: SalesActivity) -> str:
    title = clean_meeting_title(activity.subject)
    return f"{SUBJECT_PREFIX}: {title}"[:300] if title else SUBJECT_PREFIX


def normalize_address(value: str) -> Optional[str]:
    address = (value or "").strip().lower()
    return address if _ADDRESS.match(address) and len(address) <= 320 else None


async def candidate_addresses(db: AsyncSession, addresses: Sequence[str]) -> set[str]:
    """Adresy z bazy kandydatów (wyrażenie jak w indeksie 0391)."""

    if not addresses:
        return set()
    found = await db.scalars(
        select(func.lower(func.btrim(Candidate.email))).where(
            func.lower(func.btrim(Candidate.email)).in_(list(addresses))
        )
    )
    return set(found.all())


async def attendees(
    db: AsyncSession, activity: SalesActivity, owner_address: Optional[str]
) -> list[Recipient]:
    """Uczestnicy spoza firmy z kalendarzy NEXUSA, w kolejności z zaproszenia."""

    names: dict[str, Optional[str]] = {}
    for rows in (
        await db.scalars(
            select(CalendarEvent.attendees).where(
                CalendarEvent.m365_ical_uid == activity.external_id
            )
        )
    ).all():
        for entry in rows or []:
            if not isinstance(entry, dict):
                continue
            address = normalize_address(str(entry.get("address") or ""))
            if address and not names.get(address):
                names[address] = str(entry.get("name") or "").strip() or None
    external = set(matcher.external_addresses(list(names), owner_address))
    ordered = [address for address in names if address in external]
    blocked = await candidate_addresses(db, ordered)
    return [
        Recipient(
            address=address,
            name=names[address],
            blocked="candidate" if address in blocked else None,
        )
        for address in ordered
    ]


def mailbox_state(connection: Optional[M365Connection]) -> str:
    """``ok``, ``missing`` (brak aktywnej skrzynki) albo ``no_send_scope``."""

    if connection is None or not connection.is_active:
        return "missing"
    scopes = connection.scopes_granted or []
    if not any(SEND_SCOPE in str(scope).lower() for scope in scopes):
        return "no_send_scope"
    return "ok"


def _call_model(prompt: str) -> str:
    """Jedno wywołanie modelu (w wątku). Osobna funkcja: testy ją podmieniają."""
    from app.services.ai_models import fallbacks_for, model_for  # noqa: PLC0415
    from app.services.claude_client import call_claude_text  # noqa: PLC0415

    return call_claude_text(
        model=model_for(FEATURE),
        fallback_models=fallbacks_for(FEATURE),
        max_tokens=800,
        thinking={"type": "disabled"},
        system=SALES_MEETING_CLIENT_SUMMARY.system_prompt or "",
        messages=[{"role": "user", "content": prompt}],
    )


async def client_summary(
    db: AsyncSession, meeting: Meeting, *, user_id: int
) -> tuple[str, bool]:
    """Szkic treści i to, czy model zawiódł. Udany szkic zostaje przy transkrypcie."""

    from app.services.ai_models import model_for  # noqa: PLC0415
    from app.services.llm_providers import api_key_configured  # noqa: PLC0415

    transcript = meeting.transcript
    if transcript.client_summary:
        return transcript.client_summary, False
    text = transcript.plain_text or ""
    if (
        not text
        or len(text) > MAX_TRANSCRIPT_CHARS
        or not api_key_configured(model_for(FEATURE))
    ):
        return "", True
    transcript_id = transcript.id
    prompt = SALES_MEETING_CLIENT_SUMMARY.render(
        subject=clean_meeting_title(meeting.activity.subject) or "(bez tematu)",
        transcript=text,
    )
    try:
        async with ai_feature(db, FEATURE, user_id=user_id):
            await db.commit()  # połączenie wraca do puli na czas modelu
            draft = (await run_in_threadpool(_call_model, prompt)).strip()
    except Exception as exc:  # noqa: BLE001 — AI to dodatek, handlowiec pisze sam
        await db.rollback()
        logger.warning(
            "sales_client_mail %s: summary failed (%s)",
            transcript_id,
            type(exc).__name__,
        )
        return "", True
    if not draft:
        return "", True
    row = await db.get(SalesMeetingTranscript, transcript_id, populate_existing=True)
    if row is not None and not row.client_summary:
        row.client_summary = draft
        await db.commit()
    return draft, False


def text_to_html(body: str) -> str:
    """Zwykły tekst z okna jako HTML maila: znaki uciekają, wiersze zostają."""

    return "<br>".join(html.escape(line) for line in body.strip().splitlines())


async def deliver(
    db: AsyncSession,
    connection: M365Connection,
    *,
    subject: str,
    body: str,
    to: Sequence[str],
) -> dict[str, Any]:
    """Szkic i wysyłka ze skrzynki osoby klikającej; zwraca szkic z Graph.

    ``sales_ok=True``: skrzynka handlowca bez dostępu do kandydatów. Adresy
    kandydatów odrzuca wołający, zanim tu dojdzie (``candidate_addresses``).
    """

    draft: Optional[dict[str, Any]] = None
    try:
        async with GraphClient(connection, db, sales_ok=True) as gc:
            # Stopka z Outlooka, jak przy każdej wysyłce z NEXUSA (``m365/sender``).
            content, images = await m365_sender._signature_body(
                gc, connection, text_to_html(body)
            )
            draft = await gc.post(
                "/me/messages",
                json={
                    "subject": subject,
                    "body": {"contentType": "HTML", "content": content},
                    "toRecipients": [
                        {"emailAddress": {"address": address}} for address in to
                    ],
                },
            )
            message_id = (draft or {}).get("id")
            if not message_id:
                draft = None
                raise Undelivered("draft_without_id")
            if images:
                await m365_sender._attach_inline_images(gc, message_id, images)
            await gc.post(f"/me/messages/{message_id}/send", json={})
    except Undelivered:
        raise
    except Exception as exc:
        definitely_not_sent = draft is None or (
            isinstance(exc, GraphRequestError) and 400 <= exc.status < 500
        )
        logger.warning(
            "sales_client_mail: send %s (%s)",
            "failed" if definitely_not_sent else "uncertain",
            type(exc).__name__,
        )
        if definitely_not_sent:
            raise Undelivered(type(exc).__name__) from exc
        raise Uncertain(type(exc).__name__) from exc
    return draft


async def record_sent(
    db: AsyncSession,
    meeting: Meeting,
    *,
    opportunity_id: Optional[int],
    user_id: int,
    subject: str,
    body: str,
    internet_message_id: Optional[str],
    now: datetime,
) -> int:
    """Mail na osi szansy, z kluczem synchronizacji, żeby kopia z Wysłanych się skleiła."""

    external_id = (internet_message_id or "").strip()[:255] or None
    values = {
        "company_id": meeting.activity.company_id,
        "opportunity_id": opportunity_id,
        "kind": "email",
        "subject": subject[:500],
        "body": body,
        "occurred_at": now,
        "done_at": now,
        "created_by_user_id": user_id,
        "direction": "out",
        "external_source": EMAIL_SOURCE if external_id else None,
        "external_id": external_id,
    }
    statement = pg_insert(SalesActivity).values(**values)
    if external_id:
        statement = statement.on_conflict_do_update(
            index_elements=["external_source", "external_id", "company_id"],
            index_where=and_(
                SalesActivity.external_id.is_not(None),
                SalesActivity.external_ref.is_(None),
            ),
            set_={"opportunity_id": opportunity_id, "body": body},
        )
    activity_id = (await db.execute(statement.returning(SalesActivity.id))).scalar_one()
    if opportunity_id is not None:
        opportunity = await db.get(SalesOpportunity, opportunity_id)
        if opportunity is not None and (
            opportunity.last_activity_at is None or opportunity.last_activity_at < now
        ):
            opportunity.last_activity_at = now
    return activity_id
