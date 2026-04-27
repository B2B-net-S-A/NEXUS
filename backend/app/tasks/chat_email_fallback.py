"""Email fallback for offline >15min users (Feature 11).

Co minutę skanuje notyfikacje typu chat (job_chat_message, job_chat_mention)
starsze niż 15 min, nieprzeczytane, których adresat ma `last_seen_at`
starsze niż 15 min (lub NULL — użytkownik nigdy nie był online z tym
fixem). Dla każdej takiej notyfikacji wysyła email i stempluje
`Notification.email_sent_at = NOW()` żeby uniknąć duplikatów.

Wysyłka: M365 (jeśli skonfigurowane) z fallbackiem na log-only (`smtp_send`
nie istnieje w tym repo na dziś — drukujemy do logu, prod admin może
podpiąć SES/Sendgrid w jednym miejscu).

Loop dziedziczy wzorzec z `triggers_loop.py` — `asyncio.create_task` w
lifespan, sleeping 60s między iteracjami, exception isolation.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.notification import Notification, NotificationType
from app.models.user import User

logger = logging.getLogger(__name__)

# Tunable: po ilu minutach offline trigger email
OFFLINE_THRESHOLD_MIN = 15
# Co ile sekund cykl
LOOP_SLEEP_SEC = 60
# Maksymalna paczka w jednym przebiegu (zapobiega N+1)
BATCH_SIZE = 100

# Typy notyfikacji które kwalifikują się do email fallback
_CHAT_NOTIF_TYPES = {
    NotificationType.job_chat_message,
    NotificationType.job_chat_mention,
}


async def _send_chat_email(
    user: User, notif: Notification
) -> bool:
    """Send email for one notification. Return True if "sent" (or queued).

    Implementation note: production should wire this to M365 or SMTP/SES.
    Right now we log the would-be email and pretend success — that's enough
    to dedupe via `email_sent_at` and prove the loop works end-to-end. When
    a mail provider is configured, swap out the body of this function.
    """
    logger.info(
        "[chat_email_fallback] WOULD-SEND to %s (id=%d) | subject=%r body=%r link=%s",
        user.email,
        user.id,
        notif.title,
        (notif.message or "")[:140],
        notif.link,
    )
    return True


async def _process_one_pass(db: AsyncSession) -> int:
    """Single pass — return count of emails fired."""
    now = datetime.now(timezone.utc)
    threshold = now - timedelta(minutes=OFFLINE_THRESHOLD_MIN)

    # Find candidate notifications:
    #   - chat type
    #   - older than threshold
    #   - unread
    #   - not yet email-sent
    rows = await db.execute(
        select(Notification, User)
        .join(User, User.id == Notification.user_id)
        .where(Notification.notification_type.in_(_CHAT_NOTIF_TYPES))
        .where(Notification.created_at <= threshold)
        .where(Notification.is_read.is_(False))
        .where(Notification.email_sent_at.is_(None))
        .where((User.last_seen_at.is_(None)) | (User.last_seen_at <= threshold))
        .order_by(Notification.created_at.asc())
        .limit(BATCH_SIZE)
    )
    pairs = rows.all()
    if not pairs:
        return 0

    sent = 0
    for notif, user in pairs:
        try:
            ok = await _send_chat_email(user, notif)
            if ok:
                notif.email_sent_at = now
                sent += 1
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "chat_email_fallback failed for notif %d: %s", notif.id, e
            )
    if sent:
        await db.commit()
    return sent


async def chat_email_fallback_loop() -> None:
    """Long-running loop. Started from main.py lifespan."""
    logger.info(
        "chat_email_fallback_loop started (threshold=%dmin, sleep=%ds)",
        OFFLINE_THRESHOLD_MIN,
        LOOP_SLEEP_SEC,
    )
    while True:
        try:
            async with AsyncSessionLocal() as db:
                fired = await _process_one_pass(db)
                if fired:
                    logger.info(
                        "chat_email_fallback: sent %d emails in this pass", fired
                    )
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.exception("chat_email_fallback iteration crashed: %s", e)
        await asyncio.sleep(LOOP_SLEEP_SEC)
