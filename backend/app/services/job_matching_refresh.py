"""Re-embed a job and invalidate its cached match scores after a change that
affects matching inputs (P0-A).

The Champion profile feeds BOTH the job embedding (the semantic query text) and
the top-weighted scoring layer, but its dedicated write paths
(``update_champion_profile`` and the AI ``apply_suggestion`` merges) bypassed the
re-embed + cache invalidation that ``update_job`` performs on its trigger fields.
The result: editing a Champion silently left the job embedding and every cached
``CandidateJobMatchScore`` computed against the OLD champion, so a Delivery
Lead's work never reached the recruiter's ranking.

Lives in its own leaf module (imports only ``index_outbox_service`` and
``match_score_cache``) so both the API layer and ``champion_draft_service`` can
call it without an import cycle.

Only matching-relevant writes should call this: the ``verification``,
``briefing`` and ``recommended_searches`` champion sections are NOT part of the
embedding text or the scoring inputs, so re-embedding on those would be wasted
work.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def refresh_job_matching(job_id: int, db: AsyncSession) -> None:
    """Re-embed ``job_id`` and mark its cached match scores stale, then commit.

    Best-effort on the embedding (never blocks the caller's write); the cache
    invalidation always runs so the next recommendation/snapshot recomputes.
    """
    from app.services.index_outbox_service import schedule_or_embed_job
    from app.services.match_score_cache import mark_stale_for_job

    try:
        await schedule_or_embed_job(job_id, db)
    except Exception as e:  # pragma: no cover — best-effort
        logger.warning("[matching-refresh] re-embed failed for job %s: %s", job_id, e)

    await mark_stale_for_job(db, job_id)
    await db.commit()
