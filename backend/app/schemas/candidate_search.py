"""Pydantic schemas for hybrid candidate search.

Hybrid request layers:

* **Free-text** (``q``) — postgres FTS via ``ts_rank`` over ``fts_doc``.
* **Boolean** (``q_all`` / ``q_any`` / ``q_none``) — Traffit-style ILIKE buckets;
  delegated to :mod:`app.services.advanced_candidate_search`.
* **Structured chips** — typed filters on indexed columns + JSONB lookups;
  delegated to :mod:`app.services.structured_candidate_search`.

The three layers AND together. ``CandidateSearchResponse.meta.ai_status`` is
populated by the matching circuit breaker (``recommendations.py``) — opaque
``"ok"`` here, refined by callers that proxy AI calls.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from app.models.candidate import AvailabilityStatus, CandidateStatus
from app.services.candidate_monthly_rate_retirement import (
    reject_retired_candidate_rate,
)

SortOrder = Literal["relevance", "recent", "name"]
AiStatus = Literal["ok", "degraded", "down"]

# CEFR-style language proficiency thresholds. Stored levels in
# ``Candidate.languages`` JSONB use the same vocabulary; the filter compares
# lexicographically (``A1 < A2 < B1 < B2 < C1 < C2``).
LanguageLevel = Literal["A1", "A2", "B1", "B2", "C1", "C2", "native"]


class LanguageRequirement(BaseModel):
    code: str = Field(..., min_length=2, max_length=10)  # ISO-ish: "EN", "PL", "DE"
    min_level: LanguageLevel = "B2"


class CandidateSearchRequest(BaseModel):
    """All-in-one request schema for ``POST /api/search/candidates``."""

    @model_validator(mode="before")
    @classmethod
    def reject_retired_monthly_rate(cls, data: Any) -> Any:
        """Fail loudly instead of silently accepting retired monthly filters."""
        return reject_retired_candidate_rate(data)

    # === Boolean text (Traffit-style; AND-of-buckets, ILIKE) ==================
    q_all: list[str] = Field(default_factory=list, max_length=20)
    q_any: list[str] = Field(default_factory=list, max_length=20)
    q_none: list[str] = Field(default_factory=list, max_length=20)
    # Extra OR-groups for the ANY bucket. Each inner list is one OR-group; the
    # groups AND together, and AND with the legacy flat ``q_any`` (group 0):
    #   q_any=[react, vue], q_any_groups=[[java, kotlin]]
    #     ⇒ (react OR vue) AND (java OR kotlin)
    q_any_groups: list[list[str]] = Field(default_factory=list, max_length=10)

    # === Free-text (postgres FTS, ts_rank ordering) ===========================
    q: Optional[str] = Field(default=None, max_length=500)

    # === Structured chips =====================================================
    competence_category_ids: list[int] = Field(default_factory=list, max_length=20)
    skills_must: list[str] = Field(default_factory=list, max_length=20)
    skills_any: list[str] = Field(default_factory=list, max_length=20)
    skills_none: list[str] = Field(default_factory=list, max_length=20)
    experience_years_min: Optional[int] = Field(default=None, ge=0, le=60)
    experience_years_max: Optional[int] = Field(default=None, ge=0, le=60)
    languages: list[LanguageRequirement] = Field(default_factory=list, max_length=10)
    location_cities: list[str] = Field(default_factory=list, max_length=10)
    location_countries: list[str] = Field(default_factory=list, max_length=10)
    status: list[CandidateStatus] = Field(default_factory=list)
    availability_status: list[AvailabilityStatus] = Field(default_factory=list)
    availability_date_before: Optional[date] = None
    notice_period_max: Optional[int] = Field(default=None, ge=0, le=365)
    # Global candidate rate has one immutable meaning: B2B, PLN net/hour.
    # A missing rate remains unknown and is never excluded by the filter.
    rate_hourly_min: Optional[Decimal] = Field(default=None, ge=0)
    rate_hourly_max: Optional[Decimal] = Field(default=None, ge=0)
    sources: list[str] = Field(default_factory=list, max_length=10)
    tags: list[str] = Field(default_factory=list, max_length=20)
    has_cv: Optional[bool] = None
    has_linkedin: Optional[bool] = None
    is_champion: Optional[bool] = None
    is_ambassador: Optional[bool] = None
    open_to_side_projects: Optional[bool] = None
    open_to_sales_support: Optional[bool] = None
    open_to_expert_consult: Optional[bool] = None
    cv_parsed_after: Optional[date] = None

    # === Job-context exclusion ================================================
    exclude_in_job_id: Optional[int] = Field(
        default=None,
        description="Exclude candidates already added (any stage) to this job.",
    )
    # Hide globally-blacklisted candidates (eligibility visibility=hidden). The
    # search endpoint forces this on whenever a job context is present; the
    # global candidate list leaves it off so blacklisted profiles stay
    # manageable there. See SEARCH-P0-04.
    exclude_blacklisted: bool = False

    # === Sort + paging ========================================================
    sort: SortOrder = "relevance"
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)

    # === Search mode ==========================================================
    # "boolean" — current default, ts_rank FTS over fts_doc.
    # "hybrid"  — BM25 (Postgres FTS) + dense (Voyage/Qdrant) parallel + RRF
    #             fusion (k=60) + Voyage Rerank 2.5 on top-100 → top-K.
    # Hybrid only kicks in when `q` is non-empty; otherwise behaves as boolean.
    search_mode: Literal["boolean", "hybrid"] = "boolean"


class CandidateSearchItem(BaseModel):
    id: int
    name: str
    lastname: str
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    status: Optional[str] = None
    availability_status: Optional[str] = None
    source: Optional[str] = None
    competence_category: Optional[str] = None
    competence_category_id: Optional[int] = None
    expected_rate_hourly: Optional[Decimal] = None
    availability_date: Optional[str] = None
    years_it_experience: Optional[int] = None
    # Each of these JSONB columns is either a dict or a list in production
    # depending on importer history (e.g. ``languages`` is sometimes
    # ``["Polish", "English"]`` and sometimes ``{"PL": "C2"}``). Keep the
    # response permissive — the frontend already handles both shapes.
    tags: Optional[Any] = None
    skills: Optional[Any] = None
    languages: Optional[Any] = None
    ai_summary: Optional[str] = None
    avatar_url: Optional[str] = None
    relevance_score: float = 0.0
    has_cv: bool = False
    has_linkedin: bool = False
    is_champion: bool = False
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class CompetenceCategoryFacet(BaseModel):
    id: int
    name: str
    count: int


class SearchFacets(BaseModel):
    competence_categories: list[CompetenceCategoryFacet] = Field(default_factory=list)


class SearchMeta(BaseModel):
    ai_status: AiStatus = "ok"
    took_ms: int = 0
    # True when a *hybrid* search ran but its semantic (Voyage/Qdrant) leg was
    # down for THIS request, so results came from BM25 alone. Lets the UI say
    # "wyszukiwanie semantyczne niedostępne" instead of "brak kandydatów" — an
    # outage must never read as an empty database. Unlike ``ai_status`` (a
    # rolling health window), this reflects the current request's outcome.
    search_degraded: bool = False
    # Per softened chip: how many of the `total` results actually state a
    # matching value. Experience and location no longer exclude candidates whose
    # field is blank (see NULL_POLICY in structured_candidate_search), so a
    # narrow band can return thousands — which reads as a broken filter unless
    # the UI can say how many of them genuinely match. Empty when no such chip
    # was sent. Keys: "experience", "location".
    soft_match_counts: dict[str, int] = Field(default_factory=dict)


class CandidateSearchResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[CandidateSearchItem]
    facets: SearchFacets = Field(default_factory=SearchFacets)
    meta: SearchMeta = Field(default_factory=SearchMeta)


class MatchScoresRequest(BaseModel):
    """Ask for cached hybrid match scores of some candidates against a job."""

    job_id: int
    candidate_ids: list[int] = Field(default_factory=list, max_length=200)


class MatchScoresResponse(BaseModel):
    """``candidate_id`` (string key for JSON) → hybrid match score in [0, 100].

    Only candidates with a fresh cached score are present; the rest simply have
    no entry (the endpoint never computes, so coverage depends on prior
    recommendation/kanban scoring). ``breakdowns`` carries the stored
    explainability payload (per-layer points + matched/gap skills) for the same
    candidates, for the request-fit detail panel."""

    scores: dict[str, int] = Field(default_factory=dict)
    breakdowns: dict[str, Any] = Field(default_factory=dict)


class WaterfallStage(BaseModel):
    """One cumulative step of the zero-result exclusion waterfall: the count of
    candidates surviving this filter *and all filters before it*."""

    key: str
    label: str
    count: int


class SearchDiagnosticsResponse(BaseModel):
    """Explains where a search lost its candidates (SEARCH-P1-04). ``stages`` are
    cumulative; ``first_zeroing_stage`` is the key of the first stage whose
    running count hit 0 (the likely culprit), or ``None`` if results remain."""

    base_count: int
    stages: list[WaterfallStage]
    total: int
    first_zeroing_stage: Optional[str] = None
