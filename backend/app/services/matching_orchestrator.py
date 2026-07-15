"""Unified retrieval orchestrator (plan PR8).

One pipeline — eligibility → sparse+dense candidate generation → RRF fusion →
adaptive overfetch → optional rerank → scoring v2 — producing a canonical
``MatchingRun``. Surfaces inject their building blocks (retrieval / eligibility
/ scoring callables) so the *policy* differs per surface but the *implementation
and trace* do not.

The fusion and overfetch primitives are pure and unit-tested; ``run_matching``
composes injected callables so it can be exercised end-to-end with fakes (no
Voyage/Qdrant/DB). Flag-gated per surface via ``surface_enabled``; existing
surfaces are untouched until opted in.
"""

from __future__ import annotations

import logging
import math
import uuid
from typing import Awaitable, Callable, Optional, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.matching_contracts import (
    MatchingRequest,
    MatchingResult,
    MatchingRun,
    current_version_trace,
)

logger = logging.getLogger(__name__)

# Injected building blocks (all async):
#   dense/sparse : () -> Sequence[tuple[candidate_id, score]]  (ranked desc)
#   eligibility  : (ids) -> dict[id, tuple[bool, list[str]]]
#   scoring      : (ids) -> dict[id, tuple[float, dict]]        (fit_score, breakdown)
RankFn = Callable[[], Awaitable[Sequence[tuple[int, float]]]]
EligibilityFn = Callable[[Sequence[int]], Awaitable[dict]]
ScoreFn = Callable[[Sequence[int]], Awaitable[dict]]


def surface_enabled(surface: str) -> bool:
    if not getattr(settings, "AI_UNIFIED_RETRIEVAL_ENABLED", False):
        return False
    raw = getattr(settings, "AI_UNIFIED_RETRIEVAL_SURFACES", "") or ""
    allowed = {s.strip() for s in raw.split(",") if s.strip()}
    return not allowed or surface in allowed


def reciprocal_rank_fusion(
    rankings: dict[str, Sequence[int]], *, k: int = 60
) -> list[tuple[int, float, list[str]]]:
    """Fuse ranked id lists with RRF: score(id) = Σ 1/(k + rank).

    Returns ``[(candidate_id, fused_score, contributing_sources)]`` sorted by
    fused score desc, tie-broken by candidate_id for determinism.
    """
    scores: dict[int, float] = {}
    sources: dict[int, list[str]] = {}
    for source, ids in rankings.items():
        for rank, cid in enumerate(ids):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
            sources.setdefault(cid, [])
            if source not in sources[cid]:
                sources[cid].append(source)
    fused = [(cid, scores[cid], sources[cid]) for cid in scores]
    fused.sort(key=lambda t: (-t[1], t[0]))
    return fused


def adaptive_overfetch(top_k: int, eligible_ratio: float, *, cap: int = 500) -> int:
    """How many candidates to generate so ~top_k survive hard filters.

    A low eligible ratio (filters reject most of the pool) means we must fetch
    proportionally more. Clamped to ``cap`` so a pathological ratio can't ask
    for an unbounded pool.
    """
    top_k = max(0, top_k)
    ratio = min(max(eligible_ratio, 0.02), 1.0)  # floor avoids div-by-~0 blowup
    return min(cap, max(top_k, math.ceil(top_k / ratio)))


