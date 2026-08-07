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
from functools import reduce
from typing import Optional

from sqlalchemy import String, and_, case, cast, func, not_, or_, select
from sqlalchemy.sql import ColumnElement

from app.models.candidate import (
    Candidate,
    CandidateStatus,
)
from app.models.candidate_language import CandidateLanguage
from app.schemas.candidate_search import (
    CandidateSearchRequest,
    LanguageRequirement,
)
from app.services.candidate_profile_rate import (
    canonical_profile_rate_currency_clause,
)

# CEFR ordering — monotonic in ASCII so plain ``>=`` on the JSON value works.
_LEVEL_ORDER = ["A1", "A2", "B1", "B2", "C1", "C2", "native"]


def _safe(col: ColumnElement) -> ColumnElement:
    """Coalesce NULL → '' so ILIKE doesn't yield NULL (which excludes rows)."""
    return func.coalesce(col, "")


def _escape_like(value: str) -> str:
    return value.replace("\\", r"\\").replace("%", r"\%").replace("_", r"\_")


def _skills_text() -> ColumnElement:
    """Zrzut JSONB ``skills`` + ``verified_tech`` + ``tags`` jako tekst.

    Umiejętności bywają listą stringów albo listą słowników
    (``{name, level, years}``); rzutowanie na ``text`` daje surowy JSON, który
    pokrywa oba kształty.

    ``verified_tech`` dołączone dla parzystości z listą kandydatów
    (``candidates.py::_build_candidate_filtered_query``), która zawsze
    przeszukiwała trzy kolumny. Dopóki te dwie powierzchnie brały różne zbiory
    kolumn, ten sam filtr dawał różne wyniki zależnie od tego, który ekran go
    wysłał — i nikt tego nie widział, bo obie odpowiadały 200.
    """
    return (
        func.coalesce(cast(Candidate.skills, String), "")
        + " "
        + func.coalesce(cast(Candidate.verified_tech, String), "")
        + " "
        + func.coalesce(cast(Candidate.tags, String), "")
    )


