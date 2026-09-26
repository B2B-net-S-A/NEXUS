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
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Optional

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
    status_synced: int = 0
    revived: int = 0

    def as_log(self) -> str:
        return (
            f"scanned={self.scanned} drifted={self.drifted} "
            f"unseen(skipped)={self.unseen} revived={self.revived} "
            f"status_synced={self.status_synced} next_cursor={self.next_cursor}"
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
    unseen_predicate: Optional[Callable[[Any], bool]] = None,
    revive_dead_unseen: bool = False,
    sync_job_status: bool = False,
) -> ReconcileResult:
    """Scan one batch of entities and enqueue those whose hash has drifted.

    ``unseen_predicate`` (audyt 22.09 r2, INTG-05) — węższa furtka niż
    ``include_unseen``: encja, której indeks nigdy nie widział, jest
    kolejkowana, gdy predykat zwróci True (dla rekrutacji: opublikowana)
    ORAZ nie ma już w kolejce intencji w toku (`pending`/`processing`/
    `failed`) — inaczej każdy przebieg dopisywałby kolejny duplikat. Bez tego
    9 opublikowanych rekrutacji zostawało bez wektora NA STAŁE: worker
    zamienił ich intencje w `dead`, a reconciler je pomijał jako „nieznane".

    ``revive_dead_unseen`` (runda 8, R8-N11-4) — encja nigdy nie
    zaindeksowana, której jedyna intencja skończyła jako ``dead`` (np. Qdrant
    leżał dłużej niż budżet prób workera), jest kolejkowana ponownie. Warunek:
    brak JAKIEGOKOLWIEK wiersza ``done`` (kwarantanna zostawia ``done`` z pustym
    haszem i nie może zostać odwrócona) i brak intencji w toku.

    ``sync_job_status`` (runda 8, R8-N11-2) — tylko dla ofert: porównuje
    ``status`` w payloadzie punktów z bazą i poprawia go tanim ``set_payload``
    (bez Voyage'a). Łapie zmiany statusu robione zwykłym SQL-em (archiwum
    Traffita, 0378, usunięcie klienta), których żaden hak nie widzi.

    ``cursor`` is the last id examined, so a caller can walk the whole table
    across ticks without holding a transaction open, and without loading the
    *whole table* at once. Returns ``next_cursor=None`` once the end is reached.

    One batch is not free, though: ``desired_state`` hashes the same text that
    gets embedded, so these are full ORM objects including ``raw_cv_text`` —
    several KB per candidate. At the default 500 that is a few hundred MB of
    peak transient memory per tick, and ~95 ticks to cross the candidate table.
    Lower ``AI_INDEX_RECONCILER_BATCH`` (100–200) to trade passes for headroom;
    this is worth checking before flipping the reconciler on in production.
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

    in_flight: set[int] = set()
    dead_only: set[int] = set()
    if (unseen_predicate is not None or revive_dead_unseen) and not include_unseen:
        unseen_ids = [int(r.id) for r in rows if int(r.id) not in indexed]
        if unseen_ids and revive_dead_unseen:
            dead_only = await _dead_never_done(db, entity_type, unseen_ids)
        if unseen_ids:
            in_flight = set(
                (
                    await db.execute(
                        select(IndexOutboxEvent.entity_id)
                        .where(
                            IndexOutboxEvent.entity_type == entity_type,
                            IndexOutboxEvent.entity_id.in_(unseen_ids),
                            IndexOutboxEvent.status.in_(
                                ("pending", "processing", "failed")
                            ),
                        )
                        .distinct()
                    )
                ).scalars()
            )

    drifted = 0
    unseen = 0
    revived = 0
    to_enqueue: list[int] = []
    for row in rows:
        entity_id = int(row.id)
        known = indexed.get(entity_id)
        if known is None:
            unseen += 1
            if include_unseen:
                to_enqueue.append(entity_id)
            elif entity_id in in_flight:
                pass
            elif unseen_predicate is not None and unseen_predicate(row):
                to_enqueue.append(entity_id)
            elif entity_id in dead_only:
                revived += 1
                to_enqueue.append(entity_id)
            continue
        desired = outbox.desired_state(entity_type, row)
        # `hashes_match`, nie `!=`: hasz sprzed 18.09.2026 nie niesie nazwy
        # modelu i porównywany dosłownie wyglądałby jak dryf na CAŁEJ bazie.
        if not outbox.hashes_match(desired, known):
            drifted += 1
            to_enqueue.append(entity_id)

    if to_enqueue:
        # Writes in the caller's transaction and deliberately ignores
        # AI_INDEX_OUTBOX_ENABLED — recording that something needs reindexing is
        # not the same decision as routing writes through the outbox, and a
        # reconciler that silently records nothing would be worse than absent.
        await outbox.record_bulk_reindex(db, entity_type, to_enqueue)
        # Flush, żeby kolejny przebieg w tej samej sesji (i sprawdzenie
        # intencji w toku, INTG-05) widział właśnie zapisane wiersze.
        await db.flush()

    status_synced = 0
    if sync_job_status and entity_type == outbox.JOB:
        status_synced = await _sync_job_statuses(rows)

    return ReconcileResult(
        scanned=len(rows),
        drifted=drifted,
        unseen=unseen,
        next_cursor=ids[-1],
        status_synced=status_synced,
        revived=revived,
    )


async def _dead_never_done(
    db: AsyncSession, entity_type: str, entity_ids: list[int]
) -> set[int]:
    """Encje z intencją ``dead`` i bez żadnego wiersza ``done`` (R8-N11-4)."""
    dead_rows = (
        await db.execute(
            select(IndexOutboxEvent.entity_id)
            .where(
                IndexOutboxEvent.entity_type == entity_type,
                IndexOutboxEvent.entity_id.in_(entity_ids),
                IndexOutboxEvent.status == "dead",
                IndexOutboxEvent.operation == "upsert",
            )
            .distinct()
        )
    ).scalars()
    dead = {int(e) for e in dead_rows}
    if not dead:
        return set()
    with_done = set(
        (
            await db.execute(
                select(IndexOutboxEvent.entity_id)
                .where(
                    IndexOutboxEvent.entity_type == entity_type,
                    IndexOutboxEvent.entity_id.in_(dead),
                    IndexOutboxEvent.status == "done",
                )
                .distinct()
            )
        ).scalars()
    )
    return dead - {int(e) for e in with_done}


async def _sync_job_statuses(rows) -> int:
    """Payload ``status`` punktów ofert zgodny z bazą (R8-N11-2)."""
    from app.services.embedding_service import (
        job_payload_statuses,
        job_status_value,
        sync_job_status_payloads,
    )

    wanted = {int(r.id): job_status_value(r.status) for r in rows}
    indexed = await job_payload_statuses(list(wanted))
    if not indexed:
        return 0
    stale = {
        job_id: wanted[job_id]
        for job_id, status in indexed.items()
        if job_id in wanted and status != wanted[job_id]
    }
    if not stale:
        return 0
    return await sync_job_status_payloads(stale)
