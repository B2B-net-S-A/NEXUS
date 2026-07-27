"""Indexing outbox service (plan PR5).

Enqueue side (hot path) and worker side (background drain) for the durable
reindex queue. Everything is flag-gated:

* ``AI_INDEX_OUTBOX_ENABLED`` — ``schedule_or_embed_*`` enqueues instead of
  embedding inline. OFF ⇒ inline embed, byte-for-byte the current behaviour.
* ``AI_INDEX_WORKER_ENABLED`` — the worker loop drains the queue. OFF ⇒ no-op.

The worker builds the document + content hash in Python (never a DB trigger),
uses ``FOR UPDATE SKIP LOCKED`` so multiple workers don't collide, and applies
compare-and-set so a stale event can never overwrite a newer index state.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.index_outbox import IndexOutboxEvent

logger = logging.getLogger(__name__)

CANDIDATE = "candidate"
JOB = "job"

# reindex_fn(entity_type, entity_id, operation) -> awaitable[bool]
ReindexFn = Callable[[str, int, str], Awaitable[bool]]


def outbox_enabled() -> bool:
    return bool(getattr(settings, "AI_INDEX_OUTBOX_ENABLED", False))


def worker_enabled() -> bool:
    return bool(getattr(settings, "AI_INDEX_WORKER_ENABLED", False))


def _revision(entity) -> int:
    """Monotonic revision from the entity's updated_at (epoch micros)."""
    ts = getattr(entity, "updated_at", None) or getattr(entity, "created_at", None)
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return int(ts.timestamp() * 1_000_000)
    return 0


