"""Zaproszenie Teams od osoby, która umawia (decyzja Artura 23.11.2026, wariant A).

Na kopii produkcji z 23.11: 24 przekazania z kolejki dzwonienia, 10 maili do klienta
od dzwoniących i 0 zaproszeń wysłanych przez prowadzącego (``handoff_invite``). Od
teraz zaproszenie wysyła osoba, która umawia (``booked_by``) albo admin, jednym
kliknięciem w formularzu „Umów spotkanie”. Spotkanie Teams powstaje w kalendarzu
**prowadzącego** (opiekuna szansy), więc to on jest organizatorem: transkrypt i mail
po spotkaniu działają jak dotąd. Uczestnicy: klient i osoba, która umawia.

Osoba klikająca nie ma prawa do cudzej skrzynki, więc zapis robi osobna rejestracja
app-only (``sales_invite_auth``) przez ``POST /users/{upn}/events``. Bez jej
poświadczeń formularz zostaje przy mailu do klienta (``booking_mail``).

Rezerwacja, ``transactionId``, oś szansy i historia są wspólne z zaproszeniem
prowadzącego (``handoff_invite``): ten sam klucz ``invite`` w bloku przekazania,
więc spotkanie ma jedno zaproszenie bez względu na to, kto je wysłał.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional
from uuid import UUID

import httpx
from fastapi import HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.staging import StagingEgressBlocked
from app.models.sales import SalesOpportunity
from app.models.user import User
from app.services.m365 import calendar as m365_calendar
from app.services.m365.app_graph_client import AppGraphClient, AppOnlyTokenUnavailable
from app.services.m365.graph_client import GraphRequestError
from app.services.m365.sales_invite_auth import (
    acquire_sales_invite_token,
    credentials_configured,
)
from app.services.sales import handoff_hosts
from app.services.sales.handoff_invite import MAX_ATTENDEES, Uncertain, Undelivered
from app.services.sales.meeting_client_mail import normalize_address, text_to_html

logger = logging.getLogger(__name__)

NOT_CONFIGURED_DETAIL = (
    "Zaproszenia Teams z NEXUSA nie są jeszcze włączone (aplikacja w Microsoft 365). "
    "Wyślij mail do klienta, a zaproszenie wyśle prowadzący."
)
NO_HOST_DETAIL = "Prowadzący nie ma adresu w NEXUSIE: zaproszenia nie da się założyć."
UNDELIVERED_DETAIL = (
    "Outlook prowadzącego nie przyjął zaproszenia. Nic nie wyszło, spróbuj ponownie."
)
NO_ACCESS_DETAIL = (
    "NEXUS nie ma dostępu do kalendarza tego prowadzącego. Nic nie wyszło: "
    "poproś administratora o dopisanie skrzynki do aplikacji zaproszeń."
)
UNCERTAIN_DETAIL = (
    "Nie wiadomo, czy zaproszenie wyszło. Poproś prowadzącego o sprawdzenie "
    "kalendarza, zanim spróbujesz ponownie."
)

# Połączenie nie powstało: Graph nie widział żądania (jak w ``handoff_invite``), także
# zapora wyjścia stagingu i brak tokenu (``sales_invite_auth`` łapie błędy MSAL).
_NEVER_SENT = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    AppOnlyTokenUnavailable,
    StagingEgressBlocked,
)


class NoAccess(Undelivered):
    """Graph odmówił dostępu do skrzynki prowadzącego (403/404): poza zakresem aplikacji."""


class BookingInviteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Adres klienta (i ewentualnie kolejne osoby po stronie klienta).
    to: list[str] = Field(min_length=1, max_length=MAX_ATTENDEES - 1)
    subject: str = Field(min_length=1, max_length=255)
    message: str = Field(min_length=1, max_length=5000)
    #: Osoba, która umawia, jako uczestnik spotkania.
    include_me: bool = True
    #: Nadawany przy otwarciu okna: drugi klik z tym samym kluczem nie wysyła drugi raz.
    request_id: UUID


def configured() -> bool:
    return credentials_configured()


async def host_upn(db: AsyncSession, opportunity: SalesOpportunity) -> Optional[str]:
    """Skrzynka prowadzącego (opiekuna szansy): w niej powstaje spotkanie.

    Opiekuna można zmienić po umówieniu na dowolne aktywne konto, więc bramka
    prowadzącego z „Umów spotkanie” (``handoff_hosts.ensure_host``, „Sprzedaż: edycja”)
    jest sprawdzana jeszcze raz: aplikacja nie zakłada spotkania w kalendarzu kogoś,
    komu nie można przekazać spotkania, nawet gdy zakres w Exchange byłby za szeroki.
    """

    if opportunity.owner_user_id is None:
        return None
    try:
        host = await handoff_hosts.ensure_host(db, opportunity.owner_user_id)
    except HTTPException:
        return None
    return normalize_address(host.email or "")


async def own_address(db: AsyncSession, user_id: int) -> Optional[str]:
    user = await db.get(User, user_id)
    return normalize_address(user.email or "") if user is not None else None


def attendee_list(to: list[str], me: Optional[str], host: str) -> list[str]:
    """Klient, potem osoba, która umawia; organizatora Outlook nie zaprasza drugi raz."""

    attendees = [address for address in to if address != host]
    if me and me != host and me not in attendees:
        attendees.append(me)
    return attendees


async def deliver(
    *,
    host: str,
    host_user_id: int,
    opportunity_id: int,
    subject: str,
    message: str,
    start: datetime,
    minutes: int,
    attendees: list[str],
) -> dict[str, Any]:
    """Spotkanie Teams w kalendarzu prowadzącego; Outlook rozsyła zaproszenia."""

    end = start + timedelta(minutes=minutes)
    payload = m365_calendar._build_event_payload(
        title=subject,
        description=text_to_html(message),
        start=start,
        end=end,
        attendee_emails=attendees,
        want_teams=True,
        transaction_id=m365_calendar.event_transaction_id(
            owner_user_id=host_user_id,
            title=subject,
            start=start,
            end=end,
            attendee_emails=attendees,
            # Ten sam co w ``handoff_invite``: zaproszenie prowadzącego i umawiającego
            # na ten sam termin to w Outlooku jedno spotkanie.
            intent_id=f"sales-handoff-{opportunity_id}-{start.isoformat()}",
        ),
    )
    try:
        async with AppGraphClient(token_provider=acquire_sales_invite_token) as gc:
            event = await gc.post(f"/users/{host}/events", json=payload)
    except Exception as exc:
        no_access = isinstance(exc, GraphRequestError) and exc.status in (403, 404)
        refused = (
            no_access
            or isinstance(exc, _NEVER_SENT)
            or (isinstance(exc, GraphRequestError) and 400 <= exc.status < 500)
        )
        logger.warning(
            "sales_booking_invite: %s (%s)",
            "no_access" if no_access else "refused" if refused else "uncertain",
            type(exc).__name__,
        )
        if no_access:
            raise NoAccess(type(exc).__name__) from exc
        if refused:
            raise Undelivered(type(exc).__name__) from exc
        raise Uncertain(type(exc).__name__) from exc
    if not isinstance(event, dict) or not event.get("id"):
        raise Uncertain("event_without_id")
    return event


def ensure_configured() -> None:
    if not configured():
        raise HTTPException(status.HTTP_409_CONFLICT, detail=NOT_CONFIGURED_DETAIL)
