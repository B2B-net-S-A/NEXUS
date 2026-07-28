"""
Hybrid candidate-job scoring engine (Phase 2).

Layered scoring — each layer returns points that add up to 100:

  semantic        0-40pt   Qdrant cosine similarity between job query and candidate embedding
  skills          0-30pt   weighted must/nice overlap (must=20pt, nice=10pt)
  salary_fit      0-15pt   candidate rate fits inside job salary_min..salary_max
  location_fit    0-10pt   remote/hybrid compat + country + city bonus
  availability    0-5pt    candidate availability_date before/at job deadline

Penalties zero the score:
  blacklist            -100  Candidate.status == blacklisted
  active_conflict      -100  CandidateConflict.active == True for this (candidate, client)
  client_excluded      -100  client_id in Candidate.preferences.excluded_clients

Explainable: every call returns a ScoreBreakdown with per-layer points, matched/gap
lists, and active penalties so the UI can render a "why" tooltip.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.candidate import Candidate, CandidateStatus
from app.models.candidate_conflict import CandidateConflict
from app.models.job import Job
from app.services.location_utils import location_tokens, tokens_overlap

logger = logging.getLogger(__name__)


# ── Calibration knobs (runtime-tunable via Coolify env; reversible) ──────────
#
# The hybrid composite (0-100) was chronically DEFLATED for two reasons:
#   1. Raw Voyage cosine (voyage-3-large) for genuinely-relevant candidates
#      clusters ~0.4-0.65, so a linear `sim * budget` under-credits good
#      semantic fits (a 0.55 match earned only ~55% of the budget).
#   2. salary/location returned 0 when the underlying data was simply UNKNOWN
#      (true for ~99% of imported candidates / ~99.6% of imported jobs) — unlike
#      availability and champion_fit, which already award a neutral half-budget
#      for "no signal". The inconsistency depressed the composite for the whole
#      imported pool (see config.py calibration notes — the "zaniżony" bug).
#
# Both are corrected below and gated behind env so the exact legacy behaviour is
# one flip away (gamma=1.0 + neutral=0.0):
#
#   SEMANTIC_CALIBRATION_GAMMA  power curve applied to cosine before scaling
#                               (0.6 default; 1.0 == legacy linear). Strictly
#                               increasing in sim → per-candidate semantic
#                               ranking is preserved exactly.
#   UNKNOWN_NEUTRAL_FRACTION    fraction of a layer's budget awarded when there
#                               is genuinely no data to judge it (0.5 default,
#                               matching availability/champion; 0.0 == legacy).
#
# Read as module globals inside the scoring functions so tests can monkeypatch
# them and an offline override (eval/tooling) takes effect at call time.
SEMANTIC_CALIBRATION_GAMMA: float = float(
    getattr(settings, "SEMANTIC_CALIBRATION_GAMMA", 0.6)
)
UNKNOWN_NEUTRAL_FRACTION: float = float(
    getattr(settings, "SCORE_UNKNOWN_NEUTRAL_FRACTION", 0.5)
)


# ── Point budgets (defaults; overridable by WeightProfile) ──────────────────
#
# Phase 10: added `champion_fit` layer (0-10pt) at cost of other layers so the
# sum stays at 100. Rebalancing:
#   semantic     40 → 35
#   skills       30 → 28  (must 19, nice 9)
#   salary       15 → 13
#   location     10 → 9
#   availability  5 → 5
#   champion_fit  0 → 10
#
# Legacy numeric constants (SEMANTIC_MAX etc.) still reflect Phase 0 values
# because `WeightProfile.from_record` resolves actual weights at call time;
# the constants are only fallbacks for callers that skip the profile.

# Keep SKILLS_MAX at 30 (must=20, nice=10) so Phase 2 unit tests that assert
# specific point sums remain green. We subtract the 10pt Champion budget from
# semantic/salary/location instead.
SEMANTIC_MAX = 35.0
SKILLS_MAX = 30.0
SKILLS_MUST_MAX = 20.0
SKILLS_NICE_MAX = 10.0
SALARY_MAX = 12.0
LOCATION_MAX = 8.0
AVAILABILITY_MAX = 5.0
CHAMPION_FIT_MAX = 10.0
# sum = 35 + 30 + 12 + 8 + 5 + 10 = 100


@dataclass(frozen=True)
class WeightProfile:
    """Resolved layer budgets used by the scoring engine on a single pass.

    `skills` is split into must/nice with the classic 2:1 ratio. The caller
    (e.g. Phase D1 `scoring_weight_profiles` table) supplies the 5 aggregate
    weights; the engine expands them internally.
    """

    id: int = 0  # 0 = built-in default; real profiles use their DB id
    name: str = "default"
    semantic: float = SEMANTIC_MAX
    skills: float = SKILLS_MAX
    salary: float = SALARY_MAX
    location: float = LOCATION_MAX
    availability: float = AVAILABILITY_MAX
    champion_fit: float = CHAMPION_FIT_MAX

    @property
    def skills_must(self) -> float:
        return self.skills * (2.0 / 3.0) if self.skills else 0.0

    @property
    def skills_nice(self) -> float:
        return self.skills * (1.0 / 3.0) if self.skills else 0.0

    @classmethod
    def from_record(cls, record) -> "WeightProfile":
        """Build from a `ScoringWeightProfile` ORM row.

        The persisted ``weights`` dict may carry only the five legacy layers
        (semantic/skills/salary/location/availability = 100). The old code then
        added a default ``champion_fit=10`` on top, giving a 110-point budget
        (AI-P0-05). Under ``AI_SCORING_CONTRACT_V2`` the champion layer instead
        absorbs whatever the other five leave unallocated, so the budget is
        always exactly 100. With the flag OFF, behaviour is unchanged.
        """
        w = record.weights or {}
        semantic = float(w.get("semantic", SEMANTIC_MAX))
        skills = float(w.get("skills", SKILLS_MAX))
        salary = float(w.get("salary", SALARY_MAX))
        location = float(w.get("location", LOCATION_MAX))
        availability = float(w.get("availability", AVAILABILITY_MAX))

        if "champion_fit" in w:
            champion_fit = float(w["champion_fit"])
        elif getattr(settings, "AI_SCORING_CONTRACT_V2", False):
            # Champion takes the remaining budget so the six layers sum to 100.
            other = semantic + skills + salary + location + availability
            champion_fit = max(0.0, 100.0 - other)
        else:
            champion_fit = CHAMPION_FIT_MAX  # legacy: may overshoot 100

        return cls(
            id=record.id,
            name=record.name,
            semantic=semantic,
            skills=skills,
            salary=salary,
            location=location,
            availability=availability,
            champion_fit=champion_fit,
        )


# Version stamp for the match-score cache. Derives from the scoring-contract
# flag so flipping AI_SCORING_CONTRACT_V2 changes the string, which the cache
# treats as a full invalidation (old rows recompute under the new budget rule).
#
# The embedding model is folded in (AI-P0-06 part c): the cached semantic layer
# is only comparable within one embedding space, so swapping VOYAGE_MODEL must
# invalidate every cached score. Weight-profile edits are handled separately by
# mark_stale_for_profile (parts a/b) — those don't change this global string.
SCORING_ALGORITHM_VERSION: str = (
    "score-v2-budget100"
    if getattr(settings, "AI_SCORING_CONTRACT_V2", False)
    else "score-v1-legacy"
) + f"+emb-{getattr(settings, 'VOYAGE_MODEL', 'unknown')}"


DEFAULT_PROFILE = WeightProfile()


async def resolve_active_profile(
    db,
    *,
    user_id: Optional[int] = None,
    client_id: Optional[int] = None,
) -> WeightProfile:
    """Pick the most specific active scoring weight profile.

    Precedence: user_id match → client_id match → global (user_id IS NULL AND
    client_id IS NULL) → built-in DEFAULT_PROFILE. Non-active profiles are
    ignored.
    """
    # Local import to avoid circular at module load
    from sqlalchemy import select as _select

    from app.models.scoring_weight_profile import ScoringWeightProfile

    async def _fetch(where) -> Optional[WeightProfile]:
        row = await db.scalar(
            _select(ScoringWeightProfile)
            .where(ScoringWeightProfile.active.is_(True))
            .where(where)
            .limit(1)
        )
        return WeightProfile.from_record(row) if row else None

    if user_id is not None:
        p = await _fetch(ScoringWeightProfile.user_id == user_id)
        if p is not None:
            return p
    if client_id is not None:
        p = await _fetch(ScoringWeightProfile.client_id == client_id)
        if p is not None:
            return p
    p = await _fetch(
        (ScoringWeightProfile.user_id.is_(None))
        & (ScoringWeightProfile.client_id.is_(None))
    )
    return p or DEFAULT_PROFILE


# ── Data classes ────────────────────────────────────────────────────────────


@dataclass
class LayerResult:
    points: float
    max_points: float
    reason: str = ""


@dataclass
class ScoreBreakdown:
    candidate_id: int
    job_id: int
    total: float  # 0-100
    semantic: LayerResult
    skills: LayerResult
    salary: LayerResult
    location: LayerResult
    availability: LayerResult
    matching_must: List[str] = field(default_factory=list)
    gap_must: List[str] = field(default_factory=list)
    matching_nice: List[str] = field(default_factory=list)
    gap_nice: List[str] = field(default_factory=list)
    penalties: List[str] = field(default_factory=list)
    # Phase 10: Champion screening layer — defaults to the neutral
    # benefit-of-the-doubt budget when there is no screening yet (recruiter
    # hasn't answered DL's questions). Governed by the same UNKNOWN_NEUTRAL_
    # FRACTION knob as the live `_score_champion_fit` path (read at instantiation
    # so monkeypatch/env overrides apply). Placeholder only — real scoring always
    # supplies a computed champion_fit.
    champion_fit: LayerResult = field(
        default_factory=lambda: LayerResult(
            points=CHAMPION_FIT_MAX * UNKNOWN_NEUTRAL_FRACTION,
            max_points=CHAMPION_FIT_MAX,
            reason="brak screeningu",
        )
    )
    # Post-processing adjustment layered on top of `total` when the candidate
    # was present on semantically-similar historical jobs. NOT persisted in
    # the match-score cache — recomputed per request because pipeline state
    # changes too often to warrant explicit invalidation.
    historical_boost: float = 0.0
    historical_sources_count: int = 0
    # Plan PR8/4.2: input-data completeness in [0,1], SEPARATE from `total`.
    # NOT a probability and NOT part of ranking — it tells the recruiter how much
    # evidence backed this score (a full score built on a near-empty profile is
    # low-confidence). None when not computed (e.g. hydrated legacy cache row).
    fit_confidence: Optional[float] = None

    def as_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "job_id": self.job_id,
            "total": round(self.total, 1),
            "semantic": {
                "points": round(self.semantic.points, 1),
                "max": self.semantic.max_points,
                "reason": self.semantic.reason,
            },
            "skills": {
                "points": round(self.skills.points, 1),
                "max": self.skills.max_points,
                "reason": self.skills.reason,
            },
            "salary": {
                "points": round(self.salary.points, 1),
                "max": self.salary.max_points,
                "reason": self.salary.reason,
            },
            "location": {
                "points": round(self.location.points, 1),
                "max": self.location.max_points,
                "reason": self.location.reason,
            },
            "availability": {
                "points": round(self.availability.points, 1),
                "max": self.availability.max_points,
                "reason": self.availability.reason,
            },
            "champion_fit": {
                "points": round(self.champion_fit.points, 1),
                "max": self.champion_fit.max_points,
                "reason": self.champion_fit.reason,
            },
            "matching_must": self.matching_must,
            "gap_must": self.gap_must,
            "matching_nice": self.matching_nice,
            "gap_nice": self.gap_nice,
            "penalties": self.penalties,
            "historical_boost": round(self.historical_boost, 1),
            "historical_sources_count": self.historical_sources_count,
            "fit_confidence": self.fit_confidence,
        }


# ── Helpers ──────────────────────────────────────────────────────────────────


def _nonempty(v) -> bool:
    """Truthy for a populated list/dict/str/number; False for None/empty."""
    if v is None:
        return False
    if isinstance(v, (list, dict, str)):
        return len(v) > 0
    return True


def compute_fit_confidence(candidate, job) -> float:
    """Input-data completeness in [0,1] — how much evidence backs a score.

    Deliberately independent of the score itself and of ranking: it counts the
    presence of the signals the matcher relies on. A candidate with a full CV,
    skills, verified tech, experience and known availability scores at high
    confidence; a near-empty stub scores low even if its `total` is high.
    """
    signals = [
        _nonempty(getattr(candidate, "skills", None)),
        _nonempty(getattr(candidate, "verified_tech", None)),
        _nonempty(getattr(candidate, "experience", None)),
        getattr(candidate, "years_it_experience", None) is not None,
        _nonempty(getattr(candidate, "ai_summary", None))
        or _nonempty(getattr(candidate, "raw_cv_text", None)),
        _availability_known(candidate),
        # Job-side context reliability (defined criteria → a more trustworthy fit).
        _nonempty(getattr(job, "must_skills", None)),
    ]
    return round(sum(1 for s in signals if s) / len(signals), 3)


def _availability_known(candidate) -> bool:
    status = getattr(candidate, "availability_status", None)
    if status is None:
        return False
    val = getattr(status, "value", status)
    return str(val).lower() not in ("unknown", "")


_DICT_SKILL_LIST_KEYS = ("technologies", "skills", "stack", "tech")


def _split_skill_tokens(text: str) -> List[str]:
    """Split a free-form skills string into lowercase tokens.

    Splits on comma / semicolon / newline but NOT on ``/`` so compound names
    like ``CI/CD`` and ``TCP/IP`` survive (mirrors
    ``api.matching._parse_required_skills``). Used for Traffit
    ``cv_extracted_data.traffit_technologie`` ("JAVA, Spring, Kafka, ...") and
    for non-JSON string-typed ``skills`` columns.
    """
    if not text:
        return []
    return [t.strip().lower() for t in re.split(r"[,;\n]+", text) if t.strip()]


# ── Alias map (Phase B1 skill taxonomy) ──────────────────────────────────────
#
# Populated at application startup from the `skill_aliases` table; normalized
# lookup `alias (lower) -> canonical (lower)`. Empty by default so tests and
# offline tools work without a DB connection.

ALIAS_MAP: dict[str, str] = {}

# Odwrotność ALIAS_MAP: `kanoniczna -> [kanoniczna, alias, alias, ...]`.
# Budowana leniwie, unieważniana przez `set_alias_map` poniżej. Deklaracja stoi
# PRZED tą funkcją celowo — inaczej `global _RODZINY_ALIASOW` odwołuje się do
# nazwy zdefiniowanej niżej w pliku. Działa (globalne są wiązane w czasie
# wywołania), ale czyta się to jak błąd.
_RODZINY_ALIASOW: Optional[dict[str, List[str]]] = None


def set_alias_map(mapping: dict[str, str]) -> None:
    """Replace the in-memory alias map atomically (called from FastAPI startup)."""
    ALIAS_MAP.clear()
    ALIAS_MAP.update({k.lower(): v.lower() for k, v in mapping.items()})
    # Invalidate the compiled regex used for Champion Profile skill extraction.
    global _CHAMPION_ALIAS_PATTERN
    _CHAMPION_ALIAS_PATTERN = None
    # Invalidate the reverse index used by `skill_name_variants`.
    global _RODZINY_ALIASOW
    _RODZINY_ALIASOW = None


def _rodziny_aliasow() -> dict[str, List[str]]:
    global _RODZINY_ALIASOW
    if _RODZINY_ALIASOW is None:
        rodziny: dict[str, List[str]] = {}
        for alias, kanoniczna in ALIAS_MAP.items():
            rodzina = rodziny.setdefault(kanoniczna, [kanoniczna])
            if alias != kanoniczna:
                rodzina.append(alias)
        _RODZINY_ALIASOW = rodziny
    return _RODZINY_ALIASOW


def skill_variant_groups(raw) -> List[List[str]]:
    """Jak `skill_name_variants`, ale zachowuje granice między umiejętnościami.

    Potrzebne wszędzie tam, gdzie umiejętności łączy się przez AND. Płaska lista
    wariantów zamieniłaby „ma MSSQL ORAZ Pythona" w „ma wszystkie pisownie MSSQL
    naraz" — czyli w zapytanie, które nie zwróci nikogo. Alternatywa działa
    WEWNĄTRZ rodziny, koniunkcja MIĘDZY rodzinami.

    Zwraca listę list; każda podlista to jedna rodzina, z nazwą kanoniczną na
    początku. Puste rodziny są pomijane.
    """
    rodziny = _rodziny_aliasow()
    widziane_kanoniczne: set[str] = set()
    grupy: List[List[str]] = []
    for nazwa in _skill_names(raw):
        kanoniczna = ALIAS_MAP.get(nazwa, nazwa)
        if kanoniczna in widziane_kanoniczne:
            continue
        widziane_kanoniczne.add(kanoniczna)
        rodzina = [w for w in rodziny.get(kanoniczna, [kanoniczna]) if w]
        if rodzina:
            grupy.append(rodzina)
    return grupy


def skill_name_variants(raw) -> List[str]:
    """Rozwija nazwy umiejętności na PEŁNE rodziny aliasów.

    Czym różni się od `canonical_skill_names`. Tamta ZWIJA — zwraca jedną nazwę
    kanoniczną na umiejętność. To ma sens przy porównywaniu dwóch zbiorów
    umiejętności (scoring), ale jest błędem przy WYSZUKIWANIU, bo dane
    kandydatów nie są kanonizowane: w bazie leży dosłownie to, co przyszło z CV
    albo z importu.

    Zmierzone na produkcji 2026-07-28 (55 428 kandydatów). Rodzina
    „Microsoft SQL Server" występuje w danych jako:

        mssql=21, ms sql=18, sql server=18, microsoft sql server=9, microsoft sql=3

    Filtr sprowadzający zapytanie do nazwy kanonicznej znajdował więc **9 z ponad
    60** osób — i zwracał te same 9 niezależnie od tego, który wariant wpisał
    rekruter. Analogicznie HTML gubił 35 z 76, REST API 34 z 69, Java 27 ze 152.
    Przy filtrze „nie ma X" (twardym) pominięty kandydat wygląda dokładnie tak
    samo jak nieistniejący, więc rozjazd był z ekranu niewidoczny.

    Zwraca listę małymi literami, bez powtórzeń, z nazwą kanoniczną na początku
    każdej rodziny. Gdy `ALIAS_MAP` jest pusta (testy, narzędzia offline)
    zachowuje się jak `_skill_names` — czyli nie zmienia niczego.

    Do użycia tylko tam, gdzie wynik i tak łączy się ALTERNATYWĄ. Przy AND
    użyj `skill_variant_groups`, żeby nie zażądać wszystkich pisowni naraz.
    """
    widziane: set[str] = set()
    out: List[str] = []
    for rodzina in skill_variant_groups(raw):
        for wariant in rodzina:
            if wariant not in widziane:
                widziane.add(wariant)
                out.append(wariant)
    return out


# Compiled union regex: \b(alias1|alias2|...)\b. Built lazily, invalidated when
# `set_alias_map` rebuilds ALIAS_MAP. Used by `_extract_skills_from_champion`.
_CHAMPION_ALIAS_PATTERN: Optional[re.Pattern] = None


def _alias_pattern() -> Optional[re.Pattern]:
    global _CHAMPION_ALIAS_PATTERN
    if not ALIAS_MAP:
        return None
    if _CHAMPION_ALIAS_PATTERN is None:
        # Sort longer aliases first so "kubernetes" matches before its substring
        # "kube"; regex alternation is greedy left-to-right.
        sorted_aliases = sorted(ALIAS_MAP.keys(), key=len, reverse=True)
        # \b doesn't anchor on punctuation like # in "C#"; use lookarounds that
        # treat any non-word char OR start/end as the boundary.
        pattern = (
            r"(?<![A-Za-z0-9_])("
            + "|".join(re.escape(a) for a in sorted_aliases)
            + r")(?![A-Za-z0-9_])"
        )
        _CHAMPION_ALIAS_PATTERN = re.compile(pattern, re.IGNORECASE)
    return _CHAMPION_ALIAS_PATTERN


def _extract_skills_from_champion(job: Job) -> list[dict]:
    """Return [{name: canonical}, ...] derived from job narrative text.

    Fallback chain (first hit wins):
      1. `job.champion_profile` — Traffit-style curated profile (highest signal)
      2. `job.requirements` + `job.description` — narrative from JD itself

    Used as implicit must_skills when `job.must_skills` is empty (the case for
    ~88% of prod jobs as of 2026-05-08). Without this fallback the skills
    layer in scoring short-circuits to max points → all candidates score the
    same → matching is decided purely by semantic + metadata signals.

    Pattern matching uses the seed taxonomy (153 canonical skills + 277
    aliases). Word-boundary regex avoids false hits like "java" in "javascript".
    """
    pattern = _alias_pattern()
    if pattern is None:
        return []

    parts: list[str] = []

    # Tier 1: Champion Profile narrative (when populated by recruiter).
    champion = getattr(job, "champion_profile", None)
    if isinstance(champion, dict) and champion:
        ctx = champion.get("project_context") or {}
        if isinstance(ctx, dict):
            for k in ("about", "responsibilities", "selling_points"):
                v = ctx.get(k)
                if isinstance(v, str):
                    parts.append(v)
        questions = champion.get("screening_questions") or []
        if isinstance(questions, list):
            for q in questions:
                if isinstance(q, dict):
                    for k in ("question", "ideal_answer", "deal_breaker"):
                        v = q.get(k)
                        if isinstance(v, str):
                            parts.append(v)
        sourcing = champion.get("sourcing") or {}
        if isinstance(sourcing, dict):
            for k in ("keywords", "target_companies", "notes"):
                v = sourcing.get(k)
                if isinstance(v, str):
                    parts.append(v)
        for k in ("historical_client_questions", "internal_consultant_insight"):
            v = champion.get(k)
            if isinstance(v, str):
                parts.append(v)

    # Tier 2: JD text (when Champion not yet populated — current prod state).
    if not parts:
        for attr in ("requirements", "description"):
            v = getattr(job, attr, None)
            if isinstance(v, str) and v.strip():
                # Cap each field at 4K chars — long JDs (8K+) drag regex time
                # and add little signal beyond the headline requirements.
                parts.append(v[:4000])

    # Tier 3: title only (Traffit imports often have empty desc/req but the
    # title carries the role + tech: "Senior Angular Developer", "PKO BP:
    # Programista Java"). Always added as a low-cost extra signal so even
    # well-described jobs get title-extracted skills folded in.
    title = getattr(job, "title", None)
    if isinstance(title, str) and title.strip():
        parts.append(title)

    text = " ".join(parts)
    if not text.strip():
        return []

    found_canonicals: set[str] = set()
    for match in pattern.finditer(text):
        alias = match.group(1).lower()
        canonical = ALIAS_MAP.get(alias)
        if canonical:
            found_canonicals.add(canonical)

    return [{"name": c} for c in sorted(found_canonicals)]


def canonical_skill_names(raw) -> List[str]:
    """
    Return skill names normalized through the alias map, order-preserving,
    deduplicated. When `ALIAS_MAP` is empty, behaves exactly like `_skill_names`.
    """
    names = _skill_names(raw)
    if not ALIAS_MAP:
        return names
    seen: set[str] = set()
    out: List[str] = []
    for n in names:
        canonical = ALIAS_MAP.get(n, n)
        if canonical in seen:
            continue
        seen.add(canonical)
        out.append(canonical)
    return out


def _skill_names(raw) -> List[str]:
    """Extract lowercase skill names from JSONB.

    Accepted shapes (seed data in the wild mixes them):
      - list[str]                                        -> ["Python", "Go"]
      - list[dict]                                       -> [{"name": "Python"}, ...]
      - dict with "name" key                             -> {"name": "Python"}
      - dict with a list-valued key in _DICT_SKILL_LIST_KEYS
                                                          -> {"technologies": [...]}
      - str: JSON-encoded array/object ('["Java","Go"]') OR a free-form
             comma list ("Java, Go") -> Traffit/TalentRadar imports store
             skills this way; without decoding it the layer saw zero skills.
    Anything else yields [] (silent ignore, matches prior behavior for unknown types).
    """
    out: List[str] = []
    if not raw:
        return out
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                name = item.get("name")
                if name:
                    out.append(str(name).lower().strip())
            elif isinstance(item, str):
                out.append(item.lower().strip())
    elif isinstance(raw, dict):
        name = raw.get("name")
        if isinstance(name, str) and name.strip():
            out.append(name.lower().strip())
        for key in _DICT_SKILL_LIST_KEYS:
            value = raw.get(key)
            if isinstance(value, list):
                out.extend(_skill_names(value))
    elif isinstance(raw, str):
        stripped = raw.strip()
        if stripped.startswith("[") or stripped.startswith("{"):
            # JSON-encoded string ('["Java","Spring"]') — decode before split,
            # otherwise a comma split yields broken tokens like ``["java``.
            try:
                parsed = json.loads(stripped)
            except (ValueError, TypeError):
                parsed = None
            if isinstance(parsed, (list, dict)):
                return _skill_names(parsed)
        out.extend(_split_skill_tokens(stripped))
    return [s for s in out if s]


# Cap raw-CV regex scan — long CVs (8K+) add little signal beyond the headline
# tech and would drag the cold-path fallback on the marketplace pool scan.
_RAW_CV_SKILL_SCAN_CAP = 4000


def _skills_from_cv_extracted(candidate) -> List[str]:
    """Skills pulled from ``cv_extracted_data`` for imported candidates.

    Traffit imports drop the candidate's technology list into
    ``cv_extracted_data.traffit_technologie`` (a flat comma string), and the
    structured ``skills`` column is left empty for ~99% of the pool. TalentRadar
    imports may instead nest a list under ``skills``. Read both shapes.
    """
    data = getattr(candidate, "cv_extracted_data", None)
    if not isinstance(data, dict):
        return []
    tech = data.get("traffit_technologie")
    if isinstance(tech, str) and tech.strip():
        return _split_skill_tokens(tech)
    nested = data.get("skills")
    if nested:
        return _skill_names(nested)
    return []


def _skills_from_raw_cv(candidate) -> List[str]:
    """Last-resort: extract canonical skills from raw CV text via the alias
    pattern (same mechanism as ``_extract_skills_from_champion`` for jobs).

    Only fires when no structured/extracted skills exist (~12.7K candidates on
    prod) and only when the skill taxonomy is loaded (``ALIAS_MAP`` populated).
    """
    pattern = _alias_pattern()
    if pattern is None:
        return []
    raw = getattr(candidate, "raw_cv_text", None)
    if not isinstance(raw, str) or not raw.strip():
        return []
    found: set[str] = set()
    for match in pattern.finditer(raw[:_RAW_CV_SKILL_SCAN_CAP]):
        canonical = ALIAS_MAP.get(match.group(1).lower())
        if canonical:
            found.add(canonical)
    return sorted(found)


def candidate_skill_names(candidate) -> set[str]:
    """Canonical skill set for a candidate, with Traffit-aware fallbacks.

    On prod ~99% of imported candidates have an EMPTY structured ``skills``
    field — their tech lives in ``cv_extracted_data.traffit_technologie`` or only
    in ``raw_cv_text``. Without these fallbacks the skills layer scored 0 for
    nearly everyone, so every required skill rendered as a red ✗ gap and the
    composite score was artificially depressed (the "Targ ocenia za surowo" bug).

    Priority (first non-empty wins): structured ``skills`` + ``verified_tech``
    → CV-extracted tech → raw CV text → tags. Fallbacks only ADD candidate
    skills, so they can turn false gaps into matches but never invent a gap.
    """
    cand = set(
        canonical_skill_names(candidate.skills)
        + canonical_skill_names(getattr(candidate, "verified_tech", None))
    )
    if not cand:
        cand = set(canonical_skill_names(_skills_from_cv_extracted(candidate)))
    if not cand:
        cand = set(canonical_skill_names(_skills_from_raw_cv(candidate)))
    if not cand and candidate.tags:
        cand = set(canonical_skill_names(candidate.tags))
    return cand


def _score_skills(
    candidate: Candidate, job: Job, profile: WeightProfile = DEFAULT_PROFILE
) -> tuple[LayerResult, List[str], List[str], List[str], List[str]]:
    """Return (LayerResult, matching_must, gap_must, matching_nice, gap_nice)."""
    must = canonical_skill_names(job.must_skills)
    nice = canonical_skill_names(job.nice_skills)

    # Champion-driven fallback: when `must_skills` is empty (the case for ~88%
    # of prod jobs as of 2026-05-08 baseline), derive implicit must skills
    # from the Champion Profile narrative or — failing that — the JD text
    # itself (description + requirements). Eliminates the "skills layer
    # short-circuits to max" pattern that flattened candidate ranking on
    # imported jobs. See `_extract_skills_from_champion` for source priority.
    must_source = "structured"
    if not must:
        derived = _extract_skills_from_champion(job)
        if derived:
            must = canonical_skill_names(derived)
            must_source = (
                "champion"
                if isinstance(getattr(job, "champion_profile", None), dict)
                and (job.champion_profile or {})
                else "jd_text"
            )

    # Candidate skills with Traffit-aware fallbacks (structured → CV-extracted
    # → raw CV → tags). ~99% of imported candidates have an empty `skills`
    # column; without the fallbacks every required skill showed as a gap.
    cand_skills = candidate_skill_names(candidate)

    must_match = [s for s in must if s in cand_skills]
    must_gap = [s for s in must if s not in cand_skills]
    nice_match = [s for s in nice if s in cand_skills]
    nice_gap = [s for s in nice if s not in cand_skills]

    must_max = profile.skills_must
    nice_max = profile.skills_nice
    must_pts = (len(must_match) / len(must) * must_max) if must else must_max
    nice_pts = (len(nice_match) / len(nice) * nice_max) if nice else 0.0

    total = must_pts + nice_pts
    reason_bits = []
    if must:
        suffix = ""
        if must_source == "champion":
            suffix = " (z Championa)"
        elif must_source == "jd_text":
            suffix = " (z opisu)"
        reason_bits.append(f"must {len(must_match)}/{len(must)}{suffix}")
    else:
        reason_bits.append("must n/a")
    if nice:
        reason_bits.append(f"nice {len(nice_match)}/{len(nice)}")

    return (
        LayerResult(
            points=total, max_points=profile.skills, reason=", ".join(reason_bits)
        ),
        must_match,
        must_gap,
        nice_match,
        nice_gap,
    )


def _score_salary(
    candidate: Candidate, job: Job, profile: WeightProfile = DEFAULT_PROFILE
) -> LayerResult:
    """Salary fit — full points in range, linear decay outside. 0 if missing data."""
    max_pts = profile.salary
    cand_rate = candidate.salary_expectation
    job_min = job.salary_min
    job_max = job.salary_max

    # Prefer structured preferences.rate_min/rate_max if available
    prefs = getattr(candidate, "preferences", None) or {}
    if isinstance(prefs, dict):
        cand_rate = prefs.get("rate_min") or cand_rate or prefs.get("rate_max")

    if not cand_rate or (not job_min and not job_max):
        # No data to judge salary fit → neutral (benefit of the doubt), matching
        # the availability/champion_fit convention. Hard-zeroing here was a main
        # driver of deflated composites: ~99% of imported candidates have no
        # stated rate. A *known* mismatch still decays below this neutral value
        # via the out-of-range branch below. UNKNOWN_NEUTRAL_FRACTION=0.0 restores
        # the legacy 0.
        return LayerResult(
            points=max_pts * UNKNOWN_NEUTRAL_FRACTION,
            max_points=max_pts,
            reason="brak danych (neutralnie)",
        )

    # Inside range → full points
    if (job_min is None or cand_rate >= job_min) and (
        job_max is None or cand_rate <= job_max
    ):
        return LayerResult(points=max_pts, max_points=max_pts, reason="w widełkach")

    # Outside: linear decay within ±30% of nearest bound
    if job_max and cand_rate > job_max:
        over = cand_rate - job_max
        decay = max(0.0, 1.0 - (over / (job_max * 0.3)))
        pts = max_pts * decay
        return LayerResult(
            points=pts, max_points=max_pts, reason=f"powyżej widełek o {over} PLN"
        )
    if job_min and cand_rate < job_min:
        under = job_min - cand_rate
        decay = max(0.0, 1.0 - (under / (job_min * 0.3)))
        pts = max_pts * decay
        return LayerResult(
            points=pts, max_points=max_pts, reason=f"poniżej widełek o {under} PLN"
        )

    return LayerResult(points=0.0, max_points=max_pts, reason="poza widełkami")


def _score_location(
    candidate: Candidate, job: Job, profile: WeightProfile = DEFAULT_PROFILE
) -> LayerResult:
    """Remote/location fit. Budget split 50/50 between remote compat + city match.

    The city half parses BOTH sides through ``location_tokens`` so the
    structured JSON blob ~99% of imported candidates store in ``location``
    (``{"locality":"Warszawa",...}``) is compared on place tokens, not by
    raw-string substring (which practically never matched a blob).

    "No signal" handling (2026-06-30) — both halves now follow the same
    benefit-of-the-doubt convention as salary/availability/champion_fit: when
    there is genuinely nothing to judge, award the neutral fraction instead of a
    hard 0. Concretely:

      remote half  full      remote policy known AND candidate mode matches
                   0         known MISMATCH (candidate stated modes, job's not among them)
                   neutral   no signal (job has no remote policy OR candidate stated none)
      city  half   full      job + candidate share a place token
                   0         known DIFFERENT city (both sides have tokens, no overlap)
                   neutral   can't judge (job has a location but candidate's is unknown,
                             OR — new — the job carries no location at all)

    Previously the no-job-location case hard-zeroed the city half (a deliberate
    "don't inflate the dominant cohort by a constant" choice). ~99.6% of
    imported jobs carry no location and ~99% of imported candidates state no
    remote preference, so that left this whole 8-pt layer dead — a top match on
    a Traffit job capped at ~55. Since the lift is a per-job constant for the
    dominant "all-unknown" cohort it leaves ranking — and every rank-based eval
    metric — unchanged. ``UNKNOWN_NEUTRAL_FRACTION = 0`` reproduces the legacy
    hard-zero exactly (the offline escape hatch).
    """
    max_pts = profile.location
    points = 0.0
    reason_bits: List[str] = []

    # Split budget 50/50 between remote policy and city match.
    half = max_pts / 2.0

    # ── Remote-policy half ────────────────────────────────────────────────────
    prefs = getattr(candidate, "preferences", None) or {}
    remote_modes = prefs.get("remote_modes") if isinstance(prefs, dict) else None
    job_remote = job.remote_policy.value if job.remote_policy else None
    if job_remote and remote_modes:
        # Both sides known → judge the fit.
        if job_remote in remote_modes:
            points += half
            reason_bits.append(f"remote {job_remote} OK")
        # else: known mismatch (candidate doesn't accept the job's mode) → 0.
    else:
        # No signal: the job states no remote policy, or the candidate stated no
        # preference (~99% of the imported pool). Can't judge → neutral.
        points += half * UNKNOWN_NEUTRAL_FRACTION
        reason_bits.append("remote nieznany")

    # ── City half ─────────────────────────────────────────────────────────────
    job_tokens = location_tokens(job.location)
    cand_tokens = location_tokens(candidate.location)
    if job_tokens:
        if tokens_overlap(cand_tokens, job_tokens):
            points += half
            reason_bits.append("lokalizacja OK")
        elif not cand_tokens:
            # Job specifies a place, candidate's is unknown → can't judge a
            # mismatch → neutral. A real different-city candidate (cand_tokens
            # present, no overlap) still earns 0.
            points += half * UNKNOWN_NEUTRAL_FRACTION
            reason_bits.append("lokalizacja nieznana")
    else:
        # Job carries no location (~99.6% of imported jobs) → can't judge city
        # fit → neutral, consistent with the remote half and the
        # salary/availability convention. (Was a hard 0 before 2026-06-30.)
        points += half * UNKNOWN_NEUTRAL_FRACTION
        reason_bits.append("lokalizacja nieznana")

    return LayerResult(
        points=min(points, max_pts),
        max_points=max_pts,
        reason=", ".join(reason_bits) or "brak dopasowania",
    )


def _score_availability(
    candidate: Candidate, job: Job, profile: WeightProfile = DEFAULT_PROFILE
) -> LayerResult:
    """Availability fit. Full points before deadline, decay 30 days post."""
    max_pts = profile.availability
    if not candidate.availability_date:
        # No signal → benefit-of-the-doubt neutral (same knob as
        # salary/location/champion_fit). Was a hardcoded 0.5 before 2026-06-30.
        return LayerResult(
            points=max_pts * UNKNOWN_NEUTRAL_FRACTION,
            max_points=max_pts,
            reason="brak daty",
        )
    if not job.deadline:
        return LayerResult(points=max_pts, max_points=max_pts, reason="brak deadline")

    delta_days = (candidate.availability_date - job.deadline).days
    if delta_days <= 0:
        return LayerResult(points=max_pts, max_points=max_pts, reason="na czas")

    decay = max(0.0, 1.0 - delta_days / 30.0)
    return LayerResult(
        points=max_pts * decay,
        max_points=max_pts,
        reason=f"spóźnienie {delta_days} dni",
    )


async def _score_champion_fit(
    candidate: Candidate,
    job: Job,
    db: AsyncSession,
    profile: "WeightProfile" = None,  # type: ignore[assignment]
) -> LayerResult:
    """Read the candidate's latest screening answers (if any) for this job
    and convert its `match_percent` to layer points.

    Semantics:
      - No screening answers yet → neutral half-budget (keeps unscreened
        candidates competitive so they surface in recommendations).
      - deal_breaker_hit on any question → 0 points (effectively blocks the
        candidate from the top of the list).
      - Otherwise `match_percent / 100 * profile.champion_fit`.
    """
    from app.models.recruitment_pipeline import CandidateStage
    from app.schemas.champion import ScreeningAnswers

    if profile is None:
        profile = DEFAULT_PROFILE
    max_pts = profile.champion_fit

    # Most recent stage with screening answers for this (candidate, job)
    stage = await db.scalar(
        select(CandidateStage)
        .where(
            CandidateStage.candidate_id == candidate.id,
            CandidateStage.job_id == job.id,
            CandidateStage.screening_answers.is_not(None),
        )
        .order_by(CandidateStage.moved_at.desc())
        .limit(1)
    )
    if stage is None or not stage.screening_answers:
        # No screening yet → neutral (same knob as salary/location/availability)
        # so unscreened candidates stay competitive. Was hardcoded 0.5.
        return LayerResult(
            points=max_pts * UNKNOWN_NEUTRAL_FRACTION,
            max_points=max_pts,
            reason="brak screeningu",
        )
    try:
        answers = ScreeningAnswers.model_validate(stage.screening_answers)
    except Exception:
        return LayerResult(
            points=max_pts * UNKNOWN_NEUTRAL_FRACTION,
            max_points=max_pts,
            reason="screening niepoprawny",
        )

    pct = answers.match_percent()
    pts = pct / 100.0 * max_pts
    if pct == 0.0 and any(a.deal_breaker_hit for a in answers.answers):
        return LayerResult(points=0.0, max_points=max_pts, reason="deal-breaker")
    return LayerResult(
        points=pts,
        max_points=max_pts,
        reason=f"{answers.overall_fit} · {pct:.0f}%",
    )


async def _check_penalties(
    candidate: Candidate, job: Job, db: AsyncSession
) -> List[str]:
    penalties: List[str] = []

    if candidate.status == CandidateStatus.blacklisted:
        penalties.append("blacklist")

    # Preferences.excluded_clients
    prefs = getattr(candidate, "preferences", None) or {}
    if isinstance(prefs, dict):
        excluded = prefs.get("excluded_clients") or []
        if job.client_id and job.client_id in excluded:
            penalties.append("client_excluded")

    # Active conflict for this (candidate, client)
    if job.client_id:
        active_conflict = await db.scalar(
            select(CandidateConflict.id).where(
                CandidateConflict.candidate_id == candidate.id,
                CandidateConflict.client_id == job.client_id,
                CandidateConflict.active.is_(True),
            )
        )
        if active_conflict:
            penalties.append("active_conflict")

    return penalties


# ── Public API ──────────────────────────────────────────────────────────────


def score_semantic(
    semantic_similarity: Optional[float], profile: WeightProfile = DEFAULT_PROFILE
) -> LayerResult:
    """Convert Qdrant cosine similarity (0-1) → profile.semantic points.

    The raw cosine is passed through a power curve (``sim ** gamma``, where
    gamma = ``SEMANTIC_CALIBRATION_GAMMA``) before scaling. With the default
    gamma < 1 this lifts the mid-range similarities where genuinely-relevant
    candidates cluster (~0.4-0.65 on voyage-3-large) without saturating the top:
    the curve is strictly increasing, so per-candidate semantic ordering — and
    therefore ranking — is preserved exactly. gamma = 1.0 reproduces the legacy
    linear mapping. ``None`` (no embedding) still scores 0.
    """
    max_pts = profile.semantic
    if semantic_similarity is None:
        return LayerResult(points=0.0, max_points=max_pts, reason="brak embeddingu")
    sim = max(0.0, min(1.0, float(semantic_similarity)))
    gamma = SEMANTIC_CALIBRATION_GAMMA
    calibrated = sim**gamma if gamma and gamma > 0 else sim
    return LayerResult(
        points=calibrated * max_pts, max_points=max_pts, reason=f"sim {sim:.2f}"
    )


async def score_candidate_job(
    candidate: Candidate,
    job: Job,
    db: AsyncSession,
    *,
    semantic_similarity: Optional[float] = None,
    profile: WeightProfile = DEFAULT_PROFILE,
) -> ScoreBreakdown:
    """Compute the full ScoreBreakdown for one (candidate, job) pair."""
    import time as _time

    t0 = _time.perf_counter()
    semantic = score_semantic(semantic_similarity, profile)
    skills, must_match, must_gap, nice_match, nice_gap = _score_skills(
        candidate, job, profile
    )
    salary = _score_salary(candidate, job, profile)
    location = _score_location(candidate, job, profile)
    availability = _score_availability(candidate, job, profile)
    champion_fit = await _score_champion_fit(candidate, job, db, profile)
    penalties = await _check_penalties(candidate, job, db)

    if penalties:
        total = 0.0
    else:
        total = (
            semantic.points
            + skills.points
            + salary.points
            + location.points
            + availability.points
            + champion_fit.points
        )

    latency_ms = round((_time.perf_counter() - t0) * 1000.0, 2)
    # Structured event for log aggregation (JSON formatter reshapes extras).
    # DEBUG, nie INFO (2026-07-27): to jest najgorętsza pętla w systemie —
    # jedno wejście na listę kandydatów z kolumną dopasowań emitowało ~1000+
    # linii, zapychając Loki i I/O kontenera. Włącz LOG_LEVEL=DEBUG, gdy
    # naprawdę diagnozujesz scoring.
    logger.debug(
        "score_computed",
        extra={
            "event": "score_computed",
            "candidate_id": candidate.id,
            "job_id": job.id,
            "total_score": round(total, 2),
            "semantic_points": round(semantic.points, 2),
            "skills_points": round(skills.points, 2),
            "salary_points": round(salary.points, 2),
            "location_points": round(location.points, 2),
            "availability_points": round(availability.points, 2),
            "penalties_count": len(penalties),
            "must_matched": len(must_match),
            "must_missing": len(must_gap),
            "latency_ms": latency_ms,
        },
    )

    return ScoreBreakdown(
        candidate_id=candidate.id,
        job_id=job.id,
        total=total,
        semantic=semantic,
        skills=skills,
        salary=salary,
        location=location,
        availability=availability,
        champion_fit=champion_fit,
        matching_must=must_match,
        gap_must=must_gap,
        matching_nice=nice_match,
        gap_nice=nice_gap,
        penalties=penalties,
        fit_confidence=compute_fit_confidence(candidate, job),
    )


async def rank_candidates_for_job(
    job: Job,
    candidates: Sequence[Candidate],
    db: AsyncSession,
    *,
    similarity_map: Optional[dict[int, float]] = None,
    profile: WeightProfile = DEFAULT_PROFILE,
) -> List[ScoreBreakdown]:
    """Convenience: score each candidate and return list sorted by total desc."""
    sims = similarity_map or {}
    results: List[ScoreBreakdown] = []
    for c in candidates:
        sim = sims.get(c.id)
        results.append(
            await score_candidate_job(
                c, job, db, semantic_similarity=sim, profile=profile
            )
        )
    results.sort(key=lambda r: -r.total)
    return results


def summarize_match_stats(
    breakdowns: Sequence[ScoreBreakdown],
    total_open: int,
    *,
    min_score: float = 50.0,
) -> dict:
    """
    Summarize a list of candidate↔job ScoreBreakdowns into badge-ready stats.

    Returned shape matches what the candidates list UI renders on a row:

        {
          "open_count": int,        # breakdowns with total >= min_score
          "total_open": int,        # open jobs considered (from caller)
          "top_score": float,       # highest total (0.0 when no breakdowns)
        }
    """
    if not breakdowns:
        return {"open_count": 0, "total_open": total_open, "top_score": 0.0}
    open_count = sum(1 for b in breakdowns if b.total >= min_score)
    top_score = max(b.total for b in breakdowns)
    return {
        "open_count": open_count,
        "total_open": total_open,
        "top_score": round(top_score, 1),
    }


async def rank_jobs_for_candidate(
    candidate: Candidate,
    jobs: Iterable[Job],
    db: AsyncSession,
    *,
    similarity_map: Optional[dict[int, float]] = None,
    profile: WeightProfile = DEFAULT_PROFILE,
) -> List[ScoreBreakdown]:
    """Reverse direction — score each job for a given candidate."""
    sims = similarity_map or {}
    results: List[ScoreBreakdown] = []
    for j in jobs:
        sim = sims.get(j.id)
        results.append(
            await score_candidate_job(
                candidate, j, db, semantic_similarity=sim, profile=profile
            )
        )
    results.sort(key=lambda r: -r.total)
    return results
