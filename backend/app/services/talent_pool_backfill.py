"""Historical Talent-Pool membership backfill (re-runnable, idempotent).

Replays every ``candidate_stages`` row with stage = ``cv_sent`` ("CV wysłane do
klienta") through :func:`app.services.talent_pool_auto_add.auto_add_on_cv_sent`,
which now classifies the job title (+ candidate skills) to an existing curated
pool. This is what actually fills the 101 imported role pools that the
subcategory/seniority trigger could never reach (Traffit jobs carry neither).

Idempotent via the ``uq_pool_candidate`` UniqueConstraint — re-running only adds
memberships for pairs not already present. Shared by:
  * ``scripts.backfill_talent_pools`` (CLI, Phase B), and
  * ``POST /api/admin/talent-pools/backfill`` (in-app background task — the
    autonomous prod path, no shell-into-container required).

Progress / last-run stats are kept in-memory (reset on container restart),
which is fine: the operation is on-demand and idempotent.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.services.talent_pool_auto_add import auto_add_on_cv_sent

logger = logging.getLogger(__name__)

BATCH_COMMIT_SIZE = 500

# ── In-memory run state (single worker; backfill is a serialized admin op) ───
_running = False
_last_run: dict[str, Any] = {}


def backfill_is_running() -> bool:
    return _running


def last_backfill_stats() -> dict[str, Any]:
    return dict(_last_run)


async def run_membership_backfill(
    *,
    since: Optional[datetime] = None,
    commit: bool = True,
    limit: Optional[int] = None,
) -> dict[str, Any]:
    """Replay cv_sent stages → pool memberships. Returns a stats dict.

    Args:
        since: only replay stages with ``moved_at >= since`` (incremental top-up).
        commit: when False, rolls back at the end (dry-run within a live DB).
        limit: cap the number of stage rows processed (debugging / smoke runs).
    """
    global _running, _last_run
    if _running:
        raise RuntimeError("A talent-pool backfill is already running")
    _running = True
    started = datetime.now(timezone.utc)
    added = already = skipped = errors = 0
    by_pool: Counter[str] = Counter()
    job_cache: dict[int, Optional[Job]] = {}

    try:
        async with AsyncSessionLocal() as db:
            stmt = select(CandidateStage).where(
                CandidateStage.stage == PipelineStage.cv_sent
            )
            if since is not None:
                stmt = stmt.where(CandidateStage.moved_at >= since)
            stmt = stmt.order_by(CandidateStage.moved_at.asc())
            if limit is not None:
                stmt = stmt.limit(limit)

            # Same wartości, nie obiekty ORM: po wycofanym savepoincie
            # obiekt sesji bywa wygaszony, a leniwe doczytanie atrybutu
            # w sesji async to `MissingGreenlet` (runda 7, N7-5).
            stmt = stmt.with_only_columns(
                CandidateStage.id,
                CandidateStage.candidate_id,
                CandidateStage.job_id,
                CandidateStage.moved_by,
            )
            rows = (await db.execute(stmt)).all()
            total = len(rows)
            logger.info("talent-pool backfill: %s cv_sent rows to replay", total)

            processed = 0
            for row_id, candidate_id, job_id, moved_by in rows:
                processed += 1
                if job_id not in job_cache:
                    job_cache[job_id] = await db.get(Job, job_id)
                job = job_cache[job_id]
                if job is None:
                    skipped += 1
                    continue

                # Savepoint na wiersz, nie `db.rollback()` sesji: rollback
                # cofał do 499 niezacommitowanych członkostw z paczki, które
                # licznik `added` już policzył (runda 7, N7-5).
                result = None
                for attempt in (0, 1):
                    try:
                        async with db.begin_nested():
                            candidate = await db.get(Candidate, candidate_id)
                            extra: dict[str, Any] = {"backfill": True}
                            if attempt:
                                extra["retry"] = 1
                            outcome = await auto_add_on_cv_sent(
                                db=db,
                                candidate_id=candidate_id,
                                job=job,
                                user_id=moved_by,
                                candidate=candidate,
                                extra_activity_details=extra,
                                # Ponowny bieg przemiata całą historię —
                                # „nic się nie zmieniło” nie jest zdarzeniem.
                                log_noops=False,
                            )
                        # Dopiero po zwolnieniu savepointu — błąd przy
                        # zapisie `Activity` na wyjściu cofa też wynik.
                        result = outcome
                        break
                    except IntegrityError as e:
                        # Wyścig z ruchem na żywo na tej samej puli (drugie
                        # podejście czyta już jej wiersz) albo kandydat
                        # usunięty w trakcie biegu (FK) — wtedy drugie też
                        # padnie i wiersz liczy się jako błąd.
                        logger.warning(
                            "backfill row=%s %s (attempt %s)",
                            row_id,
                            type(e).__name__,
                            attempt + 1,
                        )
                    except Exception as e:  # noqa: BLE001
                        logger.error(
                            "backfill row=%s failed: %s", row_id, type(e).__name__
                        )
                        break
                if result is None:
                    errors += 1
                    continue

                if result.status == "added":
                    added += 1
                    if result.pool_name:
                        by_pool[result.pool_name] += 1
                elif result.status == "already_in_pool":
                    already += 1
                elif result.status == "skipped_no_category":
                    skipped += 1

                if commit and processed % BATCH_COMMIT_SIZE == 0:
                    await db.commit()
                    logger.info(
                        "backfill progress %s/%s added=%s already=%s skipped=%s errors=%s",
                        processed,
                        total,
                        added,
                        already,
                        skipped,
                        errors,
                    )

            if commit:
                await db.commit()
            else:
                await db.rollback()

        stats = {
            "total": total,
            "added": added,
            "already_in_pool": already,
            "skipped": skipped,
            "errors": errors,
            "committed": commit,
            "top_pools": dict(by_pool.most_common(40)),
            "started_at": started.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
        logger.info(
            "talent-pool backfill done: %s",
            {
                k: stats[k]
                for k in (
                    "total",
                    "added",
                    "already_in_pool",
                    "skipped",
                    "errors",
                    "committed",
                )
            },
        )
        _last_run = stats
        return stats
    finally:
        _running = False
