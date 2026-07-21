"""Email fallback for offline >15min users (Feature 11).

Co minutę skanuje notyfikacje typu chat (job_chat_message, job_chat_mention)
starsze niż 15 min, nieprzeczytane, których adresat ma `last_seen_at`
starsze niż 15 min (lub NULL — użytkownik nigdy nie był online z tym
fixem). Dla każdej takiej notyfikacji wysyła email i stempluje
`Notification.email_sent_at = NOW()` żeby uniknąć duplikatów.

Wysyłka: SMTP przez `services.email.send_chat_fallback_email` — feature-
gated przez `SMTP_ENABLED`. Gdy off zwraca `False` i pętla retry'uje w
następnej iteracji (po włączeniu SMTP creds w env). Backupowy log na
WARN gdy SMTP fail żeby nie zalewać produkcji.

Loop dziedziczy wzorzec z `triggers_loop.py` — `asyncio.create_task` w
lifespan, sleeping 60s między iteracjami, exception isolation.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.notification import Notification, NotificationType
from app.models.user import User
from app.services.email import send_chat_fallback_email

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


async def _send_chat_email(user: User, notif: Notification) -> bool:
    """Send email for one notification. Return True if SMTP confirmed.

    SMTP via `services.email.send_chat_fallback_email`. Feature-gated przez
    `SMTP_ENABLED` — gdy off lub creds brakują wraca False, loop retry-uje
    w kolejnej iteracji (bez stempla email_sent_at).
    """
    if not user.email:
        logger.debug("chat_email_fallback skip — user %s nie ma emaila", user.id)
        return False
    # Blocking smtplib send — offload off the event loop.
    return await asyncio.to_thread(
        send_chat_fallback_email,
        to_email=user.email,
        recipient_name=user.name or user.email,
        notification_title=notif.title,
        notification_message=notif.message or "",
        deep_link_path=notif.link or "/",
    )


async def _claim_notification(db: AsyncSession, notif_id: int) -> bool:
    """Atomically claim a notification for sending.

    Flips ``email_sent_at`` from NULL → ``now()`` in a single UPDATE guarded by
    ``email_sent_at IS NULL``, and returns True only for the caller that won the
    claim. A concurrent/overlapping pass (multi-worker or restart overlap)
    blocks on the row lock, then re-evaluates the WHERE against the committed
    stamp, matches zero rows and returns False — so the email is sent exactly
    once. The claim is committed immediately to release the row lock and make
    the stamp visible to the other pass.
    """
    result = await db.execute(
        update(Notification)
        .where(
            Notification.id == notif_id,
            Notification.email_sent_at.is_(None),
        )
        .values(email_sent_at=func.now())
        .returning(Notification.id)
    )
    claimed = result.scalar_one_or_none() is not None
    await db.commit()
    return claimed


async def _release_claim(db: AsyncSession, notif_id: int) -> None:
    """Release a claim so a later pass retries.

    Called when the send did not actually go out (SMTP disabled / send error).
    This preserves the original contract of only keeping the stamp on a
    confirmed send — without it, a claim taken while SMTP is off would suppress
    the email forever. Safe against the race: only the pass that won the claim
    reaches here, so no other worker is touching this row in this window.
    """
    await db.execute(
        update(Notification)
        .where(Notification.id == notif_id)
        .values(email_sent_at=None)
    )
    await db.commit()


async def _process_one_pass(db: AsyncSession) -> int:
    """Single pass — return count of emails fired."""
    now = datetime.now(timezone.utc)
    threshold = now - timedelta(minutes=OFFLINE_THRESHOLD_MIN)

    # Find candidate notifications:
    #   - chat type
    #   - older than threshold
    #   - unread
    #   - not yet email-sent
    # The `email_sent_at IS NULL` filter only narrows the batch; the atomic
    # claim below is the real guard against a double send.
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
        # Claim the row atomically BEFORE sending so an overlapping pass can't
        # send the same email twice.
        if not await _claim_notification(db, notif.id):
            continue
        ok = False
        try:
            ok = await _send_chat_email(user, notif)
        except Exception as e:  # noqa: BLE001
            logger.warning("chat_email_fallback failed for notif %d: %s", notif.id, e)
        if ok:
            sent += 1
        else:
            # SMTP off / send failed — release the claim so a later pass retries.
            await _release_claim(db, notif.id)
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
