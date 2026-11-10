"""Zaproszenie na przekazane spotkanie: prowadzący wysyła je jednym kliknięciem.

Decyzja Artura z 10.11.2026. Formularz „Umów spotkanie” niczego nie wysyła, bo
umawia inna osoba niż ta, z której skrzynki szłoby zaproszenie. Zaproszenie wysyła
**prowadzący, ze swojej skrzynki i po swoim kliknięciu** na karcie przekazania:
spotkanie Teams powstaje w jego kalendarzu, więc to on jest organizatorem i działa
dla niego transkrypt oraz mail po spotkaniu.

Skrzynka handlowca bez dostępu do kandydatów przechodzi tu z ``sales_ok=True``
(czwarte dozwolone miejsce, patrz ``outlook-handlowcow-w-sprzedazy.md``), dlatego
ta ścieżka nie zaprasza adresów z bazy kandydatów: bramka kandydatów zostaje taka
jak przy mailu po spotkaniu (``meeting_client_mail``).

Jedno zaproszenie na przekazanie: rezerwacja leży w bloku przekazania i jest
zapisana przed wywołaniem Graph, więc drugie żądanie (także z innego okna, z własnym
kluczem) czeka ``RETRY_AFTER``. Graph dostaje ``transactionId`` stały dla przekazania
i terminu, więc ponowiona wysyłka nie tworzy drugiego spotkania. Wydarzenie trafia na oś szansy
jako spotkanie z Outlooka i zastępuje wpis terminu z formularza; kopia
z synchronizacji kalendarza skleja się z nim po ``iCalUId``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional
from uuid import UUID

import httpx
from fastapi import HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.m365 import M365Connection
from app.models.sales import SalesActivity, SalesContact, SalesOpportunity
from app.services.m365 import calendar as m365_calendar
from app.services.m365.graph_client import GraphClient, GraphRequestError
from app.services.m365.oauth import M365ReauthRequired
from app.services.sales import handoff, history
from app.services.sales.handoff_state import (
    DEFAULT_DURATION,
    invite_sent_at,
    moment,
    store,
)
from app.services.sales.meeting_client_mail import (
    Recipient,
    candidate_addresses,
    normalize_address,
    text_to_html,
)
from app.services.sales.meeting_decisions import is_outlook
from app.services.sales.outlook_activities import EVENT_SOURCE
from app.services.sales_schema import OpportunityEventKind

logger = logging.getLogger(__name__)

CALENDAR_SCOPE = "calendars.readwrite"
MAX_ATTENDEES = 10
INVITE_KEY = "invite"
#: Tyle trwa blokada po żądaniu, którego wynik nie jest znany. Dłużej niż wywołanie
#: Graph; potem prowadzący, który sprawdził kalendarz, może spróbować jeszcze raz.
RETRY_AFTER = timedelta(minutes=10)

OWNER_DETAIL = "Zaproszenie wysyła prowadzący spotkanie, ze swojej skrzynki."
PAST_DETAIL = "Termin już minął. Zmień termin, a potem wyślij zaproszenie."
IN_CALENDAR_DETAIL = "To spotkanie jest już w kalendarzu Outlook."
SENT_DETAIL = "Zaproszenie na to spotkanie już wyszło."
IN_FLIGHT_DETAIL = "To zaproszenie jest już wysyłane albo wyszło. Sprawdź kalendarz."
CANDIDATE_DETAIL = (
    "Wśród zaproszonych jest osoba z bazy kandydatów. Ze Sprzedaży nie zapraszamy "
    "kandydatów: usuń ten adres."
)
NO_MAILBOX_DETAIL = "Podłącz skrzynkę Outlook w Sprzedaży, żeby wysłać zaproszenie."
NO_SCOPE_DETAIL = "Połącz skrzynkę Outlook ponownie: brakuje zgody na kalendarz."
UNDELIVERED_DETAIL = (
    "Outlook nie przyjął zaproszenia. Nic nie wyszło, spróbuj ponownie."
)
RECONNECT_DETAIL = (
    "Połącz skrzynkę Outlook ponownie: zgoda wygasła. Zaproszenie nie wyszło."
)
UNCERTAIN_DETAIL = (
    "Nie wiadomo, czy zaproszenie wyszło. Sprawdź kalendarz w Outlooku, zanim "
    "spróbujesz ponownie."
)


class InviteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=1, max_length=255)
    to: list[str] = Field(min_length=1, max_length=MAX_ATTENDEES)
    message: Optional[str] = Field(default=None, max_length=5000)
    #: Nadawany przy otwarciu okna: drugi klik z tym samym kluczem nie wysyła drugi raz.
    request_id: UUID


@dataclass(frozen=True)
class InviteDraft:
    mailbox: str
    subject: str
    recipients: list[Recipient]
    meeting_at: Optional[datetime]
    duration_minutes: int
    sent_at: Optional[datetime]


class Undelivered(RuntimeError):
    """Wydarzenie na pewno nie powstało: Graph odmówił albo żądanie do niego nie dotarło."""


class ReconnectNeeded(Undelivered):
    """Microsoft odrzucił odświeżenie zgody: skrzynkę trzeba połączyć ponownie."""


# Połączenie nie powstało, więc Graph nie widział żądania (klient Graph mówi to samo
# przy ``httpx.ConnectError``). Zerwana odpowiedź do tej grupy nie należy.
_NEVER_SENT = (httpx.ConnectError, httpx.ConnectTimeout)


class Uncertain(RuntimeError):
    """Odpowiedź nie doszła: wydarzenie mogło powstać."""


def mailbox_state(connection: Optional[M365Connection]) -> str:
    """``ok``, ``missing`` (brak aktywnej skrzynki) albo ``no_calendar_scope``."""

    if connection is None or not connection.is_active:
        return "missing"
    scopes = connection.scopes_granted or []
    if not any(CALENDAR_SCOPE in str(scope).lower() for scope in scopes):
        return "no_calendar_scope"
    return "ok"


def default_subject(service: Optional[str]) -> str:
    text = (service or "").strip()
    return (f"Spotkanie: {text}" if text else "Spotkanie")[:255]


def ensure_host(opportunity: SalesOpportunity, user_id: int) -> None:
    """Tylko prowadzący: zaproszenie wychodzi ze skrzynki osoby, która klika."""

    if opportunity.owner_user_id != user_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=OWNER_DETAIL)


async def own_connection(db: AsyncSession, user_id: int) -> Optional[M365Connection]:
    return await db.scalar(
        select(M365Connection).where(M365Connection.user_id == user_id)
    )


async def draft(
    db: AsyncSession, opportunity: SalesOpportunity, *, user_id: int
) -> InviteDraft:
    """Podpowiedzi do okna: stan skrzynki, temat i osoba ze spotkania jako adresat."""

    data = handoff.block(opportunity)
    if data is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=handoff.NO_HANDOFF_DETAIL)
    recipients: list[Recipient] = []
    contact = (
        await db.get(SalesContact, opportunity.primary_contact_id)
        if opportunity.primary_contact_id is not None
        else None
    )
    address = normalize_address(contact.email or "") if contact is not None else None
    if contact is not None and address and contact.do_not_contact_at is None:
        blocked = await candidate_addresses(db, [address])
        recipients.append(
            Recipient(
                address=address,
                name=contact.full_name,
                blocked="candidate" if address in blocked else None,
            )
        )
    return InviteDraft(
        mailbox=mailbox_state(await own_connection(db, user_id)),
        subject=default_subject(data.get("service")),
        recipients=recipients,
        meeting_at=moment(data.get("meeting_at")),
        duration_minutes=int(data.get("duration_minutes") or DEFAULT_DURATION),
        sent_at=invite_sent_at(data),
    )


def clean_addresses(values: list[str]) -> list[str]:
    addresses: list[str] = []
    invalid: list[str] = []
    for value in values:
        address = normalize_address(value)
        if address is None:
            invalid.append(value.strip()[:80])
        elif address not in addresses:
            addresses.append(address)
    if invalid:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Niepoprawny adres: {', '.join(invalid)}.",
        )
    return addresses


async def reserve(
    db: AsyncSession,
    opportunity: SalesOpportunity,
    payload: InviteRequest,
    *,
    now: datetime,
) -> tuple[datetime, int]:
    """Sprawdź przekazanie i zapisz klucz żądania; wywołujący robi commit przed Graph."""

    data = handoff.pending(opportunity)
    activity = await handoff.meeting_activity(db, opportunity, data)
    if activity is not None and is_outlook(activity):
        raise HTTPException(status.HTTP_409_CONFLICT, detail=IN_CALENDAR_DETAIL)
    meeting_at = moment(data.get("meeting_at"))
    if meeting_at is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=handoff.NO_TERM_DETAIL)
    if meeting_at <= now:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=PAST_DETAIL)
    invite = data.get(INVITE_KEY) if isinstance(data.get(INVITE_KEY), dict) else {}
    if invite.get("at"):
        raise HTTPException(status.HTTP_409_CONFLICT, detail=SENT_DETAIL)
    reserved_at = moment(invite.get("reserved_at"))
    if reserved_at is not None and now - reserved_at < RETRY_AFTER:
        # Każdy klucz, nie tylko ten sam: drugie okno albo druga karta miałyby własny
        # i przeszłyby obok trwającej wysyłki.
        raise HTTPException(status.HTTP_409_CONFLICT, detail=IN_FLIGHT_DETAIL)
    data[INVITE_KEY] = {
        "request_id": str(payload.request_id),
        "reserved_at": now.isoformat(),
        "at": None,
    }
    store(opportunity, data)
    return meeting_at, int(data.get("duration_minutes") or DEFAULT_DURATION)


async def release(db: AsyncSession, opportunity_id: int, request_id: UUID) -> None:
    """Graph odmówił: klucz znika, żeby dało się spróbować jeszcze raz."""

    opportunity = await handoff.lock(db, opportunity_id)
    data = handoff.block(opportunity) or {}
    invite = data.get(INVITE_KEY)
    if isinstance(invite, dict) and invite.get("request_id") == str(request_id):
        data.pop(INVITE_KEY, None)
        store(opportunity, data)


async def deliver(
    db: AsyncSession,
    connection: M365Connection,
    *,
    opportunity_id: int,
    subject: str,
    message: Optional[str],
    start: datetime,
    minutes: int,
    to: list[str],
) -> dict[str, Any]:
    """Utwórz spotkanie Teams w kalendarzu osoby klikającej; Outlook rozsyła zaproszenia."""

    end = start + timedelta(minutes=minutes)
    payload = m365_calendar._build_event_payload(
        title=subject,
        description=text_to_html(message or ""),
        start=start,
        end=end,
        attendee_emails=to,
        want_teams=True,
        transaction_id=m365_calendar.event_transaction_id(
            owner_user_id=connection.user_id,
            title=subject,
            start=start,
            end=end,
            attendee_emails=to,
            # Stały dla przekazania i terminu, nie dla okna: ponowiona wysyłka z nowym
            # kluczem żądania nie tworzy w Outlooku drugiego spotkania.
            intent_id=f"sales-handoff-{opportunity_id}-{start.isoformat()}",
        ),
    )
    try:
        async with GraphClient(connection, db, sales_ok=True) as gc:
            event = await gc.post("/me/events", json=payload)
    except M365ReauthRequired as exc:
        # 401 i nieudane odświeżenie: wydarzenia nie ma, a klient Graph oznaczył już
        # skrzynkę jako wymagającą ponownego połączenia.
        logger.warning("sales_handoff_invite: reconnect required")
        raise ReconnectNeeded(type(exc).__name__) from exc
    except Exception as exc:
        refused = isinstance(exc, _NEVER_SENT) or (
            isinstance(exc, GraphRequestError) and 400 <= exc.status < 500
        )
        logger.warning(
            "sales_handoff_invite: %s (%s)",
            "refused" if refused else "uncertain",
            type(exc).__name__,
        )
        if refused:
            raise Undelivered(type(exc).__name__) from exc
        raise Uncertain(type(exc).__name__) from exc
    if not isinstance(event, dict) or not event.get("id"):
        raise Uncertain("event_without_id")
    return event


async def record_sent(
    db: AsyncSession,
    opportunity: SalesOpportunity,
    event: dict[str, Any],
    *,
    request_id: UUID,
    subject: str,
    start: datetime,
    minutes: int,
    attendees: int,
    user_id: int,
    now: datetime,
) -> None:
    """Spotkanie z Outlooka na osi szansy zamiast wpisu terminu z formularza.

    Termin i czas trwania to te, które poszły w zaproszeniu, nie bieżące z bloku:
    ktoś mógł zmienić termin w trakcie wysyłki, a kalendarz ma to, co wyszło.
    """

    data = handoff.block(opportunity) or {}
    ical_uid = str(event.get("iCalUId") or "").strip()[:255]
    if ical_uid:
        statement = (
            pg_insert(SalesActivity)
            .values(
                company_id=opportunity.company_id,
                opportunity_id=opportunity.id,
                contact_id=opportunity.primary_contact_id,
                kind="meeting",
                subject=subject[:500],
                occurred_at=start,
                duration_minutes=minutes,
                created_by_user_id=user_id,
                external_source=EVENT_SOURCE,
                external_id=ical_uid,
                web_link=str(event.get("webLink") or "")[:2000] or None,
            )
            .on_conflict_do_update(
                index_elements=["external_source", "external_id", "company_id"],
                index_where=and_(
                    SalesActivity.external_id.is_not(None),
                    SalesActivity.external_ref.is_(None),
                ),
                set_={"opportunity_id": opportunity.id},
            )
            .returning(SalesActivity.id)
        )
        activity_id = (await db.execute(statement)).scalar_one()
        placeholder = await handoff.meeting_activity(db, opportunity, data)
        if placeholder is not None and placeholder.id != activity_id:
            await db.delete(placeholder)
        data["meeting_at"] = start.isoformat()
        data["duration_minutes"] = minutes
        data["meeting_activity_id"] = activity_id
    data[INVITE_KEY] = {
        "request_id": str(request_id),
        "at": now.isoformat(),
        "by": user_id,
        "attendees": attendees,
    }
    store(opportunity, data)
    # W historii sam krok: bez adresów i bez tematu zaproszenia.
    history.record(
        db,
        opportunity_id=opportunity.id,
        user_id=user_id,
        kind=OpportunityEventKind.updated,
        field=handoff.HISTORY_FIELD,
        new_value="invited",
    )
