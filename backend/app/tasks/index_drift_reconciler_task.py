"""Periodic sweep that keeps the vector index honest without asking writers.

Flag-gated and OFF by default. It walks candidates and jobs in batches, one
batch per tick, carrying a cursor across ticks — so a full pass is spread over
hours instead of arriving as one spike, and a restart resumes from the start of
the current pass rather than re-doing everything.

Ordering matters and is not optional: this must not run before the provider
health probes exist. With ``AI_INDEX_MAX_ATTEMPTS=5``, a Voyage outage plus a
reconciler feeding the worker quietly burns the whole backlog into dead rows,
and the healthcheck would have shown green throughout.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.services import index_drift_reconciler as reconciler
from app.services import index_outbox_service as outbox
from app.services import loop_heartbeat

logger = logging.getLogger(__name__)


def reconciler_enabled() -> bool:
    return bool(getattr(settings, "AI_INDEX_RECONCILER_ENABLED", True))


def embedding_provider_down() -> bool:
    """Czy dostawca embeddingów jest w awarii — wtedy NIE zapisujemy intencji.

    Powód wyłączenia reconcilera do 18.09.2026 brzmiał: przy
    ``AI_INDEX_MAX_ATTEMPTS=5`` awaria Voyage'a plus reconciler karmiący workera
    zamienia backlog w wiersze ``dead`` (worker zabiera też ``failed``, więc
    pięć nieudanych prób z rzędu i wpis wypada z kolejki na stałe). To zostało
    zamknięte tutaj, nie założeniem, że awarii nie będzie: przy niezdrowym
    dostawcy tik nic nie zapisuje i czeka. ``unknown`` (nic jeszcze nie
    wołaliśmy w tym procesie) NIE jest awarią — inaczej po każdym deployu
    reconciler stałby do pierwszego niezwiązanego wywołania modelu.
    """
    from app.services.ai_health import provider_health_label

    return provider_health_label("voyage") == "unhealthy"


def _job_is_published(job) -> bool:
    from app.models.job import JobStatus

    return getattr(job, "status", None) == JobStatus.published


async def index_drift_reconciler_loop() -> None:
    if not reconciler_enabled():
        logger.info(
            "[index-drift] reconciler disabled (AI_INDEX_RECONCILER_ENABLED=false)"
        )
        return

    interval = max(
        30, int(getattr(settings, "AI_INDEX_RECONCILER_INTERVAL_SECONDS", 300))
    )
    batch = int(getattr(settings, "AI_INDEX_RECONCILER_BATCH", 500))
    logger.info(
        "[index-drift] reconciler started (interval=%ss, batch=%s)", interval, batch
    )

    # One cursor per entity type; a completed pass resets to 0 and starts over.
    cursors: dict[str, int] = {outbox.CANDIDATE: 0, outbox.JOB: 0}

    # MON-04: pętla, która żyje, ale nic nie robi, jest awarią. Ta była
    # zwolniona z heartbeatu z uzasadnieniem „outbox indeksu jest objęty" —
    # a outbox pokazuje wyłącznie to, co ktoś do niego zapisał, więc cisza
    # reconcilera (jedynego mechanizmu, który wykrywa BRAK zapisu) była
    # niewidoczna. Audyt 18.09.2026: 41,7% opublikowanych rekrutacji bez wektora.
    beat = loop_heartbeat.register(
        "index_drift_reconciler", max_silence_seconds=interval * 3 + 300
    )

    while True:
        beat.tick()
        if embedding_provider_down():
            logger.warning(
                "[index-drift] pauza: dostawca embeddingów w awarii — "
                "intencje zapisze następny tik"
            )
            await asyncio.sleep(interval)
            continue
        for entity_type in (outbox.CANDIDATE, outbox.JOB):
            try:
                async with AsyncSessionLocal() as db:
                    result = await reconciler.reconcile_once(
                        db,
                        entity_type=entity_type,
                        batch=batch,
                        cursor=cursors[entity_type],
                        # Audyt 22.09 r2 (INTG-05): opublikowana rekrutacja bez
                        # wektora jest dziurą w puli ofert, nie „populacją
                        # początkową" — kolejkujemy ją. Kandydatów NIE (tam
                        # brak wektora domyka `reembed_collections`).
                        unseen_predicate=(
                            _job_is_published if entity_type == outbox.JOB else None
                        ),
                        # Runda 8 (R8-N11-4): kandydat, którego jedyna intencja
                        # skończyła jako `dead` (np. długa awaria Qdranta),
                        # wraca do kolejki — inaczej nie dostałby wektora nigdy.
                        revive_dead_unseen=entity_type == outbox.CANDIDATE,
                        # R8-N11-2: status w payloadzie ofert zgodny z bazą.
                        sync_job_status=entity_type == outbox.JOB,
                    )
                    await db.commit()
                if result.next_cursor is None:
                    logger.info(
                        "[index-drift] %s: pass complete, restarting", entity_type
                    )
                    cursors[entity_type] = 0
                else:
                    cursors[entity_type] = result.next_cursor
                    if result.drifted or result.revived or result.status_synced:
                        logger.info(
                            "[index-drift] %s: %s", entity_type, result.as_log()
                        )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — a tick must never kill the loop
                logger.warning("[index-drift] %s tick failed: %s", entity_type, exc)
        await asyncio.sleep(interval)