async def run_matching(
    request: MatchingRequest,
    db: AsyncSession,
    *,
    dense_fn: RankFn,
    eligibility_fn: EligibilityFn,
    score_fn: ScoreFn,
    sparse_fn: Optional[RankFn] = None,
    rerank_fn: Optional[ScoreFn] = None,
    run_id: Optional[str] = None,
    emit_telemetry: bool = True,
) -> MatchingRun:
    """Compose one canonical MatchingRun from injected building blocks.

    Ordering: fuse dense+sparse → keep eligible → score → rank by fit_score
    (fused score breaks ties / stands in when a candidate has no fit score).
    """
    rid = run_id or uuid.uuid4().hex
    degraded = False

    rankings: dict[str, Sequence[int]] = {}
    fused_scores: dict[int, float] = {}
    fused_sources: dict[int, list[str]] = {}

    try:
        dense = await dense_fn()
        rankings["dense"] = [cid for cid, _ in dense]
    except Exception as exc:  # noqa: BLE001
        logger.warning("[orchestrator] dense retrieval failed: %s", exc)
        degraded = True

    if sparse_fn is not None:
        try:
            sparse = await sparse_fn()
            rankings["sparse"] = [cid for cid, _ in sparse]
        except Exception as exc:  # noqa: BLE001
            logger.warning("[orchestrator] sparse retrieval failed: %s", exc)
            degraded = True

    for cid, sc, srcs in reciprocal_rank_fusion(rankings):
        fused_scores[cid] = sc
        fused_sources[cid] = srcs

    candidate_ids = list(fused_scores.keys())
    if not candidate_ids:
        return MatchingRun(
            run_id=rid,
            surface=request.surface,
            results=[],
            version_trace=current_version_trace(),
            degraded=degraded,
        )

    elig = await eligibility_fn(candidate_ids)
    eligible_ids = [c for c in candidate_ids if elig.get(c, (True, []))[0]]

    scored = await score_fn(eligible_ids) if eligible_ids else {}
    if rerank_fn is not None and eligible_ids:
        try:
            rescored = await rerank_fn(eligible_ids)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[orchestrator] rerank failed: %s", exc)
            degraded = True
            rescored = {}
    else:
        rescored = {}

    results: list[MatchingResult] = []
    for cid in candidate_ids:
        is_elig, reasons = elig.get(cid, (True, []))
        fit = scored.get(cid)
        rer = rescored.get(cid)
        results.append(
            MatchingResult(
                candidate_id=cid,
                rank=0,  # assigned after sort
                eligible=is_elig,
                eligibility_reasons=list(reasons),
                retrieval_score=fused_scores.get(cid),
                rerank_score=(rer[0] if rer else None),
                fit_score=(fit[0] if fit else None),
                fit_breakdown=(fit[1] if fit else None),
                sources=fused_sources.get(cid, []),
            )
        )

    # Eligible first, then by rerank/fit/retrieval score desc.
    def _key(r: MatchingResult):
        return (
            0 if r.eligible else 1,
            -(r.rerank_score if r.rerank_score is not None else -math.inf),
            -(r.fit_score if r.fit_score is not None else -math.inf),
            -(r.retrieval_score if r.retrieval_score is not None else -math.inf),
            r.candidate_id,
        )

    results.sort(key=_key)
    results = results[: request.top_k] if request.top_k else results
    for i, r in enumerate(results):
        r.rank = i

    if emit_telemetry:
        await _emit(db, request, rid, results, degraded)

    return MatchingRun(
        run_id=rid,
        surface=request.surface,
        results=results,
        version_trace=current_version_trace(),
        degraded=degraded,
    )


async def _emit(
    db: AsyncSession,
    request: MatchingRequest,
    run_id: str,
    results: list[MatchingResult],
    degraded: bool,
) -> None:
    """Best-effort impression telemetry (no-op unless telemetry flag is on)."""
    try:
        from app.services import match_telemetry_service as tel

        if not tel.telemetry_enabled():
            return
        entries = [
            tel.ImpressionEntry(
                candidate_id=r.candidate_id,
                rank=r.rank,
                eligible=r.eligible,
                retrieval_score=r.retrieval_score,
                rerank_score=r.rerank_score,
                fit_score=r.fit_score,
                fit_breakdown=r.fit_breakdown,
                retrieval_sources={"sources": r.sources} if r.sources else None,
            )
            for r in results
        ]
        await tel.record_impressions(
            db,
            run_id=run_id,
            surface=request.surface,
            entries=entries,
            job_id=request.job_id,
            request_id=request.request_id,
            user_id=request.user_id,
            client_id=request.client_id,
            degraded=degraded,
        )
    except Exception as exc:  # noqa: BLE001 — telemetry never breaks matching
        logger.warning("[orchestrator] telemetry emit failed: %s", exc)
