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
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from app.models.candidate import AvailabilityStatus, CandidateStatus

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

    # === Boolean text (Traffit-style; AND-of-buckets, ILIKE) ==================
    q_all: list[str] = Field(default_factory=list, max_length=20)
    q_any: list[str] = Field(default_factory=list, max_length=20)
    q_none: list[str] = Field(default_factory=list, max_length=20)

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
    salary_min: Optional[int] = Field(default=None, ge=0)
    salary_max: Optional[int] = Field(default=None, ge=0)
    salary_currency: Optional[str] = Field(default=None, min_length=3, max_length=3)
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
    salary_expectation: Optional[int] = None
    salary_currency: Optional[str] = None
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


class CandidateSearchResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[CandidateSearchItem]
    facets: SearchFacets = Field(default_factory=SearchFacets)
    meta: SearchMeta = Field(default_factory=SearchMeta)
