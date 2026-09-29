"""Centralna obsługa @mention dla notatek.

Funkcje używane przez notes.py i screenings.py żeby uniknąć duplikacji
trzech rzeczy które trzeba zrobić po wykryciu mention'a:

  1. INSERT Notification (typ note_mention) — w tej samej transakcji co
     parent (Note / ScreeningNote), żeby było atomowe.
  2. WS push przez ws.notify_user — best-effort po commicie (gdy odbiorca
     online → natychmiast dropdown widzi nową notyfikację).
  3. Email przez send_mention_email — best-effort po commicie (timeout 10s
     z smtplib, nie blokuje response gdy SMTP fail).

Dwie fazy:

    enqueue_mention_notifications(db, ...)
        → adds Notification rows; returns list of (user, notification) par
        → caller commit'uje razem z parent INSERT-em
        → po commicie:
    send_mention_side_effects(pairs, ...)
        → WS push + email per user
        → wszystko try/except — nie crashuje response

Dlaczego dwie fazy zamiast jednej (jak w notification_triggers.emit):
- email synchronicznie *przed* commitem to ryzyko "wysłałem mail o czymś
  co nigdy się nie zapisało" (rollback). Po commicie jest atomowo.
- WS push też po commicie z tego samego powodu.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import ws as ws_manager
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.note import Note
from app.models.notification import Notification, NotificationType
from app.models.user import User
from app.services.email import send_mention_email
from app.services.notification_delivery import DeliveryPolicy, load_policy
from app.services.notification_access import (
    filter_notification_recipients,
    user_can_receive_notification,
)
from app.services.section_permissions import resolve_effective_section_access_for_users

logger = logging.getLogger(__name__)


# ── Snippet helper ────────────────────────────────────────────────────────────


def trim_snippet(content: str, limit: int = 140) -> str:
    """Skraca content do limitu znaków + dba żeby nie ucinać w środku słowa.

    Mirror logiki z `job_chat._reply_preview` — żeby snippet w mailu nie
    kończył się "Lorem ipsu" tylko "Lorem…" .
    """
    cleaned = " ".join((content or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


# ── Deep-link / context-label builders dla Note ──────────────────────────────


def build_note_deep_link(note: Note) -> str:
    """Najbardziej specyficzny route — kandydat > job > kontrakt > orphan.

    Notatka o kandydacie (także przypięta do rekrutacji) otwiera widok notatek
    w profilu kandydata, a ``note=`` podświetla wpis. Do 09.2026 link niósł
    ``?tab=notes`` — klucz, którego ani profil kandydata, ani strona
    rekrutacji nie znały, więc wzmianka lądowała na Podsumowaniu. Notatka
    samej rekrutacji (bez kandydata) prowadzi na tablicę rekrutacji.
    """
    if note.candidate_id:
        # Jeden literał: test kontraktowy `test_client_tab_links.py` czyta
        # linki z kodu i sprawdza klucze zakładek z frontem.
        return f"/candidates/{note.candidate_id}?tab=activity&activity=notes&note={note.id}"  # noqa: E501
    if note.job_id:
        return f"/jobs/{note.job_id}?note={note.id}"
    if note.contract_id:
        return f"/contracts/{note.contract_id}?tab=notes&note={note.id}"
    return f"/?orphan_note={note.id}"


async def build_note_context_label(db: AsyncSession, note: Note) -> str:
    """Human-readable kontekst do wstawienia w "...oznaczył(a) Cię w X".

    Przykład: "notatce o kandydacie Jan Kowalski", "notatce w projekcie ABC".
    """
    if note.candidate_id:
        cand = await db.get(Candidate, note.candidate_id)
        if cand is not None:
            full = f"{cand.name or ''} {cand.lastname or ''}".strip()
            if full:
                return f"notatce o kandydacie {full}"
        return "notatce o kandydacie"
    if note.job_id:
        job = await db.get(Job, note.job_id)
        if job is not None and job.title:
            return f"notatce w projekcie {job.title}"
        return "notatce w projekcie"
    if note.contract_id:
        return "notatce w kontrakcie"
    return "notatce"


def build_screening_note_deep_link(candidate_id: int, screening_note_id: int) -> str:
    """Deep link do ScreeningNote — anchor w karcie kandydata."""
    return f"/candidates/{candidate_id}#screening-{screening_note_id}"


# ── Phase 1: enqueue (in-transaction, no commit) ─────────────────────────────


async def enqueue_mention_notifications(
    db: AsyncSession,
    *,
    mentioned_user_ids: list[int],
    author: User,
    deep_link_path: str,
    snippet: str,
    notification_title: str,
    related_entity_type: str,
    related_entity_id: int,
    notification_type: NotificationType = NotificationType.note_mention,
) -> list[tuple[User, Notification]]:
    """Dodaje Notification do sesji per user. NIE commit'uje.

    Returns: lista par (User, Notification) do późniejszego dispatch
    side-effects po commit'cie. Pomija duplikaty (każdy user dostanie max
    1 notyfikację per mention call).

    Args:
        mentioned_user_ids: już przefiltrowane przez parse_mentions* + bez self.
            Pusta lista = no-op (return []).
    """
    if not mentioned_user_ids:
        return []

    unique_ids = sorted(set(mentioned_user_ids))

    rows = await db.execute(
        select(User).where(User.id.in_(unique_ids), User.is_active.is_(True))
    )
    users = list(rows.scalars().all())
    await resolve_effective_section_access_for_users(db, users)

    # Import leniwy: ``app.api.notifications`` ciągnie za sobą routery.
    from app.api.notifications import create_notification

    pairs: list[tuple[User, Notification]] = []
    for user in users:
        if not user_can_receive_notification(
            user,
            notification_type,
            related_entity_type=related_entity_type,
            link=deep_link_path,
        ):
            continue
        # Runda 9 (R9-N2-6): ponowne oznaczenie tej samej osoby w tej samej
        # notatce tego samego dnia (usunięta i dopisana wzmianka) trafiało
        # w ``ix_notif_dedup_daily`` i wywracało zapis notatki 500-ką.
        # ``dedupe_resurface`` wstawia w savepoincie, a przy kolizji odświeża
        # dzisiejszy wiersz (znowu nieprzeczytany) zamiast dokładać drugi.
        notif = await create_notification(
            db,
            user_id=user.id,
            title=notification_title,
            message=snippet,
            link=deep_link_path,
            notification_type=notification_type,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
            dedupe_resurface=True,
        )
        # Odświeżony wiersz ma ``created_at = now()`` jako wyrażenie SQL —
        # po zapisie atrybut wygasa, a leniwe doczytanie po commicie
        # (``send_mention_side_effects``) w async to ``MissingGreenlet``.
        await db.flush()
        await db.refresh(notif, attribute_names=["created_at"])
        pairs.append((user, notif))
    return pairs


# ── Phase 2: post-commit side-effects ────────────────────────────────────────


async def send_mention_side_effects(
    pairs: list[tuple[User, Notification]],
    *,
    author_name: str,
    snippet: str,
    deep_link_path: str,
    context_label: str,
    notification_title: str,
    notification_type: NotificationType = NotificationType.note_mention,
    send_email: bool = True,
) -> int:
    """Po commicie: WS push + email per user. Best-effort (try/except).

    Odpowiedź na notatkę (``note_reply``, 0399) idzie bez maila — mail
    wzmianki mówi „oznaczył(a) Cię”, a odpowiedź widać w dzwonku.
    """
    if not pairs:
        return 0

    # The note transaction has already committed; re-read recipients so a
    # policy revocation racing that commit cannot leak the snippet by email.
    async with AsyncSessionLocal() as db:
        allowed_users = await filter_notification_recipients(
            db,
            (user.id for user, _ in pairs),
            notification_type,
            related_entity_type="note",
            link=deep_link_path,
        )
        try:
            policy = await load_policy(db)
        except Exception:
            logger.warning("mention email policy unavailable; email blocked")
            policy = DeliveryPolicy()
    allowed_ids = {user.id for user in allowed_users}

    sent = 0
    for user, notif in pairs:
        if user.id not in allowed_ids:
            continue
        # WS push — natychmiastowe pojawienie się w NotificationsDropdown.
        try:
            await ws_manager.notify_user(
                user.id,
                {
                    "type": "notification",
                    "data": {
                        "id": notif.id,
                        "title": notif.title,
                        "message": notif.message,
                        "link": notif.link,
                        "notification_type": notification_type.value,
                        "created_at": (
                            notif.created_at.isoformat()
                            if notif.created_at is not None
                            else None
                        ),
                    },
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "mention WS push failed user=%s notif=%s err=%s",
                user.id,
                notif.id,
                exc,
            )

        # Email — tylko gdy user ma email i jest aktywny.
        if (
            not send_email
            or not user.email
            or not policy.allows("mentions", notif.created_at)
        ):
            continue
        try:
            # Blocking smtplib send — offload off the event loop.
            ok = await run_in_threadpool(
                send_mention_email,
                to_email=user.email,
                recipient_name=user.name or user.email,
                author_name=author_name,
                snippet=snippet,
                deep_link_path=deep_link_path,
                context_label=context_label,
                event_at=notif.created_at,
            )
            if ok:
                sent += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("mention email failed user=%s err=%s", user.id, exc)
    return sent


# ── Usunięta / poprawiona treść (runda 10, R10-N6-3) ─────────────────────────
#
# Powiadomienie niesie FRAGMENT treści (``message``), a mail zastępczy czatu
# wysyła go po 15 min osobom offline. Do rundy 10 usunięcie albo poprawka
# wiadomości czy notatki nie dotykały powiadomień: skasowana treść (np. stawka
# wpisana przez pomyłkę) zostawała w dzwonku i wychodziła mailem.

NOTE_DELETED_PLACEHOLDER = "[notatka usunięta]"
CHAT_DELETED_PLACEHOLDER = "[wiadomość usunięta]"
CHAT_NOTIFICATION_TYPES = (
    NotificationType.job_chat_message,
    NotificationType.job_chat_mention,
)
# Powiadomienia wiadomości powstają w tej samej transakcji co wiadomość (albo
# później — wzmianka dopisana przy edycji), więc zawężenie po czasie jest
# bezpieczne, a zapytanie nie przegląda całej historii powiadomień czatu.
_CHAT_NOTIFICATION_SLACK = timedelta(minutes=1)


def _chat_message_clause(
    *, related_entity_type: str, link: str, message_created_at: Optional[datetime]
) -> list:
    clauses = [
        Notification.notification_type.in_(CHAT_NOTIFICATION_TYPES),
        Notification.related_entity_type == related_entity_type,
        Notification.link == link,
    ]
    if message_created_at is not None:
        clauses.append(
            Notification.created_at >= message_created_at - _CHAT_NOTIFICATION_SLACK
        )
    return clauses


async def retract_chat_message_notifications(
    db: AsyncSession,
    *,
    related_entity_type: str,
    link: str,
    message_created_at: Optional[datetime],
) -> None:
    """Usunięta wiadomość czatu: powiadomienia nie niosą już jej treści.

    Wiersze, których mail jeszcze nie ruszył, są KASOWANE — oznaczenie jako
    przeczytane zostawiłoby „nowsze powiadomienie wątku”, które w
    ``chat_email_fallback`` wstrzymuje mail o wcześniejszej, prawdziwej
    wiadomości. Wiersze z rozpoczętą albo wysłaną wysyłką zostają (ślad
    wysyłki), ale jako przeczytane i z zastępczą treścią — worker po
    rezerwacji ponownie czyta ``is_read`` i ``message``.
    """
    base = _chat_message_clause(
        related_entity_type=related_entity_type,
        link=link,
        message_created_at=message_created_at,
    )
    await db.execute(
        delete(Notification)
        .where(
            *base,
            Notification.email_sent_at.is_(None),
            Notification.email_send_started_at.is_(None),
            Notification.email_delivery_uncertain.is_(False),
        )
        .execution_options(synchronize_session=False)
    )
    await db.execute(
        update(Notification)
        .where(*base)
        .values(is_read=True, message=CHAT_DELETED_PLACEHOLDER)
        .execution_options(synchronize_session=False)
    )


async def refresh_chat_message_snippets(
    db: AsyncSession,
    *,
    related_entity_type: str,
    link: str,
    message_created_at: Optional[datetime],
    snippet: str,
) -> None:
    """Poprawiona wiadomość czatu: dzwonek i mail pokazują nową treść."""
    await db.execute(
        update(Notification)
        .where(
            *_chat_message_clause(
                related_entity_type=related_entity_type,
                link=link,
                message_created_at=message_created_at,
            )
        )
        .values(message=snippet)
        .execution_options(synchronize_session=False)
    )


async def retract_note_mention_notifications(db: AsyncSession, note_id: int) -> None:
    """Usunięta notatka: wzmianka w dzwonku nie niesie już jej fragmentu."""
    await db.execute(
        update(Notification)
        .where(
            Notification.notification_type == NotificationType.note_mention,
            Notification.related_entity_type == "note",
            Notification.related_entity_id == note_id,
        )
        .values(is_read=True, message=NOTE_DELETED_PLACEHOLDER)
        .execution_options(synchronize_session=False)
    )


async def refresh_note_mention_snippets(
    db: AsyncSession, note_id: int, snippet: str
) -> None:
    """Poprawiona notatka: wzmianki w dzwonku pokazują nowy fragment."""
    await db.execute(
        update(Notification)
        .where(
            Notification.notification_type == NotificationType.note_mention,
            Notification.related_entity_type == "note",
            Notification.related_entity_id == note_id,
        )
        .values(message=snippet)
        .execution_options(synchronize_session=False)
    )


__all__ = [
    "CHAT_DELETED_PLACEHOLDER",
    "NOTE_DELETED_PLACEHOLDER",
    "refresh_chat_message_snippets",
    "refresh_note_mention_snippets",
    "retract_chat_message_notifications",
    "retract_note_mention_notifications",
    "build_note_context_label",
    "build_note_deep_link",
    "build_screening_note_deep_link",
    "enqueue_mention_notifications",
    "send_mention_side_effects",
    "trim_snippet",
]