def _desired_hash(entity_type: str, entity) -> str:
    from app.services.embedding_service import (
        _build_candidate_text,
        _build_job_text,
    )

    text_blob = (
        _build_candidate_text(entity)
        if entity_type == CANDIDATE
        else _build_job_text(entity)
    )
    return hashlib.sha256((text_blob or "").encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DesiredState:
    revision: int
    desired_hash: str


def desired_state(entity_type: str, entity) -> DesiredState:
    return DesiredState(_revision(entity), _desired_hash(entity_type, entity))


# ── Enqueue side ──────────────────────────────────────────────────────────────


async def enqueue(
    db: AsyncSession,
    *,
    entity_type: str,
    entity_id: int,
    revision: int,
    desired_hash: str,
    operation: str = "upsert",
) -> None:
    """Insert a pending reindex event in the CALLER's transaction (no commit).

    No-op when the outbox flag is off. Idempotent-ish: a fresh pending row per
    change is fine — the worker's compare-and-set collapses superseded events.
    """
    if not outbox_enabled():
        return
    db.add(
        IndexOutboxEvent(
            entity_type=entity_type,
            entity_id=entity_id,
            entity_revision=revision,
            desired_hash=desired_hash,
            operation=operation,
            status="pending",
        )
    )


async def schedule_or_embed_candidate(candidate_id: int, db: AsyncSession) -> bool:
    """Outbox-on ⇒ enqueue an upsert; outbox-off ⇒ embed inline (legacy)."""
    from app.services.embedding_service import embed_candidate

    if not outbox_enabled():
        return await embed_candidate(candidate_id, db)

    from app.models.candidate import Candidate

    entity = await db.get(Candidate, candidate_id)
    if entity is None:
        await _enqueue_isolated(
            entity_type=CANDIDATE,
            entity_id=candidate_id,
            revision=0,
            desired_hash="",
            operation="delete",
        )
    else:
        st = desired_state(CANDIDATE, entity)
        await _enqueue_isolated(
            entity_type=CANDIDATE,
            entity_id=candidate_id,
            revision=st.revision,
            desired_hash=st.desired_hash,
        )
    return True


async def schedule_or_embed_job(job_id: int, db: AsyncSession) -> bool:
    from app.services.embedding_service import embed_job

    if not outbox_enabled():
        return await embed_job(job_id, db)

    from app.models.job import Job

    entity = await db.get(Job, job_id)
    if entity is None:
        await _enqueue_isolated(
            entity_type=JOB,
            entity_id=job_id,
            revision=0,
            desired_hash="",
            operation="delete",
        )
    else:
        st = desired_state(JOB, entity)
        await _enqueue_isolated(
            entity_type=JOB,
            entity_id=job_id,
            revision=st.revision,
            desired_hash=st.desired_hash,
        )
    return True


async def _enqueue_isolated(
    *,
    entity_type: str,
    entity_id: int,
    revision: int,
    desired_hash: str,
    operation: str = "upsert",
) -> None:
    """Persist one pending reindex event on a DEDICATED session (M3-TX-01).

    The enqueue runs post-write on the hot path (candidate edit / CV upload /
    job save) and is strictly best-effort — those call-sites document that a
    reindex failure must never surface to, or roll back, the business write.

    The previous wrapper committed the CALLER's request session and, on failure,
    ``rollback()``-ed it, so a transient outbox hiccup could discard the
    unrelated edit that the endpoint had only flushed (it relies on
    ``get_db``'s end-of-request commit). Inserting on its own
    ``AsyncSessionLocal`` fully isolates the failure (mirroring
    :func:`_default_reindex`) and keeps the durable-at-return semantics the
    call-sites expect. No-op when the outbox flag is off.
    """
    if not outbox_enabled():
        return
    from app.core.database import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as s:
            s.add(
                IndexOutboxEvent(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    entity_revision=revision,
                    desired_hash=desired_hash,
                    operation=operation,
                    status="pending",
                )
            )
            await s.commit()
    except Exception as exc:  # noqa: BLE001 — enqueue is best-effort
        logger.warning("[index-outbox] enqueue failed: %s", exc)


# ── Worker side ───────────────────────────────────────────────────────────────


async def claim_batch(db: AsyncSession, limit: int) -> list[IndexOutboxEvent]:
    """Atomically claim up to ``limit`` pending/failed events (SKIP LOCKED)."""
    rows = (
        (
            await db.execute(
                select(IndexOutboxEvent)
                .where(IndexOutboxEvent.status.in_(("pending", "failed")))
                .order_by(IndexOutboxEvent.created_at.asc())
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    now = datetime.now(timezone.utc)
    for ev in rows:
        ev.status = "processing"
        ev.heartbeat_at = now
    await db.flush()
    return list(rows)


async def _default_reindex(entity_type: str, entity_id: int, operation: str) -> bool:
    from app.services import embedding_service as emb
    from app.core.database import AsyncSessionLocal

    if operation == "delete":
        if entity_type == CANDIDATE:
            return await emb.delete_candidate_embedding(entity_id)
        return True  # job tombstone: best-effort, jobs rarely hard-deleted
    async with AsyncSessionLocal() as s:
        if entity_type == CANDIDATE:
            return await emb.embed_candidate(entity_id, s)
        return await emb.embed_job(entity_id, s)


async def _superseded(db: AsyncSession, ev: IndexOutboxEvent) -> bool:
    """True if a newer revision for the same entity is already indexed done."""
    newer = await db.scalar(
        select(func.count(IndexOutboxEvent.id)).where(
            IndexOutboxEvent.entity_type == ev.entity_type,
            IndexOutboxEvent.entity_id == ev.entity_id,
            IndexOutboxEvent.status == "done",
            IndexOutboxEvent.indexed_revision > ev.entity_revision,
        )
    )
    return bool(newer)


async def process_event(
    db: AsyncSession,
    ev: IndexOutboxEvent,
    *,
    reindex_fn: Optional[ReindexFn] = None,
) -> str:
    """Process one claimed event. Returns the resulting status.

    Compare-and-set: an event whose revision is older than an already-indexed
    newer revision is marked ``done`` without touching the index.
    """
    fn = reindex_fn or _default_reindex
    max_attempts = int(getattr(settings, "AI_INDEX_MAX_ATTEMPTS", 5))

    if ev.operation == "upsert" and await _superseded(db, ev):
        ev.status = "done"
        ev.last_error = "superseded by newer revision"
        await db.flush()
        return ev.status

    try:
        ok = await fn(ev.entity_type, ev.entity_id, ev.operation)
        if ok:
            ev.status = "done"
            ev.indexed_hash = ev.desired_hash
            ev.indexed_revision = ev.entity_revision
            ev.last_error = None
            # A candidate's semantic vector just changed → any cached match
            # score for that candidate now embeds a stale semantic layer
            # (AI-P0-06 b). Invalidate so the next read recomputes. Local import
            # avoids an import cycle (match_score_cache → scoring_service).
            if ev.entity_type == CANDIDATE and ev.operation == "upsert":
                from app.services.match_score_cache import mark_stale_for_candidate

                await mark_stale_for_candidate(db, ev.entity_id)
        else:
            raise RuntimeError("reindex returned False")
    except Exception as exc:  # noqa: BLE001
        ev.attempts += 1
        ev.last_error = str(exc)[:500]
        ev.status = "dead" if ev.attempts >= max_attempts else "failed"
        logger.warning(
            "[index-outbox] event %s (%s:%s) → %s (attempt %s): %s",
            ev.id,
            ev.entity_type,
            ev.entity_id,
            ev.status,
            ev.attempts,
            exc,
        )
    await db.flush()
    return ev.status


async def drain_once(
    db: AsyncSession, *, batch: int, reindex_fn: Optional[ReindexFn] = None
) -> dict:
    """Claim + process one batch. Returns per-status counts."""
    events = await claim_batch(db, batch)
    counts: dict[str, int] = {}
    for ev in events:
        status = await process_event(db, ev, reindex_fn=reindex_fn)
        counts[status] = counts.get(status, 0) + 1
    await db.commit()
    return counts


async def diagnostics(db: AsyncSession) -> dict:
    """Queue depth, oldest-pending age and failure/dead counts."""
    by_status = dict(
        (
            await db.execute(
                select(
                    IndexOutboxEvent.status, func.count(IndexOutboxEvent.id)
                ).group_by(IndexOutboxEvent.status)
            )
        ).all()
    )
    oldest = await db.scalar(
        select(func.min(IndexOutboxEvent.created_at)).where(
            IndexOutboxEvent.status.in_(("pending", "failed"))
        )
    )
    oldest_age = None
    if oldest is not None:
        if oldest.tzinfo is None:
            oldest = oldest.replace(tzinfo=timezone.utc)
        oldest_age = (datetime.now(timezone.utc) - oldest).total_seconds()
    return {
        "by_status": {k: int(v) for k, v in by_status.items()},
        "queue_depth": int(by_status.get("pending", 0))
        + int(by_status.get("failed", 0)),
        "oldest_pending_age_seconds": oldest_age,
        "dead": int(by_status.get("dead", 0)),
    }
