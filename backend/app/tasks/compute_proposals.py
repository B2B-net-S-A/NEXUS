"""Background task: compute + persist AI candidate proposals for a job.

Triggered via FastAPI `BackgroundTasks` from `POST /api/jobs` and from
`POST /api/jobs/{id}/proposals/regenerate`. Writes a `ProposalSnapshot` row
that the frontend polls while `status="pending"`.

The task opens its own DB session via `AsyncSessionLocal` because
`Depends(get_db)` is already closed by the time FastAPI fires background tasks.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate, CandidateStatus
from app.models.job import Job
from app.models.proposal_snapshot import (
    ProposalSnapshot,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_READY,
)
from app.models.recruitment_pipeline import CandidateStage
from app.services.retrieval_pool import retrieve_candidate_pool

logger = logging.getLogger(__name__)


async def create_pending_snapshot(
    job_id: int,
    *,
    top_k: int = settings.MATCH_MAX_RESULTS,
    source: str = "create",
    created_by: Optional[int] = None,
    profile_id: int = 0,
) -> int:
    """Insert a pending snapshot row and return its id.

    Called synchronously from the request handler so the frontend can start
    polling immediately (even before the heavier scoring pass finishes).
    """
    async with AsyncSessionLocal() as session:
        snap = ProposalSnapshot(
            job_id=job_id,
            source=source,
            status=STATUS_PENDING,
            top_k=top_k,
            profile_id=profile_id,
            created_by=created_by,
            run_id=uuid.uuid4().hex,
        )
        session.add(snap)
        await session.commit()
        await session.refresh(snap)
        return snap.id


async def compute_proposal_for_job(
    snapshot_id: int,
    job_id: int,
    *,
    top_k: int = settings.MATCH_MAX_RESULTS,
) -> None:
    """Populate snapshot `snapshot_id` with top-K scored candidates.

    Never raises — any failure is recorded on the snapshot row as
    status="failed" + error_message so the frontend can display it cleanly.
    """
    # Lazy imports keep module import cheap and avoid circular deps with the
    # scoring stack (which imports models at init time).
    from app.services.embedding_service import (
        _build_job_text,
        embed_job,
    )
    from app.services.match_score_cache import bulk_get_or_compute
    from app.services.scoring_service import (
        DEFAULT_PROFILE,
        WeightProfile,
        resolve_active_profile,
    )

    async with AsyncSessionLocal() as session:
        snap = await session.scalar(
            select(ProposalSnapshot).where(ProposalSnapshot.id == snapshot_id)
        )
        if snap is None:
            logger.warning(
                "[Proposals] snapshot %s missing — cannot compute", snapshot_id
            )
            return

        try:
            job = await session.scalar(select(Job).where(Job.id == job_id))
            if job is None:
                raise RuntimeError(f"job {job_id} not found")

            # Make sure the job has a semantic embedding before we rank, so the
            # semantic layer isn't just zeros for a freshly-created job.
            if not getattr(job, "embedding_id", None):
                try:
                    await embed_job(job_id, session)
                    await session.refresh(job)
                except Exception as e:  # pragma: no cover — best-effort
                    logger.warning(
                        "[Proposals] embed_job(%s) failed, continuing without "
                        "semantic layer: %s",
                        job_id,
                        e,
                    )

            profile: WeightProfile = DEFAULT_PROFILE
            if snap.profile_id and snap.profile_id > 0:
                from app.models.scoring_weight_profile import ScoringWeightProfile

                row = await session.scalar(
                    select(ScoringWeightProfile).where(
                        ScoringWeightProfile.id == snap.profile_id
                    )
                )
                if row:
                    profile = WeightProfile.from_record(row)
            else:
                profile = await resolve_active_profile(
                    session, user_id=snap.created_by, client_id=job.client_id
                )

            query_text = _build_job_text(job)
            # P0-B: fingerprint the matching inputs (brief + Champion narrative,
            # folded into _build_job_text) so a later brief/Champion edit that
            # changes them can be detected and this snapshot marked stale.
            input_fingerprint = hashlib.sha256(query_text.encode("utf-8")).hexdigest()

            # Mirror recommendations.py: pull a wider pool, then re-rank.
            # Pool size is independent of `top_k` on purpose. The old `top_k * 4`
            # heuristic tied "how many we retrieve" to "how many we show", so a request
            # for the top 20 retrieved 80 and capped its own recall ceiling at ~4%
            # (measured 2026-08-10: ceiling is 1.8% at pool 20, 13.6% at 200, 32.6% at
            # 1000). `top_k` still caps what comes back — it just no longer decides what
            # scoring is allowed to see.
            pool_size = settings.MATCH_POOL_SIZE
            hits = await retrieve_candidate_pool(session, query_text, top_k=pool_size)
            similarity_map = {h["candidate_id"]: h["score"] for h in hits}
            candidate_ids = list(similarity_map.keys())

            # Degraded retrieval (Qdrant down/empty) — mirror recommendations:
            # composites liczone z neutralnym semantic NIE mogą trafić do
            # wspólnego score cache jako świeże (M3-CACHE-01).
            semantic_degraded = not candidate_ids

            # Fallback when Qdrant is empty / job not indexed yet.
            if not candidate_ids:
                fallback = await session.execute(
                    select(Candidate.id)
                    .where(Candidate.status != CandidateStatus.blacklisted)
                    .limit(settings.MATCH_POOL_SIZE)
                )
                candidate_ids = [c for (c,) in fallback.all()]

            # Exclude candidates already in this job's pipeline — they aren't
            # "proposals" anymore; they're already being worked.
            if candidate_ids:
                in_pipeline = await session.execute(
                    select(CandidateStage.candidate_id)
                    .where(
                        CandidateStage.job_id == job_id,
                        CandidateStage.candidate_id.in_(candidate_ids),
                    )
                    .distinct()
                )
                already = {cid for (cid,) in in_pipeline.all()}
                candidate_ids = [cid for cid in candidate_ids if cid not in already]

            breakdowns: list = []
            if candidate_ids:
                cand_res = await session.execute(
                    select(Candidate).where(Candidate.id.in_(candidate_ids))
                )
                candidates = list(cand_res.scalars().all())

                # P0-A: hard eligibility prefilter — the handoff snapshot IS the
                # recruiter's operational ranking, so a blacklisted /
                # hard-conflict / hiring-manager-vetoed candidate must never land
                # in it. Mirrors the live /recommendations path exactly; soft
                # warnings (current employment, candidate-excluded) stay.
                from app.services.pipeline_eligibility import (
                    filter_eligible_candidates,
                )

                candidates = await filter_eligible_candidates(
                    session,
                    job=job,
                    candidates=candidates,
                    now=datetime.now(timezone.utc),
                )

                if candidates:
                    breakdowns = await bulk_get_or_compute(
                        job,
                        candidates,
                        session,
                        similarity_map=similarity_map,
                        profile=profile,
                        allow_cache_write=not semantic_degraded,
                    )
                    # Persist ALL candidates that fit (score >= threshold),
                    # ranked best-first — not a fixed top-K. `top_k` is now just
                    # a payload safety cap. Mirrors the live /recommendations
                    # endpoint so the snapshot and fallback paths agree on
                    # "who matches".
                    breakdowns = [
                        b
                        for b in breakdowns
                        if b.total >= settings.RECOMMENDATION_MIN_SCORE
                    ][:top_k]

            snap.status = STATUS_READY
            snap.candidate_ids = [b.candidate_id for b in breakdowns]
            snap.breakdowns = [b.as_dict() for b in breakdowns]
            # P0-A: record whether the semantic leg was degraded (Qdrant/Voyage
            # down or the job unindexed) so the UI can flag this ranking as a
            # fallback instead of a healthy one. Previously computed only to gate
            # cache writes, then discarded.
            snap.degraded = semantic_degraded
            # P0-B: a fresh compute is current by definition; record the revision
            # it was scored against and clear any stale flag.
            snap.input_fingerprint = input_fingerprint
            snap.stale = False
            snap.error_message = None
            await session.commit()
            logger.info(
                "[Proposals] snapshot %s ready — %d candidates for job %s",
                snapshot_id,
                len(breakdowns),
                job_id,
            )
        except Exception as e:  # pragma: no cover
            logger.exception(
                "[Proposals] snapshot %s failed for job %s: %s",
                snapshot_id,
                job_id,
                e,
            )
            snap.status = STATUS_FAILED
            snap.error_message = str(e)[:500]
            try:
                await session.commit()
            except Exception as commit_err:
                logger.warning(
                    "[Proposals] failed to persist failure state: %s", commit_err
                )
                await session.rollback()
