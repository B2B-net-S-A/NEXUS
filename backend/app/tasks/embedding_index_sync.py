"""Single-concurrency worker for the transactional embedding outbox."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, text

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.embedding_index_queue import EmbeddingIndexQueue
from app.models.job import Job
from app.services.embedding_service import (
    _build_candidate_text,
    _build_job_text,
    delete_candidate_embedding,
    delete_job_embedding,
    embed_candidate,
    embed_job,
)

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 5
LOCK_TIMEOUT = timedelta(minutes=15)
MAINTENANCE_INTERVAL = timedelta(hours=24)


def source_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def _claim_one() -> tuple[int, str, int, str, str | None, int] | None:
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(EmbeddingIndexQueue)
            .where(
                or_(
                    (EmbeddingIndexQueue.status.in_(("pending", "retry")))
                    & (EmbeddingIndexQueue.available_at <= now),
                    (EmbeddingIndexQueue.status == "processing")
                    & (EmbeddingIndexQueue.locked_at < now - LOCK_TIMEOUT),
                )
            )
            .order_by(EmbeddingIndexQueue.available_at, EmbeddingIndexQueue.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if row is None:
            return None
        row.status = "processing"
        row.locked_at = now
        row.attempts += 1
        await db.commit()
        return (
            row.id,
            row.entity_type,
            row.entity_id,
            row.operation,
            row.source_hash,
            row.attempts,
        )


async def _finish(
    queue_id: int,
    *,
    ok: bool,
    attempts: int,
    new_hash: str | None = None,
    error: str | None = None,
) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(EmbeddingIndexQueue, queue_id)
        if row is None:
            return
        # A DB trigger can enqueue the same entity again while the provider call
        # is in flight.  In that case it resets this row to ``pending`` and the
        # current worker must not overwrite the newer event with ``done``.
        if row.status != "processing" or row.attempts != attempts:
            return
        if ok:
            row.status = "done"
            row.source_hash = new_hash
            row.last_error = None
        elif attempts >= MAX_ATTEMPTS:
            row.status = "dead"
            row.last_error = (error or "embedding sync failed")[:1000]
        else:
            row.status = "retry"
            row.available_at = datetime.now(timezone.utc) + timedelta(
                seconds=min(300, 2**attempts)
            )
            row.last_error = (error or "embedding sync failed")[:1000]
        row.locked_at = None
        await db.commit()


async def _process(claim: tuple[int, str, int, str, str | None, int]) -> None:
    queue_id, entity_type, entity_id, operation, previous_hash, attempts = claim
    try:
        if operation == "delete":
            ok = (
                await delete_candidate_embedding(entity_id)
                if entity_type == "candidate"
                else await delete_job_embedding(entity_id)
            )
            await _finish(queue_id, ok=ok, attempts=attempts)
            return

        async with AsyncSessionLocal() as db:
            if entity_type == "candidate":
                entity = await db.get(Candidate, entity_id)
                text = _build_candidate_text(entity) if entity else ""
            else:
                entity = await db.get(Job, entity_id)
                text = _build_job_text(entity) if entity else ""
            if entity is None:
                await _finish(queue_id, ok=True, attempts=attempts)
                return
            current_hash = source_hash(text)
            if previous_hash == current_hash:
                await _finish(
                    queue_id, ok=True, attempts=attempts, new_hash=current_hash
                )
                return
            ok = (
                await embed_candidate(entity_id, db)
                if entity_type == "candidate"
                else await embed_job(entity_id, db)
            )
        await _finish(
            queue_id,
            ok=ok,
            attempts=attempts,
            new_hash=current_hash if ok else previous_hash,
            error=None if ok else "embedding provider or Qdrant unavailable",
        )
    except Exception as exc:  # noqa: BLE001 - queue must absorb provider failures
        logger.warning(
            "[embedding_index_sync] entity_type=%s entity_id=%s error_type=%s",
            entity_type,
            entity_id,
            type(exc).__name__,
        )
        await _finish(queue_id, ok=False, attempts=attempts, error=type(exc).__name__)


async def _purge_expired_ai_ledger() -> None:
    """Apply the 13-month control-plane retention without another lifespan task."""
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                "DELETE FROM ai_call_ledger WHERE created_at < now() - interval '13 months'"
            )
        )
        await db.execute(
            text(
                "DELETE FROM ai_budget_reservations "
                "WHERE created_at < now() - interval '13 months'"
            )
        )
        # Evaluation outputs are encrypted but intentionally short-lived.
        await db.execute(text("DELETE FROM ai_eval_outputs WHERE expires_at <= now()"))
        await db.commit()


async def embedding_index_sync_loop() -> None:
    if not settings.EMBEDDING_INDEX_SYNC_ENABLED:
        logger.info("[embedding_index_sync] disabled")
        return
    interval = max(1, int(settings.EMBEDDING_INDEX_SYNC_INTERVAL_SECONDS))
    last_maintenance: datetime | None = None
    while True:
        try:
            now = datetime.now(timezone.utc)
            if (
                last_maintenance is None
                or now - last_maintenance >= MAINTENANCE_INTERVAL
            ):
                await _purge_expired_ai_ledger()
                last_maintenance = now
            claim = await _claim_one()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - keep worker alive on DB recovery
            logger.warning(
                "[embedding_index_sync] loop error_type=%s", type(exc).__name__
            )
            await asyncio.sleep(interval)
            continue
        if claim is None:
            await asyncio.sleep(interval)
        else:
            await _process(claim)
