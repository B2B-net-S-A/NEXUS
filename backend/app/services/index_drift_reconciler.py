"""Find entities whose indexed vector no longer matches their content.

The writers are the problem, and patching them one by one does not fix it.
Three Traffit import phases — ``import_candidates_cv``, ``enrich_missing_names``
and ``import_candidate_files`` — change fields that feed the embedding text
(``lastname``, ``ai_summary``, ``raw_cv_text``) and record no reindex intent at
all. The June 2026 cohort sitting at 0.02% index coverage is not an anomaly;
it is what this system does by default, because every writer has to *remember*
to say "I changed something the index cares about".

So nobody is asked to remember. This walks entities in batches, recomputes the
hash the index *should* hold, compares it with the hash the outbox recorded as
*actually* indexed, and enqueues the difference. ``record_bulk_reindex`` in the
importer becomes a latency optimisation rather than a correctness requirement.

No migration: :class:`IndexOutboxEvent` already stores ``indexed_hash`` and
``indexed_revision`` per entity, which is exactly the "what does the index hold"
side of the comparison.

Scope, deliberately narrow: an entity the outbox has never seen is **skipped**.
Those are not drift — they are the initial-population gap, whose tool is
``reembed_collections --only-missing``. Treating them as drift here would
enqueue tens of thousands of re-embeds on the first tick and bill the full
import over again.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.index_outbox import IndexOutboxEvent
from app.services import index_outbox_service as outbox

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReconcileResult:
    scanned: int
    drifted: int
    unseen: int
    next_cursor: Optional[int]

    def as_log(self) -> str:
        return (
            f"scanned={self.scanned} drifted={self.drifted} "
            f"unseen(skipped)={self.unseen} next_cursor={self.next_cursor}"
        )


def _model_for(entity_type: str):
    if entity_type == outbox.CANDIDATE:
        from app.models.candidate import Candidate

        return Candidate
    if entity_type == outbox.JOB:
        from app.models.job import Job

        return Job
    raise ValueError(f"unknown entity type {entity_type!r}")


async def _last_indexed_hashes(
    db: AsyncSession, entity_type: str, entity_ids: list[int]
) -> dict[int, str]:
    """Newest recorded ``indexed_hash`` per entity, from completed events.

    Only ``done`` rows count: a pending or failed event describes an intent,
    not the state of the index, and treating it as the latter would make the
    reconciler consider work already handled while the vector is still stale.
    """
    if not entity_ids:
        return {}

    newest = (
        select(
            IndexOutboxEvent.entity_id,
            func.max(IndexOutboxEvent.id).label("last_id"),
        )
        .where(
            IndexOutboxEvent.entity_type == entity_type,
            IndexOutboxEvent.entity_id.in_(entity_ids),
            IndexOutboxEvent.status == "done",
            IndexOutboxEvent.indexed_hash.is_not(None),
        )
        .group_by(IndexOutboxEvent.entity_id)
        .subquery()
    )
    rows = await db.execute(
        select(IndexOutboxEvent.entity_id, IndexOutboxEvent.indexed_hash).join(
            newest, IndexOutboxEvent.id == newest.c.last_id
        )
    )
    return {int(eid): h for eid, h in rows.all() if h}


async def reconcile_once(
    db: AsyncSession,
    *,
    entity_type: str,
    batch: int = 500,
    cursor: int = 0,
    include_unseen: bool = False,
) -> ReconcileResult:
    """Scan one batch of entities and enqueue those whose hash has drifted.

    ``cursor`` is the last id examined, so a caller can walk the whole table
    across ticks without holding a transaction open or loading it into memory.
    Returns ``next_cursor=None`` once the end is reached.
    """
    model = _model_for(entity_type)
    rows = (
        (
            await db.execute(
                select(model)
                .where(model.id > cursor)
                .order_by(model.id.asc())
                .limit(batch)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return ReconcileResult(scanned=0, drifted=0, unseen=0, next_cursor=None)

    ids = [int(r.id) for r in rows]
    indexed = await _last_indexed_hashes(db, entity_type, ids)

    drifted = 0
    unseen = 0
    to_enqueue: list[int] = []
    for row in rows:
        entity_id = int(row.id)
        known = indexed.get(entity_id)
        if known is None:
            unseen += 1
            if include_unseen:
                to_enqueue.append(entity_id)
            continue
        desired = outbox.desired_state(entity_type, row)
        if desired.desired_hash != known:
            drifted += 1
            to_enqueue.append(entity_id)

    if to_enqueue:
        # Writes in the caller's transaction and deliberately ignores
        # AI_INDEX_OUTBOX_ENABLED — recording that something needs reindexing is
        # not the same decision as routing writes through the outbox, and a
        # reconciler that silently records nothing would be worse than absent.
        await outbox.record_bulk_reindex(db, entity_type, to_enqueue)

    return ReconcileResult(
        scanned=len(rows),
        drifted=drifted,
        unseen=unseen,
        next_cursor=ids[-1],
    )
