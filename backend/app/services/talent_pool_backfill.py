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

            rows = (await db.execute(stmt)).scalars().all()
            total = len(rows)
            logger.info("talent-pool backfill: %s cv_sent rows to replay", total)

            processed = 0
            for row in rows:
                processed += 1
                if row.job_id not in job_cache:
                    job_cache[row.job_id] = await db.get(Job, row.job_id)
                job = job_cache[row.job_id]
                if job is None:
                    skipped += 1
                    continue

                candidate = await db.get(Candidate, row.candidate_id)

                try:
                    result = await auto_add_on_cv_sent(
                        db=db,
                        candidate_id=row.candidate_id,
                        job=job,
                        user_id=row.moved_by,
                        candidate=candidate,
                        extra_activity_details={"backfill": True},
                    )
                except IntegrityError as e:
                    # Race with a live cv_sent move on the same pool — roll back
                    # this row and retry once; the second try reuses the row.
                    await db.rollback()
                    job_cache.pop(row.job_id, None)
                    logger.warning(
                        "backfill row=%s IntegrityError, retry: %s", row.id, e
                    )
                    try:
                        job = await db.get(Job, row.job_id)
                        if job is None:
                            errors += 1
                            continue
                        candidate = await db.get(Candidate, row.candidate_id)
                        result = await auto_add_on_cv_sent(
                            db=db,
                            candidate_id=row.candidate_id,
                            job=job,
                            user_id=row.moved_by,
                            candidate=candidate,
                            extra_activity_details={"backfill": True, "retry": 1},
                        )
                    except Exception as retry_err:  # noqa: BLE001
                        await db.rollback()
                        logger.error(
                            "backfill row=%s retry failed: %s", row.id, retry_err
                        )
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
