"""
Hybrid candidate-job scoring engine (Phase 2).

Layered scoring — each layer returns points that add up to 100:

  semantic        0-40pt   Qdrant cosine similarity between job query and candidate embedding
  skills          0-30pt   weighted must/nice overlap (must=20pt, nice=10pt)
  salary_fit      0-15pt   comparable financial fit, otherwise non-penalizing
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
from datetime import date, timedelta
from dataclasses import dataclass, field
from typing import Any, Iterable, List, Optional, Sequence

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
# Fallback matches `config.py` (0.65). It read 0.5 here, so any environment
# where the setting was absent scored every unknown-data layer lower than the
# documented default — a silent second calibration nobody chose.
UNKNOWN_NEUTRAL_FRACTION: float = float(
    getattr(settings, "SCORE_UNKNOWN_NEUTRAL_FRACTION", 0.65)
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
# 60/10/15/5/0 (+champion 10) od 18.08.2026 — LTR-lite: pełny simpleks 7315
# wektorów na zrzucie warstw zbioru ROZŁĄCZNEGO (scripts/weight_search),
# nominacja zwalidowana prawdziwym biegiem na zamrożonych 50: P@5 +2%,
# R@20n +4%, MRR +6% vs 45/25/10/8/2. Dostępność 0 spójna z podwójnym NO-GO
# tej warstwy (fallback −24%, konflikt −4% R@20n). Historia: 35/30/12/8/5
# → 45/25/10/8/2 (17.08, siatka 7 profili) → obecne.
SEMANTIC_MAX = 60.0
SKILLS_MAX = 10.0
# Pochodne z SKILLS_MAX (klasyczny podział 2:1), nie osobne literały — przy
# strojeniu wag rozjeżdżały się z budżetem warstwy (zostały 20/10 przy 25).
SKILLS_MUST_MAX = SKILLS_MAX * (2.0 / 3.0)
SKILLS_NICE_MAX = SKILLS_MAX * (1.0 / 3.0)
SALARY_MAX = 15.0
LOCATION_MAX = 5.0
AVAILABILITY_MAX = 0.0
CHAMPION_FIT_MAX = 10.0
# sum = 60 + 10 + 15 + 5 + 0 + 10 = 100


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
# Every input that changes a produced score, listed once and exhaustively.
# Explicit, not `settings.model_dump()`: hashing the whole config would make an
# unrelated setting invalidate the cache on every deploy.
#
# The two calibration knobs used to be missing from here, so `config.py` could
# promise "full rollback without a redeploy: set 1.0 / 0.0" while flipping them
# left every cached score in place — mixing values from two calibrations with
# no way to tell them apart. It was patched twice by hand (migrations 0143 and
# 0150 did a mass invalidation); a third time was only a matter of when.
_SCORING_CACHE_INPUTS: tuple[str, ...] = (
    "CHAMPION_MATCH_SIGNALS_ENABLED",
    "CHAMPION_SENIORITY_PENALTY_ENABLED",
    "CHAMPION_AVAILABILITY_FALLBACK_ENABLED",
    "CHAMPION_AVAILABILITY_CONFLICT_ENABLED",
    # 4a: rozszerzenie taksonomii zmienia derived-must (regex z ALIAS_MAP),
    # a więc warstwę skills każdego composite'u.
    "SKILL_ALIAS_EXTENDED_ENABLED",
    "AI_SCORING_CONTRACT_V2",
    "VOYAGE_MODEL",
    "SEMANTIC_CALIBRATION_GAMMA",
    "SCORE_UNKNOWN_NEUTRAL_FRACTION",
    # Changes the embedding TEXT, hence the similarity, hence the score.
    "AI_TEXT_SCHEMA_V2",
    # Runda 2: v3 zmienia tekst kandydata (pełne CV + notatki), a przełączenie
    # kolekcji zmienia ŹRÓDŁO wektorów — oba przestawiają skalę podobieństwa
    # semantycznego, więc flip musi unieważnić cache (ten sam mechanizm, który
    # ratowały migracje 0143/0150).
    "AI_TEXT_SCHEMA_V3",
    "QDRANT_COLLECTION",
    # Changes how a no-signal layer contributes — i.e. the composite itself.
    "SCORE_RENORMALIZE_UNSCORED_LAYERS",
    # Fala 2: włączenie pasaży CV zmienia skalę podobieństwa semantycznego
    # (unia wektora kandydata z najlepszym pasażem), a więc każdy composite.
    # Bez tego wpisu prod po flipie serwowałby score'y policzone na STAREJ
    # skali, ewaluacja pokazałaby brak efektu, a wnioskiem byłoby „chunkowanie
    # nie działa". Ten mechanizm był już ratowany ręcznie dwa razy (0143, 0150).
    "CV_PASSAGES_ENABLED",
)


def scoring_algorithm_version() -> str:
    """Cache key for a produced score: readable prefix + digest of the inputs.

    A function, not a constant, because the calibration knobs are module
    globals that tests and offline tooling monkeypatch at call time — a value
    frozen at import would disagree with the score actually being computed.

    Weight-profile edits are deliberately NOT folded in: those are handled by
    `mark_stale_for_profile`, which invalidates only the affected rows instead
    of the whole table.
    """
    import hashlib
    import json

    payload = {
        key: (
            UNKNOWN_NEUTRAL_FRACTION
            if key == "SCORE_UNKNOWN_NEUTRAL_FRACTION"
            else SEMANTIC_CALIBRATION_GAMMA
            if key == "SEMANTIC_CALIBRATION_GAMMA"
            else getattr(settings, key, None)
        )
        for key in _SCORING_CACHE_INPUTS
    }
    # Wbudowane wagi DEFAULT wchodzą do digestu: zmiana stałych w kodzie
    # (np. strojenie 4b 35/30/12/8/5 -> 45/25/10/8/2) zmienia score'y pod tym
    # samym profile_id=0, więc bez tego wpisu stary cache mieszałby dwie skale.
    # Edycje profili z BAZY zostają poza digestem — je unieważnia punktowo
    # `mark_stale_for_profile` (patrz docstring wyżej).
    payload["default_weights"] = [
        SEMANTIC_MAX,
        SKILLS_MAX,
        SALARY_MAX,
        LOCATION_MAX,
        AVAILABILITY_MAX,
        CHAMPION_FIT_MAX,
    ]
    # Round the floats: a 1e-16 difference in how a value was parsed must not
    # invalidate a hundred thousand cached scores.
    for k, v in payload.items():
        if isinstance(v, float):
            payload[k] = round(v, 4)
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[
        :12
    ]

    base = (
        "score-v2-budget100"
        if getattr(settings, "AI_SCORING_CONTRACT_V2", False)
        else "score-v1-legacy"
    )
    return f"{base}+emb-{getattr(settings, 'VOYAGE_MODEL', 'unknown')}+{digest}"


# NO module-level `SCORING_ALGORITHM_VERSION` constant on purpose. Freezing the
# version at import time is the exact bug this function exists to kill: a knob
# patched after import (tests, a runtime override) would leave the constant
# stale, so cached rows computed under the new weights would keep the old
# version string and never be invalidated. Call `scoring_algorithm_version()`.
# Column is VARCHAR(64) — this shape is ~45 chars.


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
    status: Optional[str] = None
    # False when the layer had nothing to judge — no `nice_skills` on the job, no
    # rate to compare, no screening answers. Such a layer is dropped from the
    # budget and the composite renormalised, instead of handing every candidate
    # the same constant. A constant cannot rank anyone; it only shifts the floor.
    scored: bool = True


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
    # v1.1: powód mnożnikowej kary seniority — kara 16-32% bez śladu w
    # breakdownie byłaby niediagnozowalna ("68 po karze" vs "68 bez kary").
    seniority_note: Optional[str] = None
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
                "status": self.salary.status or "scored",
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
    # Brak listy = brak sygnału, po OBU stronach tak samo. Stara reguła robiła
    # to w przeciwne strony: pusta `must` dawała pełne punkty, pusta `nice` —
    # zero. Zmierzone na prodzie: 90% ofert nie ma `nice_skills`, 13% nie ma
    # `must_skills`, więc obie gałęzie trafiały w większość korpusu i żadna
    # nikogo nie różnicowała.
    if must:
        must_pts = len(must_match) / len(must) * must_max
    else:
        # Legacy handed out the full must budget here — a free 20 points on the
        # 13% of jobs with no must_skills. Under renormalisation the half simply
        # leaves the budget instead.
        must_pts = 0.0 if _renormalizing() else must_max
    nice_pts = (len(nice_match) / len(nice) * nice_max) if nice else 0.0
    scored_max = (must_max if must else 0.0) + (nice_max if nice else 0.0)

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
            points=total
            if scored_max > 0
            else (0.0 if _renormalizing() else profile.skills_must),
            max_points=scored_max if scored_max > 0 else profile.skills,
            reason=", ".join(reason_bits),
            status=None if scored_max > 0 else "unknown",
            scored=scored_max > 0,
        ),
        must_match,
        must_gap,
        nice_match,
        nice_gap,
    )


def _champion_signals_enabled() -> bool:
    return bool(getattr(settings, "CHAMPION_MATCH_SIGNALS_ENABLED", False))


def _champion_dict(job: Job) -> dict:
    champion = getattr(job, "champion_profile", None)
    return champion if isinstance(champion, dict) else {}


def _champion_hourly_rate(job: Job) -> Optional[float]:
    """Stawka Championa w PLN/h — jedyna porównywalna z profilem kandydata.

    `rate_value` pochodzi z parsera profili (import 2026-08-14) i z definicji
    dokumentu jest stawką DLA KANDYDATA w PLN/h. To odblokowuje warstwę
    finansową: legacy `Job.salary_min/max` jest w PLN/mies. i z kandydackim
    PLN/h porównywalne nie będzie nigdy (patrz docstring `_score_salary`).
    """

    if not _champion_signals_enabled():
        return None
    value = _champion_dict(job).get("rate_value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if 0 < float(value) < 2000 else None


def get_champion_hourly_rate(job: Job) -> Optional[float]:
    """Publiczny alias `_champion_hourly_rate` dla konsumentów spoza modułu.

    `dealbreaker_filters` potrzebuje tej samej stawki co warstwa salary; import
    prywatnej nazwy pękłby cicho przy refaktorze (ImportError w łańcuchu filtra,
    nie przy starcie). Ten alias jest kontraktem publicznym.
    """
    return _champion_hourly_rate(job)


def _notes_insights(candidate: Candidate) -> dict:
    extracted = getattr(candidate, "cv_extracted_data", None)
    if not isinstance(extracted, dict):
        return {}
    insights = extracted.get("_notes_insights")
    return insights if isinstance(insights, dict) else {}


# Tryb pracy z dokumentu Championa → słownik remote_policy używany przez
# warstwę lokalizacji po stronie kandydata (preferences.remote_modes).
_CHAMPION_WORK_MODE_TO_REMOTE = {
    "zdalnie": "remote",
    "hybrydowo": "hybrid",
    "stacjonarnie": "onsite",
}


def _score_salary(
    candidate: Candidate, job: Job, profile: WeightProfile = DEFAULT_PROFILE
) -> LayerResult:
    """Financial fit without mixing the retired monthly candidate salary.

    The global candidate fact is always B2B PLN net/hour, while the legacy
    ``Job.salary_min/max`` budget is PLN/month. There is no automatic
    conversion policy for this profile fact. A known cross-unit pair is
    therefore explicitly ``not_comparable`` and scored NEUTRALLY (the same
    fraction as missing data) — it must neither penalise nor over-credit the
    composite. P0-A: previously it returned full points, so an unverifiable
    salary silently inflated the total by the whole salary budget.
    """
    max_pts = profile.salary
    cand_rate = getattr(candidate, "expected_rate_hourly", None)
    cand_currency = getattr(candidate, "expected_rate_currency", None)
    job_min = job.salary_min
    job_max = job.salary_max

    from app.services.candidate_profile_rate import (
        is_canonical_profile_rate_currency,
    )

    if cand_rate is not None and not is_canonical_profile_rate_currency(cand_currency):
        return _unscored(
            max_pts,
            "not_comparable: historyczna stawka ma niekanoniczną walutę "
            "i wymaga ręcznej korekty",
            "not_comparable",
        )

    champion_rate = _champion_hourly_rate(job)
    if champion_rate is not None and cand_rate is not None:
        # Jedyna para w tej samej jednostce (PLN/h vs PLN/h): stawka Championa
        # to budżet klienta NA KANDYDATA. Oczekiwania w budżecie = pełne
        # punkty; przekroczenie degraduje liniowo do zera przy +30%.
        cand = float(cand_rate)
        if cand <= champion_rate:
            return LayerResult(
                points=max_pts,
                max_points=max_pts,
                reason=f"w budżecie Championa ({cand:.0f} ≤ {champion_rate:.0f} PLN/h)",
            )
        overshoot = (cand - champion_rate) / champion_rate
        factor = max(0.0, 1.0 - overshoot / 0.30)
        return LayerResult(
            points=max_pts * factor,
            max_points=max_pts,
            reason=(
                f"ponad budżet Championa o {overshoot:.0%} "
                f"({cand:.0f} > {champion_rate:.0f} PLN/h)"
            ),
        )

    if cand_rate is None or (job_min is None and job_max is None):
        return _unscored(max_pts, "brak danych")

    return _unscored(
        max_pts,
        "not_comparable: kandydat PLN netto/h, budżet joba PLN/mies.",
        "not_comparable",
    )


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
    if _champion_signals_enabled():
        # Strona ofertowa: tryb pracy z dokumentu Championa, gdy oferta sama
        # nie deklaruje polityki (typowe dla importów). Strona kandydacka:
        # `remote_only` z faktów notatkowych, gdy brak jawnych preferencji —
        # rekruter zapisał twardy warunek, którego nie wolno zgubić.
        if not job_remote:
            champion_mode = _champion_dict(job).get("work_mode")
            job_remote = _CHAMPION_WORK_MODE_TO_REMOTE.get(champion_mode)
        if not remote_modes:
            pref = _notes_insights(candidate).get("preferences")
            # isinstance, nie .get w łańcuchu: dane kształtuje AI i "preferences"
            # bywa stringiem — łańcuch .get rzucałby AttributeError (500 w scoringu).
            if isinstance(pref, dict) and pref.get("remote_only") is True:
                remote_modes = ["remote"]
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
    job_location = job.location
    if _champion_signals_enabled() and not job_location:
        champion = _champion_dict(job)
        basics = champion.get("basics") or {}
        job_location = basics.get("candidate_location_pref") or champion.get("location")
    job_tokens = location_tokens(job_location)
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


def _seniority_penalty_enabled() -> bool:
    return bool(getattr(settings, "CHAMPION_SENIORITY_PENALTY_ENABLED", False))


def _availability_conflict_enabled() -> bool:
    return bool(getattr(settings, "CHAMPION_AVAILABILITY_CONFLICT_ENABLED", False))


def _availability_fallback_enabled() -> bool:
    return bool(getattr(settings, "CHAMPION_AVAILABILITY_FALLBACK_ENABLED", False))


# Kara mnożnikowa, nie punktowa: kompozyt ma dwa tryby (suma i renormalizacja
# do 100), w których stała liczba punktów znaczyłaby co innego. Mnożnik działa
# w obu identycznie. Tolerancja 1 roku, bo lata z CV są szacunkiem (±1 to szum,
# nie sygnał); cap -32%%, bo sam dokument Championa ostrzega przed nadmiernym
# filtrowaniem ("nie zawężamy do X" — sekcja uwag Delivery Leada).
_SENIORITY_TOLERANCE_YEARS = 1
_SENIORITY_PENALTY_PER_YEAR = 0.08
_SENIORITY_PENALTY_CAP = 0.32

# Dostępność v2: kara wyłącznie za TWARDĄ kolizję jawnych dat (kolumna albo
# explicit available_from z notatek) ze startem Championa. Zero decay i zero
# oceniania dat WYPROWADZANYCH z wypowiedzenia — to była przyczyna NO-GO
# fallbacku (R@20n −24%): karał kandydatów bogatych w dane względem tych bez
# żadnego sygnału. Grace 30 dni, bo starty projektów się przesuwają.
_AVAILABILITY_CONFLICT_GRACE_DAYS = 30
_AVAILABILITY_CONFLICT_PENALTY = 0.10


def _champion_seniority_factor(
    candidate: Candidate, job: Job
) -> tuple[float, Optional[str]]:
    """(mnożnik totalu, powód) — 1.0/None gdy nie ma czego oceniać."""

    if not _seniority_penalty_enabled():
        return 1.0, None
    required = _champion_dict(job).get("seniority_min_years")
    if isinstance(required, bool) or not isinstance(required, (int, float)):
        return 1.0, None
    years = getattr(candidate, "years_it_experience", None)
    if years is None or not isinstance(years, (int, float)) or isinstance(years, bool):
        return 1.0, None
    deficit = float(required) - float(years)
    if deficit <= _SENIORITY_TOLERANCE_YEARS:
        return 1.0, None
    penalty = min(
        (deficit - _SENIORITY_TOLERANCE_YEARS) * _SENIORITY_PENALTY_PER_YEAR,
        _SENIORITY_PENALTY_CAP,
    )
    return 1.0 - penalty, (
        f"seniority: {years:.0f} lat vs wymagane {required:.0f}+ (kara {penalty:.0%})"
    )


_DATE_PATTERNS = (
    re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})"),  # 2026-09-01
    re.compile(r"(\d{1,2})[./](\d{1,2})[./](\d{4})"),  # 1.09.2026
)
_ASAP = re.compile(r"asap|od zaraz|natychmiast|od ręki|immediately", re.I)
_NOTICE = re.compile(
    r"(\d+)\s*(tydz|tyg|week|mies|miesiąc|miesiec|month|dni|dzień|dzien|day|mc)",
    re.I,
)


def _parse_champion_date(
    raw: object, *, today: Optional[date] = None
) -> Optional[date]:
    """Data startu z dokumentu Championa — formaty PL, ASAP = dziś."""

    if not isinstance(raw, str) or not raw.strip():
        return None
    text_value = raw.strip()
    if _ASAP.search(text_value):
        return today or date.today()
    m = _DATE_PATTERNS[0].search(text_value)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = _DATE_PATTERNS[1].search(text_value)
        if not m:
            return None
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def _notes_explicit_available_date(
    candidate: Candidate, *, today: Optional[date] = None
) -> Optional[date]:
    """WYŁĄCZNIE jawna data z notatek (available_from) — bez wyprowadzania
    z wypowiedzenia. Osobny helper od `_notes_available_date`, bo kara za
    kolizję (v2) nie może dziedziczyć derywacji, która pogrzebała fallback."""

    availability = _notes_insights(candidate).get("availability")
    if not isinstance(availability, dict):
        return None
    return _parse_champion_date(availability.get("available_from"), today=today)


def _champion_availability_conflict_factor(
    candidate: Candidate, job: Job, *, today: Optional[date] = None
) -> tuple[float, Optional[str]]:
    """(mnożnik totalu, powód) — kara wyłącznie za twardą kolizję jawnych dat.

    Wymaga OBU stron jawnie: start z dokumentu Championa ORAZ data dostępności
    kandydata z kolumny albo explicit z notatek. Brak którejkolwiek = 1.0
    (warstwa dostępności zachowuje się jak dotąd). Kolizja = dostępny później
    niż start + grace; pojedyncza stała kara, bez krzywej decay.
    """

    if not _availability_conflict_enabled():
        return 1.0, None
    start = _parse_champion_date(_champion_dict(job).get("start_date"), today=today)
    if start is None:
        return 1.0, None
    available = getattr(candidate, "availability_date", None)
    if available is None:
        available = _notes_explicit_available_date(candidate, today=today)
    if available is None:
        return 1.0, None
    late_days = (available - start).days
    if late_days <= _AVAILABILITY_CONFLICT_GRACE_DAYS:
        return 1.0, None
    return 1.0 - _AVAILABILITY_CONFLICT_PENALTY, (
        f"dostępność: {available.isoformat()} vs start {start.isoformat()} "
        f"(+{late_days} dni, kara {_AVAILABILITY_CONFLICT_PENALTY:.0%})"
    )


def _notes_available_date(
    candidate: Candidate, *, today: Optional[date] = None
) -> Optional[date]:
    """Dostępność z faktów notatkowych: jawna data > dziś+wypowiedzenie."""

    availability = _notes_insights(candidate).get("availability")
    if not isinstance(availability, dict):
        return None
    base = today or date.today()
    explicit = _parse_champion_date(availability.get("available_from"), today=base)
    if explicit:
        return explicit
    for raw in (availability.get("notice_period"), availability.get("raw")):
        if not isinstance(raw, str):
            continue
        if _ASAP.search(raw):
            return base
        m = _NOTICE.search(raw)
        if m:
            n, unit = int(m.group(1)), m.group(2).lower()
            if unit.startswith(("tydz", "tyg", "week")):
                days = n * 7
            elif unit.startswith(("mies", "month", "mc")):
                days = n * 30
            else:
                days = n
            return base + timedelta(days=days)
    return None


def _score_availability(
    candidate: Candidate,
    job: Job,
    profile: WeightProfile = DEFAULT_PROFILE,
    *,
    today: Optional[date] = None,
) -> LayerResult:
    """Availability fit. Full points before deadline, decay 30 days post."""
    max_pts = profile.availability
    availability_date = candidate.availability_date
    reference_deadline = job.deadline
    source_note = ""
    if _availability_fallback_enabled():
        # v1.1: 99% importowanych kandydatów nie ma availability_date, ale
        # 13,9k ma fakty notatkowe ("2 tygodnie wypowiedzenia", "od zaraz"),
        # a oferty z Championem mają datę startu. Fallback po OBU stronach —
        # kolumna i deadline nadal wygrywają, gdy istnieją.
        if not availability_date:
            derived = _notes_available_date(candidate, today=today)
            if derived:
                availability_date = derived
                source_note = " (z notatek)"
        if not reference_deadline:
            champion_start = _parse_champion_date(
                _champion_dict(job).get("start_date"), today=today
            )
            if champion_start:
                reference_deadline = champion_start
                source_note += " (start Championa)"
    if not availability_date:
        # No signal → out of the budget, like every other layer that has
        # nothing to judge. Awarding a neutral share here ranked nobody: ~99%
        # of imported candidates have no availability date, so the constant
        # landed on almost the whole corpus.
        return _unscored(max_pts, "brak daty")
    if not reference_deadline:
        return LayerResult(points=max_pts, max_points=max_pts, reason="brak deadline")

    delta_days = (availability_date - reference_deadline).days
    if delta_days <= 0:
        return LayerResult(
            points=max_pts, max_points=max_pts, reason="na czas" + source_note
        )

    decay = max(0.0, 1.0 - delta_days / 30.0)
    return LayerResult(
        points=max_pts * decay,
        max_points=max_pts,
        reason=f"spóźnienie {delta_days} dni" + source_note,
    )


# ── Batched per-job context (kills the N+1) ─────────────────────────────────


@dataclass(frozen=True)
class JobScoringContext:
    """Everything ``score_candidate_job`` would otherwise fetch per pair.

    Two layers issue one SELECT each per (candidate, job): champion_fit reads the
    newest screened stage, and the penalty check reads the active client
    conflict. Scoring a cold pool is therefore 2N round-trips — 400 for today's
    pool of 200, and 2 000 for the 1 000-row pool the retrieval ceiling calls
    for. Building this once turns 2N into 2.

    ``None`` is a valid argument everywhere: single-pair callers
    (``marketplace_service``, ``match_justification_service``) keep the old path
    untouched.
    """

    screening_by_candidate: dict[int, Any]
    conflicted_candidate_ids: frozenset[int]


async def build_job_scoring_context(
    db: AsyncSession, job: Job, candidate_ids: Sequence[int]
) -> JobScoringContext:
    """Fetch both per-pair inputs for a whole pool in two queries."""
    from app.models.recruitment_pipeline import CandidateStage

    ids = [int(c) for c in candidate_ids]
    if not ids:
        return JobScoringContext({}, frozenset())

    # DISTINCT ON reproduces `ORDER BY moved_at DESC LIMIT 1` per candidate
    # exactly. Anything looser (a GROUP BY, a join on max(moved_at)) would pick a
    # different row when a candidate has several screened stages, and scores
    # would shift silently rather than fail.
    stage_rows = (
        await db.execute(
            select(CandidateStage.candidate_id, CandidateStage.screening_answers)
            .where(
                CandidateStage.job_id == job.id,
                CandidateStage.candidate_id.in_(ids),
                CandidateStage.screening_answers.is_not(None),
            )
            .distinct(CandidateStage.candidate_id)
            .order_by(CandidateStage.candidate_id, CandidateStage.moved_at.desc())
        )
    ).all()

    conflicted: set[int] = set()
    if job.client_id:
        conflicted = {
            row[0]
            for row in (
                await db.execute(
                    select(CandidateConflict.candidate_id).where(
                        CandidateConflict.candidate_id.in_(ids),
                        CandidateConflict.client_id == job.client_id,
                        CandidateConflict.active.is_(True),
                    )
                )
            ).all()
        }

    return JobScoringContext(
        screening_by_candidate={cid: answers for cid, answers in stage_rows},
        conflicted_candidate_ids=frozenset(conflicted),
    )


def _renormalizing() -> bool:
    return bool(getattr(settings, "SCORE_RENORMALIZE_UNSCORED_LAYERS", False))


def _unscored(max_points: float, reason: str, status: str = "unknown") -> LayerResult:
    """A layer that had nothing to judge.

    With renormalisation ON it contributes to neither numerator nor denominator,
    so its points are 0. With it OFF it keeps paying the neutral constant — that
    is the pre-2026-08-10 behaviour, and "off" has to mean EXACTLY that, or the
    flag stops being a rollback.
    """
    return LayerResult(
        points=0.0 if _renormalizing() else max_points * UNKNOWN_NEUTRAL_FRACTION,
        max_points=max_points,
        reason=reason,
        status=status,
        scored=False,
    )


async def _score_champion_fit(
    candidate: Candidate,
    job: Job,
    db: AsyncSession,
    profile: "WeightProfile" = None,  # type: ignore[assignment]
    context: Optional[JobScoringContext] = None,
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

    # Most recent stage with screening answers for this (candidate, job).
    # Prebuilt context short-circuits the query; without one we fall back to the
    # per-pair SELECT so single-pair callers are untouched.
    if context is not None:
        raw_answers = context.screening_by_candidate.get(candidate.id)
    else:
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
        raw_answers = stage.screening_answers if stage is not None else None
    if not raw_answers:
        # No screening yet → neutral (same knob as salary/location/availability)
        # so unscreened candidates stay competitive. Was hardcoded 0.5.
        # Not a rare edge: the recommendation pool excludes candidates already in
        # the pipeline, and screening answers exist only for those — so this
        # layer has no signal for essentially every candidate it scores.
        return _unscored(max_pts, "brak screeningu")
    try:
        answers = ScreeningAnswers.model_validate(raw_answers)
    except Exception:
        return _unscored(max_pts, "screening niepoprawny")

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
    candidate: Candidate,
    job: Job,
    db: AsyncSession,
    context: Optional[JobScoringContext] = None,
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
        if context is not None:
            has_conflict = candidate.id in context.conflicted_candidate_ids
        else:
            has_conflict = bool(
                await db.scalar(
                    select(CandidateConflict.id).where(
                        CandidateConflict.candidate_id == candidate.id,
                        CandidateConflict.client_id == job.client_id,
                        CandidateConflict.active.is_(True),
                    )
                )
            )
        if has_conflict:
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
        # UWAGA przy zmianie tego napisu: `None` dociera tu z DWÓCH powodów —
        # kandydat naprawdę nie ma wektora ALBO wyszukiwanie/embedding nie
        # odpowiedziało. Ta funkcja nie ma jak ich odróżnić, więc „brak
        # embeddingu" twierdzi więcej, niż wiadomo, i przy awarii Qdranta
        # wysyła diagnozę w stronę profilu kandydata (#414).
        #
        # Napis mimo to ZOSTAJE dosłowny, bo jest KLUCZEM, nie tylko tekstem:
        # `admin_match_score_repair.NO_EMBEDDING_REASON` dopasowuje go w SQL
        # (`breakdown->'semantic'->>'reason' = 'brak embeddingu'`), żeby znaleźć
        # zatrute wiersze cache'u z #130. Zmiana samego napisu sprawiłaby, że
        # narzędzie naprawcze przestaje je znajdować — CICHO, bo raportuje
        # wtedy „0 do naprawy" zamiast błędu. Na produkcji takie wiersze
        # istnieją DZIŚ (#130 nie zostało jeszcze uruchomione).
        #
        # Uczciwa naprawa #414 wymaga rozdzielenia przyczyny U ŹRÓDŁA (wołający
        # wie, czy pytał Qdranta i dostał odpowiedź) oraz dopasowywania OBU
        # napisów w narzędziu naprawczym przez czas życia historycznych wierszy
        # — to osobna zmiana, nie poprawka tekstu.
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
    context: Optional[JobScoringContext] = None,
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
    champion_fit = await _score_champion_fit(
        candidate, job, db, profile, context=context
    )
    penalties = await _check_penalties(candidate, job, db, context=context)

    layers = (semantic, skills, salary, location, availability, champion_fit)
    if penalties:
        total = 0.0
    elif _renormalizing():
        # Score only on what could actually be judged, then rescale to 100:
        # "of what we could assess, this candidate is X%". A layer with no
        # signal contributes to neither numerator nor denominator, so it can no
        # longer inflate or deflate everyone equally.
        earned = sum(layer.points for layer in layers if layer.scored)
        available = sum(layer.max_points for layer in layers if layer.scored)
        total = (earned / available * 100.0) if available > 0 else 0.0
    else:
        total = sum(layer.points for layer in layers)

    # v1.1: niedobór seniority względem Championa tnie total MNOŻNIKOWO —
    # stała punktowa znaczyłaby co innego w trybie sumy i renormalizacji.
    seniority_factor, seniority_reason = _champion_seniority_factor(candidate, job)
    if seniority_factor < 1.0 and total > 0:
        total *= seniority_factor
    # Kary MNOŻĄ SIĘ świadomie (seniority × dostępność): to niezależne ryzyka
    # i kandydat z oboma jest gorszym zakładem niż z jednym — maks. łącznie
    # 0.68 × 0.90 ≈ −39%. Werdykt o skali wydaje pomiar A/B, nie intuicja.
    availability_factor, availability_reason = _champion_availability_conflict_factor(
        candidate, job
    )
    if availability_factor < 1.0 and total > 0:
        total *= availability_factor
        # Ślad w logach jak przy karze seniority — bez niego dochodzenie
        # regresu nie widzi, którzy kandydaci dostali cięcie.
        logger.debug(
            "availability_conflict_penalty",
            extra={
                "candidate_id": candidate.id,
                "job_id": job.id,
                "reason": availability_reason,
            },
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
            "seniority_note": seniority_reason,
            "must_matched": len(must_match),
            "must_missing": len(must_gap),
            "latency_ms": latency_ms,
        },
    )

    return ScoreBreakdown(
        candidate_id=candidate.id,
        job_id=job.id,
        total=total,
        seniority_note=seniority_reason,
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
    # One context for the whole pool instead of two SELECTs per candidate.
    context = await build_job_scoring_context(db, job, [c.id for c in candidates])
    results: List[ScoreBreakdown] = []
    for c in candidates:
        sim = sims.get(c.id)
        results.append(
            await score_candidate_job(
                c, job, db, semantic_similarity=sim, profile=profile, context=context
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
