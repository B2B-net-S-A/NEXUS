"""„Gdy Cię nie było”: praca, która przyszła w czasie nieobecności (16.11.2026).

Zgłoszenie z 16.11.2026: rekruterka wróciła z urlopu (9–13.11) i nie wiedziała,
że dwie rekrutacje z jej kandydatami u klienta zostały zamknięte. Zamknął je
zastępca, a reguła „autor nie dostaje dzwonka o własnym ruchu” wyrzucała wtedy
wiersz w całości. Pozostałe 29 powiadomień z jej pracy poszło do zastępcy
(``on_behalf_of_user_id``) i po powrocie nie widziała żadnego.

Decyzja Artura z 16.11.2026 (wariant A z makiet): po powrocie pulpit pokazuje
sekcję z tymi wierszami. Na górze sprawy do załatwienia (``ACTION_TYPES``,
dziś zamknięcia rekrutacji z osobami w toku), resztę zwija licznik po
kategoriach. Sprawę może oznaczyć jako załatwioną osoba albo jej zastępca —
to jeden wiersz, więc oboje widzą ten sam stan. Sekcja nie pokazuje się, póki
osoba jest zastępowana, i znika, gdy ją zamknie.

Reguła: ``docs/claude/powiadomienia/gdy-cie-nie-bylo-po-powrocie.md``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional, Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import DEFAULT_TZ
from app.models.notification import Notification, NotificationType
from app.models.user import User
from app.services.notification_categories import CATEGORY_INFO, category_for
from app.services.workforce_availability import workforce_context

logger = logging.getLogger(__name__)

#: Tyle wstecz szukamy wierszy z nieobecności — dłuższy urlop to rzadkość,
#: a stare zamknięcia i tak nie są już do załatwienia.
LOOKBACK = timedelta(days=30)

#: Wiersze, które wymagają ruchu osoby po powrocie.
ACTION_TYPES: frozenset[NotificationType] = frozenset(
    {NotificationType.job_closed_people_waiting}
)


#: Nazwy w liczniku „Pozostałe”. Kategorie dzwonka służą wyciszeniom i bywają
#: mylące w podsumowaniu (zejście z P1 jest tam „Wzmianką”); reszta z kategorii.
TYPE_LABELS: dict[NotificationType, str] = {
    NotificationType.stage_rule: "Ruchy kandydatów",
    NotificationType.stage_changed: "Ruchy kandydatów",
    NotificationType.auto_match_proposals: "Propozycje systemu",
    NotificationType.autofill_decisions_due: "Osoby od systemu do decyzji",
    NotificationType.recruiter_parked: "Zejścia z P1",
    NotificationType.request_assignment_changed: "Zmiany requestów",
    NotificationType.new_application: "Nowe aplikacje",
}


@dataclass(frozen=True)
class AwayRow:
    id: int
    notification_type: NotificationType
    title: str
    message: str
    link: Optional[str]
    created_at: datetime
    substitute_id: int
    seen_by_substitute: bool
    handled_at: Optional[datetime]
    handled_by_id: Optional[int]


@dataclass(frozen=True)
class AwayGroup:
    label: str
    count: int


@dataclass(frozen=True)
class AwaySummary:
    since: date
    until: date
    substitute_ids: tuple[int, ...]
    total: int
    actions: tuple[AwayRow, ...]
    others: tuple[AwayGroup, ...]


def summarize(rows: Sequence[AwayRow]) -> Optional[AwaySummary]:
    """Wiersze z nieobecności → podsumowanie; brak wierszy = brak sekcji.

    Sprawy do załatwienia od najnowszej, niezałatwione przed załatwionymi.
    Reszta jako licznik per kategoria dzwonka, od największej.
    """
    if not rows:
        return None
    actions = sorted(
        (row for row in rows if row.notification_type in ACTION_TYPES),
        key=lambda row: (row.handled_at is not None, -row.created_at.timestamp()),
    )
    counts: dict[str, int] = {}
    for row in rows:
        if row.notification_type in ACTION_TYPES:
            continue
        label = TYPE_LABELS.get(row.notification_type) or (
            CATEGORY_INFO[category_for(row.notification_type)].label
        )
        counts[label] = counts.get(label, 0) + 1
    others = tuple(
        AwayGroup(label, count)
        for label, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    )
    substitutes: list[int] = []
    for row in sorted(rows, key=lambda r: r.created_at):
        if row.substitute_id not in substitutes:
            substitutes.append(row.substitute_id)
    days = [_local_day(row.created_at) for row in rows]
    return AwaySummary(
        since=min(days),
        until=max(days),
        substitute_ids=tuple(substitutes),
        total=len(rows),
        actions=tuple(actions),
        others=others,
    )


def _local_day(moment: datetime) -> date:
    """Dzień w kalendarzu firmy (Europe/Warsaw), nie w UTC."""
    return moment.astimezone(ZoneInfo(DEFAULT_TZ)).date()


async def is_substituted(db: AsyncSession, user_id: int) -> bool:
    """Osobę ktoś dziś zastępuje — sekcja czeka do powrotu."""
    try:
        context = await workforce_context(db)
    except Exception:  # noqa: BLE001 — bez silnika pokazujemy sekcję
        logger.exception("while_away: workforce context failed")
        return False
    performer = context.performer(user_id)
    return performer is not None and performer != user_id


async def load_rows(db: AsyncSession, user_id: int) -> list[AwayRow]:
    floor = datetime.now(timezone.utc) - LOOKBACK
    notes = (
        await db.scalars(
            select(Notification)
            .where(
                Notification.on_behalf_of_user_id == user_id,
                Notification.away_dismissed_at.is_(None),
                Notification.created_at >= floor,
            )
            .order_by(Notification.created_at.asc(), Notification.id.asc())
        )
    ).all()
    return [
        AwayRow(
            id=note.id,
            notification_type=note.notification_type,
            title=note.title,
            message=note.message,
            link=note.link,
            created_at=note.created_at,
            substitute_id=note.user_id,
            # Cichy wiersz zastępca „widział”, bo sam wykonał ten ruch.
            seen_by_substitute=bool(note.is_read),
            handled_at=note.handled_at,
            handled_by_id=note.handled_by_user_id,
        )
        for note in notes
    ]


async def user_names(db: AsyncSession, ids: Sequence[int]) -> dict[int, str]:
    if not ids:
        return {}
    rows = await db.execute(select(User.id, User.name).where(User.id.in_(set(ids))))
    return {row.id: row.name for row in rows}


async def mark_handled(
    db: AsyncSession, notification_id: int, *, actor_id: int
) -> Optional[Notification]:
    """Załatwione: osoba, za którą przyszło, albo jej zastępca (adresat wiersza)."""
    note = await db.get(Notification, notification_id)
    if note is None or note.on_behalf_of_user_id is None:
        return None
    if actor_id not in (note.on_behalf_of_user_id, note.user_id):
        return None
    if note.handled_at is None:
        note.handled_at = datetime.now(timezone.utc)
        note.handled_by_user_id = actor_id
    return note


async def dismiss(db: AsyncSession, user_id: int) -> int:
    """Osoba zamyka podsumowanie: jej wiersze nie wracają na pulpit."""
    result = await db.execute(
        update(Notification)
        .where(
            Notification.on_behalf_of_user_id == user_id,
            Notification.away_dismissed_at.is_(None),
        )
        .values(away_dismissed_at=datetime.now(timezone.utc))
    )
    return int(result.rowcount or 0)
