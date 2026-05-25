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

from typing import Optional

from sqlalchemy import String, case, cast, func, not_, or_
from sqlalchemy.sql import ColumnElement

from app.models.candidate import (
    Candidate,
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
    pattern = f"%{_escape_like(skill)}%"
    return _skills_text().ilike(pattern, escape="\\")


def _language_clause(req: LanguageRequirement) -> Optional[ColumnElement]:
    """Match ``Candidate.languages`` JSONB containing a ``code`` entry whose
    ``level`` is at least ``req.min_level``.

    Schema convention (legacy + parser-emitted):
    ``[{"code": "EN", "level": "B2"}, ...]``  *or*  ``{"EN": "B2", ...}``.

    We render an OR over both shapes so older candidates still match.
    """
    code_upper = req.code.upper()
    try:
        min_idx = _LEVEL_ORDER.index(req.min_level)
    except ValueError:
        return None
    accepted_levels = _LEVEL_ORDER[min_idx:]

    # JSONB array shape: languages @> '[{"code": "EN", "level": "B2"}]' for any
    # accepted level. We can't AND an array contains across multiple acceptable
    # levels in one expression efficiently — rely on text fallback below.
    text_blob = func.coalesce(cast(Candidate.languages, String), "")
    pattern_clauses = [
        text_blob.ilike(f'%"{code_upper}"%"{lvl}"%') for lvl in accepted_levels
    ]
    pattern_clauses += [
        text_blob.ilike(f'%"{lvl}"%"{code_upper}"%') for lvl in accepted_levels
    ]
    return or_(*pattern_clauses) if pattern_clauses else None


def _bool_eq(col: ColumnElement, value: Optional[bool]) -> Optional[ColumnElement]:
    if value is None:
        return None
    return col.is_(True) if value else col.is_(False)


def build_structured_filter(req: CandidateSearchRequest) -> list[ColumnElement]:
    """Return SQLAlchemy WHERE clauses for every populated structured chip.

    The caller is responsible for ``AND``-ing this list with the boolean
    clause and the FTS clause.
    """
    clauses: list[ColumnElement] = []

    if req.competence_category_ids:
        clauses.append(
            Candidate.competence_category_id.in_(req.competence_category_ids)
        )

    for skill in req.skills_must:
        clauses.append(_skill_match(skill))
    if req.skills_any:
        clauses.append(or_(*(_skill_match(s) for s in req.skills_any)))
    for skill in req.skills_none:
        clauses.append(not_(_skill_match(skill)))

    if req.experience_years_min is not None:
        clauses.append(Candidate.years_it_experience >= req.experience_years_min)
    if req.experience_years_max is not None:
        clauses.append(Candidate.years_it_experience <= req.experience_years_max)

    for lang in req.languages:
        lang_clause = _language_clause(lang)
        if lang_clause is not None:
            clauses.append(lang_clause)

    if req.location_cities:
        city_clauses = [
            or_(
                _safe(Candidate.city).ilike(f"%{_escape_like(c)}%", escape="\\"),
                _safe(Candidate.location).ilike(f"%{_escape_like(c)}%", escape="\\"),
            )
            for c in req.location_cities
        ]
        clauses.append(or_(*city_clauses))

    if req.location_countries:
        clauses.append(
            Candidate.country.in_([c.upper() for c in req.location_countries])
        )

    if req.status:
        clauses.append(Candidate.status.in_(req.status))
    if req.availability_status:
        clauses.append(Candidate.availability_status.in_(req.availability_status))

    if req.availability_date_before is not None:
        clauses.append(
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
        clauses.append(
            Candidate.notice_period.is_(None)
            | (notice_days <= req.notice_period_max)
        )

    if req.salary_min is not None:
        clauses.append(Candidate.salary_expectation >= req.salary_min)
    if req.salary_max is not None:
        clauses.append(Candidate.salary_expectation <= req.salary_max)
    if req.salary_currency:
        clauses.append(
            func.upper(Candidate.salary_currency) == req.salary_currency.upper()
        )

    if req.sources:
        clauses.append(Candidate.source.in_(req.sources))

    if req.tags:
        tags_text = func.coalesce(cast(Candidate.tags, String), "")
        for tag in req.tags:
            clauses.append(tags_text.ilike(f"%{_escape_like(tag)}%", escape="\\"))

    has_cv_clause = _bool_clause_has_cv(req.has_cv)
    if has_cv_clause is not None:
        clauses.append(has_cv_clause)

    if req.has_linkedin is not None:
        if req.has_linkedin:
            clauses.append(Candidate.linkedin.isnot(None))
        else:
            clauses.append(Candidate.linkedin.is_(None))

    champion_clause = _bool_eq(Candidate.champion, req.is_champion)
    if champion_clause is not None:
        clauses.append(champion_clause)

    ambassador_clause = _bool_eq(Candidate.is_ambassador, req.is_ambassador)
    if ambassador_clause is not None:
        clauses.append(ambassador_clause)

    side_proj_clause = _bool_eq(
        Candidate.open_to_side_projects, req.open_to_side_projects
    )
    if side_proj_clause is not None:
        clauses.append(side_proj_clause)

    sales_clause = _bool_eq(Candidate.open_to_sales_support, req.open_to_sales_support)
    if sales_clause is not None:
        clauses.append(sales_clause)

    expert_clause = _bool_eq(
        Candidate.open_to_expert_consult, req.open_to_expert_consult
    )
    if expert_clause is not None:
        clauses.append(expert_clause)

    if req.cv_parsed_after is not None:
        clauses.append(Candidate.cv_parsed_at >= req.cv_parsed_after)

    return clauses


def _bool_clause_has_cv(has_cv: Optional[bool]) -> Optional[ColumnElement]:
    if has_cv is None:
        return None
    if has_cv:
        return Candidate.cv_filename.isnot(None)
    return Candidate.cv_filename.is_(None)
