"""Background task: compute + persist AI candidate proposals for a job.

Triggered via FastAPI `BackgroundTasks` from `POST /api/jobs` and from
`POST /api/jobs/{id}/proposals/regenerate`. Writes a `ProposalSnapshot` row
that the frontend polls while `status="pending"`.

The task opens its own DB session via `AsyncSessionLocal` because
`Depends(get_db)` is already closed by the time FastAPI fires background tasks.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.services.proposal_contract import proposal_fingerprint
from app.models.candidate import Candidate, CandidateStatus
from app.models.job import Job
from app.models.proposal_snapshot import (
    ProposalSnapshot,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_READY,
)
from app.models.recruitment_pipeline import CandidateStage
from app.services.canonical_text import build_job_query_variants
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
    from app.services.canonical_fit import score_candidates
    from app.services.request_matching_context import build_request_context
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

            fit_context = build_request_context(job, profile)
            query_text = fit_context.query_text
            input_fingerprint = proposal_fingerprint(fit_context.fingerprint)

            # Mirror recommendations.py: pull a wider pool, then re-rank.
            # Pool size is independent of `top_k` on purpose. The old `top_k * 4`
            # heuristic tied "how many we retrieve" to "how many we show", so a request
            # for the top 20 retrieved 80 and capped its own recall ceiling at ~4%
            # (measured 2026-08-10: ceiling is 1.8% at pool 20, 13.6% at 200, 32.6% at
            # 1000). `top_k` still caps what comes back — it just no longer decides what
            # scoring is allowed to see.
            pool_size = settings.MATCH_POOL_SIZE
            # C12: noga BM25 dostaje TERMINY, nie `query_text`. Dokument
            # w roli tsquery ANDuje setki leksemów, czyli zwraca zero zawsze —
            # cicho, bo fuzja RRF z pustą listą wygląda jak porządek wektora.
            from app.services.hybrid_search import (
                build_job_bm25_query,
                build_job_must_groups,
            )

            hits = await retrieve_candidate_pool(
                session,
                query_text,
                top_k=pool_size,
                query_variants=build_job_query_variants(job, query_text),
                bm25_query=build_job_bm25_query(job),
                # 0278: no-op, dopóki `STRUCTURED_POOL_ENABLED` jest wyłączona.
                must_groups=build_job_must_groups(job),
            )
            candidate_ids = list(dict.fromkeys(h["candidate_id"] for h in hits))

            # Retrieval completeness is separate from the exact fit measurements.
            semantic_unknown_ids = {
                h["candidate_id"] for h in hits if h.get("semantic_unknown")
            }
            semantic_degraded = not candidate_ids or bool(semantic_unknown_ids)

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

            # Post-0237 snapshot ZAWSZE niesie liczniki (choćby zerowe) —
            # NULL zostaje jednoznacznym znacznikiem „sprzed 0237 /
            # nieprzefiltrowany", także gdy retrieval zwrócił pustą pulę
            # i dealbreakery nie miały na czym pracować (review #1207).
            from app.services.dealbreaker_filters import (
                DealbreakerResult,
                apply_dealbreakers,
            )
            from app.services.requirement_contract import search_dealbreaker_inputs

            snap.hidden = DealbreakerResult().hidden_meta()
            breakdowns: list = []
            fits_by_id = {}
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

                # Twardy sufit budżetu Z AUTOMATU (decyzja produktowa 19.08):
                # snapshot jest DOMYŚLNYM widokiem rekrutera, więc znany budżet
                # oferty musi ukrywać znane stawki powyżej także tutaj — nie
                # tylko na żywej ścieżce /recommendations. Liczniki idą do
                # `snap.hidden`, bo ukrywanie nigdy nie jest ciche. Rubryki 0278
                # (must-have / dni w biurze / miasto) i AUTO `exclude_remote_only`
                # (uzbraja się, gdy oferta chce biura) liczone RAZ przez
                # `dealbreaker_inputs_for_job` — ta sama funkcja co na żywej
                # ścieżce, więc handoff-snapshot i /recommendations zgadzają się
                # co do tego, kogo ukrywają.
                dealbreakers = apply_dealbreakers(
                    candidates,
                    inputs=search_dealbreaker_inputs(job),
                )
                candidates = dealbreakers.kept
                snap.hidden = dealbreakers.hidden_meta()

                if candidates:
                    fits = await score_candidates(session, fit_context, candidates)
                    fits_by_id = {fit.breakdown.candidate_id: fit for fit in fits}
                    breakdowns = [fit.breakdown for fit in fits]
                    semantic_degraded = semantic_degraded or any(
                        fit.fit_score is None for fit in fits
                    )
                    # History is separate evidence; it never changes fit.
                    from app.api.recommendations import _annotate_historical_context
                    from app.services.similar_job_candidates import (
                        fetch_historical_boost_map,
                    )

                    try:
                        boost_map = await fetch_historical_boost_map(session, job_id)
                    except Exception as boost_exc:  # pragma: no cover — best-effort
                        logger.warning(
                            "[Proposals] historical_boost lookup failed for job=%s: %s",
                            job_id,
                            boost_exc,
                        )
                        boost_map = {}
                    _annotate_historical_context(breakdowns, boost_map)

                    # Persist ALL candidates that fit (score >= threshold),
                    # ranked best-first — not a fixed top-K. `top_k` is now just
                    # a payload safety cap. Mirrors the live /recommendations
                    # endpoint so the snapshot and fallback paths agree on
                    # "who matches".
                    breakdowns = [
                        fit.breakdown
                        for fit in fits
                        if fit.fit_score is None
                        or fit.fit_score >= settings.RECOMMENDATION_MIN_SCORE
                    ][:top_k]

            snap.status = STATUS_READY
            snap.candidate_ids = [b.candidate_id for b in breakdowns]
            snap.breakdowns = [fits_by_id[b.candidate_id].as_dict() for b in breakdowns]
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