def _skill_match(skill: str) -> ColumnElement:
    """Dopasuj umiejętność jako CAŁY token JSON, w obu spotykanych kodowaniach.

    Zrzut ``_skills_text()`` to JSON, więc każda wartość stoi w cudzysłowach —
    ``["Python", "Go"]`` i ``[{"name": "Go"}]`` tak samo zawierają ``"Go"``.
    Wymaganie tych cudzysłowów zamienia nieprecyzyjny test podłańcuchowy na test
    całego tokenu.

    DLACZEGO TO WAŻNE: ``skills_none`` jest filtrem TWARDYM. Przy gołym ``%Go%``
    zapytanie „nie ma Go" wycinało z wyników **196 osób, z których tylko 15 zna
    Go** — resztę stanowili deweloperzy Django, MongoDB i Golang. Rekruter nie
    miał jak tego zauważyć: brakujący kandydat wygląda identycznie jak kandydat,
    którego nie ma w bazie.

    DWA KODOWANIA, nie jedno. Część wierszy trzyma JSON **podwójnie zakodowany**
    — wartość jest stringiem JSON wewnątrz JSONB, więc w zrzucie granicą tokenu
    jest ``\\"`` zamiast ``"``. Zmierzone na produkcji 28.07: token ``"Go"``
    trafia w 5 kandydatów, token ``\\"Go\\"`` w kolejnych 10 — łącznie 15.
    Wzorzec sprawdzający tylko pierwszy kształt gubił dwie trzecie prawdziwych
    trafień. Wierszy z podwójnym kodowaniem jest w bazie 303.

    ``strpos`` zamiast ``ILIKE`` **świadomie**: LIKE traktuje ``\\`` jako znak
    ucieczki, więc wzorzec na podwójne kodowanie wymagałby podwajania ukośników
    i degenerował się po cichu do wariantu bez nich (ta sama pułapka przewróciła
    pomiar przy pisaniu tej poprawki). ``strpos`` szuka dosłownego podłańcucha —
    bez znaków ucieczki, bez wieloznaczników, więc nazwa umiejętności zawierająca
    ``%`` lub ``_`` też przestaje być wzorcem.

    Ograniczenie świadome: w kształcie słownikowym zrzut zawiera też klucze
    ``"name"``, ``"level"``, ``"years"`` — chip nazwany dokładnie jak klucz trafi
    sam w siebie. Nieszkodliwe i wciąż ściśle lepsze od stanu poprzedniego;
    właściwym rozwiązaniem jest złączenie z ``cortex_skill_facts``, które wymaga
    pokrycia Cortexa powyżej ~60% (zmierzone 56,8% na 2026-07-27).

    RODZINA ALIASÓW, nie jedna pisownia. Dane kandydatów nie są kanonizowane —
    w bazie leży dosłownie to, co przyszło z CV albo z importu — a semantyka
    całego tokenu (powyżej) sprawia, że ``"golang"`` NIE zawiera ``"go"``.
    Zbiory wariantów są więc rozłączne. Zmierzone na produkcji 2026-07-28 dla
    rodziny „Microsoft SQL Server”::

        mssql=21, ms sql=18, sql server=18, microsoft sql server=9, microsoft sql=3

    Wcześniej lista kandydatów zwijała zapytanie do nazwy kanonicznej i szukała
    wyłącznie jej dosłownego brzmienia (9 z ponad 60 osób, te same 9 niezależnie
    od wpisanego wariantu), a wyszukiwarka nie normalizowała nic (tylko dosłowne
    trafienia wpisanej pisowni). Żadna z powierzchni nie była nadzbiorem drugiej:
    przy „REST” wyszukiwarka znajdowała 35, lista 31. Poza MSSQL gubione było
    m.in. 35 z 76 przy HTML, 34 z 69 przy REST API, 27 ze 152 przy Javie.

    Rozwinięcie siedzi TUTAJ, a nie w miejscach wywołania, bo to jedyny punkt
    wspólny obu powierzchni — poprawkę w wywołaniach da się pominąć przy
    dopisywaniu kolejnego endpointu i dokładnie tak powstał poprzedni rozjazd.
    Efekt uboczny jest korzystny: skoro alternatywa siedzi wewnątrz predykatu,
    koniunkcja przy ``skill_combine="and"`` nadal działa MIĘDZY umiejętnościami,
    a nie między pisowniami tej samej (co nie zwróciłoby nikogo).
    """  # noqa: D301
    blob = func.lower(_skills_text())

    # Import lokalny: `scoring_service` importuje modele i schematy, a ten moduł
    # jest ładowany z `candidates.py` — import na górze pliku domyka cykl.
    from app.services.scoring_service import skill_name_variants

    # Zabezpieczenie na końcu jest jedynym działającym: `skill_name_variants`
    # zwraca listę (nigdy None), ale przy pustej mapie aliasów i pustej nazwie
    # może zwrócić [] — wtedy predykat musi mieć w co trafiać.
    igly = [w for w in skill_name_variants([skill]) if w] or [skill.lower()]

    warunki: list[ColumnElement] = []
    for igla in igly:
        warunki.append(func.strpos(blob, f'"{igla}"') > 0)
        warunki.append(func.strpos(blob, f'\\"{igla}\\"') > 0)
    return or_(*warunki)


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


def _city_match_clauses(cities: list[str]) -> list[ColumnElement]:
    """One ILIKE-pair predicate per requested city.

    Shared by the WHERE clause and ``location_soft_rank`` so the two can never
    disagree about what "matches this city" means.
    """
    return [
        or_(
            _safe(Candidate.city).ilike(f"%{_escape_like(c)}%", escape="\\"),
            _safe(Candidate.location).ilike(f"%{_escape_like(c)}%", escape="\\"),
        )
        for c in cities
    ]


def experience_soft_rank(req: CandidateSearchRequest) -> Optional[ColumnElement]:
    """ORDER BY expression: 1 when the stated experience is inside the request.

    The second half of making the experience filter NULL-tolerant. Dropping the
    hard cut alone would be a regression: on the measured example the 45 people
    who actually state 2-6 years would be scattered among 11 046 whose field is
    blank. This lifts the ones who said so; the rest keep their place below.

    Returns ``None`` when no bound was requested (nothing to rank by).
    """
    bounds: list[ColumnElement] = []
    if req.experience_years_min is not None:
        bounds.append(Candidate.years_it_experience >= req.experience_years_min)
    if req.experience_years_max is not None:
        bounds.append(Candidate.years_it_experience <= req.experience_years_max)
    if not bounds:
        return None
    return case((and_(Candidate.years_it_experience.is_not(None), *bounds), 1), else_=0)


