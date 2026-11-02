"""Skrzynki poza zakresem aplikacji „NEXUS Kadry” — dzienny alarm dla adminów (0632).

Exchange wpuszcza aplikację tylko do skrzynek z grupy ``SCOPE_GROUP`` (RBAC for
Applications), a grupę prowadzi się ręcznie. Na produkcji 02.11.2026 wszystkie
konta założone 18–29.10 dostawały 403 i nikt nie dostał sygnału: osoba poza
grupą wychodzi na urlop bez autoodpowiedzi, wydarzenia i kopii poczty do
zastępcy. NEXUS nie może sam dopisywać do grup (decyzja Artura 22.10.2026 przy
grupie Teams), więc podpowiada kogo.

Graph nie jest pytany drugi raz: uzgadnianie o 7:00 czyta każdą skrzynkę
i zapisuje ``last_error``, a alarm czyta wiersze zaraz po przebiegu
(``hr_loops.hr_m365_reconcile_job``). Nieudany przebieg albo alarm wraca
następnego dnia razem z kolejnym przebiegiem.

Osoba, która ma zostać poza grupą (decyzja Artura 02.11.2026: Zarząd), dostaje
znacznik ``scope_exempt`` w ``hr_m365_mailbox_state.state``: przycisk „Zostaw
poza grupą” w karcie Microsoft 365. Zostaje na liście „Skrzynki z błędem”
z dopiskiem, ale znika z alarmu.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Any, Optional, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_leave import HrM365MailboxState
from app.models.hr_profile import EmployeeProfile
from app.models.notification import NotificationType
from app.models.user import User
from app.services.hr.m365.executor import current_mode, mailbox_address
from app.services.hr.m365.ops import MailboxError
from app.services.hr.notify import notify_each
from app.services.hr.recipients import admin_ids
from app.services.hr_foundation_schema import EmploymentStatus

logger = logging.getLogger(__name__)

SCOPE_GROUP = os.environ.get(
    "HR_M365_SCOPE_GROUP", "nexus-kadry-skrzynki@b2bnetwork.pl"
)

#: Etykieta 403 w ``last_error`` — ta sama, którą zapisuje odczyt skrzynki.
FORBIDDEN = MailboxError(403).label
EXEMPT_KEY = "scope_exempt"

#: Zakładka „Urlopy i M365”, w której leży karta z listą skrzynek.
CARD_LINK = "/settings/hr?zakladka=urlopy"

#: Jeden alarm dziennie: dedup ``emit`` patrzy na (odbiorca, typ, id encji, dzień).
ENTITY_TYPE = "hr_m365_scope"
ENTITY_ID = 0


class Named(Protocol):
    name: str
    address: str


@dataclass(frozen=True)
class Person:
    user_id: int
    name: str
    address: str


def enabled() -> bool:
    return (
        os.environ.get("HR_M365_SCOPE_ALERTS_ENABLED", "true").strip().lower()
        != "false"
    )


def is_exempt(state: Optional[dict[str, Any]]) -> bool:
    return bool((state or {}).get(EXEMPT_KEY))


def set_exempt(row: HrM365MailboxState, *, exempt: bool) -> None:
    """Nowy słownik, bo przypisanie w miejscu nie zapisałoby JSONB."""

    state = dict(row.state or {})
    if exempt:
        state[EXEMPT_KEY] = True
    else:
        state.pop(EXEMPT_KEY, None)
    row.state = state


async def outside_scope(
    db: AsyncSession, user_ids: Optional[Collection[int]] = None
) -> list[Person]:
    """Aktywne osoby z kartoteką i odczytem 403, bez świadomych wyjątków."""

    query = (
        select(User, HrM365MailboxState.state)
        .join(HrM365MailboxState, HrM365MailboxState.user_id == User.id)
        .join(EmployeeProfile, EmployeeProfile.user_id == User.id)
        .where(
            HrM365MailboxState.last_error == FORBIDDEN,
            User.is_active.is_(True),
            EmployeeProfile.employment_status != EmploymentStatus.exited,
        )
        .order_by(User.id)
    )
    if user_ids is not None:
        query = query.where(User.id.in_(list(user_ids)))
    people = []
    for user, state in (await db.execute(query)).all():
        address = mailbox_address(user)
        if address and not is_exempt(state):
            people.append(Person(user.id, user.name or address, address))
    return people


def alert_text(people: Sequence[Named]) -> tuple[str, str]:
    """Tytuł i treść dla adminów — kogo dopisać i jakim poleceniem."""

    count = len(people)
    title = (
        "NEXUS nie widzi skrzynki 1 osoby"
        if count == 1
        else f"NEXUS nie widzi skrzynek {count} osób"
    )
    names = ", ".join(f"{p.name} ({p.address})" for p in people)
    message = (
        f"Poza grupą {SCOPE_GROUP}: {names}. Dopóki tam nie trafią, ich urlop "
        "przejdzie bez autoodpowiedzi, wydarzenia w kalendarzu i kopii poczty do "
        "zastępcy. W Exchange Online: "
        f"Add-DistributionGroupMember -Identity {SCOPE_GROUP} -Member <adres>. "
        "Po kilkunastu minutach sprawdź: Test-ServicePrincipalAuthorization "
        "-Identity <AppId NEXUS Kadry> -Resource <adres>, ma być InScope = True. "
        "Przy InScope = True i dalszym 403 przyczyna jest inna: nie dodawaj "
        "uprawnień w Entra, bo działałyby na całą firmę. Osoba, która ma zostać "
        "poza grupą: „Zostaw poza grupą” w Ustawienia → Kadry → Microsoft 365."
    )
    return title, message


async def scan_once(
    db: AsyncSession,
    *,
    mode: Optional[str] = None,
    user_ids: Optional[Collection[int]] = None,
) -> int:
    """Alarm po przebiegu uzgadniania; zwraca liczbę nowych powiadomień.

    ``user_ids`` zawęża listę osób (testy). Poza trybem ``live`` uzgadnianie nie
    zapisuje ``last_error``, więc wiersze mówiłyby o przeszłości.
    """

    if not enabled() or (mode or current_mode()) != "live":
        return 0
    people = await outside_scope(db, user_ids)
    if not people:
        return 0
    title, message = alert_text(people)
    sent = await notify_each(
        db,
        await admin_ids(db),
        title=title,
        message=message,
        ntype=NotificationType.hr_m365_scope_missing,
        link=CARD_LINK,
        related_entity_type=ENTITY_TYPE,
        related_entity_id=ENTITY_ID,
        log_tag="hr_m365_scope",
    )
    await db.commit()
    logger.info("hr_m365_scope: outside=%s sent=%s", [p.user_id for p in people], sent)
    return sent
