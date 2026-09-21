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
from pydantic_core import PydanticCustomError

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
    # Trzy JAWNE kubełki (decyzja 09.2026) — to samo znaczenie co w
    # `GET /api/candidates`: „Musi mieć" (twardo), „którakolwiek z grupy"
    # (twardo), „Mile widziane" (tylko ranking), „Wyklucz" (twardo). Każda
    # pozycja może być grupą LUB w formacie `a|b`. Pola legacy wyżej zachowują
    # dotychczasowe znaczenie: `skills_must`/`skills_any` = „Mile widziane",
    # `skills_none` = „Wyklucz" — zapisane wyszukiwania zwracają to samo.
    skills_required: list[str] = Field(default_factory=list, max_length=20)
    skills_required_any_groups: list[list[str]] = Field(
        default_factory=list, max_length=10
    )
    skills_preferred: list[str] = Field(default_factory=list, max_length=20)
    skills_excluded: list[str] = Field(default_factory=list, max_length=20)
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
    # „Otwarty na" — KTÓRYKOLWIEK z zaznaczonych (LUB), jak na liście. Pola
    # `open_to_*: true` wyżej dokładają się do tej samej alternatywy.
    open_to: list[Literal["side_projects", "sales_support", "expert_consult"]] = Field(
        default_factory=list
    )
    # Ukryj osoby BEZ danych dla aktywnych filtrów lokalizacji / stażu / stawki.
    # Domyślnie (v2) takie osoby ZOSTAJĄ i są oznaczane w `unknown_fields`.
    hide_unknown: Optional[bool] = None
    # Wersja semantyki filtrów. Brak pola (v1) = DOKŁADNIE dotychczasowe wyniki
    # tego endpointu — zapisane wyszukiwania nie zmieniają się bez zgody
    # właściciela. `2` = jedna semantyka wspólna z `GET /api/candidates`
    # (`candidate_search_predicates.Semantics`).
    semantics_version: Optional[Literal[1, 2]] = None
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

    # === Tryb tekstu `q` ======================================================
    # "auto"     — `q` wyglądające na osobę (dwa–trzy wyrazy, e-mail, telefon
    #              albo JEDNO słowo będące czyimś imieniem/nazwiskiem w bazie)
    #              jest dopasowywane DOSŁOWNIE, tak samo jak `?q=` na liście;
    #              każdy inny tekst idzie ścieżką wg `search_mode`.
    # "literal"  — zawsze dosłownie, bez retrievalu wektorowego.
    # "semantic" — zawsze hybryda (BM25 + wektor), niezależnie od `search_mode`.
    # Brak pola: v2 zachowuje się jak "auto"; v1 zostaje przy dotychczasowym
    # `q` (bez automatycznego przełączania). Co faktycznie zrobiono, mówi
    # `meta.text_mode_applied` + `meta.interpretation`.
    text_mode: Optional[Literal["auto", "literal", "semantic"]] = None

    @model_validator(mode="after")
    def ranges_are_ordered(self) -> "CandidateSearchRequest":
        """Odwrócony przedział (min > max) to 422, nie pusty wynik.

        Do 09.2026 „min 10 / max 2 lat" przechodziło i zwracało wyłącznie
        osoby bez uzupełnionego stażu — wynik poprawny arytmetycznie, dla
        rekrutera nie do odróżnienia od działającego filtra (UAT B28).
        """
        raise_if_range_reversed(
            self.experience_years_min,
            self.experience_years_max,
            EXPERIENCE_RANGE_REVERSED_MSG,
        )
        raise_if_range_reversed(
            self.rate_hourly_min, self.rate_hourly_max, RATE_RANGE_REVERSED_MSG
        )
        return self


EXPERIENCE_RANGE_REVERSED_MSG = (
    "Minimalna liczba lat doświadczenia nie może być większa niż maksymalna."
)
RATE_RANGE_REVERSED_MSG = "Minimalna stawka nie może być większa niż maksymalna."


