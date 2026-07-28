"""Builder for structured chip filters on the Candidate listing.

Companion to :mod:`app.services.advanced_candidate_search` (which builds the
boolean ILIKE clause). This module returns a list of SQLAlchemy expressions
that the search endpoint AND-s together with the boolean clause and the FTS
clause.

Why a separate module:

* :func:`build_structured_filter` is pure — no I/O, no session — and unit-test
  friendly. The endpoint composes the WHERE clause, runs the query, and
  formats the response.
* JSONB lookups (``skills``, ``tags``, ``languages``) live here so the
  endpoint stays declarative.
* Language-level comparison sorts CEFR strings lexicographically; this works
  because ``A1 < A2 < B1 < B2 < C1 < C2`` is monotonic in ASCII.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import reduce
from typing import Optional

from sqlalchemy import String, and_, case, cast, func, not_, or_, select
from sqlalchemy.sql import ColumnElement

from app.models.candidate import (
    Candidate,
    CandidateStatus,
)
from app.schemas.candidate_search import (
    CandidateSearchRequest,
    LanguageRequirement,
)

# CEFR ordering — monotonic in ASCII so plain ``>=`` on the JSON value works.
_LEVEL_ORDER = ["A1", "A2", "B1", "B2", "C1", "C2", "native"]


def _safe(col: ColumnElement) -> ColumnElement:
    """Coalesce NULL → '' so ILIKE doesn't yield NULL (which excludes rows)."""
    return func.coalesce(col, "")


def _escape_like(value: str) -> str:
    return value.replace("\\", r"\\").replace("%", r"\%").replace("_", r"\_")


def _skills_text() -> ColumnElement:
    """Concatenate JSONB ``skills`` + ``tags`` text for substring lookup.

    Skills are stored as either a list of strings or a list of dicts
    (``{name, level, years}``). Casting to ``text`` returns the raw JSON dump,
    which is good enough for ILIKE substring matching across both shapes.
    """
    return (
        func.coalesce(cast(Candidate.skills, String), "")
        + " "
        + func.coalesce(cast(Candidate.tags, String), "")
    )


def _skill_match(skill: str) -> ColumnElement:
    """Match a skill as a WHOLE quoted JSON token, not a bare substring.

    Both ``skills`` and ``tags`` are JSONB, so ``_skills_text()`` is a JSON dump
    in which every value is quoted — ``["Python", "Go"]`` and
    ``[{"name": "Go", "level": "senior"}]`` alike contain the literal ``"Go"``.
    Requiring those surrounding quotes turns an imprecise substring test into an
    exact token test.

    Why this matters (SEARCH-P0-03 follow-up): the bare ``%Go%`` pattern also
    matched ``Django``, ``Golang``, ``Mongo`` and ``Django REST``. For the
    ranking signal that only misordered results, but ``skills_none`` is a HARD
    exclusion — "nie ma Go" silently dropped every Django developer from the
    result set, and a recruiter had no way to see it happen.

    Known limitation, deliberate: in the dict shape the dump also contains the
    literal keys ``"name"``, ``"level"``, ``"years"``, so a chip named exactly
    like a key self-matches. Harmless in practice and strictly better than the
    old behaviour; the real fix is the normalised ``cortex_skill_facts`` join,
    which needs Cortex coverage above ~60% (measured 56.8% on 2026-07-27).
    """
    pattern = f'%"{_escape_like(skill)}"%'
    return _skills_text().ilike(pattern, escape="\\")


def skills_soft_rank(req: CandidateSearchRequest) -> Optional[ColumnElement]:
    """ORDER BY expression: how many of the requested (must ∪ any) skills the
    candidate's structured text matches. Higher = more relevant.

    SEARCH-P0-03: skill chips are a SOFT signal — they rank, they never cut.
    Returns ``None`` when no inclusion chips were sent (nothing to rank by).
    A candidate the substring misses simply scores 0 here and sinks, rather
    than being excluded from the result set entirely.
    """
    wanted = list(req.skills_must) + list(req.skills_any or [])
    if not wanted:
        return None
    matches = [case((_skill_match(s), 1), else_=0) for s in wanted]
    return reduce(lambda a, b: a + b, matches)


