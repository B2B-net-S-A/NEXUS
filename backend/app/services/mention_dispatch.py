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

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import ws as ws_manager
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.note import Note
from app.models.notification import Notification, NotificationType
from app.models.user import User
from app.services.email import send_mention_email
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

    Frontend musi obsłużyć query params `?tab=notes&note={id}` (scroll/highlight).
    """
    if note.candidate_id:
        return f"/candidates/{note.candidate_id}?tab=notes&note={note.id}"
    if note.job_id:
        return f"/jobs/{note.job_id}?tab=notes&note={note.id}"
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

    pairs: list[tuple[User, Notification]] = []
    for user in users:
        if not user_can_receive_notification(
            user,
            NotificationType.note_mention,
            related_entity_type=related_entity_type,
            link=deep_link_path,
        ):
            continue
        notif = Notification(
            user_id=user.id,
            title=notification_title,
            message=snippet,
            link=deep_link_path,
            notification_type=NotificationType.note_mention,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
        )
        db.add(notif)
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
) -> int:
    """Po commicie: WS push + email per user. Best-effort (try/except)."""
    if not pairs:
        return 0

    # The note transaction has already committed; re-read recipients so a
    # policy revocation racing that commit cannot leak the snippet by email.
    async with AsyncSessionLocal() as db:
        allowed_users = await filter_notification_recipients(
            db,
            (user.id for user, _ in pairs),
            NotificationType.note_mention,
            related_entity_type="note",
            link=deep_link_path,
        )
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
                        "notification_type": NotificationType.note_mention.value,
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
        if not user.email:
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
            )
            if ok:
                sent += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("mention email failed user=%s err=%s", user.id, exc)
    return sent


__all__ = [
    "build_note_context_label",
    "build_note_deep_link",
    "build_screening_note_deep_link",
    "enqueue_mention_notifications",
    "send_mention_side_effects",
    "trim_snippet",
]