def location_soft_rank(req: CandidateSearchRequest) -> Optional[ColumnElement]:
    """ORDER BY expression: how many of the requested cities the candidate matches."""
    if not req.location_cities:
        return None
    matches = [
        case((clause, 1), else_=0)
        for clause in _city_match_clauses(req.location_cities)
    ]
    return reduce(lambda a, b: a + b, matches)


def _language_clause(req: LanguageRequirement) -> Optional[ColumnElement]:
    """Match an active normalized fact at/above the requested CEFR level.

    ``native`` is a distinct fact and satisfies every CEFR threshold.  An
    unknown/descriptive level deliberately satisfies none: descriptive labels
    are suggestions, never silently promoted to CEFR.
    """
    code_upper = req.code.upper()
    try:
        min_idx = _LEVEL_ORDER.index(req.min_level)
    except ValueError:
        return None
    accepted_levels = [lvl for lvl in _LEVEL_ORDER[min_idx:] if lvl != "native"]

    return (
        select(CandidateLanguage.id)
        .where(
            CandidateLanguage.candidate_id == Candidate.id,
            CandidateLanguage.deleted_at.is_(None),
            func.upper(CandidateLanguage.language_code) == code_upper,
            and_(
                CandidateLanguage.is_level_unknown.is_(False),
                or_(
                    CandidateLanguage.is_native.is_(True),
                    CandidateLanguage.cefr_level.in_(accepted_levels),
                ),
            ),
        )
        .correlate(Candidate)
        .exists()
    )


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
    "availability": GroupPolicy(NullPolicy.include, 0.0, "2026-08-07"),
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
    exp_bounds: list[ColumnElement] = []
    if req.experience_years_min is not None:
        exp_bounds.append(Candidate.years_it_experience >= req.experience_years_min)
    if req.experience_years_max is not None:
        exp_bounds.append(Candidate.years_it_experience <= req.experience_years_max)
    if exp_bounds:
        # NULL-tolerant per NULL_POLICY["experience"]: `years_it_experience` is
        # filled for 1.2% of the base, so a hard bound selects on bookkeeping
        # rather than on seniority. Candidates who DO state a matching range are
        # lifted by `experience_soft_rank`.
        experience.append(nullable(Candidate.years_it_experience, *exp_bounds))
    add("experience", "Doświadczenie", experience)

    languages: list[ColumnElement] = []
    for lang in req.languages:
        lang_clause = _language_clause(lang)
        if lang_clause is not None:
            languages.append(lang_clause)
    add("languages", "Języki", languages)

    location: list[ColumnElement] = []
    if req.location_cities:
        # NULL-tolerant per NULL_POLICY["location"]: city/location are filled for
        # ~15% of the base. `_safe` coalesces NULL → '' so ILIKE returns a
        # boolean rather than NULL — which reads as "safe" but *guarantees* the
        # unknown-location rows are excluded. Known-and-not-matching still drops;
        # unknown stays and sinks via `location_soft_rank`.
        location.append(
            or_(
                and_(Candidate.city.is_(None), Candidate.location.is_(None)),
                or_(*_city_match_clauses(req.location_cities)),
            )
        )
    if req.location_countries:
        location.append(
            nullable(
                Candidate.country,
                Candidate.country.in_([c.upper() for c in req.location_countries]),
            )
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

    # Global candidate rate has fixed semantics: B2B, PLN net/hour. Missing rate
    # is unknown → included (never a hard exclusion), matching the
    # availability/notice-period NULL policy above.
    rate: list[ColumnElement] = []
    if req.rate_hourly_min is not None or req.rate_hourly_max is not None:
        bounds: list[ColumnElement] = []
        if req.rate_hourly_min is not None:
            bounds.append(Candidate.expected_rate_hourly >= req.rate_hourly_min)
        if req.rate_hourly_max is not None:
            bounds.append(Candidate.expected_rate_hourly <= req.rate_hourly_max)
        comparable = canonical_profile_rate_currency_clause(
            Candidate.expected_rate_currency
        )
        rate.append(
            Candidate.expected_rate_hourly.is_(None)
            | ~comparable
            | (comparable & and_(*bounds))
        )
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
