"""Retention purge for dialer call recordings (RODO).

Audio recordings hold candidate voice data, so they are deleted after
``settings.DIALER_RECORDING_RETENTION_DAYS`` (default 60). Transcripts and the
``Note`` summaries are kept longer under the candidate-data retention policy and
are NOT touched here — only the audio blob is removed and
``Call.recording_storage_key`` is nulled.

Runs as a kill-switched background loop (``OWN_DIALER_ENABLED``), checking a few
times per day. The reconciliation of missed recording webhooks is a separate
concern handled once the gateway is live.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.call import Call

logger = logging.getLogger(__name__)

# Check 4×/day — recordings only need coarse-grained purging.
_PURGE_INTERVAL_SECONDS = 6 * 3600


async def purge_expired_recordings(
    db: AsyncSession, *, now: Optional[datetime] = None
) -> int:
    """Delete recordings older than the retention window and null their key.

    Returns the number of recordings purged. The caller's session is committed
    here. Deletion from Object Storage is best-effort: on a storage error we log
    and still null the key (RODO intent = stop referencing the audio; a rare
    orphaned blob is acceptable and swept by storage lifecycle).
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=settings.DIALER_RECORDING_RETENTION_DAYS)

    rows = (
        (
            await db.execute(
                select(Call).where(
                    Call.recording_storage_key.isnot(None),
                    Call.created_at < cutoff,
                )
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return 0

    from app.services.object_storage import delete_cv, is_available

    purged = 0
    for call in rows:
        key = call.recording_storage_key
        try:
            if is_available() and key:
                delete_cv(key)
        except Exception as exc:  # noqa: BLE001 — best-effort; still null below
            logger.warning(
                "dialer retention: storage delete failed for key=%s call=%s: %s",
                key,
                call.id,
                exc,
            )
        call.recording_storage_key = None
        purged += 1

    await db.commit()
    return purged


async def dialer_retention_loop() -> None:
    """Periodic recording-retention purge. Cancellation-aware."""
    logger.info("Dialer retention loop started")
    while True:
        try:
            if not settings.OWN_DIALER_ENABLED:
                await asyncio.sleep(300)
                continue
            try:
                async with AsyncSessionLocal() as db:
                    purged = await purge_expired_recordings(db)
                if purged:
                    logger.info(
                        "dialer retention: purged %d expired recording(s)", purged
                    )
            except Exception:  # noqa: BLE001
                logger.exception("dialer retention iteration crashed")
            await asyncio.sleep(_PURGE_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            logger.info("Dialer retention loop cancelled — shutting down")
            return
