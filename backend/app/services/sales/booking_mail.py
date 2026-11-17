"""Mail do klienta po „Umów spotkanie” z kolejki dzwonienia (decyzja Artura 17.11.2026).

Prośba osób dzwoniących: po kliknięciu „Umów spotkanie” mail wychodzi ze skrzynki
Outlook osoby, która umówiła spotkanie, do klienta, z kopią do prowadzącego. Wysyła
**osoba, która umówiła** (albo admin), **ze swojej skrzynki i po swoim kliknięciu**:
to nie zmienia zasady z 10.11, że nic nie wychodzi z cudzej skrzynki. Spotkanie Teams
dalej wysyła prowadzący (``handoff_invite``), żeby to on był organizatorem.

Skrzynka handlowca bez dostępu do kandydatów przechodzi tu z ``sales_ok=True`` (piąte
dozwolone miejsce, ``outlook-handlowcow-w-sprzedazy.md``), dlatego ta ścieżka odrzuca
adresy z bazy kandydatów i osoby ze sprzeciwem, zanim zawoła Graph.

Jeden mail na przekazanie: rezerwacja leży w bloku przekazania (``booking_mail``)
i jest zapisana przed wywołaniem Graph. Odmowa Graph zwalnia ją od razu (nic nie
wyszło), niepewny wynik trzyma ją ``RETRY_AFTER``, bo mail mógł wyjść.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional
from uuid import UUID

from fastapi import HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sales import SalesContact, SalesOpportunity
from app.models.user import User
from app.services.sales import handoff, history
from app.services.sales.handoff_state import moment, store, user_id_of
from app.services.sales.meeting_client_mail import (
    mailbox_state,
    normalize_address,
    record_email,
)
from app.services.sales_schema import OpportunityEventKind

MAIL_KEY = "booking_mail"
MAX_RECIPIENTS = 5
#: Tyle trwa blokada po wysyłce, której wynik nie jest znany.
RETRY_AFTER = timedelta(minutes=10)
HISTORY_VALUE = "booking_mail"

SENDER_DETAIL = (
    "Mail po umówieniu wysyła osoba, która umówiła spotkanie, ze swojej skrzynki."
)
SENT_DETAIL = "Mail o tym spotkaniu już wyszedł. Kolejny wyślij z Outlooka."
IN_FLIGHT_DETAIL = (
    "Ten mail jest już wysyłany albo wyszedł. Sprawdź Wysłane w Outlooku."
)
OBJECTION_DETAIL = (
    "Wśród adresów jest osoba, która nie zgadza się na kontakt. Usuń ten adres."
)
NO_MAILBOX_DETAIL = "Podłącz skrzynkę Outlook w Sprzedaży, żeby wysłać mail."
NO_SCOPE_DETAIL = "Połącz skrzynkę Outlook ponownie: brakuje zgody na wysyłkę."
UNDELIVERED_DETAIL = "Outlook nie przyjął maila. Nic nie wyszło, spróbuj ponownie."
UNCERTAIN_DETAIL = (
    "Nie wiadomo, czy mail wyszedł. Sprawdź Wysłane w Outlooku, zanim spróbujesz "
    "ponownie."
)

__all__ = ["mailbox_state"]


class BookingMailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to: list[str] = Field(min_length=1, max_length=MAX_RECIPIENTS)
    subject: str = Field(min_length=1, max_length=255)
    message: str = Field(min_length=1, max_length=5000)
    #: Kopia do prowadzącego spotkania (opiekuna szansy).
    cc_host: bool = True
    #: Nadawany przy otwarciu okna: drugi klik z tym samym kluczem nie wysyła drugi raz.
    request_id: UUID


def ensure_sender(opportunity: SalesOpportunity, user_id: int, *, admin: bool) -> None:
    """Osoba, która umówiła, albo admin: mail wychodzi ze skrzynki osoby, która klika."""

    data = handoff.block(opportunity)
    if data is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=handoff.NO_HANDOFF_DETAIL)
    if admin or user_id_of(data.get("booked_by")) == user_id:
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN, detail=SENDER_DETAIL)


async def objected_addresses(db: AsyncSession, addresses: list[str]) -> set[str]:
    """Adresy kontaktów sprzedaży ze sprzeciwem („Nie kontaktować”)."""

    if not addresses:
        return set()
    found = await db.scalars(
        select(func.lower(func.btrim(SalesContact.email))).where(
            func.lower(func.btrim(SalesContact.email)).in_(addresses),
            SalesContact.do_not_contact_at.is_not(None),
        )
    )
    return set(found.all())


async def host_address(
    db: AsyncSession, opportunity: SalesOpportunity, sender_id: int
) -> Optional[str]:
    """Adres prowadzącego do kopii; bez kopii, gdy prowadzący sam wysyła."""

    if opportunity.owner_user_id is None or opportunity.owner_user_id == sender_id:
        return None
    host = await db.get(User, opportunity.owner_user_id)
    return normalize_address(host.email or "") if host is not None else None


def reserve(opportunity: SalesOpportunity, request_id: UUID, *, now: datetime) -> None:
    """Sprawdź przekazanie i zapisz klucz; wywołujący robi commit przed Graph."""

    data = handoff.pending(opportunity)
    sent = data.get(MAIL_KEY) if isinstance(data.get(MAIL_KEY), dict) else {}
    if sent.get("at"):
        raise HTTPException(status.HTTP_409_CONFLICT, detail=SENT_DETAIL)
    reserved_at = moment(sent.get("reserved_at"))
    if reserved_at is not None and now - reserved_at < RETRY_AFTER:
        # Każdy klucz, nie tylko ten sam: drugie okno miałoby własny.
        raise HTTPException(status.HTTP_409_CONFLICT, detail=IN_FLIGHT_DETAIL)
    data[MAIL_KEY] = {"request_id": str(request_id), "reserved_at": now.isoformat()}
    store(opportunity, data)


async def release(db: AsyncSession, opportunity_id: int, request_id: UUID) -> None:
    """Graph odmówił albo żądanie do niego nie doszło: klucz znika."""

    opportunity = await handoff.lock(db, opportunity_id)
    data = handoff.block(opportunity) or {}
    sent = data.get(MAIL_KEY)
    if isinstance(sent, dict) and sent.get("request_id") == str(request_id):
        data.pop(MAIL_KEY, None)
        store(opportunity, data)


async def record_sent(
    db: AsyncSession,
    opportunity: SalesOpportunity,
    draft: dict[str, Any],
    *,
    request_id: UUID,
    subject: str,
    body: str,
    recipients: int,
    user_id: int,
    now: datetime,
) -> None:
    """Mail na osi szansy i firmy, znacznik w bloku i krok w historii bez adresów."""

    await record_email(
        db,
        company_id=opportunity.company_id,
        opportunity_id=opportunity.id,
        contact_id=opportunity.primary_contact_id,
        user_id=user_id,
        subject=subject,
        body=body,
        # Ten sam klucz co kopia z Wysłanych: synchronizacja skleja się z tym wierszem.
        internet_message_id=draft.get("internetMessageId"),
        now=now,
    )
    data = handoff.block(opportunity) or {}
    data[MAIL_KEY] = {
        "request_id": str(request_id),
        "at": now.isoformat(),
        "by": user_id,
        "recipients": recipients,
    }
    store(opportunity, data)
    history.record(
        db,
        opportunity_id=opportunity.id,
        user_id=user_id,
        kind=OpportunityEventKind.updated,
        field=handoff.HISTORY_FIELD,
        new_value=HISTORY_VALUE,
    )
