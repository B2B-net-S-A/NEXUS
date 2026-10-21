"""Alarm o masowym przeglądaniu CV kandydatów — bez blokady (0504, 22.10.2026).

12.10.2026 dziewięć nowych kont (kursanci Akademii Sourcera, rola Rekruter
nadana automatycznie przy pierwszym logowaniu) otworzyło w trzy godziny pliki
181 kandydatów, 41 plików zapisało na dysk — i nikt się o tym nie dowiedział.
Decyzja Artura 22.10.2026: alarm, bez wstrzymywania pracy, do adminów i Head
of Recruitment (dzwonek + mail od razu, rodzaj ``data_access_alert``).

Skąd liczby. Każda droga do pliku kandydata zapisuje już zdarzenie w
``activities`` (``services/candidate_audit.py``): podgląd i zapis na dysk
(``document_downloaded``), link do pliku (``document_url_issued``), pobranie
CV (``cv_downloaded``), paczka ZIP (``bulk_cv_downloaded``) i eksport
(``export_requested``). Skaner co kilka minut liczy je na osobę, więc nie
dotyka ścieżki pobierania. Zdarzenia API integracji nie mają osoby
(``user_id`` puste) — tu ich nie liczymy.

Progi z ruchu produkcji (30 dni do 22.10.2026, rekruterzy): 99. percentyl
33 różnych kandydatów w godzinę, maksimum 61; na dysk najwyżej 20 plików
dziennie. Juniorzy 12.10 pojedynczo nie przekroczyli tych liczb (najwięcej
55 kandydatów dziennie) — wyróżniało ich to, że były to NOWE konta i że
zaczęło ich naraz dziewięć. Stąd niższe progi dla konta młodszego niż 14 dni
i osobny alarm „kilka nowych kont naraz”.

Jeden alarm dziennie na osobę i odbiorcę (dzienny dedup ``emit`` po
``related_entity=("user", id)``), alarm „nowe konta naraz” raz dziennie.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import Integer, Select, and_, case, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import DEFAULT_TZ
from app.models.activity import Activity
from app.models.notification import NotificationType
from app.models.user import User
from app.services import candidate_audit

logger = logging.getLogger(__name__)

HOUR_CANDIDATES = int(os.environ.get("DATA_ACCESS_ALERT_HOUR_CANDIDATES", "40"))
DAY_DISK_FILES = int(os.environ.get("DATA_ACCESS_ALERT_DAY_DISK_FILES", "25"))
DAY_EXPORT_ROWS = int(os.environ.get("DATA_ACCESS_ALERT_DAY_EXPORT_ROWS", "200"))
NEW_ACCOUNT_DAYS = int(os.environ.get("DATA_ACCESS_ALERT_NEW_ACCOUNT_DAYS", "14"))
NEW_ACCOUNTS_BURST = int(os.environ.get("DATA_ACCESS_ALERT_NEW_ACCOUNTS_BURST", "3"))

#: Zdarzenia, w których ktoś otworzył albo dostał plik konkretnego kandydata.
FILE_ACTIONS: tuple[str, ...] = (
    candidate_audit.DOCUMENT_DOWNLOADED,
    candidate_audit.DOCUMENT_URL_ISSUED,
    candidate_audit.CV_DOWNLOADED,
)
WATCHED_ACTIONS: tuple[str, ...] = (
    *FILE_ACTIONS,
    candidate_audit.BULK_CV_DOWNLOADED,
    candidate_audit.EXPORT_REQUESTED,
)

BURST_ENTITY = "data_access_burst"
LINK = "/settings?tab=people"


@dataclass(frozen=True)
class Usage:
    """Ruch jednej osoby: ostatnia godzina i dzień w kalendarzu firmy."""

    user_id: int
    name: str
    account_created_at: Optional[datetime]
    candidates_last_hour: int = 0
    candidates_today: int = 0
    disk_files_today: int = 0
    export_rows_today: int = 0


def is_new_account(usage: Usage, now: datetime) -> bool:
    created = usage.account_created_at
    return created is not None and now - created < timedelta(days=NEW_ACCOUNT_DAYS)


def reasons(usage: Usage, *, new_account: bool) -> list[str]:
    """Przekroczone progi po polsku; pusta lista = nic do zgłoszenia.

    Konto młodsze niż ``NEW_ACCOUNT_DAYS`` ma progi o połowę niższe.
    """

    divisor = 2 if new_account else 1
    hour = HOUR_CANDIDATES // divisor
    disk = DAY_DISK_FILES // divisor
    export = DAY_EXPORT_ROWS // divisor
    out: list[str] = []
    if usage.candidates_last_hour > hour:
        out.append(
            f"pliki {usage.candidates_last_hour} kandydatów w ostatniej godzinie "
            f"(próg {hour})"
        )
    if usage.disk_files_today > disk:
        out.append(
            f"{usage.disk_files_today} plików zapisanych na dysk dziś (próg {disk})"
        )
    if usage.export_rows_today > export:
        out.append(f"eksport {usage.export_rows_today} osób dziś (próg {export})")
    return out


def alert_text(
    usage: Usage, found: list[str], *, new_account: bool, now: datetime
) -> tuple[str, str]:
    """Tytuł i treść alarmu. Bez nazwisk kandydatów — wiadomość idzie mailem."""

    title = f"{usage.name}: masowe przeglądanie CV kandydatów"
    since = ""
    if new_account and usage.account_created_at is not None:
        days = (now - usage.account_created_at).days
        since = (
            f" Konto założone {usage.account_created_at.astimezone(ZoneInfo(DEFAULT_TZ)):%d.%m.%Y}"
            f" ({days} dni temu) — dla nowych kont progi są o połowę niższe."
        )
    message = (
        f"{'; '.join(found).capitalize()}. Dziś łącznie: pliki "
        f"{usage.candidates_today} kandydatów, {usage.disk_files_today} zapisanych "
        f"na dysk.{since} NEXUS niczego nie zablokował. Jeśli to nie jest zwykła "
        "praca tej osoby, wyłącz jej konto w Ustawienia → Osoby i role."
    )
    return title[:255], message


def burst_text(new_accounts: list[Usage]) -> tuple[str, str]:
    names = ", ".join(u.name for u in new_accounts[:10])
    more = f" i {len(new_accounts) - 10} innych" if len(new_accounts) > 10 else ""
    title = f"{len(new_accounts)} nowe konta otwierają CV kandydatów"
    message = (
        f"W ostatniej godzinie pliki kandydatów otworzyły konta założone w ciągu "
        f"{NEW_ACCOUNT_DAYS} dni: {names}{more}. Sprawdź, czy te osoby powinny mieć "
        "dostęp do kandydatów (Ustawienia → Osoby i role). NEXUS niczego nie zablokował."
    )
    return title[:255], message


def usage_query(now: datetime) -> Select:
    """Ruch osób od północy w kalendarzu firmy (i z ostatniej godziny) do ``now``."""

    day_start = now.astimezone(ZoneInfo(DEFAULT_TZ)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    since = min(day_start.astimezone(timezone.utc), now - timedelta(hours=1))
    hour_ago = now - timedelta(hours=1)
    details = Activity.details
    is_file = Activity.action.in_(FILE_ACTIONS)
    is_today = Activity.created_at >= day_start
    to_disk = or_(
        and_(
            Activity.action.in_(
                (
                    candidate_audit.DOCUMENT_DOWNLOADED,
                    candidate_audit.DOCUMENT_URL_ISSUED,
                )
            ),
            details["disposition"].astext == "attachment",
        ),
        Activity.action == candidate_audit.CV_DOWNLOADED,
    )
    zip_files = func.coalesce(cast(details["included_count"].astext, Integer), 0)
    export_rows = func.coalesce(
        cast(details["row_count"].astext, Integer),
        cast(details["selected_count"].astext, Integer),
        0,
    )
    return (
        select(
            Activity.user_id,
            User.name,
            User.created_at,
            func.count(func.distinct(Activity.entity_id)).filter(
                is_file, Activity.created_at >= hour_ago, Activity.entity_id > 0
            ),
            func.count(func.distinct(Activity.entity_id)).filter(
                is_file, is_today, Activity.entity_id > 0
            ),
            func.coalesce(
                func.sum(
                    case(
                        (and_(to_disk, is_today), 1),
                        (
                            and_(
                                Activity.action == candidate_audit.BULK_CV_DOWNLOADED,
                                is_today,
                            ),
                            zip_files,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (
                            and_(
                                Activity.action == candidate_audit.EXPORT_REQUESTED,
                                is_today,
                            ),
                            export_rows,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
        )
        .join(User, User.id == Activity.user_id)
        .where(
            Activity.user_id.is_not(None),
            Activity.created_at >= since,
            Activity.created_at <= now,
            Activity.entity_type == "candidate",
            Activity.action.in_(WATCHED_ACTIONS),
        )
        .group_by(Activity.user_id, User.name, User.created_at)
    )


async def collect(db: AsyncSession, now: datetime) -> list[Usage]:
    rows = (await db.execute(usage_query(now))).all()
    return [
        Usage(
            user_id=user_id,
            name=name or f"Konto {user_id}",
            account_created_at=created_at,
            candidates_last_hour=int(hour or 0),
            candidates_today=int(today or 0),
            disk_files_today=int(disk or 0),
            export_rows_today=int(export or 0),
        )
        for user_id, name, created_at, hour, today, disk, export in rows
    ]


async def _recipients(db: AsyncSession) -> list[int]:
    return list(
        (
            await db.scalars(
                select(User.id).where(
                    User.is_active.is_(True),
                    or_(
                        User.roles.contains(["admin"]),
                        User.roles.contains(["head_of_recruitment"]),
                    ),
                )
            )
        ).all()
    )


async def _notify(
    db: AsyncSession,
    recipients: list[int],
    *,
    title: str,
    message: str,
    entity_type: str,
    entity_id: int,
) -> int:
    from app.services.notification_triggers import emit

    sent = 0
    for user_id in recipients:
        created = await emit(
            db,
            user_id=user_id,
            title=title,
            message=message,
            ntype=NotificationType.candidate_data_access_alert,
            related_entity_type=entity_type,
            related_entity_id=entity_id,
            link=LINK,
        )
        sent += int(created is not None)
    return sent


async def scan_once(db: AsyncSession, now: Optional[datetime] = None) -> int:
    """Jeden przebieg: liczy ruch, wysyła alarmy, commit. Zwraca liczbę wpisów."""

    now = now or datetime.now(timezone.utc)
    usages = await collect(db, now)
    flagged: list[tuple[Usage, list[str], bool]] = []
    for usage in usages:
        new_account = is_new_account(usage, now)
        found = reasons(usage, new_account=new_account)
        if found:
            flagged.append((usage, found, new_account))
    new_active = [
        u for u in usages if u.candidates_last_hour > 0 and is_new_account(u, now)
    ]
    burst = len(new_active) >= NEW_ACCOUNTS_BURST
    if not flagged and not burst:
        return 0
    recipients = await _recipients(db)
    sent = 0
    for usage, found, new_account in flagged:
        title, message = alert_text(usage, found, new_account=new_account, now=now)
        logger.warning(
            "data_access_alert: user_id=%s hour=%s today=%s disk=%s export=%s",
            usage.user_id,
            usage.candidates_last_hour,
            usage.candidates_today,
            usage.disk_files_today,
            usage.export_rows_today,
        )
        sent += await _notify(
            db,
            recipients,
            title=title,
            message=message,
            entity_type="user",
            entity_id=usage.user_id,
        )
    if burst:
        logger.warning(
            "data_access_alert: %s new accounts opening CVs", len(new_active)
        )
        title, message = burst_text(new_active)
        sent += await _notify(
            db,
            recipients,
            title=title,
            message=message,
            entity_type=BURST_ENTITY,
            entity_id=1,
        )
    await db.commit()
    return sent
