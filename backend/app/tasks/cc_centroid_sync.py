"""Background task: CC + talent pool centroid synchronization.

Uruchamiany przez lifespan w `main.py`:
  - One-shot bootstrap przy starcie (jeśli żadna CC nie ma embedding_id).
  - Okresowo (co 24h) refresh stale pul + CC.

Nie blokuje startupu — każdy błąd jest logowany, ale nie podnosi wyjątku.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.competence_category import CompetenceCategory
from app.services.cc_centroid_service import (
    _ensure_centroid_collections,
    compute_cc_centroid,
    refresh_stale_centroids,
)

logger = logging.getLogger(__name__)

BOOTSTRAP_DELAY_SECONDS = 30  # wait for Qdrant collections to be up
REFRESH_INTERVAL_SECONDS = 24 * 60 * 60  # 24h


async def _bootstrap_if_needed(db: AsyncSession) -> None:
    """Run compute_cc_centroid for every CC without embedding_id."""
    rows = (
        await db.execute(
            select(CompetenceCategory.id).where(
                CompetenceCategory.embedding_id.is_(None)
            )
        )
    ).all()
    cc_ids = [r[0] for r in rows]
    if not cc_ids:
        logger.info("[cc_centroid_sync] All CCs already have embeddings — skipping bootstrap.")
        return
    logger.info(
        "[cc_centroid_sync] Bootstrapping centroids for %d CCs…", len(cc_ids)
    )
    for cc_id in cc_ids:
        try:
            await compute_cc_centroid(db, cc_id)
        except Exception as e:
            logger.warning(
                "[cc_centroid_sync] bootstrap failed for CC %s: %s", cc_id, e
            )


async def cc_centroid_sync_loop() -> None:
    """Long-running loop: bootstrap once, then refresh every 24h."""
    # Delay startup so Qdrant + DB are ready and DEBUG `create_all` has run.
    try:
        await asyncio.sleep(BOOTSTRAP_DELAY_SECONDS)
    except asyncio.CancelledError:
        return

    # Ensure Qdrant collections exist
    try:
        await asyncio.to_thread(_ensure_centroid_collections)
    except Exception as e:
        logger.warning("[cc_centroid_sync] ensure_centroid_collections failed: %s", e)

    # Bootstrap
    try:
        async with AsyncSessionLocal() as db:
            await _bootstrap_if_needed(db)
    except Exception as e:
        logger.warning("[cc_centroid_sync] bootstrap failed: %s", e)

    # Steady-state loop: refresh stale centroids every 24h
    while True:
        try:
            await asyncio.sleep(REFRESH_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            return
        try:
            async with AsyncSessionLocal() as db:
                stats = await refresh_stale_centroids(db, stale_days=7)
            logger.info("[cc_centroid_sync] refresh complete: %s", stats)
        except Exception as e:
            logger.warning("[cc_centroid_sync] refresh failed: %s", e)
