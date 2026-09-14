"""Measure persisted notification volume without reading notification content."""

import asyncio
import logging

from sqlalchemy import text

from app.core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)
INTERVAL_SECONDS = 300


async def read_notification_volume(db) -> int:
    # A separate READ COMMITTED session sees persisted rows only, including raw
    # SQL writers. Rolled-back inserts and deduplicated attempts cannot inflate
    # this measurement. Bound the scan without introducing a business migration.
    await db.execute(text("SET LOCAL statement_timeout = '2000ms'"))
    result = await db.execute(
        text(
            "SELECT count(*) FROM notifications "
            "WHERE created_at >= CURRENT_TIMESTAMP - interval '5 minutes' "
            "AND created_at < CURRENT_TIMESTAMP"
        )
    )
    return int(result.scalar_one())


async def sample_notification_volume() -> None:
    try:
        async with AsyncSessionLocal() as db:
            count = await read_notification_volume(db)
    except Exception as exc:
        logger.warning(
            "notification_volume",
            extra={
                "event_kind": "notification_volume",
                "monitor_status": "error",
                "failure_kind": type(exc).__name__,
                "window_seconds": INTERVAL_SECONDS,
            },
        )
        return
    logger.info(
        "notification_volume",
        extra={
            "event_kind": "notification_volume",
            "monitor_status": "ok",
            "window_seconds": INTERVAL_SECONDS,
            "persisted_rows": count,
        },
    )


async def notification_volume_monitor_loop() -> None:
    await asyncio.sleep(60)
    while True:
        await sample_notification_volume()
        await asyncio.sleep(INTERVAL_SECONDS)