def raise_if_range_reversed(low: Any, high: Any, message: str) -> None:
    """Wspólna reguła dla obu schematów wyszukiwania (legacy i V3)."""
    if low is not None and high is not None and low > high:
        # PydanticCustomError: komunikat wychodzi w 422 bez prefiksu
        # „Value error, ..." — użytkownik widzi zdanie po polsku.
        raise PydanticCustomError("range_reversed", message)


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
    # Plakietka dopuszczalności w kontekście rekrutacji (``exclude_in_job_id``)
    # — ten sam kształt co w rankingu AI (``services/eligibility_annotation``).
    # Konflikt z klientem to ostrzeżenie (``assignment_allowed=True``); weto
    # hiring managera blokuje (``False``). ``None`` bez kontekstu rekrutacji
    # albo bez przeciwwskazań.
    eligibility: Optional[dict[str, Any]] = None
    # v2: które AKTYWNE filtry („location", „experience", „rate") ta osoba
    # przeszła wyłącznie dlatego, że nie mamy o niej danych — do plakietki w UI.
    unknown_fields: list[str] = Field(default_factory=list)


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
    # True gdy tryb semantyczny obejrzał PEŁNĄ pulę retrievalu, czyli `total`
    # jest sufitem puli, a nie liczbą pasujących osób w bazie. Bez tego pola
    # przełączenie „Semantycznie" na zapytaniu ogólnym („java") zamieniało
    # „11 091 wyników" w „200" i wyglądało jak utrata bazy, a nie jak
    # „200 najtrafniejszych". Zawsze False w trybie boolowskim, gdzie `total`
    # naprawdę zlicza całą bazę.
    result_cap_reached: bool = False
    # Jak potraktowano `q`: "literal" (dopasowanie dosłowne — osoba albo jawny
    # przełącznik), "keywords" (FTS słów kluczowych, tryb boolowski),
    # "semantic" (hybryda BM25 + wektor), "none" (bez `q`).
    text_mode_applied: Literal["literal", "keywords", "semantic", "none"] = "none"
    # „Rozumiem to jako…" — patrz `candidate_search_predicates.TextInterpretation`.
    interpretation: Optional[dict[str, Any]] = None


class CandidateSearchResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[CandidateSearchItem]
    facets: SearchFacets = Field(default_factory=SearchFacets)
    meta: SearchMeta = Field(default_factory=SearchMeta)


# The scores endpoint measures canonical fit ON DEMAND (query vector + exact
# vector provenance + scoring), so one request is bounded to what a recruiter
# can see at once. The front end asks only for rows on screen; a wider page is
# scored in several requests as the user scrolls.
MATCH_SCORES_MAX_CANDIDATES = 20


class MatchScoresRequest(BaseModel):
    """Ask for the canonical fit of the visible candidates against a job."""

    job_id: int
    candidate_ids: list[int] = Field(
        default_factory=list, max_length=MATCH_SCORES_MAX_CANDIDATES
    )


class MatchScoresResponse(BaseModel):
    """``candidate_id`` (string key for JSON) → canonical fit score in [0, 100].

    Only measured candidates have a score; a candidate without a verified
    measurement (stale/missing vector, provider outage) has none — it is never
    shown as 0. ``breakdowns`` carries the explainability payload (per-layer
    points + matched/gap skills, salary redacted without ``view_finance``) plus
    ``total`` and ``measurement``; for an unmeasured candidate it holds only
    ``{"total": null, "measurement": "<reason>"}``.

    ``profile_key`` identifies the weight profile (id + weights) the scores
    were computed under: the same pair scores differently under another
    profile, so a client caching scores keys them by it and never shows two
    profiles side by side. ``None`` when nothing was scored."""

    scores: dict[str, int] = Field(default_factory=dict)
    breakdowns: dict[str, Any] = Field(default_factory=dict)
    profile_key: Optional[str] = None


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
