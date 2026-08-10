"""Canonical matching request/run contracts (plan PR8).

One shape every surface (recommendations, proposals, reverse, marketplace,
search) speaks, so a result carries the same eligibility + fit breakdown + a
full version trace regardless of which screen asked. The orchestrator
(``matching_orchestrator``) produces a ``MatchingRun`` of these.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class VersionTrace:
    """Every version stamp in effect for a run — the audit trail on each result."""

    ranker_version: str
    index_version: str
    text_schema_version: str
    taxonomy_version: str

    def as_dict(self) -> dict:
        return {
            "ranker_version": self.ranker_version,
            "index_version": self.index_version,
            "text_schema_version": self.text_schema_version,
            "taxonomy_version": self.taxonomy_version,
        }


def current_version_trace() -> VersionTrace:
    """Resolve the live version trace from the running configuration."""
    from app.core.config import settings
    from app.services.canonical_text import TEXT_SCHEMA_V1, TEXT_SCHEMA_V2
    from app.services.scoring_service import scoring_algorithm_version

    text_schema = (
        TEXT_SCHEMA_V2
        if getattr(settings, "AI_TEXT_SCHEMA_V2", False)
        else TEXT_SCHEMA_V1
    )
    return VersionTrace(
        ranker_version=scoring_algorithm_version(),
        index_version="index-legacy-v1",
        text_schema_version=text_schema,
        taxonomy_version="taxonomy-legacy-v1",
    )


@dataclass(frozen=True)
class MatchingRequest:
    """What a surface asks for. Policy (top_k, thresholds) lives here, not in a
    per-surface builder."""

    surface: str
    job_id: Optional[int] = None
    request_id: Optional[int] = None
    user_id: Optional[int] = None
    client_id: Optional[int] = None
    top_k: int = 20
    rerank: bool = False


@dataclass
class RetrievalCandidate:
    """A candidate emitted by candidate generation, before scoring."""

    candidate_id: int
    dense_score: Optional[float] = None
    sparse_score: Optional[float] = None
    fused_score: Optional[float] = None
    sources: list[str] = field(default_factory=list)


@dataclass
class MatchingResult:
    """One ranked candidate with its full, surface-agnostic explanation."""

    candidate_id: int
    rank: int
    eligible: bool = True
    eligibility_reasons: list[str] = field(default_factory=list)
    retrieval_score: Optional[float] = None
    rerank_score: Optional[float] = None
    fit_score: Optional[float] = None
    fit_breakdown: Optional[dict] = None
    sources: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "rank": self.rank,
            "eligible": self.eligible,
            "eligibility_reasons": self.eligibility_reasons,
            "retrieval_score": self.retrieval_score,
            "rerank_score": self.rerank_score,
            "fit_score": self.fit_score,
            "fit_breakdown": self.fit_breakdown,
            "sources": self.sources,
        }


@dataclass
class MatchingRun:
    """The canonical output: an ordered, versioned, traceable result set."""

    run_id: str
    surface: str
    results: list[MatchingResult]
    version_trace: VersionTrace
    degraded: bool = False

    def as_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "surface": self.surface,
            "version_trace": self.version_trace.as_dict(),
            "degraded": self.degraded,
            "results": [r.as_dict() for r in self.results],
        }
