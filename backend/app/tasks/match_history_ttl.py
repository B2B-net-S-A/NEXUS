"""
Phase 7c — MatchHistory TTL cleanup.

Periodically delete match_history rows older than N days where total_score
is below a threshold. Keeps the retrospective top-scoring matches for
long-term analysis but prunes the noise.

Runs as a FastAPI background task started from main.py lifespan.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select

from app.core.database import AsyncSessionLocal
from app.models.saved_search import MatchHistory

logger = logging.getLogger(__name__)

_DEFAULT_DAYS = 90
_DEFAULT_MIN_SCORE = 50
_DEFAULT_INTERVAL_HOURS = 24


async def _prune_once(days: int, min_score: int) -> int:
    """Delete rows older than N days with total_score < min_score. Returns row count deleted."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    async with AsyncSessionLocal() as db:
        # Count first (for logging)
        count_q = select(func.count(MatchHistory.id)).where(
            MatchHistory.created_at < cutoff,
            MatchHistory.total_score < min_score,
        )
        to_delete = int((await db.execute(count_q)).scalar() or 0)
        if to_delete == 0:
            return 0
        await db.execute(
            delete(MatchHistory).where(
                MatchHistory.created_at < cutoff,
                MatchHistory.total_score < min_score,
            )
        )
        await db.commit()
        return to_delete


async def match_history_ttl_loop(
    *,
    days: int = _DEFAULT_DAYS,
    min_score: int = _DEFAULT_MIN_SCORE,
    interval_hours: float = _DEFAULT_INTERVAL_HOURS,
) -> None:
    """Long-running task: prune old low-score match history entries every N hours."""
    logger.info(
        "match_history_ttl: started days=%d min_score=%d interval_hours=%.1f",
        days,
        min_score,
        interval_hours,
    )
    # Initial small delay so app startup isn't slowed
    await asyncio.sleep(60)
    while True:
        try:
            deleted = await _prune_once(days, min_score)
            if deleted > 0:
                logger.info("match_history_ttl: pruned %d rows", deleted)
        except Exception:  # noqa: BLE001
            # `exception`, nie `warning`: Sentry ma `event_level=logging.ERROR`
            # (`main.py`), więc na WARNING trwale padający cykl nie wygenerowałby
            # ŻADNEGO zdarzenia — pętla kręciłaby się w kółko, `match_history`
            # rosłoby bez ograniczenia, a jedynym objawem byłby alert o zużyciu
            # dysku po miesiącach. Ta sama decyzja co w `contract_alerts`.
            logger.exception("match_history_ttl: cycle error")
        await asyncio.sleep(interval_hours * 3600)
