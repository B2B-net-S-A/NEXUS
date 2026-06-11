"""Candidates from similar historical jobs.

Core logic powering `GET /api/jobs/{id}/candidates-from-similar` and the
`historical_boost` adjustment applied inside
`/api/jobs/{id}/recommendations`.

Flow
----
1. Ask Qdrant for jobs semantically similar to the target job
   (`search_similar_jobs_by_job_id`).
2. Split the similar jobs into two tiers by cosine score:
     - Tier A (primary):  >= 0.70
     - Tier B (extended): >= 0.55 (used as fallback when Tier A yields < 5
       candidates)
3. Pull every `CandidateStage` row for those job_ids younger than the 18-month
   cutoff, collapsing per (candidate_id, job_id) to the latest stage.
4. Score each candidate: sum over their source-stages of
       similarity * stage_weight * exp(-months_ago / 12)
   Negative stages (rejected / withdrawn) count with a negative weight and
   flip the `negative_signal` flag but do not filter the candidate out.
5. Deduplicate, sort by `historical_score` desc, cap to `limit`, and hydrate
   with the live Candidate record so the UI can show availability badges.

Design notes
------------
- Pure, single-responsibility functions — no class state.
- Single SQL roundtrip for the stage aggregation (subquery picks latest stage
  per (candidate, job) pair) to avoid N+1.
- Callers that only need the boost amount use `fetch_historical_boost_map`,
  which returns just `{candidate_id -> source_count}` — one less query per
  recommendation request than fetching full breakdowns.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate, CandidateStatus
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.services.embedding_service import search_similar_jobs_by_job_id

logger = logging.getLogger(__name__)


# ── Configuration ────────────────────────────────────────────────────────────

TIER_A_THRESHOLD: float = 0.70
TIER_B_THRESHOLD: float = 0.55
TIER_A_MIN_CANDIDATES_FOR_EXTEND: int = 5
CUTOFF_MONTHS: int = 18
DECAY_HALF_LIFE_MONTHS: float = 12.0  # exp(-months_ago / 12)
SIMILAR_JOBS_TOP_K: int = 20
MAX_SOURCES_SHOWN: int = 5
BOOST_POINTS_PER_SOURCE: float = 5.0
BOOST_MAX_SOURCES: int = 3

STAGE_WEIGHT: dict[PipelineStage, float] = {
    PipelineStage.hired: 1.0,
    PipelineStage.acceptance: 1.0,
    PipelineStage.onboarding: 1.0,
    PipelineStage.client_interview: 0.7,
    PipelineStage.negotiation: 0.7,
    PipelineStage.cv_sent: 0.5,
    PipelineStage.interview: 0.3,
    PipelineStage.screening: 0.2,
    PipelineStage.prep_call: 0.2,
    PipelineStage.rejected: -0.3,
    PipelineStage.withdrawn: -0.3,
    # PipelineStage.new → 0 (skipped, no signal)
}

NEGATIVE_STAGES: frozenset[PipelineStage] = frozenset(
    {PipelineStage.rejected, PipelineStage.withdrawn}
)

# Stages meaning "ten kandydat realnie poszedł do klienta" — used by the
# similar-job notification (Faza 1 szybkiego przepinania) to decide whether a
# new request deserves a proactive ping.
CLIENT_FACING_STAGES: frozenset[PipelineStage] = frozenset(
    {
        PipelineStage.cv_sent,
        PipelineStage.client_interview,
        PipelineStage.negotiation,
        PipelineStage.acceptance,
        PipelineStage.onboarding,
        PipelineStage.hired,
    }
)

Tier = Literal["primary", "extended", "all"]


# ── Data classes ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class HistoricalSource:
    """One (candidate, historical job) pairing that explains a recommendation."""

    job_id: int
    job_title: str
    stage: PipelineStage
    similarity: float
    months_ago: float
    moved_at: datetime
    stage_weight: float
    contribution: float  # similarity * stage_weight * exp(-months_ago / half_life)
    client_id: Optional[int] = None


@dataclass(frozen=True)
class HistoricalCandidate:
    """Candidate ranked by their history on similar historical jobs."""

    candidate_id: int
    historical_score: float
    tier: Literal["A", "B"]
    negative_signal: bool
    sources: tuple[HistoricalSource, ...]
    # Faza 3 szybkiego przepinania: kandydat był już rozważany u klienta
    # targetowego joba (najszybsza ścieżka — klient go zna)…
    same_client: bool = False
    # …chyba że ten sam klient go wcześniej odrzucił / kandydat się wycofał —
    # wtedy ponowne wysłanie wymaga świadomej decyzji, nie bulk-selecta.
    rejected_by_same_client: bool = False


@dataclass(frozen=True)
class SimilarJobRef:
    """A single historical job semantically similar to the target."""

    job_id: int
    title: str
    similarity: float
    tier: Literal["A", "B"]


# ── Public API ───────────────────────────────────────────────────────────────


async def fetch_similar_jobs(
    job_id: int, *, tier: Tier = "primary", top_k: int = SIMILAR_JOBS_TOP_K
) -> tuple[list[SimilarJobRef], Literal["primary", "extended", "empty"]]:
    """Return similar-job refs for the requested tier.

    When ``tier="primary"``, only >= 0.70 hits are returned.
    When ``tier="extended"``, Tier A + Tier B in that order.
    When ``tier="all"``, same as "extended" but caller opted in explicitly.

    Returns ``(refs, tier_used)`` — ``tier_used`` reflects which threshold was
    actually applied, useful when a caller wants to know whether Tier B was
    needed to reach enough coverage.
    """
    hits = await search_similar_jobs_by_job_id(
        job_id=job_id, top_k=top_k, exclude_self=True
    )
    if not hits:
        return [], "empty"

    refs: list[SimilarJobRef] = []
    tier_used: Literal["primary", "extended", "empty"] = "primary"
    for hit in hits:
        score = float(hit.get("score") or 0.0)
        if score < TIER_B_THRESHOLD:
            continue
        payload = hit.get("payload") or {}
        assigned_tier: Literal["A", "B"] = "A" if score >= TIER_A_THRESHOLD else "B"
        if tier == "primary" and assigned_tier == "B":
            continue
        refs.append(
            SimilarJobRef(
                job_id=int(hit["job_id"]),
                title=str(payload.get("title") or f"Job {hit['job_id']}"),
                similarity=score,
                tier=assigned_tier,
            )
        )

    if tier in ("extended", "all") and any(r.tier == "B" for r in refs):
        tier_used = "extended"

    if not refs:
        return [], "empty"
    return refs, tier_used


async def fetch_historical_candidates(
    db: AsyncSession,
    job_id: int,
    *,
    tier: Tier = "primary",
    limit: int = 20,
    include_negative: bool = True,
    top_k_similar: int = SIMILAR_JOBS_TOP_K,
    target_client_id: Optional[int] = None,
) -> tuple[
    list[HistoricalCandidate],
    list[SimilarJobRef],
    Literal["primary", "extended", "empty"],
]:
    """Rank candidates by their pipeline presence on similar historical jobs.

    Implements the tier-fallback rule: if the primary tier yields fewer than
    ``TIER_A_MIN_CANDIDATES_FOR_EXTEND`` candidates, and the caller asked for
    the "primary" tier, we automatically promote to "extended" so the user
    does not see an empty section when Tier B could help.

    ``target_client_id`` (the client of the job we recommend FOR) powers the
    ``same_client`` / ``rejected_by_same_client`` flags; pass it when the
    caller already holds the Job row so we skip an extra query.
    """
    similar_refs, tier_used = await fetch_similar_jobs(
        job_id, tier=tier, top_k=top_k_similar
    )

    candidates: list[HistoricalCandidate] = []
    if similar_refs:
        candidates = await _rank_candidates_from_similar(
            db,
            similar_refs=similar_refs,
            include_negative=include_negative,
            target_client_id=target_client_id,
        )

    # Tier-fallback: primary → extended when Tier A either returned no similar
    # jobs at all OR returned too few candidates. This is the common case early
    # in a tenant's life — most joby sit just below the 0.70 cosine threshold.
    if tier == "primary" and (
        not similar_refs or len(candidates) < TIER_A_MIN_CANDIDATES_FOR_EXTEND
    ):
        extended_refs, extended_tier = await fetch_similar_jobs(
            job_id, tier="extended", top_k=top_k_similar
        )
        if extended_refs:
            similar_refs = extended_refs
            tier_used = extended_tier
            candidates = await _rank_candidates_from_similar(
                db,
                similar_refs=similar_refs,
                include_negative=include_negative,
                target_client_id=target_client_id,
            )

    if not similar_refs:
        return [], [], "empty"

    return candidates[:limit], similar_refs, tier_used


async def fetch_historical_boost_map(db: AsyncSession, job_id: int) -> dict[int, int]:
    """Lightweight path used by `/recommendations` to apply a rank boost.

    Returns ``{candidate_id -> source_count}`` where ``source_count`` is the
    number of distinct similar historical jobs the candidate appears in with a
    positive stage. Only Tier A + Tier B jobs are considered. Negative stages
    (rejected/withdrawn) are not counted towards the boost (they're recorded
    in the full breakdown but do not reward the candidate in the ranking).
    """
    similar_refs, _ = await fetch_similar_jobs(job_id, tier="extended")
    if not similar_refs:
        return {}

    candidates = await _rank_candidates_from_similar(
        db, similar_refs=similar_refs, include_negative=False
    )
    return {c.candidate_id: len(c.sources) for c in candidates if c.sources}


def boost_points_for_sources(source_count: int) -> float:
    """Convert a source count into recommendation-boost points."""
    capped = min(source_count, BOOST_MAX_SOURCES)
    return float(capped) * BOOST_POINTS_PER_SOURCE


# ── Internals ────────────────────────────────────────────────────────────────


def _months_ago(moved_at: datetime, now: Optional[datetime] = None) -> float:
    """Return elapsed months between ``moved_at`` and now (or given reference).

    We count calendar days / 30.0 to stay consistent with the cutoff logic
    and to avoid leap-year surprises. Returns 0.0 when the event is in the
    future (clock skew).
    """
    ref = now or datetime.now(timezone.utc)
    if moved_at.tzinfo is None:
        moved_at = moved_at.replace(tzinfo=timezone.utc)
    delta = ref - moved_at
    if delta.total_seconds() <= 0:
        return 0.0
    return delta.total_seconds() / (86400.0 * 30.0)


def _decay(months: float) -> float:
    """Exponential decay: 1.0 at 0 months, ~0.37 at 12, ~0.22 at 18."""
    if months <= 0:
        return 1.0
    return math.exp(-months / DECAY_HALF_LIFE_MONTHS)


async def _rank_candidates_from_similar(
    db: AsyncSession,
    *,
    similar_refs: list[SimilarJobRef],
    include_negative: bool,
    target_client_id: Optional[int] = None,
) -> list[HistoricalCandidate]:
    """Pull stages for similar jobs, aggregate per candidate, sort desc."""
    if not similar_refs:
        return []

    ref_by_id: dict[int, SimilarJobRef] = {r.job_id: r for r in similar_refs}
    similar_job_ids = list(ref_by_id.keys())
    cutoff = datetime.now(timezone.utc) - timedelta(days=CUTOFF_MONTHS * 30)

    # Latest stage per (candidate, job) inside the cutoff window.
    latest_subq = (
        select(
            CandidateStage.candidate_id.label("candidate_id"),
            CandidateStage.job_id.label("job_id"),
            func.max(CandidateStage.moved_at).label("latest"),
        )
        .where(CandidateStage.job_id.in_(similar_job_ids))
        .where(CandidateStage.moved_at >= cutoff)
        .group_by(CandidateStage.candidate_id, CandidateStage.job_id)
        .subquery()
    )

    stmt = (
        select(CandidateStage, Job.title, Job.client_id)
        .join(
            latest_subq,
            and_(
                CandidateStage.candidate_id == latest_subq.c.candidate_id,
                CandidateStage.job_id == latest_subq.c.job_id,
                CandidateStage.moved_at == latest_subq.c.latest,
            ),
        )
        .join(Job, Job.id == CandidateStage.job_id)
    )
    rows = (await db.execute(stmt)).all()
    if not rows:
        return []

    # Drop blacklisted candidates up front so they never reach the UI.
    cand_ids = {row[0].candidate_id for row in rows}
    blacklisted_stmt = select(Candidate.id).where(
        Candidate.id.in_(cand_ids),
        Candidate.status == CandidateStatus.blacklisted,
    )
    blacklisted = {cid for (cid,) in (await db.execute(blacklisted_stmt)).all()}

    now = datetime.now(timezone.utc)
    buckets: dict[int, list[HistoricalSource]] = {}

    for stage_row, job_title, job_client_id in rows:
        if stage_row.candidate_id in blacklisted:
            continue
        weight = STAGE_WEIGHT.get(stage_row.stage)
        if weight is None or weight == 0.0:
            continue
        if weight < 0 and not include_negative:
            continue

        ref = ref_by_id.get(stage_row.job_id)
        if ref is None:
            continue

        months = _months_ago(stage_row.moved_at, now)
        if months > CUTOFF_MONTHS:
            continue

        contribution = ref.similarity * weight * _decay(months)
        buckets.setdefault(stage_row.candidate_id, []).append(
            HistoricalSource(
                job_id=stage_row.job_id,
                job_title=job_title or f"Job {stage_row.job_id}",
                stage=stage_row.stage,
                similarity=ref.similarity,
                months_ago=round(months, 2),
                moved_at=stage_row.moved_at,
                stage_weight=weight,
                contribution=round(contribution, 4),
                client_id=job_client_id,
            )
        )

    results: list[HistoricalCandidate] = []
    for cid, sources in buckets.items():
        if not sources:
            continue
        sources_sorted = sorted(sources, key=lambda s: s.moved_at, reverse=True)
        historical_score = sum(s.contribution for s in sources_sorted)
        negative_signal = any(s.stage in NEGATIVE_STAGES for s in sources_sorted)
        # Candidate tier = best (A over B) across their sources.
        tier: Literal["A", "B"] = (
            "A" if any(ref_by_id[s.job_id].tier == "A" for s in sources_sorted) else "B"
        )
        same_client = target_client_id is not None and any(
            s.client_id == target_client_id for s in sources_sorted
        )
        rejected_by_same_client = target_client_id is not None and any(
            s.client_id == target_client_id and s.stage in NEGATIVE_STAGES
            for s in sources_sorted
        )
        results.append(
            HistoricalCandidate(
                candidate_id=cid,
                historical_score=round(historical_score, 4),
                tier=tier,
                negative_signal=negative_signal,
                sources=tuple(sources_sorted[:MAX_SOURCES_SHOWN]),
                same_client=same_client,
                rejected_by_same_client=rejected_by_same_client,
            )
        )

    results.sort(key=lambda c: c.historical_score, reverse=True)
    return results
