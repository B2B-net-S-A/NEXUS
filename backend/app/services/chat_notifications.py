"""Okienko „Czaty” w górnym pasku — powiadomienia czatów pogrupowane w rozmowy.

Powiadomienie czatu (rekrutacji i kandydata) to wiersz ``notifications`` typu
``job_chat_message`` albo ``job_chat_mention``; rozmowę rozpoznajemy po linku
(``/jobs/{id}?tab=chat&msg={id}``, ``/candidates/{id}?tab=chat&msg={id}``) —
ten sam klucz wątku co ``chat_email_fallback._newer_in_same_thread``.
Do 09.10.2026 te wiersze stały w dzwonku razem ze wszystkim innym, po jednym
na wiadomość i bez nazwy rekrutacji albo kandydata.

Od 16.10.2026 okienko nazywa się „Wiadomości” i — na życzenie
(``include_notes``) — pokazuje też wzmianki i odpowiedzi w notatkach. Wątek
notatki to jej link (odpowiedź niesie link notatki nadrzędnej, więc trafia do
tego samego wątku); rodzaj ``note``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Iterable, Literal, Optional

from sqlalchemy import distinct, func, literal_column, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.candidate_chat import CandidateChatMessage
from app.models.client import Client
from app.models.job import Job
from app.models.job_chat import JobChatMessage
from app.models.notification import Notification, NotificationType
from app.models.user import User
from app.services.job_working_title import job_display_title_expr
from app.services.mention_dispatch import CHAT_NOTIFICATION_TYPES
from app.services.notification_access import notification_visibility_predicate
from app.services.notification_topics import NOTE_NOTIFICATION_TYPES

logger = logging.getLogger(__name__)

ChatKind = Literal["job", "candidate", "note"]

# Okienko pokazuje rozmowy z ostatnich 30 dni — starsze nieprzeczytane wiersze
# (przed 09.10.2026 nikt ich nie gasił) nie zapełniają listy ani licznika.
CHAT_WINDOW_DAYS = 30

JOB_NOTIFY_EVENT = "chat:notify"
CANDIDATE_NOTIFY_EVENT = "candidate-chat:notify"

_MSG_MARK = "&msg="
_THREAD_RE = re.compile(r"^/(jobs|candidates)/(\d{1,9})\?tab=chat$")
_MSG_RE = re.compile(r"&msg=(\d{1,18})$")
_KIND_BY_PATH: dict[str, ChatKind] = {"jobs": "job", "candidates": "candidate"}
_PATH_BY_KIND: dict[str, str] = {"job": "jobs", "candidate": "candidates"}
_ENTITY_TYPE_BY_KIND: dict[str, str] = {
    "job": "job_chat_message",
    "candidate": "candidate_chat_message",
}
# Link notatki (`mention_dispatch.build_note_deep_link`): kandydat, rekrutacja
# albo kontrakt; notatka bez kontekstu prowadzi na `/?orphan_note=`.
_NOTE_CONTEXT_RE = re.compile(r"^/(candidates|jobs|contracts)/(\d{1,9})(?:[/?#]|$)")


@dataclass(frozen=True)
class ChatThread:
    kind: ChatKind
    entity_id: int
    title: str
    subtitle: Optional[str]
    unread_count: int
    has_mention: bool
    last_author_name: Optional[str]
    last_message: str
    last_at: Optional[datetime]
    link: str


def thread_prefix(kind: str, entity_id: int) -> str:
    """Początek linku każdego powiadomienia jednej rozmowy."""
    return f"/{_PATH_BY_KIND[kind]}/{entity_id}?tab=chat{_MSG_MARK}"


def _parse_thread(thread: str) -> Optional[tuple[ChatKind, int]]:
    match = _THREAD_RE.match(thread or "")
    if match is None:
        return None
    return _KIND_BY_PATH[match.group(1)], int(match.group(2))


def _message_id(link: Optional[str]) -> Optional[int]:
    match = _MSG_RE.search(link or "")
    return int(match.group(1)) if match else None


def _own_chat_rows(user: User) -> list:
    since = datetime.now(timezone.utc) - timedelta(days=CHAT_WINDOW_DAYS)
    return [
        Notification.user_id == user.id,
        Notification.notification_type.in_(CHAT_NOTIFICATION_TYPES),
        Notification.link.is_not(None),
        Notification.created_at >= since,
        notification_visibility_predicate(user),
    ]


async def job_names(
    db: AsyncSession, ids: Iterable[int]
) -> dict[int, tuple[str, Optional[str]]]:
    """Tytuł do wyświetlenia i klient rekrutacji (też dla okienka „Rekrutacje”)."""
    wanted = sorted(set(ids))
    if not wanted:
        return {}
    rows = await db.execute(
        select(Job.id, job_display_title_expr(), Client.name)
        .outerjoin(Client, Client.id == Job.client_id)
        .where(Job.id.in_(wanted))
    )
    return {row[0]: (row[1] or "", row[2]) for row in rows}


async def _candidate_names(db: AsyncSession, ids: Iterable[int]) -> dict[int, str]:
    wanted = sorted(set(ids))
    if not wanted:
        return {}
    rows = await db.execute(
        select(Candidate.id, Candidate.name, Candidate.lastname).where(
            Candidate.id.in_(wanted)
        )
    )
    return {row[0]: f"{row[1] or ''} {row[2] or ''}".strip() for row in rows}


async def _author_names(
    db: AsyncSession, model: Any, message_ids: Iterable[int]
) -> dict[int, str]:
    wanted = sorted(set(message_ids))
    if not wanted:
        return {}
    rows = await db.execute(
        select(model.id, User.name)
        .join(User, User.id == model.author_id)
        .where(model.id.in_(wanted))
    )
    return {row[0]: row[1] for row in rows}


async def list_threads(
    db: AsyncSession, user: User, *, limit: int, include_notes: bool = False
) -> tuple[list[ChatThread], int]:
    """Rozmowy użytkownika (nieprzeczytane najpierw) i liczba tych z nowymi.

    ``include_notes``: okienko „Wiadomości” (16.10.2026) — także wątki
    wzmianek i odpowiedzi w notatkach, wymieszane z czatami po świeżości.
    """
    threads, unread = await _list_chat_threads(db, user, limit=limit)
    if not include_notes:
        return threads, unread
    notes, unread_notes = await _list_note_threads(db, user, limit=limit)
    merged = sorted(
        (*threads, *notes),
        key=lambda t: (
            t.unread_count > 0,
            t.last_at or datetime.min.replace(tzinfo=timezone.utc),
        ),
        reverse=True,
    )
    return merged[:limit], unread + unread_notes


async def _list_chat_threads(
    db: AsyncSession, user: User, *, limit: int
) -> tuple[list[ChatThread], int]:
    base = _own_chat_rows(user)
    # Stałe jako literały SQL, nie parametry: ``split_part(link, $1, 1)`` w SELECT
    # i ``split_part(link, $2, 1)`` w GROUP BY to dla Postgresa dwa różne wyrażenia.
    thread = func.split_part(
        Notification.link, literal_column("'&msg='"), literal_column("1")
    )
    unread = Notification.is_read.is_(False)
    # Oznaczona osoba z zespołu ma dwa wiersze o tej samej wiadomości
    # (wiadomość i wzmianka) — liczymy wiadomości, nie wiersze.
    unread_messages = func.count(distinct(Notification.link)).filter(unread)
    latest_id = func.max(Notification.id)
    rows = (
        await db.execute(
            select(
                thread.label("thread"),
                unread_messages.label("unread_count"),
                func.count()
                .filter(
                    unread,
                    Notification.notification_type == NotificationType.job_chat_mention,
                )
                .label("unread_mentions"),
                latest_id.label("latest_id"),
                func.min(Notification.id).filter(unread).label("first_unread_id"),
            )
            .where(*base)
            .group_by(thread)
            .order_by((unread_messages > 0).desc(), latest_id.desc())
            .limit(limit)
        )
    ).all()
    unread_threads = (
        await db.scalar(select(func.count(distinct(thread))).where(*base, unread)) or 0
    )
    if not rows:
        return [], int(unread_threads)

    wanted_ids = {row.latest_id for row in rows} | {
        row.first_unread_id for row in rows if row.first_unread_id is not None
    }
    notifications = {
        row.id: row
        for row in (
            await db.execute(
                select(
                    Notification.id,
                    Notification.link,
                    Notification.message,
                    Notification.created_at,
                ).where(Notification.id.in_(sorted(wanted_ids)))
            )
        ).all()
    }

    parsed = [(row, _parse_thread(row.thread)) for row in rows]
    job_ids = [key[1] for _, key in parsed if key and key[0] == "job"]
    candidate_ids = [key[1] for _, key in parsed if key and key[0] == "candidate"]
    titles_by_job = await job_names(db, job_ids)
    candidate_names = await _candidate_names(db, candidate_ids)

    last_message_ids: dict[ChatKind, list[int]] = {"job": [], "candidate": []}
    for row, key in parsed:
        latest = notifications.get(row.latest_id)
        message_id = _message_id(latest.link) if latest else None
        if key and message_id is not None:
            last_message_ids[key[0]].append(message_id)
    authors: dict[ChatKind, dict[int, str]] = {
        "job": await _author_names(db, JobChatMessage, last_message_ids["job"]),
        "candidate": await _author_names(
            db, CandidateChatMessage, last_message_ids["candidate"]
        ),
    }

    threads: list[ChatThread] = []
    for row, key in parsed:
        latest = notifications.get(row.latest_id)
        if key is None or latest is None:
            continue
        kind, entity_id = key
        if kind == "job":
            title, subtitle = titles_by_job.get(entity_id, ("", None))
            title = title or f"Rekrutacja #{entity_id}"
        else:
            title = candidate_names.get(entity_id) or f"Kandydat #{entity_id}"
            subtitle = None
        first_unread = (
            notifications.get(row.first_unread_id)
            if row.first_unread_id is not None
            else None
        )
        message_id = _message_id(latest.link)
        threads.append(
            ChatThread(
                kind=kind,
                entity_id=entity_id,
                title=title,
                subtitle=subtitle,
                unread_count=int(row.unread_count or 0),
                has_mention=bool(row.unread_mentions),
                last_author_name=(
                    authors[kind].get(message_id) if message_id is not None else None
                ),
                last_message=latest.message or "",
                last_at=latest.created_at,
                # Klik prowadzi do pierwszej nieprzeczytanej wiadomości, a gdy
                # wszystko przeczytane — do ostatniej.
                link=(first_unread or latest).link,
            )
        )
    return threads, int(unread_threads)


def _note_context(link: str) -> Optional[tuple[str, int]]:
    match = _NOTE_CONTEXT_RE.match(link or "")
    return (match.group(1), int(match.group(2))) if match else None


async def _list_note_threads(
    db: AsyncSession, user: User, *, limit: int
) -> tuple[list[ChatThread], int]:
    """Wzmianki i odpowiedzi w notatkach — jeden wątek na link notatki."""
    since = datetime.now(timezone.utc) - timedelta(days=CHAT_WINDOW_DAYS)
    base = [
        Notification.user_id == user.id,
        Notification.notification_type.in_(NOTE_NOTIFICATION_TYPES),
        Notification.link.is_not(None),
        Notification.created_at >= since,
        notification_visibility_predicate(user),
    ]
    unread = Notification.is_read.is_(False)
    unread_rows = func.count().filter(unread)
    latest_id = func.max(Notification.id)
    rows = (
        await db.execute(
            select(
                Notification.link.label("thread"),
                unread_rows.label("unread_count"),
                func.count()
                .filter(
                    unread,
                    Notification.notification_type == NotificationType.note_mention,
                )
                .label("unread_mentions"),
                latest_id.label("latest_id"),
            )
            .where(*base)
            .group_by(Notification.link)
            .order_by((unread_rows > 0).desc(), latest_id.desc())
            .limit(limit)
        )
    ).all()
    unread_threads = (
        await db.scalar(
            select(func.count(distinct(Notification.link))).where(*base, unread)
        )
        or 0
    )
    if not rows:
        return [], int(unread_threads)

    latest_rows = {
        row.id: row
        for row in (
            await db.execute(
                select(
                    Notification.id,
                    Notification.title,
                    Notification.message,
                    Notification.created_at,
                    Notification.related_entity_id,
                ).where(Notification.id.in_(sorted(row.latest_id for row in rows)))
            )
        ).all()
    }
    contexts = {row.thread: _note_context(row.thread) for row in rows}
    titles_by_job = await job_names(
        db, [c[1] for c in contexts.values() if c and c[0] == "jobs"]
    )
    candidate_names = await _candidate_names(
        db, [c[1] for c in contexts.values() if c and c[0] == "candidates"]
    )

    threads: list[ChatThread] = []
    for row in rows:
        latest = latest_rows.get(row.latest_id)
        if latest is None:
            continue
        context = contexts[row.thread]
        if context and context[0] == "candidates":
            title = candidate_names.get(context[1]) or f"Kandydat #{context[1]}"
        elif context and context[0] == "jobs":
            title = titles_by_job.get(context[1], ("", None))[0] or (
                f"Rekrutacja #{context[1]}"
            )
        elif context:
            title = f"Kontrakt #{context[1]}"
        else:
            title = "Notatka"
        threads.append(
            ChatThread(
                kind="note",
                entity_id=int(latest.related_entity_id or 0),
                title=title,
                # „Anna D. oznaczył(a) Cię w notatce” / „… odpowiedział(a) na
                # Twoją notatkę” — tytuł wiersza mówi, kto i co.
                subtitle=latest.title,
                unread_count=int(row.unread_count or 0),
                has_mention=bool(row.unread_mentions),
                last_author_name=None,
                last_message=latest.message or "",
                last_at=latest.created_at,
                link=row.thread,
            )
        )
    return threads, int(unread_threads)


async def mark_read(
    db: AsyncSession,
    user_id: int,
    *,
    kind: Optional[str] = None,
    entity_id: Optional[int] = None,
    link: Optional[str] = None,
    include_notes: bool = False,
    extra: Optional[Any] = None,
) -> int:
    """Oznacz własne powiadomienia czatów jako przeczytane; bez commitu.

    Z ``kind`` i ``entity_id`` — jednej rozmowy, z ``kind="note"`` i ``link``
    — jednego wątku notatki, bez nich — wszystkich czatów (z
    ``include_notes`` także notatek). Zwraca liczbę zmienionych wierszy.
    """
    if kind == "note":
        types: tuple = NOTE_NOTIFICATION_TYPES
    elif kind is None and include_notes:
        types = (*CHAT_NOTIFICATION_TYPES, *NOTE_NOTIFICATION_TYPES)
    else:
        types = CHAT_NOTIFICATION_TYPES
    clauses = [
        Notification.user_id == user_id,
        Notification.is_read.is_(False),
        Notification.notification_type.in_(types),
    ]
    if kind == "note":
        clauses.append(Notification.link == link)
    elif kind is not None and entity_id is not None:
        clauses.append(
            Notification.link.startswith(
                thread_prefix(kind, entity_id), autoescape=True
            )
        )
    if extra is not None:
        clauses.append(extra)
    result = await db.execute(
        update(Notification)
        .where(*clauses)
        .values(is_read=True)
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)


async def thread_title(db: AsyncSession, kind: str, entity_id: int) -> str:
    """Nazwa rozmowy do dymka: tytuł rekrutacji albo imię i nazwisko."""
    if kind == "job":
        names = await job_names(db, [entity_id])
        return names.get(entity_id, ("", None))[0] or f"Rekrutacja #{entity_id}"
    names_by_id = await _candidate_names(db, [entity_id])
    return names_by_id.get(entity_id) or f"Kandydat #{entity_id}"


def notify_events(
    *,
    kind: str,
    entity_id: int,
    title: str,
    link: str,
    author_name: str,
    preview: str,
    message_recipient_ids: Iterable[int],
    mention_recipient_ids: Iterable[int],
) -> list[tuple[int, dict]]:
    """Zdarzenia na żywo dla odbiorców powiadomienia o nowej wiadomości.

    Jedno na osobę: wzmianka wygrywa ze zwykłą wiadomością. Bramkę odbiorcy
    (sekcja, wyciszona kategoria) stosuje ``user_can_receive_realtime_event``
    po ``notification_type`` z ładunku — tak jak dla wiersza powiadomienia.
    """
    event_type = JOB_NOTIFY_EVENT if kind == "job" else CANDIDATE_NOTIFY_EVENT
    mentioned = set(mention_recipient_ids)
    events: list[tuple[int, dict]] = []
    for user_id in sorted(mentioned | set(message_recipient_ids)):
        notification_type = (
            NotificationType.job_chat_mention
            if user_id in mentioned
            else NotificationType.job_chat_message
        )
        events.append(
            (
                user_id,
                {
                    "type": event_type,
                    "data": {
                        "kind": kind,
                        "entity_id": entity_id,
                        "notification_type": notification_type.value,
                        "related_entity_type": _ENTITY_TYPE_BY_KIND[kind],
                        "link": link,
                        "thread_title": title,
                        "author_name": author_name,
                        "preview": preview,
                    },
                },
            )
        )
    return events


async def notify_recipients(
    db: AsyncSession,
    send: Callable[[int, dict], Awaitable[None]],
    *,
    kind: str,
    entity_id: int,
    link: str,
    author_name: str,
    preview: str,
    message_recipient_ids: Iterable[int],
    mention_recipient_ids: Iterable[int],
) -> None:
    """Wyślij zdarzenie ``…:notify`` każdemu, kto dostał powiadomienie.

    Dymek i okienko „Czaty” — także dla oznaczonej osoby spoza zespołu, do
    której rozgłoszenie wiadomości nie dociera. Wołane po zapisie wiadomości
    i nigdy nie zmienia jego wyniku: błąd kończy się wpisem w logu.
    """
    try:
        async with db.begin_nested():
            title = await thread_title(db, kind, entity_id)
        events = notify_events(
            kind=kind,
            entity_id=entity_id,
            title=title,
            link=link,
            author_name=author_name,
            preview=preview,
            message_recipient_ids=message_recipient_ids,
            mention_recipient_ids=mention_recipient_ids,
        )
        for user_id, event in events:
            await send(user_id, event)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Zdarzenie czatu na żywo nie wyszło (%s %s): %s",
            kind,
            entity_id,
            type(exc).__name__,
        )
