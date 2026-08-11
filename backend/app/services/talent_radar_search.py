"""Talent Radar — score the candidate base against an ad-hoc request.

Paste a client request (or a Champion profile) and get a ranked list of people,
without creating a Job. The mirror image of ``cv_match_preview`` (CV in → jobs
out); here it is a role in → candidates out. Nothing is persisted.

Everything below the composition already existed — retrieval, scoring, the
eligibility filter, the batched per-job context. This module is the glue, which
is why it is small.

Two constraints are deliberate and load-bearing:

**A client is mandatory.** ``filter_eligible_candidates`` evaluates the client
blacklist, NDA, competitor conflicts and the hiring-manager veto *by
``job.client_id``*. An ad-hoc search without a client cannot run those checks —
they would not fail, they would silently pass, which is exactly the gap found in
``/ai-matches`` on 2026-08-11. Rather than surface an unchecked list, the module
refuses to answer without a client.

**No LLM call.** Free-text requests are fed to the engine as the job narrative;
``_score_skills`` already derives implicit must-skills from the JD text or the
Champion profile when ``must_skills`` is empty. So the module costs one Voyage
query embedding and nothing else — no quota gate, no per-search spend.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.candidate import Candidate
from app.models.client import Client
from app.services.embedding_service import (
    _build_job_text,
    search_candidates_semantic,
)
from app.services.pipeline_eligibility import filter_eligible_candidates
from app.services.scoring_service import ScoreBreakdown, rank_candidates_for_job

logger = logging.getLogger(__name__)


class TalentRadarError(ValueError):
    """Input the caller can fix — surfaced as 4xx, never as a 500."""


@dataclass(frozen=True)
class RadarQuery:
    """What to search for. Exactly one of `text` / `champion_profile` is required."""

    client_id: int
    text: Optional[str] = None
    champion_profile: Optional[dict[str, Any]] = None
    title: Optional[str] = None
    location: Optional[str] = None
    top_k: int = 20
    min_score: Optional[float] = None


@dataclass
class RadarResult:
    breakdowns: list[ScoreBreakdown]
    pool_size: int
    eligible_size: int
    degraded: bool
    reason: Optional[str] = None
    # `ScoreBreakdown` carries `candidate_id` and nothing else about the person.
    # A search that answers with opaque integers is not a search a recruiter can
    # read, and making the browser resolve each id would be an N+1 over the
    # network on a list this endpoint already holds in memory.
    candidates_by_id: dict[int, Any] = field(default_factory=dict)

    def as_meta(self) -> dict[str, Any]:
        return {
            "pool_size": self.pool_size,
            "eligible_size": self.eligible_size,
            "returned": len(self.breakdowns),
            "degraded": self.degraded,
            "reason": self.reason,
        }


def shape_radar_candidate(candidate: Any) -> dict[str, Any]:
    """Identity fields a result row needs — and no more.

    Mirrors `_shape_seek_candidate` in `recommendations.py`, minus `email`.
    A ranked list is a triage surface: the recruiter reads it to decide whom to
    open. Contact details belong on the profile behind that click, so shipping
    them in every search response would widen the exposure of personal data
    without changing a single decision made on this screen.
    """

    availability = getattr(candidate, "availability_status", None)
    return {
        "id": candidate.id,
        "name": candidate.name,
        "lastname": candidate.lastname,
        "location": getattr(candidate, "location", None),
        "competence_category": getattr(candidate, "competence_category", None),
        "years_it_experience": getattr(candidate, "years_it_experience", None),
        "availability_status": availability.value if availability else None,
        "champion": bool(getattr(candidate, "champion", False)),
        "avatar_url": getattr(candidate, "avatar_url", None),
    }


def build_ephemeral_job(query: RadarQuery) -> SimpleNamespace:
    """A Job-shaped object that is never persisted.

    Every attribute the scoring and embedding paths touch is set explicitly.
    A `SimpleNamespace` rather than an unsaved ORM `Job` on purpose: an unsaved
    instance still carries relationship descriptors that can trigger a lazy load
    on attribute access, which in async SQLAlchemy raises `MissingGreenlet`
    rather than returning a default.

    `id=None` is meaningful, not a placeholder: `build_job_scoring_context`
    filters `CandidateStage.job_id == job.id`, so a None id yields no screening
    rows — correct, because an ad-hoc search has no pipeline history to read.
    """
    return SimpleNamespace(
        id=None,
        client_id=query.client_id,
        title=(query.title or "").strip() or None,
        description=(query.text or "").strip() or None,
        requirements=None,
        champion_profile=query.champion_profile or None,
        # No structured skills: `_score_skills` derives implicit must-skills from
        # the Champion profile, then from the narrative, so a pasted request is
        # scored on its content rather than on an empty list.
        must_skills=None,
        nice_skills=None,
        location=(query.location or "").strip() or None,
        remote_policy=None,
        salary_min=None,
        salary_max=None,
        deadline=None,
        seniority=None,
        subcategory=None,
        industry=None,
        embedding_id=None,
    )


async def _load_candidates(
    db: AsyncSession, candidate_ids: Sequence[int]
) -> list[Candidate]:
    if not candidate_ids:
        return []
    rows = (
        (await db.execute(select(Candidate).where(Candidate.id.in_(candidate_ids))))
        .scalars()
        .all()
    )
    by_id = {c.id: c for c in rows}
    # Preserve retrieval order; a missing row means the vector outlived its
    # candidate (there are ~1 900 such orphans in Qdrant) and is skipped.
    return [by_id[cid] for cid in candidate_ids if cid in by_id]


async def search(db: AsyncSession, query: RadarQuery) -> RadarResult:
    """Rank the candidate base against an ad-hoc role. Persists nothing."""
    if not query.text and not query.champion_profile:
        raise TalentRadarError(
            "Podaj treść zapytania albo profil Championa — bez tego nie ma czego szukać."
        )
    client = await db.scalar(select(Client).where(Client.id == query.client_id))
    if client is None:
        # Not a formality: without a real client the NDA / competitor / veto
        # checks below have nothing to evaluate against.
        raise TalentRadarError(
            "Wskaż klienta — bez niego nie da się sprawdzić NDA, konfliktów "
            "konkurencyjnych ani weta hiring managera."
        )

    job = build_ephemeral_job(query)
    query_text = _build_job_text(job)
    if not query_text.strip():
        raise TalentRadarError("Zapytanie jest puste po normalizacji.")

    hits = await search_candidates_semantic(query_text, top_k=settings.MATCH_POOL_SIZE)
    if not hits:
        # Qdrant or Voyage is down. Say so instead of returning an empty list
        # that reads as "we have nobody like that".
        return RadarResult(
            breakdowns=[],
            pool_size=0,
            eligible_size=0,
            degraded=True,
            reason="semantic_unavailable",
        )

    similarity_map = {h["candidate_id"]: h["score"] for h in hits}
    candidates = await _load_candidates(db, list(similarity_map))
    pool_size = len(candidates)

    candidates = await filter_eligible_candidates(
        db, job=job, candidates=candidates, now=datetime.now(timezone.utc)
    )
    eligible_size = len(candidates)

    # `rank_candidates_for_job`, NOT `bulk_get_or_compute`: the score cache is
    # keyed by (candidate, job, profile) and this job has no id, so caching would
    # either collide across unrelated searches or crash on the null key.
    breakdowns = await rank_candidates_for_job(
        job, candidates, db, similarity_map=similarity_map
    )

    threshold = (
        query.min_score
        if query.min_score is not None
        else settings.RECOMMENDATION_MIN_SCORE
    )
    ranked = [b for b in breakdowns if b.total >= threshold][: query.top_k]

    # Only the rows that survived ranking — the eligible pool can be a thousand
    # wide, and shipping all of it would undo the trimming done above.
    kept = {b.candidate_id for b in ranked}
    return RadarResult(
        breakdowns=ranked,
        pool_size=pool_size,
        eligible_size=eligible_size,
        degraded=False,
        candidates_by_id={c.id: c for c in candidates if c.id in kept},
    )