def _language_clause(req: LanguageRequirement) -> Optional[ColumnElement]:
    """Match a candidate whose ``languages`` JSONB carries ``req.code`` at or
    above ``req.min_level`` — with the code and the level bound to the SAME
    element (SEARCH-18).

    The prior implementation cast the whole ``languages`` array to text and ran
    a single ILIKE (``%"EN"%"B2"%``), so ``EN`` in one element and ``B2`` in a
    *different* element counted as a match: a candidate with
    ``[{lang:EN,level:A2},{lang:DE,level:C2}]`` wrongly satisfied ``EN>=B2``.
    We now require one element to carry both fields.

    Two stored shapes are supported, per-element correct in both:

    * array of dicts — ``[{"lang": "EN", "level": "B2"}, ...]`` (``code`` is an
      accepted alias for ``lang``);
    * flat map — ``{"EN": "B2", ...}`` where the key *is* the language code.

    Code and level are both case-folded (preserving the old ILIKE tolerance);
    ``level`` acceptance follows the CEFR ordering in ``_LEVEL_ORDER``.
    """
    code_upper = req.code.upper()
    try:
        min_idx = _LEVEL_ORDER.index(req.min_level)
    except ValueError:
        return None
    accepted_levels = [lvl.upper() for lvl in _LEVEL_ORDER[min_idx:]]

    langs = Candidate.languages

    # Array shape: ONE element must carry both the code and an accepted level.
    # ``jsonb_array_elements`` errors on non-arrays, so guard the type first.
    array_elem = func.jsonb_array_elements(
        case(
            (func.jsonb_typeof(langs) == "array", langs),
            else_=func.jsonb_build_array(),
        )
    ).table_valued("value")
    elem_code = func.upper(
        func.coalesce(
            array_elem.c.value.op("->>")("lang"),
            array_elem.c.value.op("->>")("code"),
            "",
        )
    )
    elem_level = func.upper(func.coalesce(array_elem.c.value.op("->>")("level"), ""))
    array_match = (
        select(array_elem.c.value)
        .where(and_(elem_code == code_upper, elem_level.in_(accepted_levels)))
        .correlate(Candidate)
        .exists()
    )

    # Flat-map shape: the key is the code, the value its level — inherently
    # per-element. ``jsonb_each_text`` gives case-insensitive key matching.
    map_kv = func.jsonb_each_text(
        case(
            (func.jsonb_typeof(langs) == "object", langs),
            else_=func.jsonb_build_object(),
        )
    ).table_valued("key", "value")
    map_match = (
        select(map_kv.c.value)
        .where(
            and_(
                func.upper(map_kv.c.key) == code_upper,
                func.upper(map_kv.c.value).in_(accepted_levels),
            )
        )
        .correlate(Candidate)
        .exists()
    )

    return or_(array_match, map_match)


def _bool_eq(col: ColumnElement, value: Optional[bool]) -> Optional[ColumnElement]:
    if value is None:
        return None
    return col.is_(True) if value else col.is_(False)


@dataclass(frozen=True)
class FilterGroup:
    """A named bundle of WHERE clauses for one filter dimension.

    Used both to build the flat filter (``build_structured_filter``) and to
    drive the zero-result exclusion waterfall (``/diagnostics``), where each
    group is applied cumulatively and its surviving count is reported."""

    key: str
    label: str
    clauses: list[ColumnElement]


