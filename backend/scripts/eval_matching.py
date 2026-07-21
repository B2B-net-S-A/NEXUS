"""
Offline evaluation of the hybrid matching engine (Phase 0 audit).

Takes N jobs that already have ground-truth signal in the pipeline
(CandidateStage with stage >= screening) and evaluates the top-K output of
`rank_candidates_for_job` using Precision@5, Recall@20, MRR, and nDCG@10.

Also supports ablation runs with overridden layer weights so you can see
whether the live six-layer default (35/30/12/8/5/10 = semantic/skills/salary/
location/availability/champion_fit) is optimal. Ablation profiles are passed
explicitly into ``rank_candidates_for_job`` — they no longer rely on the old
(silently no-op) monkeypatch of module constants.

Labeling note: candidates who never reached a positive pipeline stage are
treated as *unknown*, not as negatives — they are simply absent from a job's
ground-truth set. Precision@k still penalises unranked-but-relevant misses, but
the evaluator never fabricates a negative label from missing signal.

Usage
-----
    python -m scripts.eval_matching --jobs 10 --output docs/matching-eval.md
    python -m scripts.eval_matching --ablation --output docs/matching-ablation.md

Ground truth definition
-----------------------
Positive examples = candidates that a recruiter pushed past initial screening.
Graded relevance (for nDCG):

    hired                                      -> 4
    onboarding / negotiation / acceptance      -> 3
    client_interview                           -> 2
    interview / cv_sent                        -> 1
    screening                                  -> 0.5
    new / prep_call / rejected / withdrawn     -> 0  (excluded from GT)

The `new`/`prep_call` stages are excluded because they carry no qualification
signal yet, and terminal negative stages are excluded as well.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import sys
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

# Allow "python scripts/eval_matching.py" from the backend/ directory
BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import case, func, select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.models.candidate import Candidate, CandidateStatus  # noqa: E402
from app.models.job import Job  # noqa: E402
from app.models.recruitment_pipeline import CandidateStage, PipelineStage  # noqa: E402
from app.services import scoring_service  # noqa: E402
from app.services.embedding_service import (  # noqa: E402
    _build_job_text,
    search_candidates_semantic,
)
from app.services.scoring_service import rank_candidates_for_job  # noqa: E402
from app.services.similar_job_candidates import (  # noqa: E402
    boost_points_for_sources,
    fetch_historical_boost_map,
)

logger = logging.getLogger("eval_matching")


# ── Ground truth config ──────────────────────────────────────────────────────

STAGE_RELEVANCE: dict[PipelineStage, float] = {
    PipelineStage.hired: 4.0,
    PipelineStage.onboarding: 3.0,
    PipelineStage.negotiation: 3.0,
    PipelineStage.acceptance: 3.0,
    PipelineStage.client_interview: 2.0,
    PipelineStage.interview: 1.0,
    PipelineStage.cv_sent: 1.0,
    PipelineStage.screening: 0.5,
    # Excluded from GT (no signal or negative): new, prep_call, rejected, withdrawn
}

POSITIVE_STAGES: frozenset[PipelineStage] = frozenset(STAGE_RELEVANCE.keys())


# ── Data classes ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class WeightProfile:
    """Six-layer point budget matching the live scoring engine.

    The engine (``scoring_service.WeightProfile``) scores with SIX layers
    summing to 100: semantic + skills + salary + location + availability +
    champion_fit. The old evaluator profile had only five and monkeypatched
    module constants that the engine no longer reads at call time (it takes an
    explicit ``profile=`` argument), so every "ablation" silently scored
    identically. This profile now carries all six layers and is passed straight
    into ``rank_candidates_for_job`` — see ``_to_scoring_profile``.
    """

    name: str
    semantic: float
    skills: float
    salary: float
    location: float
    availability: float
    champion_fit: float

    @property
    def budget(self) -> float:
        return (
            self.semantic
            + self.skills
            + self.salary
            + self.location
            + self.availability
            + self.champion_fit
        )

    def as_dict(self) -> dict:
        return asdict(self)


# Mirrors the live engine default (scoring_service: 35/30/12/8/5/10 = 100).
DEFAULT_PROFILE = WeightProfile(
    name="default_35_30_12_8_5_10",
    semantic=35.0,
    skills=30.0,
    salary=12.0,
    location=8.0,
    availability=5.0,
    champion_fit=10.0,
)

# Each ablation profile is a valid six-layer budget summing to exactly 100 so
# the comparison isolates *distribution*, not total point mass.
ABLATION_PROFILES: tuple[WeightProfile, ...] = (
    DEFAULT_PROFILE,
    WeightProfile("semantic_only", 100.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    WeightProfile("skills_only", 0.0, 100.0, 0.0, 0.0, 0.0, 0.0),
    WeightProfile("skills_heavy", 20.0, 55.0, 10.0, 5.0, 5.0, 5.0),
    WeightProfile("semantic_heavy", 55.0, 20.0, 10.0, 5.0, 5.0, 5.0),
    WeightProfile("balanced", 25.0, 25.0, 20.0, 15.0, 5.0, 10.0),
)


def _without_champion(profile: WeightProfile) -> WeightProfile:
    """Zero the champion_fit layer to close eval label leakage (AI-P0-01).

    ``_score_champion_fit`` reads ``CandidateStage.screening_answers`` for the
    exact (candidate, job) pair — but those answers only exist for candidates
    already advanced to screening, which is *precisely* the ground-truth
    positive set this eval scores against. Scoring on that signal inflates every
    metric (the model is peeking at the label). Ranking metrics don't depend on
    the absolute budget, so dropping the layer to 0 is the honest headline.
    Opt back in with ``--include-champion``.
    """
    return replace(profile, champion_fit=0.0)


def _to_scoring_profile(profile: WeightProfile) -> "scoring_service.WeightProfile":
    """Convert an eval profile into the engine's ``WeightProfile``.

    This is the ONE place ablation weights reach the scoring engine, replacing
    the old (no-op) monkeypatch of ``scoring_service.SEMANTIC_MAX`` &c.
    """
    return scoring_service.WeightProfile(
        name=profile.name,
        semantic=profile.semantic,
        skills=profile.skills,
        salary=profile.salary,
        location=profile.location,
        availability=profile.availability,
        champion_fit=profile.champion_fit,
    )


@dataclass
class JobEval:
    job_id: int
    job_title: str
    ground_truth_ids: list[int]
    ranked_candidate_ids: list[int]
    relevance_map: dict[int, float]
    precision_at_5: float
    recall_at_20: float
    mrr: float
    ndcg_at_10: float
    pool_size: int
    # Phase 14: fraction of top-10 ranked candidates who were present in the
    # pipeline of at least one semantically-similar historical job.
    historical_hit_rate_at_10: float = 0.0
    notes: str = ""


@dataclass
class ProfileEval:
    profile: WeightProfile
    per_job: list[JobEval] = field(default_factory=list)
    with_boost: bool = False

    @property
    def mean_precision_at_5(self) -> float:
        return _mean(j.precision_at_5 for j in self.per_job)

    @property
    def mean_recall_at_20(self) -> float:
        return _mean(j.recall_at_20 for j in self.per_job)

    @property
    def mean_mrr(self) -> float:
        return _mean(j.mrr for j in self.per_job)

    @property
    def mean_ndcg_at_10(self) -> float:
        return _mean(j.ndcg_at_10 for j in self.per_job)

    @property
    def mean_historical_hit_rate_at_10(self) -> float:
        return _mean(j.historical_hit_rate_at_10 for j in self.per_job)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _mean(values: Iterable[float]) -> float:
    vs = [v for v in values]
    return sum(vs) / len(vs) if vs else 0.0


@dataclass(frozen=True)
class DataQuality:
    total_jobs: int
    jobs_missing_must: int
    jobs_missing_nice: int
    total_candidates: int
    candidates_skills_list: int
    candidates_skills_dict: int
    candidates_skills_null: int

    def as_markdown_rows(self) -> list[str]:
        pct = lambda n, d: f"{n} ({(n / d * 100):.0f}%)" if d else "0"
        return [
            f"- Jobs: {self.total_jobs} total; **missing must_skills**: {pct(self.jobs_missing_must, self.total_jobs)}; missing nice_skills: {pct(self.jobs_missing_nice, self.total_jobs)}",
            f"- Candidate skills JSONB format: list-of-dict/str = {self.candidates_skills_list}, dict (`technologies`/`stack`) = {self.candidates_skills_dict}, null = {self.candidates_skills_null} (total={self.total_candidates})",
        ]


async def _audit_data_quality(db: AsyncSession) -> DataQuality:
    total_jobs = await db.scalar(select(func.count(Job.id))) or 0
    # Guard with CASE — prod has rows where must_skills/nice_skills are scalar
    # values (not arrays). Postgres does not short-circuit AND in WHERE, so a
    # plain `jsonb_typeof = 'array' AND jsonb_array_length(...)` crashes when
    # the planner evaluates jsonb_array_length first on a scalar row.
    must_len = case(
        (func.jsonb_typeof(Job.must_skills) == "array",
         func.jsonb_array_length(Job.must_skills)),
        else_=0,
    )
    nice_len = case(
        (func.jsonb_typeof(Job.nice_skills) == "array",
         func.jsonb_array_length(Job.nice_skills)),
        else_=0,
    )
    present_must = await db.scalar(
        select(func.count(Job.id)).where(must_len > 0)
    ) or 0
    missing_must = total_jobs - present_must
    present_nice = await db.scalar(
        select(func.count(Job.id)).where(nice_len > 0)
    ) or 0
    missing_nice = total_jobs - present_nice

    total_candidates = await db.scalar(select(func.count(Candidate.id))) or 0
    list_fmt = await db.scalar(
        select(func.count(Candidate.id)).where(
            func.jsonb_typeof(Candidate.skills) == "array"
        )
    ) or 0
    dict_fmt = await db.scalar(
        select(func.count(Candidate.id)).where(
            func.jsonb_typeof(Candidate.skills) == "object"
        )
    ) or 0
    null_fmt = await db.scalar(
        select(func.count(Candidate.id)).where(Candidate.skills.is_(None))
    ) or 0

    return DataQuality(
        total_jobs=total_jobs,
        jobs_missing_must=missing_must,
        jobs_missing_nice=missing_nice,
        total_candidates=total_candidates,
        candidates_skills_list=list_fmt,
        candidates_skills_dict=dict_fmt,
        candidates_skills_null=null_fmt,
    )


async def _discover_jobs_with_ground_truth(
    db: AsyncSession, limit: int, min_ground_truth: int = 3
) -> list[tuple[Job, list[int], dict[int, float]]]:
    """
    Return jobs with at least `min_ground_truth` positive candidates in pipeline.

    The relevance_map keeps the highest relevance reached by each candidate
    (so if a person went through screening -> hired, they score as hired).
    """
    # Aggregate max-relevance per (job, candidate) across all historical stage rows
    stages_res = await db.execute(
        select(CandidateStage.job_id, CandidateStage.candidate_id, CandidateStage.stage)
    )
    rows = stages_res.all()

    job_to_gt: dict[int, dict[int, float]] = {}
    for job_id, candidate_id, stage in rows:
        if stage not in POSITIVE_STAGES:
            continue
        rel = STAGE_RELEVANCE[stage]
        current = job_to_gt.setdefault(job_id, {}).get(candidate_id, 0.0)
        if rel > current:
            job_to_gt[job_id][candidate_id] = rel

    qualifying_job_ids = [jid for jid, m in job_to_gt.items() if len(m) >= min_ground_truth]
    if not qualifying_job_ids:
        return []

    jobs_res = await db.execute(
        select(Job).where(Job.id.in_(qualifying_job_ids)).order_by(Job.id)
    )
    jobs = jobs_res.scalars().all()[:limit]

    return [
        (j, list(job_to_gt[j.id].keys()), job_to_gt[j.id])
        for j in jobs
    ]


async def _score_job_candidates(
    job: Job,
    db: AsyncSession,
    *,
    profile: WeightProfile = DEFAULT_PROFILE,
    pool_cap: int = 200,
    with_historical_boost: bool = False,
) -> tuple[list[int], int, dict[int, int]]:
    """
    Reproduce the recommendations endpoint pipeline for one job:
      Qdrant pool -> re-rank with hybrid scoring.

    Returns ``(ranked_candidate_ids desc by total score, pool_size, boost_map)``
    where ``boost_map`` is ``{candidate_id -> source_count}`` from
    similar-job history. When ``with_historical_boost`` is True, the map is
    also folded into ranking as ``total += min(count, 3) * 5``.
    """
    query_text = _build_job_text(job)

    try:
        hits = await search_candidates_semantic(query_text, top_k=pool_cap)
    except Exception as e:
        logger.warning("semantic search failed for job=%s: %s", job.id, e)
        hits = []

    similarity_map = {h["candidate_id"]: h["score"] for h in hits}
    candidate_ids = list(similarity_map.keys())

    if not candidate_ids:
        fallback = await db.execute(
            select(Candidate.id)
            .where(Candidate.status != CandidateStatus.blacklisted)
            .limit(pool_cap)
        )
        candidate_ids = [c for (c,) in fallback.all()]

    pool_size = len(candidate_ids)
    if not candidate_ids:
        return [], 0, {}

    cand_res = await db.execute(
        select(Candidate).where(Candidate.id.in_(candidate_ids))
    )
    candidates = cand_res.scalars().all()

    breakdowns = await rank_candidates_for_job(
        job,
        candidates,
        db,
        similarity_map=similarity_map,
        profile=_to_scoring_profile(profile),
    )

    try:
        boost_map = await fetch_historical_boost_map(db, job.id)
    except Exception as e:
        logger.warning("boost_map lookup failed for job=%s: %s", job.id, e)
        boost_map = {}

    if with_historical_boost and boost_map:
        for b in breakdowns:
            count = boost_map.get(b.candidate_id, 0)
            if count <= 0:
                continue
            b.total += boost_points_for_sources(count)
        breakdowns.sort(key=lambda r: -r.total)

    return [b.candidate_id for b in breakdowns], pool_size, boost_map


def _metrics(
    ranked_ids: list[int], relevance: dict[int, float]
) -> tuple[float, float, float, float]:
    """Compute (Precision@5, Recall@20, MRR, nDCG@10)."""
    gt_ids = set(relevance.keys())
    if not gt_ids:
        return 0.0, 0.0, 0.0, 0.0

    top5 = ranked_ids[:5]
    top20 = ranked_ids[:20]

    precision_at_5 = sum(1 for c in top5 if c in gt_ids) / 5.0
    recall_at_20 = sum(1 for c in top20 if c in gt_ids) / len(gt_ids)

    mrr = 0.0
    for rank, cid in enumerate(ranked_ids, start=1):
        if cid in gt_ids:
            mrr = 1.0 / rank
            break

    # nDCG@10 with graded relevance
    def dcg(rels: list[float]) -> float:
        return sum(r / math.log2(i + 2) for i, r in enumerate(rels))

    gains = [relevance.get(c, 0.0) for c in ranked_ids[:10]]
    ideal_gains = sorted(relevance.values(), reverse=True)[:10]
    denom = dcg(ideal_gains)
    ndcg_at_10 = dcg(gains) / denom if denom else 0.0

    return precision_at_5, recall_at_20, mrr, ndcg_at_10


# ── Orchestration ────────────────────────────────────────────────────────────


async def evaluate_profile(
    profile: WeightProfile,
    job_records: list[tuple[Job, list[int], dict[int, float]]],
    db: AsyncSession,
    *,
    with_historical_boost: bool = False,
) -> ProfileEval:
    result = ProfileEval(profile=profile, with_boost=with_historical_boost)
    for job, gt_ids, relevance in job_records:
        ranked_ids, pool_size, boost_map = await _score_job_candidates(
            job, db, profile=profile, with_historical_boost=with_historical_boost
        )
        p5, r20, mrr, ndcg = _metrics(ranked_ids, relevance)
        hhr = _historical_hit_rate(ranked_ids, boost_map, k=10)
        result.per_job.append(
            JobEval(
                job_id=job.id,
                job_title=job.title or f"Job {job.id}",
                ground_truth_ids=gt_ids,
                ranked_candidate_ids=ranked_ids[:20],
                relevance_map={str(k): v for k, v in relevance.items()},  # type: ignore[misc]
                precision_at_5=p5,
                recall_at_20=r20,
                mrr=mrr,
                ndcg_at_10=ndcg,
                historical_hit_rate_at_10=hhr,
                pool_size=pool_size,
                notes=("no pool" if pool_size == 0 else ""),
            )
        )
    return result


def _historical_hit_rate(
    ranked_ids: list[int], boost_map: dict[int, int], *, k: int = 10
) -> float:
    """Fraction of the top-k ranked candidates who appear in the boost map.

    Measures "would this candidate have been found by looking at similar
    past jobs?" — a proxy for the feature's signal strength. When k is
    larger than the ranked list, it caps to the list length.
    """
    if not ranked_ids or not boost_map:
        return 0.0
    top = ranked_ids[:k]
    if not top:
        return 0.0
    hits = sum(1 for cid in top if boost_map.get(cid, 0) > 0)
    return hits / len(top)


def _go_no_go(
    default: "ProfileEval",
    best: "ProfileEval",
    data_quality: DataQuality,
) -> str:
    """Decide Go/No-Go using both default and best profile, plus data-quality context."""
    all_jobs_missing_must = (
        data_quality.total_jobs > 0
        and data_quality.jobs_missing_must == data_quality.total_jobs
    )

    d_recall = default.mean_recall_at_20
    d_prec = default.mean_precision_at_5
    b_recall = best.mean_recall_at_20
    b_prec = best.mean_precision_at_5

    if d_recall >= 0.80 and d_prec >= 0.60:
        return (
            "GO — current scoring meets the bar (Recall@20 ≥ 80%, Precision@5 ≥ 60%). "
            "Proceed to Phase A."
        )
    if b_recall >= 0.60 and b_prec >= 0.15:
        data_note = (
            " Note: these numbers are on a dataset where 100% of jobs lack `must_skills`, "
            "so the skills layer is effectively disabled — production numbers should be "
            "materially higher once must/nice are populated."
            if all_jobs_missing_must
            else ""
        )
        weight_note = (
            f" Best profile `{best.profile.name}` (Recall@20 = {b_recall:.2f}) beats "
            f"default (Recall@20 = {d_recall:.2f}) — recommend Phase D1 weight tuning."
        )
        return "GO (with caveats) — ship Phase A in parallel with Phase D1/B1." + weight_note + data_note
    if d_recall >= 0.50:
        return (
            "CAUTION — Recall@20 below the 0.60 target even after ablation. Ship Phase A "
            "only for UX that does not block on match quality; start Phase B1 (skill "
            "aliases) and Phase D1 (weight tuning) immediately."
        )
    return (
        "NO-GO — Recall@20 under 50%. Fix scoring (B1 aliases + D1 tuning) or data quality "
        "(backfill must/nice skills) before investing in Phase A UX. Re-run this eval."
    )


def _render_markdown(
    profile_results: list[ProfileEval],
    generated_at: datetime,
    data_quality: DataQuality,
    voyage_configured: bool,
    error_cases_max: int = 10,
) -> str:
    lines: list[str] = []
    lines.append("# Matching Quality Audit — Phase 0")
    lines.append("")
    lines.append(f"Generated at: `{generated_at.isoformat()}`")
    lines.append("")
    lines.append("## Data quality snapshot")
    lines.append("")
    lines.extend(data_quality.as_markdown_rows())
    lines.append(
        f"- Voyage API key configured: **{'yes' if voyage_configured else 'no (semantic layer inert — pool falls back to all active candidates)'}**"
    )
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(
        "| Profile | Boost | Jobs | Precision@5 | Recall@20 | MRR | nDCG@10 | HistHit@10 |"
    )
    lines.append("|---|:---:|---:|---:|---:|---:|---:|---:|")
    for p in profile_results:
        boost_flag = "✓" if p.with_boost else ""
        lines.append(
            f"| `{p.profile.name}` | {boost_flag} | {len(p.per_job)} "
            f"| {p.mean_precision_at_5:.3f} "
            f"| {p.mean_recall_at_20:.3f} "
            f"| {p.mean_mrr:.3f} "
            f"| {p.mean_ndcg_at_10:.3f} "
            f"| {p.mean_historical_hit_rate_at_10:.3f} |"
        )
    lines.append("")

    default = next(
        (p for p in profile_results if p.profile.name == DEFAULT_PROFILE.name),
        profile_results[0],
    )
    best = max(profile_results, key=lambda p: p.mean_recall_at_20)
    lines.append("## Go/No-Go verdict")
    lines.append("")
    lines.append(f"> {_go_no_go(default, best, data_quality)}")
    lines.append("")

    # Findings derived from data quality + profile comparison
    lines.append("## Findings & recommended actions")
    lines.append("")
    findings: list[str] = []
    if data_quality.jobs_missing_must / max(data_quality.total_jobs, 1) > 0.2:
        pct = data_quality.jobs_missing_must / data_quality.total_jobs * 100
        findings.append(
            f"**{pct:.0f}% jobs lack `must_skills`** — skills layer short-circuits to max for "
            "these jobs (see `_score_skills` line 150). Run `POST /api/jobs/{id}/refresh-criteria` "
            "or a one-time backfill so skills layer can differentiate candidates."
        )
    if data_quality.candidates_skills_dict > 0:
        findings.append(
            f"**{data_quality.candidates_skills_dict} candidates** store skills as a dict "
            "(`{technologies: [...]}`) — already handled by the patched `_skill_names()` "
            "parser, but consider migrating to the canonical `[{name, level, years}]` shape "
            "so UI and filters see uniform data."
        )
    if not voyage_configured:
        findings.append(
            "**Semantic layer is inert** (no `VOYAGE_API_KEY` in env) — scoring falls back to "
            "skills/salary/location/availability only. Configure Voyage + embed existing "
            "candidates/jobs before trusting production numbers."
        )
    # Compare best ablation profile to default
    best = max(profile_results, key=lambda p: p.mean_recall_at_20)
    if best.profile.name != DEFAULT_PROFILE.name and best.mean_recall_at_20 > default.mean_recall_at_20 + 0.02:
        findings.append(
            f"**Profile `{best.profile.name}`** beats the default on Recall@20 "
            f"({best.mean_recall_at_20:.3f} vs {default.mean_recall_at_20:.3f}). "
            "Consider adopting these weights (Phase D1 — weight tuning)."
        )
    if not findings:
        findings.append(
            "No systemic issues detected at data layer. Any recall gap is attributable to "
            "the scoring function; revisit layer formulas or embedding model."
        )
    for f in findings:
        lines.append(f"- {f}")
    lines.append("")

    for p in profile_results:
        lines.append(f"## Profile: `{p.profile.name}`")
        lines.append("")
        lines.append(
            "Weights: semantic={0}, skills={1}, salary={2}, location={3}, "
            "availability={4}, champion_fit={5} (budget={6:.0f})".format(
                p.profile.semantic,
                p.profile.skills,
                p.profile.salary,
                p.profile.location,
                p.profile.availability,
                p.profile.champion_fit,
                p.profile.budget,
            )
        )
        lines.append("")
        lines.append("| Job ID | Title | GT size | Pool | P@5 | R@20 | MRR | nDCG@10 |")
        lines.append("|---:|---|---:|---:|---:|---:|---:|---:|")
        for j in p.per_job:
            title = (j.job_title or "").replace("|", "\\|")[:60]
            lines.append(
                f"| {j.job_id} | {title} | {len(j.ground_truth_ids)} "
                f"| {j.pool_size} | {j.precision_at_5:.2f} "
                f"| {j.recall_at_20:.2f} | {j.mrr:.2f} | {j.ndcg_at_10:.2f} |"
            )
        lines.append("")

    # Qualitative error analysis on default profile
    error_cases: list[JobEval] = sorted(
        default.per_job, key=lambda j: j.recall_at_20
    )[:error_cases_max]
    if error_cases:
        lines.append("## Error analysis (worst Recall@20, default profile)")
        lines.append("")
        for j in error_cases:
            gt_set = set(j.ground_truth_ids)
            missed = [cid for cid in gt_set if cid not in j.ranked_candidate_ids]
            lines.append(
                f"- **Job {j.job_id} — {j.job_title}** — "
                f"GT={len(gt_set)}, R@20={j.recall_at_20:.2f}, "
                f"missed={missed[:5]}{' ...' if len(missed) > 5 else ''}"
            )
        lines.append("")

    lines.append("## Reproduce")
    lines.append("")
    lines.append("```bash")
    lines.append("cd backend && python -m scripts.eval_matching --ablation \\")
    lines.append("    --output ../docs/matching-eval-$(date +%F).md")
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


async def _run(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    profiles: list[WeightProfile]
    if args.ablation:
        profiles = list(ABLATION_PROFILES)
    else:
        profiles = [DEFAULT_PROFILE]

    # AI-P0-01: close champion_fit label leakage unless explicitly opted in.
    if not args.include_champion:
        profiles = [_without_champion(p) for p in profiles]
        logger.info(
            "champion_fit zeroed (leakage guard) — pass --include-champion to keep it"
        )

    # Phase B1: preload alias map so skills layer sees canonical names.
    try:
        from app.services.skill_taxonomy_loader import refresh_alias_map

        count = await refresh_alias_map()
        logger.info("Alias map preloaded: %d entries", count)
    except Exception as e:
        logger.warning("Alias map preload skipped: %s", e)

    async with AsyncSessionLocal() as db:
        data_quality = await _audit_data_quality(db)
        job_records = await _discover_jobs_with_ground_truth(
            db, limit=args.jobs, min_ground_truth=args.min_gt
        )

        if not job_records:
            logger.error(
                "No jobs with ≥%s ground-truth candidates found. "
                "Seed the pipeline first (e.g. `python seed_v6_pipeline.py`).",
                args.min_gt,
            )
            return 2

        logger.info(
            "Evaluating %s jobs across %s profiles", len(job_records), len(profiles)
        )

        profile_results: list[ProfileEval] = []
        for profile in profiles:
            logger.info("-> profile %s", profile.name)
            res = await evaluate_profile(
                profile,
                job_records,
                db,
                with_historical_boost=args.with_historical_boost,
            )
            profile_results.append(res)

        # Ablation mode additionally runs the default profile WITH boost so the
        # markdown table shows the direct delta vs. baseline.
        if args.ablation and not args.with_historical_boost:
            logger.info("-> profile default + historical_boost (delta run)")
            delta_res = await evaluate_profile(
                DEFAULT_PROFILE,
                job_records,
                db,
                with_historical_boost=True,
            )
            # Rename for unambiguous output.
            delta_res = ProfileEval(
                profile=WeightProfile(
                    name=f"{DEFAULT_PROFILE.name}+boost",
                    semantic=DEFAULT_PROFILE.semantic,
                    skills=DEFAULT_PROFILE.skills,
                    salary=DEFAULT_PROFILE.salary,
                    location=DEFAULT_PROFILE.location,
                    availability=DEFAULT_PROFILE.availability,
                    champion_fit=DEFAULT_PROFILE.champion_fit,
                ),
                per_job=delta_res.per_job,
                with_boost=True,
            )
            profile_results.append(delta_res)

    generated_at = datetime.now(timezone.utc)
    voyage_configured = bool(os.environ.get("VOYAGE_API_KEY"))
    markdown = _render_markdown(
        profile_results,
        generated_at,
        data_quality=data_quality,
        voyage_configured=voyage_configured,
    )

    out_path = Path(args.output).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(markdown, encoding="utf-8")
    logger.info("Report written to %s", out_path)

    if args.json:
        json_path = out_path.with_suffix(".json")
        from app.services.embedding_service import VECTOR_SIZE as _VEC

        payload = {
            "generated_at": generated_at.isoformat(),
            "manifest": {
                # Explicit legacy placeholders until later plan PRs introduce
                # real runtime versioning (PR4 scoring, PR6 index, PR10 taxonomy).
                "scoring_algorithm_version": getattr(
                    scoring_service, "SCORING_ALGORITHM_VERSION", "scoring-v1-legacy"
                ),
                "embedding_model": os.environ.get(
                    "EMBEDDING_MODEL", "voyage-3-large"
                ),
                "embedding_dimension": _VEC,
                "index_version": "index-legacy-v1",
                "taxonomy_version": "taxonomy-legacy-v1",
                "eval_dataset": "historical_pipeline_stages",
                "unknown_treated_as_negative": False,
                "num_jobs": len(job_records),
                "min_ground_truth": args.min_gt,
            },
            "profiles": [
                {
                    "profile": p.profile.as_dict(),
                    "with_boost": p.with_boost,
                    "mean_precision_at_5": p.mean_precision_at_5,
                    "mean_recall_at_20": p.mean_recall_at_20,
                    "mean_mrr": p.mean_mrr,
                    "mean_ndcg_at_10": p.mean_ndcg_at_10,
                    "mean_historical_hit_rate_at_10": (
                        p.mean_historical_hit_rate_at_10
                    ),
                    "per_job": [asdict(j) for j in p.per_job],
                }
                for p in profile_results
            ],
        }
        json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.info("JSON dump written to %s", json_path)

    # AI-P0-01: quality gate. Without this the eval always exit-0'd, so it could
    # never guard CI — a regression in matching would go green. The primary
    # profile is profile_results[0] (default, champion-masked by default).
    exit_code = 0
    primary = profile_results[0]
    if (
        args.fail_under_precision is not None
        and primary.mean_precision_at_5 < args.fail_under_precision
    ):
        logger.error(
            "QUALITY GATE FAIL: Precision@5 %.4f < threshold %.4f",
            primary.mean_precision_at_5,
            args.fail_under_precision,
        )
        exit_code = 1
    if (
        args.fail_under_recall is not None
        and primary.mean_recall_at_20 < args.fail_under_recall
    ):
        logger.error(
            "QUALITY GATE FAIL: Recall@20 %.4f < threshold %.4f",
            primary.mean_recall_at_20,
            args.fail_under_recall,
        )
        exit_code = 1
    return exit_code


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Offline evaluation of Nexus ATS hybrid matching."
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=10,
        help="Max number of jobs to evaluate (need ≥ --min-gt ground-truth each).",
    )
    parser.add_argument(
        "--min-gt",
        type=int,
        default=3,
        help="Minimum ground-truth candidates per job (default: 3).",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "docs",
            f"matching-eval-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.md",
        ),
        help="Markdown report output path.",
    )
    parser.add_argument(
        "--ablation",
        action="store_true",
        help="Run every profile in ABLATION_PROFILES instead of just default.",
    )
    parser.add_argument(
        "--with-historical-boost",
        action="store_true",
        help=(
            "Apply similar-job historical boost to rankings. When combined "
            "with --ablation, a baseline (no boost) and boost variant are run "
            "for the default profile so you can read the delta directly."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Also write a sibling .json file with raw metrics.",
    )
    parser.add_argument(
        "--include-champion",
        action="store_true",
        help=(
            "Include the champion_fit layer. OFF by default: it reads "
            "screening_answers that only exist for ground-truth positives "
            "(label leakage, AI-P0-01), so the honest headline zeroes it."
        ),
    )
    parser.add_argument(
        "--fail-under-precision",
        type=float,
        default=None,
        help=(
            "Quality gate: exit non-zero if the primary profile's mean "
            "Precision@5 is below this value (e.g. 0.15)."
        ),
    )
    parser.add_argument(
        "--fail-under-recall",
        type=float,
        default=None,
        help=(
            "Quality gate: exit non-zero if the primary profile's mean "
            "Recall@20 is below this value."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
