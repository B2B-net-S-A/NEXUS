"""Independent heartbeat for system mail delivery, retries and uncertain results."""

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import func, select, text

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.services import loop_heartbeat
from app.services.m365 import app_mail, mail_circuit
from app.tasks.chat_email_fallback import pending_candidate_query

logger = logging.getLogger(__name__)
INTERVAL_SECONDS = 60


def verdict(*, enabled: bool, configured: bool, state: dict, queue: dict) -> int:
    if not enabled:
        return 0
    return int(
        not configured
        or bool(state.get("consecutive_failures"))
        or queue["uncertain"] > 0
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
            row = (
                (
                    await db.execute(
                        text("""
                SELECT count(*) FILTER (WHERE email_delivery_uncertain) AS uncertain,
                  count(*) FILTER (WHERE email_next_attempt_at IS NOT NULL AND NOT n.is_read AND u.is_active) AS pending_retry,
                  coalesce(max(extract(epoch FROM (now() - n.created_at))) FILTER
                    (WHERE email_next_attempt_at IS NOT NULL AND NOT n.is_read AND u.is_active), 0) AS oldest_retry_seconds
                FROM notifications n JOIN users u ON u.id=n.user_id
                WHERE email_sent_at IS NULL AND
                  (email_delivery_uncertain OR email_next_attempt_at IS NOT NULL)
            """)
                    )
                )
                .mappings()
                .one()
            )
            queue = {key: int(value) for key, value in row.items()}
            candidates = (
                pending_candidate_query(datetime.now(timezone.utc))
                .order_by(None)
                .subquery()
            )
            queue["ready_candidates_upper_bound"] = int(
                (
                    await db.execute(select(func.count()).select_from(candidates))
                ).scalar_one()
            )
        configured = app_mail.is_configured()
        logger.info(
            "app_mail_monitor",
            extra={
                "event_kind": "app_mail_monitor",
                "monitor_status": "ok",
                "enabled": settings.M365_APP_MAIL_ENABLED,
                "alarm": verdict(
                    enabled=settings.M365_APP_MAIL_ENABLED,
                    configured=configured,
                    state=state,
                    queue=queue,
                ),
                "delivery_status": app_mail.app_mail_send_verdict(
                    app_mail.AppMailSendState(
                        **{
                            k: state[k]
                            for k in app_mail.AppMailSendState.__dataclass_fields__
                            if k in state
                        }
                    ),
                    configured=configured,
                ),
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
