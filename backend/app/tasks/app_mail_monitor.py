"""Independent heartbeat for system mail delivery, retries and uncertain results."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, false, func, select, text

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.notification import Notification, NotificationType
from app.models.user import User
from app.services import loop_heartbeat
from app.services.m365 import app_mail, mail_circuit
from app.services.notification_delivery import DeliveryPolicy, load_policy
from app.tasks.chat_email_fallback import pending_candidate_query

logger = logging.getLogger(__name__)
INTERVAL_SECONDS = 60
# Runda 7 (R7-N5-4): alarm liczy tylko NIEDAWNE niepewne wysyłki. Flagi nikt
# nie czyści (i nie wolno — chroni przed duplikatem), więc liczona bez okna
# trzymała alarm na zawsze po pierwszym incydencie, a nowego nie dało się
# odróżnić od starego. Łączna liczba zostaje w logu jako `uncertain`.
UNCERTAIN_ALARM_WINDOW = timedelta(hours=24)


async def snapshot_queue(db, policy: DeliveryPolicy, now: datetime) -> dict:
    """Chat fallback queue only; policy-suppressed history is never a retry.

    Other routine channels have separate dispatchers. Uncertain deliveries
    remain visible even when disabled, without making them eligible to resend.
    """
    cutoff = policy.cutoff_for("chat_unread")
    permitted = (
        Notification.created_at >= cutoff
        if policy.kind_enabled("chat_unread") and cutoff is not None
        else false()
    )
    unread_active = and_(Notification.is_read.is_(False), User.is_active.is_(True))
    pending = and_(
        permitted, unread_active, Notification.email_next_attempt_at.is_not(None)
    )
    row = (
        (
            await db.execute(
                select(
                    func.count()
                    .filter(Notification.email_delivery_uncertain.is_(True))
                    .label("uncertain"),
                    func.count()
                    .filter(
                        Notification.email_delivery_uncertain.is_(True),
                        func.coalesce(
                            Notification.email_send_started_at,
                            Notification.created_at,
                        )
                        >= now - UNCERTAIN_ALARM_WINDOW,
                    )
                    .label("uncertain_recent"),
                    func.count().filter(pending).label("pending_retry"),
                    func.coalesce(
                        func.max(
                            func.extract("epoch", now - Notification.created_at)
                        ).filter(pending),
                        0,
                    ).label("oldest_retry_seconds"),
                    func.count()
                    .filter(and_(~permitted, unread_active))
                    .label("legacy_suppressed"),
                )
                .select_from(Notification)
                .join(User, User.id == Notification.user_id)
                .where(
                    Notification.notification_type.in_(
                        [
                            NotificationType.job_chat_message,
                            NotificationType.job_chat_mention,
                        ]
                    ),
                    Notification.email_sent_at.is_(None),
                )
            )
        )
        .mappings()
        .one()
    )
    queue = {key: int(value) for key, value in row.items()}
    candidates = pending_candidate_query(now, policy).order_by(None).subquery()
    queue["ready_candidates_upper_bound"] = int(
        (await db.execute(select(func.count()).select_from(candidates))).scalar_one()
    )
    return {**queue, "scope": "chat_unread"}


def verdict(*, enabled: bool, configured: bool, state: dict, queue: dict) -> int:
    if not enabled:
        return 0
    return int(
        not configured
        or bool(state.get("consecutive_failures"))
        or queue["uncertain_recent"] > 0
        or queue["oldest_retry_seconds"] > 3600
    )


async def sample_app_mail() -> None:
    try:
        state = (
            await asyncio.to_thread(mail_circuit.snapshot)
            if settings.M365_APP_MAIL_ENABLED
            else {}
        )
        async with AsyncSessionLocal() as db:
            await db.execute(text("SET LOCAL statement_timeout = '2000ms'"))
            policy = await load_policy(db)
            queue = await snapshot_queue(db, policy, datetime.now(timezone.utc))
        configured = app_mail.is_configured()
        enabled = settings.M365_APP_MAIL_ENABLED and policy.effective_enabled
        provider_status = app_mail.app_mail_send_verdict(
            app_mail.AppMailSendState(
                **{
                    k: state[k]
                    for k in app_mail.AppMailSendState.__dataclass_fields__
                    if k in state
                }
            ),
            configured=configured,
        )
        logger.info(
            "app_mail_monitor",
            extra={
                "event_kind": "app_mail_monitor",
                "monitor_status": "ok",
                "enabled": enabled,
                "policy_enabled": policy.effective_enabled,
                "provider_enabled": settings.M365_APP_MAIL_ENABLED,
                "alarm": verdict(
                    enabled=enabled,
                    configured=configured,
                    state=state,
                    queue=queue,
                ),
                "delivery_status": provider_status
                if policy.effective_enabled
                else "disabled",
                "provider_status": provider_status,
                **queue,
                "attempts": state.get("attempts", 0),
                "failures": state.get("failures", 0),
                "failure_kind": state.get("last_failure_code") or "none",
            },
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning(
            "app_mail_monitor",
            extra={
                "event_kind": "app_mail_monitor",
                "monitor_status": "error",
                "alarm": 1,
            },
        )


async def app_mail_monitor_loop() -> None:
    beat = loop_heartbeat.register(
        "app_mail_monitor", max_silence_seconds=INTERVAL_SECONDS * 3
    )
    while True:
        beat.tick()
        await sample_app_mail()
        await asyncio.sleep(INTERVAL_SECONDS)