def build_filter_groups(req: CandidateSearchRequest) -> list[FilterGroup]:
    """Return the populated structured filters, grouped and labelled.

    Only groups with at least one clause are returned. The concatenation of
    ``group.clauses`` (in order) is exactly what ``build_structured_filter``
    emits — this is the single source of truth for both.
    """
    groups: list[FilterGroup] = []

    def add(key: str, label: str, clauses: list[ColumnElement]) -> None:
        if clauses:
            groups.append(FilterGroup(key=key, label=label, clauses=clauses))

    cc: list[ColumnElement] = []
    if req.competence_category_ids:
        cc.append(Candidate.competence_category_id.in_(req.competence_category_ids))
    add("competence_category", "Kategoria kompetencji", cc)

    skills: list[ColumnElement] = []
    # SEARCH-P0-03: skills_must / skills_any are a SOFT ranking signal now
    # (see ``skills_soft_rank``), NOT a hard filter. A candidate the scorer
    # rates highly must never be cut from the list before ranking just because
    # a substring ILIKE over the structured `skills`+`tags` column missed (that
    # column is empty for ~99% of imported candidates, and 'Go' spuriously
    # matches 'Django'). Only skills_none stays a hard filter — "must NOT have
    # X" is a real exclusion the recruiter explicitly asked for.
    for skill in req.skills_none:
        skills.append(not_(_skill_match(skill)))
    add("skills", "Umiejętności (wykluczenia)", skills)

    experience: list[ColumnElement] = []
    if req.experience_years_min is not None:
        experience.append(Candidate.years_it_experience >= req.experience_years_min)
    if req.experience_years_max is not None:
        experience.append(Candidate.years_it_experience <= req.experience_years_max)
    add("experience", "Doświadczenie", experience)

    languages: list[ColumnElement] = []
    for lang in req.languages:
        lang_clause = _language_clause(lang)
        if lang_clause is not None:
            languages.append(lang_clause)
    add("languages", "Języki", languages)

    location: list[ColumnElement] = []
    if req.location_cities:
        city_clauses = [
            or_(
                _safe(Candidate.city).ilike(f"%{_escape_like(c)}%", escape="\\"),
                _safe(Candidate.location).ilike(f"%{_escape_like(c)}%", escape="\\"),
            )
            for c in req.location_cities
        ]
        location.append(or_(*city_clauses))
    if req.location_countries:
        location.append(
            Candidate.country.in_([c.upper() for c in req.location_countries])
        )
    add("location", "Lokalizacja", location)

    eligibility: list[ColumnElement] = []
    if req.exclude_blacklisted:
        # Global blacklist = eligibility visibility "hidden" (SEARCH-P0-04).
        # Forced on for job-context search server-side; opt-in elsewhere.
        eligibility.append(Candidate.status != CandidateStatus.blacklisted)
    add("eligibility", "Dostępność do przypisania", eligibility)

    status: list[ColumnElement] = []
    if req.status:
        status.append(Candidate.status.in_(req.status))
    add("status", "Status kandydata", status)

    availability: list[ColumnElement] = []
    if req.availability_status:
        availability.append(Candidate.availability_status.in_(req.availability_status))
    if req.availability_date_before is not None:
        availability.append(
            Candidate.availability_date.is_(None)
            | (Candidate.availability_date <= req.availability_date_before)
        )
    if req.notice_period_max is not None:
        # Normalize value+unit to days for comparison. NULL unit = legacy days.
        # Approximation: 1 week = 7 days, 1 month = 30 days. Stored intent
        # (e.g. "3 months") is preserved on the candidate row; only the filter
        # comparison is approximate.
        notice_days = case(
            (Candidate.notice_period_unit == "weeks", Candidate.notice_period * 7),
            (Candidate.notice_period_unit == "months", Candidate.notice_period * 30),
            else_=Candidate.notice_period,
        )
        availability.append(
            Candidate.notice_period.is_(None) | (notice_days <= req.notice_period_max)
        )
    add("availability", "Dyspozycyjność", availability)

    salary: list[ColumnElement] = []
    if req.salary_min is not None:
        salary.append(Candidate.salary_expectation >= req.salary_min)
    if req.salary_max is not None:
        salary.append(Candidate.salary_expectation <= req.salary_max)
    if req.salary_currency:
        salary.append(
            func.upper(Candidate.salary_currency) == req.salary_currency.upper()
        )
    add("salary_monthly", "Wynagrodzenie miesięczne", salary)

    # Hourly rate (PLN/h) — filter on ``expected_rate_hourly``, NOT the monthly
    # ``salary_expectation``. Missing rate is unknown → included (never a hard
    # exclusion), matching the availability/notice-period NULL policy above.
    rate: list[ColumnElement] = []
    if req.rate_hourly_min is not None or req.rate_hourly_max is not None:
        bounds: list[ColumnElement] = []
        if req.rate_hourly_min is not None:
            bounds.append(Candidate.expected_rate_hourly >= req.rate_hourly_min)
        if req.rate_hourly_max is not None:
            bounds.append(Candidate.expected_rate_hourly <= req.rate_hourly_max)
        rate.append(Candidate.expected_rate_hourly.is_(None) | and_(*bounds))
    add("rate_hourly", "Stawka godzinowa", rate)

    sources: list[ColumnElement] = []
    if req.sources:
        sources.append(Candidate.source.in_(req.sources))
    add("sources", "Źródło", sources)

    tags: list[ColumnElement] = []
    if req.tags:
        tags_text = func.coalesce(cast(Candidate.tags, String), "")
        for tag in req.tags:
            tags.append(tags_text.ilike(f"%{_escape_like(tag)}%", escape="\\"))
    add("tags", "Tagi", tags)

    attributes: list[ColumnElement] = []
    has_cv_clause = _bool_clause_has_cv(req.has_cv)
    if has_cv_clause is not None:
        attributes.append(has_cv_clause)
    if req.has_linkedin is not None:
        if req.has_linkedin:
            attributes.append(Candidate.linkedin.isnot(None))
        else:
            attributes.append(Candidate.linkedin.is_(None))
    champion_clause = _bool_eq(Candidate.champion, req.is_champion)
    if champion_clause is not None:
        attributes.append(champion_clause)
    ambassador_clause = _bool_eq(Candidate.is_ambassador, req.is_ambassador)
    if ambassador_clause is not None:
        attributes.append(ambassador_clause)
    side_proj_clause = _bool_eq(
        Candidate.open_to_side_projects, req.open_to_side_projects
    )
    if side_proj_clause is not None:
        attributes.append(side_proj_clause)
    sales_clause = _bool_eq(Candidate.open_to_sales_support, req.open_to_sales_support)
    if sales_clause is not None:
        attributes.append(sales_clause)
    expert_clause = _bool_eq(
        Candidate.open_to_expert_consult, req.open_to_expert_consult
    )
    if expert_clause is not None:
        attributes.append(expert_clause)
    if req.cv_parsed_after is not None:
        attributes.append(Candidate.cv_parsed_at >= req.cv_parsed_after)
    add("attributes", "Atrybuty", attributes)

    return groups


def build_structured_filter(req: CandidateSearchRequest) -> list[ColumnElement]:
    """Return SQLAlchemy WHERE clauses for every populated structured chip.

    The caller is responsible for ``AND``-ing this list with the boolean
    clause and the FTS clause. Delegates to :func:`build_filter_groups` so the
    grouping and the flat filter never drift.
    """
    clauses: list[ColumnElement] = []
    for group in build_filter_groups(req):
        clauses.extend(group.clauses)

    return clauses


def _bool_clause_has_cv(has_cv: Optional[bool]) -> Optional[ColumnElement]:
    if has_cv is None:
        return None
    if has_cv:
        return Candidate.cv_filename.isnot(None)
    return Candidate.cv_filename.is_(None)
