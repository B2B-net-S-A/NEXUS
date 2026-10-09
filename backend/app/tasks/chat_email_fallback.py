"""Chat mail fallback with bounded retry and durable delivery uncertainty.

The sender circuit is shared across processes. Claims prevent concurrent sends;
marking uncertainty BEFORE the external call prevents replay after a crash in
its ambiguous acceptance window. Definite rejection schedules a later attempt.
No automatic deletion or expiration of pending business notifications.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone

from sqlalchemy import exists, false, func, or_, select, tuple_, update
from sqlalchemy.orm import aliased
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
from app.services.notification_delivery import (
    DeliveryPolicy,
    email_queue_clause,
    email_wanted,
    load_policy,
)

logger = logging.getLogger(__name__)

# Tunable: po ilu minutach offline trigger email
OFFLINE_THRESHOLD_MIN = 15
# Co ile sekund cykl
LOOP_SLEEP_SEC = 60
# Maksymalna paczka w jednym przebiegu (zapobiega N+1)
BATCH_SIZE = 100
# Ile paczek przejrzeć w jednym przebiegu, gdy pierwsza składa się z wierszy
# odrzuconych w Pythonie (sekcja, rola, osoba online) — runda 9 (R9-N2-1).
MAX_BATCHES_PER_PASS = 10
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


def pending_candidate_query(
    now: datetime,
    policy: DeliveryPolicy | None = None,
    *,
    exclude_user_ids: Iterable[int] = (),
    after: tuple[datetime, int] | None = None,
):
    """SQL candidate queue; final section access is checked by the worker.

    Reused by monitoring so unattempted rows are included in backlog evidence.
    This is an upper bound, not a promise that every row will be emailed.

    ``exclude_user_ids`` — osoby z otwartym gniazdem w tym procesie (są
    online, choć ``last_seen_at`` stemplujemy co kilka minut); ``after`` —
    klucz ostatniego obejrzanego wiersza (keyset), żeby przebieg mógł zajrzeć
    dalej niż pierwsza setka (runda 9, R9-N2-1 i R9-N2-2).
    """
    threshold = now - timedelta(minutes=OFFLINE_THRESHOLD_MIN)
    stale_cutoff = now - timedelta(minutes=CLAIM_STALE_MIN)
    policy = policy or DeliveryPolicy()
    query = (
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
        .where(~_newer_in_same_thread())
        # Admin jest dopisywany do KAŻDEGO czatu rekrutacji („komplet obsady”),
        # więc mail o zwykłej wiadomości szedłby do niego z całej firmy; mail
        # dostaje tylko wtedy, gdy ktoś go oznaczył (runda 7, R7-N5-3).
        .where(
            or_(
                Notification.notification_type == NotificationType.job_chat_mention,
                User.role != UserRole.admin,
            )
        )
        # Wyciszony „Czat" (0349) odpada już w SQL. Do rundy 9 odrzucał go
        # Python, więc setka takich wierszy na czele kolejki (najstarsze)
        # blokowała maile czatu wszystkim innym (R9-N2-1). Wzmianki są
        # kategorią obowiązkową — wyciszyć ich nie można.
        .where(
            or_(
                Notification.notification_type != NotificationType.job_chat_message,
                ~User.muted_notification_categories.has_key("chat"),
            )
        )
        # Własny wyłącznik maila („Maile do Ciebie”) — z tego samego powodu.
        .where(email_queue_clause("chat_unread", Notification.created_at))
        .order_by(Notification.created_at.asc(), Notification.id.asc())
    )
    excluded = sorted({int(uid) for uid in exclude_user_ids})
    if excluded:
        query = query.where(User.id.not_in(excluded))
    if after is not None:
        query = query.where(
            tuple_(Notification.created_at, Notification.id) > tuple_(*after)
        )
    return query


def _newer_in_same_thread():
    """Czy ta osoba ma nowsze powiadomienie z tego samego czatu (runda 7, R7-N5-3).

    Wzmianka to DWA powiadomienia o jednej wiadomości (`job_chat_message`
    i `job_chat_mention`), a każda kolejna wiadomość w wątku — następne; bez
    tego osoba offline dostawała osobny mail za każde z nich. Mail idzie tylko
    o najnowszym powiadomieniu wątku (link bez `&msg=`); przeczytane albo już
    wysłane nowsze też wystarcza — wątek był otwarty albo zgłoszony.
    """
    newer = aliased(Notification)
    thread = func.split_part(Notification.link, "&msg=", 1)
    return exists().where(
        newer.user_id == Notification.user_id,
        newer.notification_type.in_(_CHAT_NOTIF_TYPES),
        newer.id > Notification.id,
        func.split_part(newer.link, "&msg=", 1) == thread,
        # Nowsze powiadomienie wstrzymuje mail tylko wtedy, gdy samo może
        # dostać maila — admin dostaje wyłącznie wzmianki, więc zwykła
        # wiadomość w wątku nie może zjeść jego maila o wzmiance.
        or_(
            User.role != UserRole.admin,
            newer.notification_type == NotificationType.job_chat_mention,
        ),
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
    online = _online_user_ids()
    sent = 0
    attempts = 0
    after: tuple[datetime, int] | None = None
    # Keyset po (created_at, id): wiersze odrzucone w Pythonie (sekcja, rola)
    # nie zajmują już całego przebiegu — kolejna paczka zaczyna się za nimi
    # (runda 9, R9-N2-1).
    for _batch in range(MAX_BATCHES_PER_PASS):
        rows = await db.execute(
            pending_candidate_query(
                now, policy, exclude_user_ids=online, after=after
            ).limit(BATCH_SIZE)
        )
        pairs = rows.all()
        if not pairs:
            break
        last_notif = pairs[-1][0]
        after = (last_notif.created_at, last_notif.id)
        await resolve_effective_section_access_for_users(
            db, [user for _, user in pairs]
        )
        batch_sent, attempts, stop = await _process_batch(
            db, pairs, threshold=threshold, attempts=attempts
        )
        sent += batch_sent
        if stop or len(pairs) < BATCH_SIZE:
            break
    return sent


def _online_user_ids() -> frozenset[int]:
    """Osoby z otwartym gniazdem powiadomień (runda 9, R9-N2-2).

    ``last_seen_at`` stemplujemy przy połączeniu, rozłączeniu i co kilka
    minut podtrzymania, ale osoba z otwartą kartą jest online niezależnie od
    stempla. Backend to jeden proces uvicorna, więc menedżer gniazd zna
    wszystkich podłączonych.
    """
    try:
        from app.api.ws import manager

        return frozenset(manager.get_connected_user_ids())
    except Exception:  # noqa: BLE001 — bez menedżera zostaje sam stempel
        return frozenset()


async def _process_batch(
    db: AsyncSession,
    pairs,
    *,
    threshold: datetime,
    attempts: int,
) -> tuple[int, int, bool]:
    """Obsłuż jedną paczkę. Zwraca (wysłane, próby łącznie, czy przerwać)."""
    sent = 0
    for notif, user in pairs:
        if attempts >= MAX_SENDS_PER_PASS:
            return sent, attempts, True
        # Role changes can race with the SELECT. Re-evaluate the complete,
        # current role union before even claiming the notification; a stale
        # unread chat row must never email candidate/recruitment PII to Finance.
        if (
            not _eligible_chat_email_recipient(user)
            # Własny wyłącznik maila („Maile do Ciebie”); dzwonek zostaje.
            or not email_wanted(user, "chat_unread", notif.created_at)
            or not user_can_receive_notification(
                user,
                notif.notification_type,
                related_entity_type=notif.related_entity_type,
                link=notif.link,
            )
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
            user,
            attribute_names=[
                "role",
                "roles",
                "is_active",
                "last_seen_at",
                "email_opt_outs",
            ],
        )
        await resolve_effective_section_access(db, user)
        if (
            not _eligible_chat_email_recipient(user)
            or not email_wanted(user, "chat_unread", notif.created_at)
            or not user_can_receive_notification(
                user,
                notif.notification_type,
                related_entity_type=notif.related_entity_type,
                link=notif.link,
            )
        ):
            await _release_claim(db, notif.id)
            continue
        # Runda 10 (R10-N6-3): usunięta albo poprawiona wiadomość zmienia
        # `is_read` / `message` powiadomienia — mail ma nieść stan z bazy.
        await db.refresh(
            notif, attribute_names=["is_read", "email_sent_at", "message", "title"]
        )
        if (
            not user.is_active
            or notif.is_read
            or notif.email_sent_at is not None
            or (user.last_seen_at and user.last_seen_at > threshold)
            # Kartę mógł otworzyć między SELECT-em a rezerwacją.
            or user.id in _online_user_ids()
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
                return sent, attempts, True
    return sent, attempts, False


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
