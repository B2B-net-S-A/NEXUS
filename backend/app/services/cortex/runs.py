"""Cortex — cykl życia przebiegów ekstrakcji (``cortex_extraction_runs``).

Zastępuje dawny in-memory ``_TRAFFIT_JOB`` dict trwałym śladem w DB:
- **restart-safe status** — przeżywa restart/deploy Coolify (był tracony);
- **single-flight** — częściowy unique index ``(source) WHERE status='running'``
  gwarantuje atomowo najwyżej jeden aktywny run (zamiast TOCTOU na fladze
  in-memory, gdzie guard sprawdzał ``running`` przed ``create_task``, a task
  ustawiał flagę później → dwa równoległe backfille). Odporny na wymianę
  połączenia z puli między commitami (advisory lock by tego nie przeżył);
- **orphan reaper** — runy porzucone (task padł bez finalizacji) po stale
  heartbeat → ``failed`` (zwalnia slot single-flight).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cortex import CortexExtractionRun

logger = logging.getLogger(__name__)

# Run bez heartbeatu dłużej niż tyle → uznany za osierocony.
ORPHAN_STALE_SECONDS = 900
# Bump przy zmianie logiki ekstrakcji (provenance na faktach).
EXTRACTOR_VERSION = "traffit-1"


async def create_run(
    db: AsyncSession,
    *,
    run_type: str,
    triggered_by: Optional[str] = None,
    source: str = "traffit",
) -> Optional[int]:
    """Atomowo zarezerwuj slot single-flight. Zwraca ``run_id`` albo ``None`` gdy
    inny run tego źródła już trwa (kolizja na ``uq_cortex_single_running``)."""
    stmt = (
        pg_insert(CortexExtractionRun)
        .values(
            run_type=run_type,
            triggered_by=triggered_by,
            source=source,
            status="running",
            heartbeat_at=func.now(),
        )
        .on_conflict_do_nothing(
            index_elements=["source"],
            index_where=text("status = 'running'"),
        )
        .returning(CortexExtractionRun.id)
    )
    run_id = (await db.execute(stmt)).scalar()
    await db.commit()
    return run_id


async def heartbeat_run(
    db: AsyncSession,
    run_id: int,
    *,
    cursor_candidate_id: Optional[int] = None,
    stats: Optional[dict[str, Any]] = None,
) -> None:
    values: dict[str, Any] = {"heartbeat_at": func.now()}
    if cursor_candidate_id is not None:
        values["cursor_candidate_id"] = cursor_candidate_id
    if stats is not None:
        values["stats"] = stats
    await db.execute(
        update(CortexExtractionRun)
        .where(CortexExtractionRun.id == run_id)
        .values(**values)
    )
    await db.commit()


async def finish_run(
    db: AsyncSession,
    run_id: int,
    *,
    status: str,
    stats: Optional[dict[str, Any]] = None,
    last_error: Optional[str] = None,
) -> None:
    values: dict[str, Any] = {
        "status": status,
        "finished_at": func.now(),
        "heartbeat_at": func.now(),
    }
    if stats is not None:
        values["stats"] = stats
    if last_error is not None:
        values["last_error"] = last_error[:2000]
    await db.execute(
        update(CortexExtractionRun)
        .where(CortexExtractionRun.id == run_id)
        .values(**values)
    )
    await db.commit()


async def reap_orphans(
    db: AsyncSession, *, stale_after_seconds: int = ORPHAN_STALE_SECONDS
) -> int:
    """Oznacz jako ``failed`` runy ``running`` bez świeżego heartbeatu."""
    res = await db.execute(
        text(
            """
            UPDATE cortex_extraction_runs
               SET status = 'failed',
                   finished_at = now(),
                   last_error = COALESCE(last_error, '') || ' [reaped: stale heartbeat]'
             WHERE status = 'running'
               AND COALESCE(heartbeat_at, started_at)
                     < now() - make_interval(secs => :s)
            """
        ),
        {"s": stale_after_seconds},
    )
    await db.commit()
    return res.rowcount or 0


async def has_active_run(
    db: AsyncSession,
    *,
    source: str = "traffit",
    stale_after_seconds: int = ORPHAN_STALE_SECONDS,
) -> bool:
    """Szybki (nieautorytatywny) check dla UX-owego 409 — autorytatywny guard to
    advisory lock w tasku."""
    row = (
        await db.execute(
            text(
                """
                SELECT 1 FROM cortex_extraction_runs
                 WHERE source = :src AND status = 'running'
                   AND COALESCE(heartbeat_at, started_at)
                         > now() - make_interval(secs => :s)
                 LIMIT 1
                """
            ),
            {"src": source, "s": stale_after_seconds},
        )
    ).first()
    return row is not None


async def latest_run(
    db: AsyncSession, *, source: str = "traffit"
) -> Optional[CortexExtractionRun]:
    return (
        await db.execute(
            select(CortexExtractionRun)
            .where(CortexExtractionRun.source == source)
            .order_by(CortexExtractionRun.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
