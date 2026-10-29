"""„Ogłoszenia” na pulpicie każdej osoby (decyzja Artura 28.10.2026).

Propozycja Olafa: strefa, na której Head of Recruitment publikuje ważne
informacje. Artur zatwierdził sam panel; własnego komunikatora nie budujemy
(Teams niesie rozmowy z klientem, prepy i kalendarz M365).

* publikują Head of Recruitment i admin (``PUBLISH_ROLES``): tytuł, treść
  (zwykły tekst), „widoczne do” (data w kalendarzu firmy, włącznie),
  odbiorcy (wszyscy albo wybrane role), przypięcie, „ważne”;
* ogłoszenie obowiązuje, dopóki nie minął dzień „widoczne do” i nikt go nie
  zdjął (``is_live`` / ``live_clause``) — bez pętli w tle;
* „przeczytane” per osoba (``announcement_reads``); przeczytane schodzi niżej,
  nie znika do terminu; publikujący widzą „przeczytało N z M”;
* „ważne” = dzwonek ``announcement_important`` i mail obowiązkowy do
  odbiorców, raz (``notified_at``), bez autora.

Reguła: ``docs/claude/ui/ogloszenia-na-pulpicie.md``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today
from app.models.activity import Activity
from app.models.announcement import Announcement, AnnouncementRead
from app.models.notification import NotificationType
from app.models.user import User, UserRole
from app.services.announcements_schema import BODY_MAX, TITLE_MAX

logger = logging.getLogger(__name__)

PUBLISH_ROLES: tuple[UserRole, ...] = (UserRole.admin, UserRole.head_of_recruitment)
PUBLISH_DENIED = "Ogłoszenia publikuje Head of Recruitment albo administrator."

# Role do wyboru w „Odbiorcy” — bez wycofanego `user`.
AUDIENCE_ROLES: tuple[str, ...] = tuple(
    role.value for role in UserRole if role is not UserRole.user
)

TITLE_MIN = 3
# Najdalszy termin „widoczne do” — ogłoszenie to sprawa bieżąca, nie regulamin.
MAX_DAYS_AHEAD = 90
BELL_MESSAGE_MAX = 300

_HTML_TAG = re.compile(r"<\s*/?\s*[a-zA-Z][^<>]*>")

ACTION_PUBLISHED = "announcement_published"
ACTION_EDITED = "announcement_edited"
ACTION_WITHDRAWN = "announcement_withdrawn"


@dataclass(frozen=True)
class AnnouncementError(Exception):
    status: int
    detail: str


@dataclass(frozen=True)
class AnnouncementInput:
    title: str
    body: str
    visible_until: date
    audience_roles: tuple[str, ...] = ()
    pinned: bool = False
    important: bool = False


def can_publish(user: Any) -> bool:
    return bool(user is not None and user.has_any_role(*PUBLISH_ROLES))


def addressed_to(announcement: Any, user: Any) -> bool:
    roles = announcement.audience_roles or []
    return not roles or any(user.has_role(role) for role in roles)


def is_live(announcement: Any, today: Optional[date] = None) -> bool:
    today = today or business_today()
    return announcement.withdrawn_at is None and announcement.visible_until >= today


def live_clause(today: date):
    return and_(
        Announcement.withdrawn_at.is_(None), Announcement.visible_until >= today
    )


def clean(raw: AnnouncementInput, today: Optional[date] = None) -> AnnouncementInput:
    """Waliduje wejście z formularza; błąd = ``AnnouncementError`` 422."""
    today = today or business_today()
    title = re.sub(r"\s+", " ", raw.title or "").strip()
    if not TITLE_MIN <= len(title) <= TITLE_MAX:
        raise AnnouncementError(
            422, f"Tytuł ogłoszenia: od {TITLE_MIN} do {TITLE_MAX} znaków."
        )
    body = (raw.body or "").replace("\r\n", "\n").strip()
    if not body or len(body) > BODY_MAX:
        raise AnnouncementError(422, f"Treść ogłoszenia: od 1 do {BODY_MAX} znaków.")
    if _HTML_TAG.search(title) or _HTML_TAG.search(body):
        raise AnnouncementError(
            422, "Ogłoszenie to zwykły tekst — usuń znaczniki HTML (<…>)."
        )
    if raw.visible_until < today:
        raise AnnouncementError(422, "„Widoczne do” nie może być w przeszłości.")
    if raw.visible_until > today + timedelta(days=MAX_DAYS_AHEAD):
        raise AnnouncementError(
            422, f"„Widoczne do” najdalej {MAX_DAYS_AHEAD} dni od dziś."
        )
    roles = tuple(dict.fromkeys(raw.audience_roles))
    unknown = [role for role in roles if role not in AUDIENCE_ROLES]
    if unknown:
        raise AnnouncementError(422, f"Nieznana rola odbiorców: {', '.join(unknown)}.")
    return AnnouncementInput(
        title=title,
        body=body,
        visible_until=raw.visible_until,
        audience_roles=roles,
        pinned=raw.pinned,
        important=raw.important,
    )


def _details(data: AnnouncementInput) -> dict[str, Any]:
    return {
        "title": data.title,
        "visible_until": data.visible_until.isoformat(),
        "audience_roles": list(data.audience_roles),
        "pinned": data.pinned,
        "important": data.important,
    }


async def create(
    db: AsyncSession, raw: AnnouncementInput, *, actor_id: int
) -> Announcement:
    data = clean(raw)
    announcement = Announcement(
        title=data.title,
        body=data.body,
        visible_until=data.visible_until,
        audience_roles=list(data.audience_roles),
        pinned=data.pinned,
        important=data.important,
        author_id=actor_id,
    )
    db.add(announcement)
    await db.flush()
    db.add(
        Activity(
            entity_type="announcement",
            entity_id=announcement.id,
            action=ACTION_PUBLISHED,
            user_id=actor_id,
            details=_details(data),
        )
    )
    await db.flush()
    return announcement


def _require_live(announcement: Announcement) -> None:
    if announcement.withdrawn_at is not None:
        raise AnnouncementError(409, "To ogłoszenie zostało już zdjęte.")
    if not is_live(announcement):
        raise AnnouncementError(409, "Termin tego ogłoszenia minął.")


async def update(
    db: AsyncSession,
    announcement: Announcement,
    raw: AnnouncementInput,
    *,
    actor_id: int,
) -> None:
    _require_live(announcement)
    data = clean(raw)
    announcement.title = data.title
    announcement.body = data.body
    announcement.visible_until = data.visible_until
    announcement.audience_roles = list(data.audience_roles)
    announcement.pinned = data.pinned
    announcement.important = data.important
    db.add(
        Activity(
            entity_type="announcement",
            entity_id=announcement.id,
            action=ACTION_EDITED,
            user_id=actor_id,
            details=_details(data),
        )
    )
    await db.flush()


async def withdraw(
    db: AsyncSession, announcement: Announcement, *, actor_id: int
) -> None:
    """„Zdejmij” przed terminem — wiersz zostaje (ślad), panel go nie pokazuje."""
    _require_live(announcement)
    announcement.withdrawn_at = datetime.now(timezone.utc)
    announcement.withdrawn_by = actor_id
    db.add(
        Activity(
            entity_type="announcement",
            entity_id=announcement.id,
            action=ACTION_WITHDRAWN,
            user_id=actor_id,
            details={"title": announcement.title},
        )
    )
    await db.flush()


async def mark_read(db: AsyncSession, announcement: Announcement, user: Any) -> None:
    """„Przeczytane” — ponowne kliknięcie nic nie zmienia (pierwsza chwila zostaje)."""
    if not (is_live(announcement) and addressed_to(announcement, user)):
        raise AnnouncementError(404, "Nie ma takiego ogłoszenia.")
    await db.execute(
        pg_insert(AnnouncementRead)
        .values(announcement_id=announcement.id, user_id=user.id)
        .on_conflict_do_nothing(index_elements=["announcement_id", "user_id"])
    )


async def _active_users(db: AsyncSession) -> list[User]:
    return list((await db.scalars(select(User).where(User.is_active.is_(True)))).all())


def _recipients(announcement: Any, users: Iterable[User]) -> list[int]:
    return [user.id for user in users if addressed_to(announcement, user)]


async def recipient_ids(db: AsyncSession, announcement: Announcement) -> list[int]:
    """Aktywne konta, do których ogłoszenie jest skierowane."""
    return _recipients(announcement, await _active_users(db))


def _local_label(day: date) -> str:
    return day.strftime("%d.%m")


async def notify_important(
    db: AsyncSession, announcement: Announcement, *, actor_id: Optional[int]
) -> list[int]:
    """Dzwonek i mail obowiązkowy do odbiorców „ważnego” — raz na ogłoszenie.

    Savepoint na osobę: nieudane powiadomienie nie cofa publikacji.
    """
    from app.services.notification_triggers import emit  # noqa: PLC0415

    if not announcement.important or announcement.notified_at is not None:
        return []
    announcement.notified_at = datetime.now(timezone.utc)
    recipients = [
        uid for uid in await recipient_ids(db, announcement) if uid != actor_id
    ]
    body = re.sub(r"\s+", " ", announcement.body).strip()
    if len(body) > BELL_MESSAGE_MAX:
        body = body[: BELL_MESSAGE_MAX - 1].rstrip() + "…"
    message = f"{body} (widoczne do {_local_label(announcement.visible_until)})"
    sent: list[int] = []
    for user_id in recipients:
        try:
            async with db.begin_nested():
                row = await emit(
                    db,
                    user_id=user_id,
                    title=announcement.title,
                    message=message,
                    ntype=NotificationType.announcement_important,
                    related_entity_type="announcement",
                    related_entity_id=announcement.id,
                    link="/dashboard",
                )
            if row is not None:
                sent.append(user_id)
        except Exception:  # noqa: BLE001 — dzwonek nie może cofnąć ogłoszenia
            logger.exception(
                "announcements: dzwonek dla user_id=%s announcement_id=%s nie powstał",
                user_id,
                announcement.id,
            )
    return sent


def _sort_key(item: dict[str, Any]) -> tuple:
    # Nieprzeczytane nad przeczytanymi; w każdej grupie przypięte, potem najnowsze.
    return (item["read"], not item["pinned"], -item["created_at"].timestamp())


async def list_for(db: AsyncSession, viewer: Any) -> list[dict[str, Any]]:
    """Aktywne ogłoszenia na pulpit patrzącego.

    Odbiorca widzi skierowane do siebie; publikujący (HoR, admin) — wszystkie
    aktywne, z „przeczytało N z M”, żeby mogli je poprawić albo zdjąć.
    """
    today = business_today()
    rows = list(
        (await db.scalars(select(Announcement).where(live_clause(today)))).all()
    )
    publisher = can_publish(viewer)
    rows = [row for row in rows if publisher or addressed_to(row, viewer)]
    if not rows:
        return []
    ids = [row.id for row in rows]
    reads = (
        await db.execute(
            select(AnnouncementRead.announcement_id, AnnouncementRead.user_id).where(
                AnnouncementRead.announcement_id.in_(ids)
            )
        )
    ).all()
    readers: dict[int, set[int]] = {}
    for announcement_id, user_id in reads:
        readers.setdefault(announcement_id, set()).add(user_id)
    author_ids = {row.author_id for row in rows if row.author_id is not None}
    names = (
        dict(
            (
                await db.execute(
                    select(User.id, User.name).where(User.id.in_(author_ids))
                )
            )
            .tuples()
            .all()
        )
        if author_ids
        else {}
    )
    users = await _active_users(db) if publisher else []
    items: list[dict[str, Any]] = []
    for row in rows:
        item: dict[str, Any] = {
            "id": row.id,
            "title": row.title,
            "body": row.body,
            "visible_until": row.visible_until,
            "audience_roles": list(row.audience_roles or []),
            "pinned": row.pinned,
            "important": row.important,
            "author_name": names.get(row.author_id),
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "for_me": addressed_to(row, viewer),
            "read": viewer.id in readers.get(row.id, set()),
            "read_count": None,
            "recipient_count": None,
        }
        if publisher:
            recipients = set(_recipients(row, users))
            item["recipient_count"] = len(recipients)
            item["read_count"] = len(recipients & readers.get(row.id, set()))
        items.append(item)
    return sorted(items, key=_sort_key)
