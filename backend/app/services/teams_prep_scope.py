"""Kto może prowadzić prep w Teams — dzienna kontrola zakresu aplikacji (0510).

Aplikacja „NEXUS Teams Prep” zakłada prepy w kalendarzu prowadzącego, ale
Exchange wpuszcza ją tylko do skrzynek z grupy ``NEXUS-Meetings-Scope``
(App RBAC, ``docs/teams-prep-setup.md``). Grupę wypełniono ręcznie 26.09.2026
i 22.10 dziesięć osób — DL, Head of Recruitment i rekruterzy — dostawało przy
planowaniu prepu 409 „nie jest w grupie NEXUS-Meetings”, choć nikt o tym nie
wiedział. NEXUS nie może sam dopisywać do tej grupy (Graph nie zmienia grup
mail-enabled, a zapis przez Exchange app-only zwrócił 403 — decyzja Artura
22.10.2026: dopisuje admin ręcznie, NEXUS podpowiada kogo).

Raz dziennie pytamy Graph tokenem aplikacji o nagłówek kalendarza każdej
osoby, która może prowadzić prep (``GET /users/{upn}/calendar?$select=id`` —
bez wydarzeń): 200 = w zakresie, 403 = poza grupą, 404 = brak skrzynki
w M365. Inny błąd to „nie wiadomo” — nie zgłaszamy nikogo na zapas.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Awaitable, Callable, Literal, Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import NotificationType
from app.models.user import User, UserRole

logger = logging.getLogger(__name__)

Access = Literal["ok", "outside", "no_mailbox", "unknown"]

#: Role, z których okno prepu podpowiada albo pozwala wybrać prowadzącego.
ORGANIZER_ROLES: tuple[UserRole, ...] = (
    UserRole.delivery_lead,
    UserRole.recruiter,
    UserRole.head_of_recruitment,
)

SCOPE_GROUP = os.environ.get(
    "TEAMS_PREP_SCOPE_GROUP", "nexus-meetings-scope@b2bnetwork.pl"
)

#: Jeden alarm dziennie: dedup ``emit`` patrzy na (odbiorca, typ, id encji, dzień).
ENTITY_TYPE = "teams_prep_scope"
ENTITY_ID = 0


@dataclass(frozen=True)
class Person:
    user_id: int
    name: str
    email: str


def classify(status: Optional[int]) -> Access:
    """Kod odpowiedzi Graph → stan dostępu; ``None`` = odpowiedź 200."""
    if status is None:
        return "ok"
    if status == 403:
        return "outside"
    if status == 404:
        return "no_mailbox"
    return "unknown"


async def calendar_access(email: str) -> Access:
    """Czy aplikacja prepów widzi kalendarz tej osoby. Nie czyta wydarzeń."""
    from app.services.m365 import teams_prep_graph as tpg  # noqa: PLC0415
    from app.services.m365.graph_client import GraphRequestError  # noqa: PLC0415

    try:
        async with tpg._client() as gc:
            await gc.get(f"{tpg._user(email)}/calendar", params={"$select": "id"})
    except GraphRequestError as exc:
        return classify(exc.status)
    return "ok"


async def organizers(db: AsyncSession) -> list[Person]:
    values = [r.value for r in ORGANIZER_ROLES]
    rows = (
        await db.execute(
            select(User.id, User.name, User.email)
            .where(
                User.is_active.is_(True),
                User.email.is_not(None),
                or_(
                    User.role.in_(ORGANIZER_ROLES),
                    *[User.roles.contains([v]) for v in values],
                ),
            )
            .order_by(User.id)
        )
    ).all()
    return [
        Person(user_id=uid, name=name or email, email=email)
        for uid, name, email in rows
        if email and email.strip()
    ]


def alert_text(outside: list[Person], no_mailbox: list[Person]) -> tuple[str, str]:
    """Tytuł i treść dla adminów — lista osób z adresami i co zrobić."""

    def names(people: list[Person]) -> str:
        return ", ".join(f"{p.name} ({p.email})" for p in people)

    count = len(outside) + len(no_mailbox)
    title = (
        "1 osoba nie może prowadzić prepów w Teams"
        if count == 1
        else f"{count} osób nie może prowadzić prepów w Teams"
    )
    parts: list[str] = []
    if outside:
        parts.append(
            f"Poza grupą {SCOPE_GROUP}: {names(outside)}. Dopisz je w Exchange "
            f"(Add-DistributionGroupMember -Identity {SCOPE_GROUP} -Member <adres>) — "
            "polityki Teams przychodzą z grupy, zaczyna działać po ok. 30 min."
        )
    if no_mailbox:
        parts.append(
            f"Bez skrzynki w Microsoft 365: {names(no_mailbox)}. "
            "Sprawdź adres w Ustawienia → Osoby i role albo wyłącz konto."
        )
    parts.append(
        "Do tego czasu przy planowaniu prepu z taką osobą jako prowadzącym "
        "Microsoft odmówi założenia spotkania."
    )
    return title[:255], " ".join(parts)


async def _admin_ids(db: AsyncSession) -> list[int]:
    return list(
        (
            await db.scalars(
                select(User.id).where(
                    User.is_active.is_(True),
                    or_(User.role == UserRole.admin, User.roles.contains(["admin"])),
                )
            )
        ).all()
    )


async def scan_once(
    db: AsyncSession,
    *,
    probe: Callable[[str], Awaitable[Access]] = calendar_access,
) -> int:
    """Jeden przebieg: sprawdza osoby, wysyła alarm, commit. Zwraca liczbę wpisów."""
    from app.services import prep_meetings  # noqa: PLC0415 — cykl importów
    from app.services.notification_triggers import emit  # noqa: PLC0415

    if not prep_meetings.app_only_ready():
        return 0
    outside: list[Person] = []
    no_mailbox: list[Person] = []
    unknown = 0
    for person in await organizers(db):
        access = await probe(person.email)
        if access == "outside":
            outside.append(person)
        elif access == "no_mailbox":
            no_mailbox.append(person)
        elif access == "unknown":
            unknown += 1
    logger.info(
        "teams_prep_scope: outside=%s no_mailbox=%s unknown=%s",
        [p.user_id for p in outside],
        [p.user_id for p in no_mailbox],
        unknown,
    )
    if not outside and not no_mailbox:
        return 0
    title, message = alert_text(outside, no_mailbox)
    sent = 0
    for admin_id in await _admin_ids(db):
        created = await emit(
            db,
            user_id=admin_id,
            title=title,
            message=message,
            ntype=NotificationType.teams_prep_scope_missing,
            related_entity_type=ENTITY_TYPE,
            related_entity_id=ENTITY_ID,
        )
        sent += int(created is not None)
    await db.commit()
    return sent
