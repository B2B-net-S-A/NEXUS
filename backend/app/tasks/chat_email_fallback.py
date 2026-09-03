"""Email fallback for offline >15min users (Feature 11).

Co minutę skanuje notyfikacje typu chat (job_chat_message, job_chat_mention)
starsze niż 15 min, nieprzeczytane, których adresat ma `last_seen_at`
starsze niż 15 min (lub NULL — użytkownik nigdy nie był online z tym
fixem). Dla każdej takiej notyfikacji rezerwuje wiersz
(`Notification.email_send_started_at = NOW()`), wysyła email i dopiero
po potwierdzonej wysyłce stempluje `Notification.email_sent_at = NOW()`.

Rozdzielenie „rezerwacja" od „wysłane" jest celowe: gdyby `email_sent_at`
padało przed wysyłką (tak było wcześniej), twardy crash/restart między
commitem a SMTP zostawiałby wiersz na zawsze oznaczony jako wysłany —
mail nigdy nie wychodzi i nikt się o tym nie dowiaduje. Teraz crash
zostawia jedynie wiszącą rezerwację, którą kolejny przebieg przejmuje po
`CLAIM_STALE_MIN` minutach i wysyła. Mail bywa opóźniony, nigdy zgubiony.

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

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.api.candidate_access import (
    CANDIDATE_READ_ROLES,
    user_can_access_candidate_domain,
)
from app.services.section_permissions import (
    resolve_effective_section_access,
    resolve_effective_section_access_for_users,
)
from app.services.notification_access import user_can_receive_notification
from app.services.email import send_chat_fallback_email

logger = logging.getLogger(__name__)

# Tunable: po ilu minutach offline trigger email
OFFLINE_THRESHOLD_MIN = 15
# Co ile sekund cykl
LOOP_SLEEP_SEC = 60
# Maksymalna paczka w jednym przebiegu (zapobiega N+1)
BATCH_SIZE = 100
# Po ilu minutach rezerwacja bez rozstrzygnięcia (crash w trakcie wysyłki)
# uznawana jest za porzuconą i może ją przejąć kolejny przebieg. Musi być
# wyraźnie dłuższa niż najdłuższa realna wysyłka SMTP, żeby nie odebrać
# rezerwacji procesowi, który wciąż wysyła.
CLAIM_STALE_MIN = 15

# Typy notyfikacji które kwalifikują się do email fallback
_CHAT_NOTIF_TYPES = {
    NotificationType.job_chat_message,
    NotificationType.job_chat_mention,
}


def _eligible_chat_email_recipient(user: User) -> bool:
    """Re-check current candidate-domain authorization before PII fan-out."""

    return user_can_access_candidate_domain(user)


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
    """Atomically reserve a notification for sending — without marking it sent.

    Flips ``email_send_started_at`` to ``now()`` in a single UPDATE guarded by
    ``email_sent_at IS NULL`` (never sent) AND ``email_send_started_at`` being
    either NULL (nobody holds it) or older than ``CLAIM_STALE_MIN`` (a previous
    holder died mid-send). Returns True only for the caller that won the row.

    A concurrent/overlapping pass (multi-worker or restart overlap) blocks on
    the row lock, then re-evaluates the WHERE against the committed reservation,
    matches zero rows and returns False — so the email is sent exactly once.
    The reservation is committed immediately to release the row lock and make it
    visible to the other pass.

    Crucially this stamps the *reservation* field, not ``email_sent_at``. A hard
    crash between this commit and the actual SMTP send therefore leaves the row
    recoverable: ``email_sent_at`` is still NULL, and once the reservation goes
    stale the next pass re-claims and sends it.
    """
    stale_cutoff = datetime.now(timezone.utc) - timedelta(minutes=CLAIM_STALE_MIN)
    result = await db.execute(
        update(Notification)
        .where(
            Notification.id == notif_id,
            Notification.email_sent_at.is_(None),
            or_(
                Notification.email_send_started_at.is_(None),
                Notification.email_send_started_at <= stale_cutoff,
            ),
        )
        .values(email_send_started_at=func.now())
        .returning(Notification.id)
    )
    claimed = result.scalar_one_or_none() is not None
    await db.commit()
    return claimed


async def _mark_sent(db: AsyncSession, notif_id: int) -> None:
    """Stamp ``email_sent_at`` — only ever called AFTER a confirmed SMTP send.

    ``email_send_started_at`` is deliberately left in place: it is the audit
    trail of when the attempt began, and ``email_sent_at IS NULL`` is what
    guards re-claiming, so the row can never be picked up again.
    """
    await db.execute(
        update(Notification)
        .where(Notification.id == notif_id)
        .values(email_sent_at=func.now())
    )
    await db.commit()


async def _release_claim(db: AsyncSession, notif_id: int) -> None:
    """Release a reservation so the next pass retries immediately.

    Called when the send did not actually go out (SMTP disabled / send error).
    Without it the row would sit unavailable until the stale timeout expires.
    Only clears the reservation — ``email_sent_at`` was never set on this path.
    Safe against the race: only the pass that won the claim reaches here, so no
    other worker is touching this row in this window.
    """
    await db.execute(
        update(Notification)
        .where(Notification.id == notif_id)
        .values(email_send_started_at=None)
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
    #   - not currently reserved by a live pass (stale reservations left by a
    #     crashed process ARE picked up again — that is the recovery path)
    # These filters only narrow the batch; the atomic claim below is the real
    # guard against a double send.
    stale_cutoff = now - timedelta(minutes=CLAIM_STALE_MIN)
    rows = await db.execute(
        select(Notification, User)
        .join(User, User.id == Notification.user_id)
        .where(Notification.notification_type.in_(_CHAT_NOTIF_TYPES))
        .where(User.is_active.is_(True))
        .where(User.role.in_(CANDIDATE_READ_ROLES))
        # Primary-role SQL keeps the batch from being starved by ordinary
        # Finance/viewer rows. JSONB exclusions also remove malformed hybrids;
        # the Python full-role guard below remains authoritative.
        .where(~User.roles.contains([UserRole.finance.value]))
        .where(~User.roles.contains([UserRole.user.value]))
        .where(Notification.created_at <= threshold)
        .where(Notification.is_read.is_(False))
        .where(Notification.email_sent_at.is_(None))
        .where(
            or_(
                Notification.email_send_started_at.is_(None),
                Notification.email_send_started_at <= stale_cutoff,
            )
        )
        .where((User.last_seen_at.is_(None)) | (User.last_seen_at <= threshold))
        .order_by(Notification.created_at.asc())
        .limit(BATCH_SIZE)
    )
    pairs = rows.all()
    if not pairs:
        return 0

    await resolve_effective_section_access_for_users(db, [user for _, user in pairs])

    sent = 0
    for notif, user in pairs:
        # Role changes can race with the SELECT. Re-evaluate the complete,
        # current role union before even claiming the notification; a stale
        # unread chat row must never email candidate/recruitment PII to Finance.
        if not _eligible_chat_email_recipient(
            user
        ) or not user_can_receive_notification(
            user,
            notif.notification_type,
            related_entity_type=notif.related_entity_type,
            link=notif.link,
        ):
            continue
        # Reserve the row atomically BEFORE sending so an overlapping pass can't
        # send the same email twice. The reservation is NOT the "sent" stamp.
        if not await _claim_notification(db, notif.id):
            continue
        # The role/account state may have changed after the batch SELECT but
        # before this row was claimed. Force a current DB read before SMTP so a
        # transition to Finance/viewer (or deactivation) cannot leak the stale
        # notification body.
        await db.refresh(user, attribute_names=["role", "roles", "is_active"])
        await resolve_effective_section_access(db, user)
        if not _eligible_chat_email_recipient(
            user
        ) or not user_can_receive_notification(
            user,
            notif.notification_type,
            related_entity_type=notif.related_entity_type,
            link=notif.link,
        ):
            await _release_claim(db, notif.id)
            continue
        ok = False
        try:
            ok = await _send_chat_email(user, notif)
        except Exception as e:  # noqa: BLE001
            logger.warning("chat_email_fallback failed for notif %d: %s", notif.id, e)
        if ok:
            # Only now — after SMTP confirmed — is the row marked as sent.
            await _mark_sent(db, notif.id)
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
