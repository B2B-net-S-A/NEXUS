"""Chat mail fallback with bounded retry and durable delivery uncertainty.

The sender circuit is shared across processes. Claims prevent concurrent sends;
marking uncertainty BEFORE the external call prevents replay after a crash in
its ambiguous acceptance window. Definite rejection schedules a later attempt.
No automatic deletion or expiration of pending business notifications.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import false, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.config import settings
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
from app.services.notification_delivery import DeliveryPolicy, load_policy

logger = logging.getLogger(__name__)

# Tunable: po ilu minutach offline trigger email
OFFLINE_THRESHOLD_MIN = 15
# Co ile sekund cykl
LOOP_SLEEP_SEC = 60
# Maksymalna paczka w jednym przebiegu (zapobiega N+1)
BATCH_SIZE = 100
MAX_SENDS_PER_PASS = 10
RETRY_DELAY_MIN = 5
# Po ilu minutach rezerwacja porzucona PRZED granicą rozpoczęcia wysyłki
# może być przejęta. Niepewna dostawa nie podlega temu odzyskaniu. Musi być
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


class DeliveryUncertain(Exception):
    """Graph may have accepted the message; operator reconciliation is required."""


async def _send_chat_email(user: User, notif: Notification) -> bool:
    if not user.email:
        return False

    def send():
        from app.services.m365.app_mail import last_delivery_uncertain
        from app.services.notification_delivery import last_send_policy_blocked

        ok = send_chat_fallback_email(
            to_email=user.email,
            recipient_name=user.name or user.email,
            notification_title=notif.title,
            notification_message=notif.message or "",
            deep_link_path=notif.link or "/",
            event_at=notif.created_at,
        )
        if (
            settings.M365_APP_MAIL_ENABLED
            and not ok
            and not last_send_policy_blocked()
            and last_delivery_uncertain()
        ):
            raise DeliveryUncertain()
        return ok

    return await asyncio.to_thread(send)


async def _claim_notification(db: AsyncSession, notif_id: int) -> bool:
    """Atomically reserve a notification for sending — without marking it sent.

    Flips ``email_send_started_at`` to ``now()`` in a single UPDATE guarded by
    ``email_sent_at IS NULL`` (never sent) AND ``email_send_started_at`` being
    either NULL (nobody holds it) or older than ``CLAIM_STALE_MIN`` (a previous
    holder died mid-send). Returns True only for the caller that won the row.

    A concurrent/overlapping pass (multi-worker or restart overlap) blocks on
    the row lock, then re-evaluates the WHERE against the committed reservation,
    matches zero rows and returns False. Acceptance is not an exactly-once guarantee.
    The reservation is committed immediately to release the row lock and make it
    visible to the other pass.

    Crucially this stamps the *reservation* field, not ``email_sent_at``. A hard
    crash after this commit but BEFORE ``_mark_delivery_started`` leaves the row
    recoverable once its reservation goes stale. Once delivery may have started,
    the separate durable uncertainty flag blocks automatic replay.
    """
    stale_cutoff = datetime.now(timezone.utc) - timedelta(minutes=CLAIM_STALE_MIN)
    result = await db.execute(
        update(Notification)
        .where(
            Notification.id == notif_id,
            Notification.email_sent_at.is_(None),
            Notification.email_delivery_uncertain.is_(False),
            or_(
                Notification.email_next_attempt_at.is_(None),
                Notification.email_next_attempt_at <= func.now(),
            ),
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
        .values(
            email_sent_at=func.now(),
            email_delivery_uncertain=False,
            email_next_attempt_at=None,
        )
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


async def _defer_notification(db: AsyncSession, notif_id: int) -> None:
    await db.execute(
        update(Notification)
        .where(Notification.id == notif_id)
        .values(
            email_send_started_at=None,
            email_delivery_uncertain=False,
            email_next_attempt_at=datetime.now(timezone.utc)
            + timedelta(minutes=RETRY_DELAY_MIN),
        )
    )
    await db.commit()


async def _mark_delivery_started(db: AsyncSession, notif_id: int) -> None:
    # Commit BEFORE network I/O; a process death must leave an uncertain result.
    await db.execute(
        update(Notification)
        .where(Notification.id == notif_id)
        .values(email_delivery_uncertain=True)
    )
    await db.commit()


async def _channel_waiting() -> bool:
    if not settings.M365_APP_MAIL_ENABLED:
        return False
    from app.services.m365 import mail_circuit

    state = await asyncio.to_thread(mail_circuit.snapshot)
    now = datetime.now(timezone.utc).timestamp()
    return max(state.get("next_attempt_at", 0), state.get("lease_until", 0)) > now


def pending_candidate_query(now: datetime, policy: DeliveryPolicy | None = None):
    """SQL candidate queue; final section access is checked by the worker.

    Reused by monitoring so unattempted rows are included in backlog evidence.
    This is an upper bound, not a promise that every row will be emailed.
    """
    threshold = now - timedelta(minutes=OFFLINE_THRESHOLD_MIN)
    stale_cutoff = now - timedelta(minutes=CLAIM_STALE_MIN)
    policy = policy or DeliveryPolicy()
    return (
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
        .where(
            Notification.created_at >= policy.cutoff_for("chat_unread")
            if policy.kind_enabled("chat_unread")
            else false()
        )
        .where(Notification.is_read.is_(False))
        .where(Notification.email_sent_at.is_(None))
        .where(Notification.email_delivery_uncertain.is_(False))
        .where(
            or_(
                Notification.email_next_attempt_at.is_(None),
                Notification.email_next_attempt_at <= now,
            )
        )
        .where(
            or_(
                Notification.email_send_started_at.is_(None),
                Notification.email_send_started_at <= stale_cutoff,
            )
        )
        .where((User.last_seen_at.is_(None)) | (User.last_seen_at <= threshold))
        .order_by(Notification.created_at.asc())
    )


async def _process_one_pass(db: AsyncSession) -> int:
    """Single pass — return count of emails fired."""
    policy = await load_policy(db)
    if not policy.kind_enabled("chat_unread"):
        return 0
    if await _channel_waiting():
        return 0
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
    rows = await db.execute(pending_candidate_query(now, policy).limit(BATCH_SIZE))
    pairs = rows.all()
    if not pairs:
        return 0

    await resolve_effective_section_access_for_users(db, [user for _, user in pairs])

    sent = 0
    attempts = 0
    for notif, user in pairs:
        if attempts >= MAX_SENDS_PER_PASS:
            break
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
        await db.refresh(
            user, attribute_names=["role", "roles", "is_active", "last_seen_at"]
        )
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
        await db.refresh(notif, attribute_names=["is_read", "email_sent_at"])
        if (
            not user.is_active
            or notif.is_read
            or notif.email_sent_at is not None
            or (user.last_seen_at and user.last_seen_at > threshold)
        ):
            await _release_claim(db, notif.id)
            continue
        if not (await load_policy(db)).allows("chat_unread", notif.created_at):
            await _release_claim(db, notif.id)
            continue
        await _mark_delivery_started(db, notif.id)
        attempts += 1
        ok = False
        try:
            ok = await _send_chat_email(user, notif)
        except (
            Exception
        ):  # Unknown result: keep durable quarantine, no automatic replay.
            logger.warning(
                "chat_email_delivery_uncertain",
                extra={
                    "event_kind": "chat_email_delivery",
                    "failure_kind": "delivery_uncertain",
                },
            )
            continue
        if ok:
            # Only now — after SMTP confirmed — is the row marked as sent.
            await _mark_sent(db, notif.id)
            sent += 1
        else:
            await _defer_notification(db, notif.id)
            if await _channel_waiting():
                break
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
