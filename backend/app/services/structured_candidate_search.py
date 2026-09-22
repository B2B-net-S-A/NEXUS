"""Builder for structured chip filters on the Candidate listing.

Companion to :mod:`app.services.advanced_candidate_search` (which builds the
boolean ILIKE clause). This module returns a list of SQLAlchemy expressions
that the search endpoint AND-s together with the boolean clause and the FTS
clause.

Why a separate module:

* :func:`build_structured_filter` is pure — no I/O, no session — and unit-test
  friendly. The endpoint composes the WHERE clause, runs the query, and
  formats the response.
* JSONB lookups (``skills``, ``tags``) and normalized language-fact lookups
  live here so the endpoint stays declarative.
* Language-level comparison uses an explicit accepted-level set over
  ``candidate_languages``; native and unknown are distinct states.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from sqlalchemy import and_, case, or_
from sqlalchemy.sql import ColumnElement

from app.models.candidate import (
    Candidate,
    CandidateStatus,
)
from app.schemas.candidate_search import (
    CandidateSearchRequest,
    LanguageRequirement,
)
from app.services import candidate_search_predicates as predicates

# CEFR ordering — wspólna definicja w `candidate_search_predicates`.
_LEVEL_ORDER = list(predicates.LANGUAGE_LEVELS)


# Dopasowanie umiejętności mieszka w `candidate_search_predicates` — JEDNYM
# module wspólnym dla listy i wyszukiwarki. Aliasy zostają wyłącznie dla
# istniejących importów; nie dopisuj tu logiki.
_skills_text = predicates.skills_text
_skill_match = predicates.skill_match


def request_semantics(req: CandidateSearchRequest) -> predicates.Semantics:
    """Wersja semantyki żądania wyszukiwarki (`semantics_version`, `hide_unknown`).
    Bez pola = v1: DOKŁADNIE dotychczasowe wyniki."""
    return predicates.semantics_for(
        "search",
        getattr(req, "semantics_version", None),
        getattr(req, "hide_unknown", None),
    )


def skills_soft_rank(req: CandidateSearchRequest) -> Optional[ColumnElement]:
    """ORDER BY: ile pozycji „Mile widziane" kandydat spełnia. Higher = better.

    SEARCH-P0-03: legacy `skills_must` / `skills_any` są sygnałem MIĘKKIM —
    szeregują, nigdy nie tną; razem z jawnym `skills_preferred` tworzą kubełek
    „Mile widziane" (`predicates.skill_buckets_from_search`). ``None``, gdy
    nie ma czym szeregować.
    """
    return predicates.skills_preferred_rank(predicates.skill_buckets_from_search(req))


def experience_soft_rank(req: CandidateSearchRequest) -> Optional[ColumnElement]:
    """ORDER BY / licznik: 1, gdy ZNANY staż kandydata (liczba albo koszyk
    Traffita) mieści się w żądaniu. Druga połowa tolerancji na brak danych:
    bez niej osoby z podanym stażem ginęłyby wśród tysięcy bez niego.
    """
    return predicates.experience_stated_rank(
        req.experience_years_min, req.experience_years_max, request_semantics(req)
    )


def location_soft_rank(req: CandidateSearchRequest) -> Optional[ColumnElement]:
    """ORDER BY / licznik: ile z żądanych miast kandydat faktycznie podaje."""
    return predicates.location_rank(req.location_cities)


def _language_clause(req: LanguageRequirement) -> Optional[ColumnElement]:
    """Filtr języka — reguła mieszka w `candidate_search_predicates.language_clause`
    (wspólna z listą `?languages=`)."""
    return predicates.language_clause(req.code, req.min_level)


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


# ── NULL policy ──────────────────────────────────────────────────────────────
# Every filter group must declare what a MISSING value means. The default is
# "missing → keep the candidate": on this dataset most structured columns are
# empty for the overwhelming majority of rows, so a filter that drops NULLs
# selects on *who happened to have the field filled in*, not on relevance.
#
# Measured on prod 2026-08-07 (56 608 candidates): a search for
# "2-6 years of experience" narrowed a genuinely relevant pool of 11 091 down
# to 45 — a 99.6% cut driven entirely by 1.2% column coverage. The same shape
# was already fixed once for skills (SEARCH-P0-03) and correctly avoided for
# rate/availability/notice-period; experience and location were simply missed.
#
# The registry — not the helper — is what stops this recurring: a new filter
# group with no entry fails `test_every_group_declares_a_null_policy`, so the
# omission becomes a red build instead of a silent 99% cut nobody notices.


class NullPolicy(str, Enum):
    include = "include"  # missing value → candidate STAYS (default)
    exclude = "exclude"  # missing value → candidate DROPS (needs justification)


@dataclass(frozen=True)
class GroupPolicy:
    policy: NullPolicy
    coverage_pct: float
    measured_at: str
    justification: str = ""


NULL_POLICY: dict[str, GroupPolicy] = {
    "competence_category": GroupPolicy(
        NullPolicy.exclude,
        58.9,
        "2026-08-07",
        justification=(
            "Curated taxonomy with usable coverage, and the chip reads as an "
            "explicit 'show me Backend people'. Admitting the 41% uncategorised "
            "would change what an existing, actively used surface returns — a "
            "product decision, not a bug fix. Revisit if coverage drops."
        ),
    ),
    "skills": GroupPolicy(
        NullPolicy.exclude,
        0.5,
        "2026-08-07",
        justification=(
            "Only `skills_none` remains here — 'must NOT have X' is an exclusion "
            "the recruiter explicitly asked for. The inclusion chips became a "
            "soft ranking signal in SEARCH-P0-03 (`skills_soft_rank`)."
        ),
    ),
    "skills_required": GroupPolicy(
        NullPolicy.exclude,
        0.5,
        "2026-09-21",
        justification=(
            "„Musi mieć” is the HARD bucket by product decision (09.2026): the "
            "recruiter explicitly asked for people who have the skill, so a "
            "profile with no skills data does not satisfy it. Only the explicit "
            "`skills_required*` fields land here — the legacy `skills_must` / "
            "`skills_any` chips stay a soft ranking signal („Mile widziane”)."
        ),
    ),
    "experience": GroupPolicy(NullPolicy.include, 1.2, "2026-08-07"),
    "location": GroupPolicy(NullPolicy.include, 14.9, "2026-08-07"),
    "languages": GroupPolicy(
        NullPolicy.exclude,
        0.4,
        "2026-08-07",
        justification=(
            "A CEFR level is a claim someone recorded; absence is not evidence "
            "of ability. Softening this needs a ranking signal first, otherwise "
            "a 'German C1' search returns the whole database. Tracked separately."
        ),
    ),
    # Heterogeneous on purpose, and the contract test caught it: this group
    # holds an enum-membership filter (`availability_status`, a NOT NULL column
    # — so "missing" is not a state it can be in) alongside two range filters
    # over nullable columns. The range parts ARE NULL-tolerant individually
    # (`availability_date`, `notice_period`, both `IS NULL OR ...`); the enum
    # part legitimately excludes, because asking for "actively looking" and
    # getting someone marked "unknown" is a wrong answer, not a kind one.
    "availability": GroupPolicy(
        NullPolicy.exclude,
        0.0,
        "2026-08-07",
        justification=(
            "`availability_status` is NOT NULL — an enum equality, not a "
            "missing-data question. The nullable parts of this group "
            "(availability_date, notice_period) are individually NULL-tolerant."
        ),
    ),
    "rate_hourly": GroupPolicy(NullPolicy.include, 0.0, "2026-08-07"),
    "eligibility": GroupPolicy(
        NullPolicy.exclude,
        100.0,
        "2026-08-07",
        justification=(
            "`status` is NOT NULL, so there is no missing case; the blacklist "
            "exclusion is a hard containment rule regardless."
        ),
    ),
    "status": GroupPolicy(
        NullPolicy.exclude,
        100.0,
        "2026-08-07",
        justification="`status` is NOT NULL — no missing case exists.",
    ),
    "sources": GroupPolicy(
        NullPolicy.exclude,
        100.0,
        "2026-08-07",
        justification=(
            "Provenance filter: 'came from Traffit' is a fact about the record, "
            "and an unknown source genuinely does not satisfy it."
        ),
    ),
    "tags": GroupPolicy(
        NullPolicy.exclude,
        0.0,
        "2026-08-07",
        justification=(
            "Tags are applied by hand; an untagged candidate has not been given "
            "the tag. Same shape as `skills_none`."
        ),
    ),
    "attributes": GroupPolicy(
        NullPolicy.exclude,
        100.0,
        "2026-08-07",
        justification=(
            "Derived booleans (has_cv, has_linkedin) computed from presence — "
            "they are never NULL, they are False."
        ),
    ),
}


def nullable(col: ColumnElement, *bounds: ColumnElement) -> ColumnElement:
    """NULL-tolerant comparison: a candidate with no value is kept.

    The one way to write a bounded filter in this module. Writing
    ``Candidate.x >= v`` directly silently drops every row where ``x`` is NULL,
    which is the bug this exists to prevent.
    """
    return or_(col.is_(None), and_(*bounds))


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

    sem = request_semantics(req)

    cc: list[ColumnElement] = []
    cc_clause = predicates.competence_category_clause(req.competence_category_ids, sem)
    if cc_clause is not None:
        cc.append(cc_clause)
    add("competence_category", "Kategoria kompetencji", cc)

    # Trzy kubełki (decyzja 09.2026): „Musi mieć" i „Wyklucz" tną, „Mile
    # widziane" tylko szereguje (`skills_soft_rank`). Pola legacy
    # `skills_must`/`skills_any` zostają MIĘKKIE (SEARCH-P0-03) — twarde „Musi
    # mieć" przychodzi wyłącznie jawnym `skills_required*`. Osobne grupy, żeby
    # wodospad diagnostyki umiał powiedzieć, KTÓRY kubełek wyzerował wynik.
    buckets = predicates.skill_buckets_from_search(req)
    add(
        "skills_required",
        'Umiejętności — „Musi mieć"',
        predicates.skills_required_clauses(buckets),
    )
    add(
        "skills",
        'Umiejętności — „Wyklucz"',
        predicates.skills_excluded_clauses(buckets),
    )

    experience: list[ColumnElement] = []
    exp_clause = predicates.experience_clause(
        req.experience_years_min, req.experience_years_max, sem
    )
    if exp_clause is not None:
        experience.append(exp_clause)
    add("experience", "Doświadczenie", experience)

    languages: list[ColumnElement] = []
    for lang in req.languages:
        lang_clause = _language_clause(lang)
        if lang_clause is not None:
            languages.append(lang_clause)
    add("languages", "Języki", languages)

    add(
        "location",
        "Lokalizacja",
        predicates.location_clauses(
            req.location_cities,
            req.location_countries,
            sem,
            scope=getattr(req, "location_scope", None),
        ),
    )

    eligibility: list[ColumnElement] = []
    if req.exclude_blacklisted:
        # Global blacklist = eligibility visibility "hidden" (SEARCH-P0-04).
        # Forced on for job-context search server-side; opt-in elsewhere.
        eligibility.append(Candidate.status != CandidateStatus.blacklisted)
    add("eligibility", "Dostępność do przypisania", eligibility)

    status_clause = predicates.status_clause(req.status)
    add(
        "status",
        "Status kandydata",
        [status_clause] if status_clause is not None else [],
    )

    availability: list[ColumnElement] = []
    availability_clause = predicates.availability_clause(req.availability_status)
    if availability_clause is not None:
        availability.append(availability_clause)
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

    # Stawka profilu: B2B, PLN netto/h. Brak stawki = nie wiemy → zostaje.
    rate_clause = predicates.hourly_rate_clause(
        req.rate_hourly_min, req.rate_hourly_max, sem
    )
    add(
        "rate_hourly",
        "Stawka godzinowa",
        [rate_clause] if rate_clause is not None else [],
    )

    sources: list[ColumnElement] = []
    if req.sources:
        sources.append(Candidate.source.in_(req.sources))
    add("sources", "Źródło", sources)

    add("tags", "Tagi", predicates.tags_clauses(req.tags, sem))

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
    # „Otwarty na". v2: którykolwiek z zaznaczonych (LUB) — pola legacy
    # `open_to_*: true` dokładają się do tej samej alternatywy co jawne
    # `open_to`. v1: dotychczasowa KONIUNKCJA przełączników. `false` („NIE jest
    # otwarty") jest w obu wersjach osobnym, twardym warunkiem.
    legacy_open_to = {
        "side_projects": req.open_to_side_projects,
        "sales_support": req.open_to_sales_support,
        "expert_consult": req.open_to_expert_consult,
    }
    wanted_open_to = list(getattr(req, "open_to", None) or [])
    for key, value in legacy_open_to.items():
        if value is False:
            attributes.append(predicates.OPEN_TO_FIELDS[key].is_(False))
        elif value is True and sem.unified:
            wanted_open_to.append(key)
        elif value is True:
            attributes.append(predicates.OPEN_TO_FIELDS[key].is_(True))
    open_to_clause = predicates.open_to_clause(wanted_open_to)
    if open_to_clause is not None:
        attributes.append(open_to_clause)
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
