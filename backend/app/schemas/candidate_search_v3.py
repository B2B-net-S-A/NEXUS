"""``CandidateSearchQueryV3`` — the versioned candidate-search DSL (Phase 2).

The audit's target contract: one typed query that every search surface
(manual search, global list, AI matching, saved-search alerts) eventually
speaks, replacing the four parallel vocabularies. This module ships the
contract plus a **lossless bidirectional adapter** to today's
``CandidateSearchRequest`` so consumers can migrate incrementally:

* ``from_legacy(request)``  — upgrade a legacy request into V3 (fills V3-only
  fields with defaults);
* ``to_legacy(v3)``         — project V3 back onto the legacy request (drops
  V3-only richness such as ``soft_preferences`` — documented lossy).

Contract properties (enforced by ``tests/test_candidate_search_v3.py``):

1. ``from_legacy(to_legacy(v3)) == v3`` for every V3 produced by
   ``from_legacy`` (V3 is canonical through the cycle);
2. ``to_legacy(from_legacy(req)) == req`` for requests in canonical form —
   the one documented normalisation is that the legacy flat ``q_any`` bucket
   is group 0 of ``query.any_groups`` (an equivalent predicate).

Rates are hourly-only candidate expectations with immutable semantics:
B2B, PLN, net, per hour. Monthly candidate-rate filters are retired and
rejected at validation time. V3-only capabilities (per-skill
level/years/recency, soft preferences with weights, retrieval rerank) are
modelled now so later phases don't re-break the wire.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator
from pydantic_core import PydanticCustomError

from app.schemas.candidate_search import (
    CandidateSearchRequest,
    LanguageRequirement,
)
from app.services.candidate_monthly_rate_retirement import (
    reject_retired_candidate_rate,
)

# ── Building blocks ──────────────────────────────────────────────────────────


class SkillRequirement(BaseModel):
    key: str
    min_level: Optional[str] = None
    min_years: Optional[int] = None
    recency_months: Optional[int] = None
    accepted_sources: list[str] = Field(default_factory=list)


class SkillFilters(BaseModel):
    all: list[SkillRequirement] = Field(default_factory=list)
    any: list[SkillRequirement] = Field(default_factory=list)
    none: list[SkillRequirement] = Field(default_factory=list)


class RateFilter(BaseModel):
    """Hourly global candidate-rate constraint with immutable semantics."""

    @model_validator(mode="before")
    @classmethod
    def reject_retired_monthly_unit(cls, data: Any) -> Any:
        if isinstance(data, dict) and str(data.get("unit", "")).strip().lower() in {
            "month",
            "monthly",
            "miesiac",
            "miesiąc",
        }:
            raise PydanticCustomError(
                "candidate_monthly_rate_retired",
                "candidate_monthly_rate_retired",
            )
        return data

    unit: Literal["hour"] = "hour"
    min: Optional[Decimal] = Field(default=None, ge=0)
    max: Optional[Decimal] = Field(default=None, ge=0)
    currency: Literal["PLN"] = "PLN"
    tax_basis: Literal["net"] = "net"
    contract_type: Literal["b2b"] = "b2b"
    meaning: Literal["candidate_expectation"] = "candidate_expectation"


class AvailabilityFilters(BaseModel):
    statuses: list[str] = Field(default_factory=list)
    date_before: Optional[date] = None
    notice_period_max_days: Optional[int] = None
    # unknown-policy: lenient = missing data does not exclude (today's default)
    mode: Literal["strict", "lenient"] = "lenient"


class AttributeFlags(BaseModel):
    has_cv: Optional[bool] = None
    has_linkedin: Optional[bool] = None
    is_champion: Optional[bool] = None
    is_ambassador: Optional[bool] = None
    open_to_side_projects: Optional[bool] = None
    open_to_sales_support: Optional[bool] = None
    open_to_expert_consult: Optional[bool] = None
    cv_parsed_after: Optional[date] = None


class HardFilters(BaseModel):
    skills: SkillFilters = Field(default_factory=SkillFilters)
    competence_category_ids: list[int] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    languages: list[LanguageRequirement] = Field(default_factory=list)
    rates: list[RateFilter] = Field(default_factory=list)
    availability: AvailabilityFilters = Field(default_factory=AvailabilityFilters)
    experience_years_min: Optional[int] = None
    experience_years_max: Optional[int] = None
    statuses: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    attributes: AttributeFlags = Field(default_factory=AttributeFlags)
    exclude_blacklisted: bool = False


class SoftPreference(BaseModel):
    """A weighted, non-eliminating preference (nice-to-have). V3-only —
    dropped by ``to_legacy`` until Phase 4 scoring consumes it."""

    type: Literal["skill", "language", "location"] = "skill"
    key: str
    weight: float = Field(default=0.3, ge=0.0, le=1.0)
    evidence_required: bool = False


class QueryText(BaseModel):
    text: Optional[str] = None
    all: list[str] = Field(default_factory=list)
    # OR-groups that AND together; legacy's flat ``q_any`` is group 0.
    any_groups: list[list[str]] = Field(default_factory=list)
    none: list[str] = Field(default_factory=list)


class QueryContext(BaseModel):
    job_id: Optional[int] = None
    exclude_in_job_id: Optional[int] = None
    strategy_key: Optional[str] = None
    strategy_version: Optional[int] = None


class Retrieval(BaseModel):
    mode: Literal["boolean", "hybrid"] = "boolean"
    rerank: bool = False


class SortSpec(BaseModel):
    field: str = "relevance"
    direction: Literal["asc", "desc"] = "desc"


class PageSpec(BaseModel):
    number: int = Field(default=1, ge=1)
    size: int = Field(default=50, ge=1, le=200)
    cursor: Optional[str] = None


class CandidateSearchQueryV3(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def reject_retired_monthly_rate(cls, data: Any) -> Any:
        return reject_retired_candidate_rate(data)

    version: Literal[3] = 3
    context: QueryContext = Field(default_factory=QueryContext)
    query: QueryText = Field(default_factory=QueryText)
    retrieval: Retrieval = Field(default_factory=Retrieval)
    hard_filters: HardFilters = Field(default_factory=HardFilters)
    soft_preferences: list[SoftPreference] = Field(default_factory=list)
    sort: SortSpec = Field(default_factory=SortSpec)
    page: PageSpec = Field(default_factory=PageSpec)


# ── Adapters ─────────────────────────────────────────────────────────────────


def from_legacy(req: CandidateSearchRequest) -> CandidateSearchQueryV3:
    """Upgrade a legacy ``CandidateSearchRequest`` into V3 (lossless)."""
    any_groups: list[list[str]] = []
    if req.q_any:
        any_groups.append(list(req.q_any))
    any_groups.extend([list(g) for g in req.q_any_groups])

    rates: list[RateFilter] = []
    if req.rate_hourly_min is not None or req.rate_hourly_max is not None:
        rates.append(
            RateFilter(unit="hour", min=req.rate_hourly_min, max=req.rate_hourly_max)
        )

    return CandidateSearchQueryV3(
        context=QueryContext(
            job_id=req.exclude_in_job_id,
            exclude_in_job_id=req.exclude_in_job_id,
        ),
        query=QueryText(
            text=req.q,
            all=list(req.q_all),
            any_groups=any_groups,
            none=list(req.q_none),
        ),
        retrieval=Retrieval(mode=req.search_mode),
        hard_filters=HardFilters(
            skills=SkillFilters(
                all=[SkillRequirement(key=s) for s in req.skills_must],
                any=[SkillRequirement(key=s) for s in req.skills_any],
                none=[SkillRequirement(key=s) for s in req.skills_none],
            ),
            competence_category_ids=list(req.competence_category_ids),
            locations=list(req.location_cities),
            countries=list(req.location_countries),
            languages=list(req.languages),
            rates=rates,
            availability=AvailabilityFilters(
                statuses=[s.value for s in req.availability_status],
                date_before=req.availability_date_before,
                notice_period_max_days=req.notice_period_max,
            ),
            experience_years_min=req.experience_years_min,
            experience_years_max=req.experience_years_max,
            statuses=[s.value for s in req.status],
            sources=list(req.sources),
            tags=list(req.tags),
            attributes=AttributeFlags(
                has_cv=req.has_cv,
                has_linkedin=req.has_linkedin,
                is_champion=req.is_champion,
                is_ambassador=req.is_ambassador,
                open_to_side_projects=req.open_to_side_projects,
                open_to_sales_support=req.open_to_sales_support,
                open_to_expert_consult=req.open_to_expert_consult,
                cv_parsed_after=req.cv_parsed_after,
            ),
            exclude_blacklisted=req.exclude_blacklisted,
        ),
        sort=SortSpec(field=req.sort),
        page=PageSpec(number=req.page, size=req.page_size),
    )


def to_legacy(v3: CandidateSearchQueryV3) -> CandidateSearchRequest:
    """Project a V3 query onto the legacy request.

    Lossy ONLY for V3-only richness: ``soft_preferences``, per-skill
    level/years/recency, ``retrieval.rerank``, cursor paging, strategy refs
    and the strict/lenient mode are dropped (legacy cannot express them).
    """
    hourly = next((r for r in v3.hard_filters.rates if r.unit == "hour"), None)

    q_any: list[str] = []
    q_any_groups: list[list[str]] = []
    if v3.query.any_groups:
        q_any = list(v3.query.any_groups[0])
        q_any_groups = [list(g) for g in v3.query.any_groups[1:]]

    return CandidateSearchRequest(
        q=v3.query.text,
        q_all=list(v3.query.all),
        q_any=q_any,
        q_any_groups=q_any_groups,
        q_none=list(v3.query.none),
        competence_category_ids=list(v3.hard_filters.competence_category_ids),
        skills_must=[s.key for s in v3.hard_filters.skills.all],
        skills_any=[s.key for s in v3.hard_filters.skills.any],
        skills_none=[s.key for s in v3.hard_filters.skills.none],
        experience_years_min=v3.hard_filters.experience_years_min,
        experience_years_max=v3.hard_filters.experience_years_max,
        languages=list(v3.hard_filters.languages),
        location_cities=list(v3.hard_filters.locations),
        location_countries=list(v3.hard_filters.countries),
        status=list(v3.hard_filters.statuses),  # type: ignore[arg-type]
        availability_status=list(v3.hard_filters.availability.statuses),  # type: ignore[arg-type]
        availability_date_before=v3.hard_filters.availability.date_before,
        notice_period_max=v3.hard_filters.availability.notice_period_max_days,
        rate_hourly_min=hourly.min if hourly else None,
        rate_hourly_max=hourly.max if hourly else None,
        sources=list(v3.hard_filters.sources),
        tags=list(v3.hard_filters.tags),
        has_cv=v3.hard_filters.attributes.has_cv,
        has_linkedin=v3.hard_filters.attributes.has_linkedin,
        is_champion=v3.hard_filters.attributes.is_champion,
        is_ambassador=v3.hard_filters.attributes.is_ambassador,
        open_to_side_projects=v3.hard_filters.attributes.open_to_side_projects,
        open_to_sales_support=v3.hard_filters.attributes.open_to_sales_support,
        open_to_expert_consult=v3.hard_filters.attributes.open_to_expert_consult,
        cv_parsed_after=v3.hard_filters.attributes.cv_parsed_after,
        exclude_in_job_id=v3.context.exclude_in_job_id,
        exclude_blacklisted=v3.hard_filters.exclude_blacklisted,
        sort=v3.sort.field,  # type: ignore[arg-type]
        page=v3.page.number,
        page_size=v3.page.size,
        search_mode=v3.retrieval.mode,
    )
