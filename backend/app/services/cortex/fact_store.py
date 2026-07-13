"""Cortex fact store — normalizacja tokenów i upserty faktów kompetencyjnych.

Zasady (docs/cortex/00-discovery.md §4):
- fakt zawsze wskazuje skill KANONICZNY z taksonomii (``skills`` + aliasy);
- dopasowanie WYŁĄCZNIE exact-token po lowercase/trim — nigdy substring-scan
  po prozie (alias „go" jest bezpieczny w tokenie CSV, w prozie nie byłby);
- token spoza taksonomii ląduje w ``cortex_unmatched_terms`` (pętla kuracji);
- UNIQUE(candidate_id, skill_id, source) → upsert = idempotentny re-run.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from sqlalchemy import delete, func, literal_column, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cortex import (
    CortexSkillFact,
    CortexUnmatchedObservation,
    CortexUnmatchedTerm,
)
from app.models.skill import Skill, SkillAlias

logger = logging.getLogger(__name__)

_ALLOWED_LEVELS = {"junior", "mid", "senior"}

# Ogonki typu "Python (3 lata)" / "AWS (certified)" — tniemy końcowy nawias,
# rdzeń zostaje tokenem do dopasowania.
_TRAILING_PARENTHETICAL_RE = re.compile(r"\s*\([^)]*\)\s*$")


@dataclass(frozen=True)
class RawSkillToken:
    """Surowy sygnał skilla z ekstraktora, przed normalizacją."""

    name: str
    level: Optional[str] = None
    years: Optional[int] = None
    confidence: float = 0.8
    evidence: Optional[str] = None
    observed_at: Optional[datetime] = None


@dataclass
class Taxonomy:
    """Zrzut taksonomii do pamięci na czas jednego przebiegu backfillu.

    Ładowany z DB na starcie runu (≈setki wierszy) — celowo NIE współdzieli
    stanu z ``scoring_service.ALIAS_MAP``, żeby normalizacja Cortexa była
    czysta i testowalna bez hydratacji startupu aplikacji.
    """

    alias_to_canonical: dict[str, str] = field(default_factory=dict)
    canonical_to_id: dict[str, int] = field(default_factory=dict)


@dataclass
class FactStats:
    matched: int = 0
    unmatched: int = 0


async def load_taxonomy(db: AsyncSession) -> Taxonomy:
    """Zbuduj mapy alias→canonical(lower) i canonical(lower)→skill_id.

    ``order_by(Skill.id)`` czyni mapowanie deterministycznym: po dedupie
    (migracja 0160 + funkcyjny unique ``lower(canonical_name)``) kolizji nie ma,
    ale gdyby jakiś duplikat przetrwał, logujemy go głośno zamiast po cichu
    nadpisywać ``skill_id`` (dawny bug last-wins).
    """
    canonical_rows = (
        await db.execute(select(Skill.id, Skill.canonical_name).order_by(Skill.id))
    ).all()
    canonical_to_id: dict[str, int] = {}
    for sid, name in canonical_rows:
        key = name.lower()
        if key in canonical_to_id and canonical_to_id[key] != sid:
            logger.warning(
                "cortex taxonomy collision on %r: skill_id %s vs %s — "
                "run dedup migration 0160",
                key,
                canonical_to_id[key],
                sid,
            )
            continue  # zachowaj pierwszy (najniższe id) — deterministycznie
        canonical_to_id[key] = sid

    alias_rows = (
        await db.execute(
            select(SkillAlias.alias, Skill.canonical_name).join(
                Skill, Skill.id == SkillAlias.skill_id
            )
        )
    ).all()
    alias_to_canonical = {
        alias.lower(): canonical.lower() for alias, canonical in alias_rows
    }
    # Nazwa kanoniczna dopasowuje samą siebie (parytet z refresh_alias_map).
    for lowered in canonical_to_id:
        alias_to_canonical.setdefault(lowered, lowered)

    return Taxonomy(
        alias_to_canonical=alias_to_canonical, canonical_to_id=canonical_to_id
    )


def _lookup(taxonomy: Taxonomy, token: str) -> Optional[int]:
    canonical = taxonomy.alias_to_canonical.get(token, token)
    return taxonomy.canonical_to_id.get(canonical)


def normalize_token(taxonomy: Taxonomy, raw: str) -> tuple[Optional[int], str]:
    """Zwróć ``(skill_id | None, znormalizowany_token)`` dla surowego tokenu.

    Exact match po lowercase/trim. Najpierw token AS-IS (chroni nazwy z
    interpunkcją: ".net", "node.js"); dopiero przy pudle fallback z odciętym
    końcowym nawiasem ("Python (3 lata)") i kropką zdaniową. Brak dopasowania
    → ``(None, token)`` — wołający rejestruje unmatched term.
    """
    token = raw.strip().lower()
    if not token:
        return None, token

    skill_id = _lookup(taxonomy, token)
    if skill_id is not None:
        return skill_id, token

    cleaned = _TRAILING_PARENTHETICAL_RE.sub("", token).rstrip(".").strip()
    if not cleaned or cleaned == token:
        return None, token
    return _lookup(taxonomy, cleaned), cleaned


def clamp_level(level: Optional[str]) -> Optional[str]:
    if level is None:
        return None
    lowered = level.strip().lower()
    return lowered if lowered in _ALLOWED_LEVELS else None


def clamp_years(years: Optional[int]) -> Optional[int]:
    if years is None:
        return None
    try:
        return max(0, min(40, int(years)))
    except (TypeError, ValueError):
        return None


def clamp_confidence(confidence: float) -> float:
    try:
        return max(0.1, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        return 0.5


async def upsert_fact(
    db: AsyncSession,
    *,
    candidate_id: int,
    skill_id: int,
    source: str,
    level: Optional[str],
    years: Optional[int],
    confidence: float,
    evidence: Optional[str],
    observed_at: Optional[datetime],
    run_id: Optional[int] = None,
    extractor_version: Optional[str] = None,
    content_hash: Optional[str] = None,
    source_ref: Optional[str] = None,
) -> None:
    """Idempotentny upsert faktu — re-run tego samego źródła to pełny refresh."""
    stmt = pg_insert(CortexSkillFact).values(
        candidate_id=candidate_id,
        skill_id=skill_id,
        source=source,
        level=clamp_level(level),
        years=clamp_years(years),
        confidence=clamp_confidence(confidence),
        evidence=(evidence or None) and evidence[:300],
        observed_at=observed_at,
        run_id=run_id,
        extractor_version=extractor_version,
        content_hash=content_hash,
        source_ref=source_ref,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_cortex_fact_cand_skill_source",
        set_={
            "level": stmt.excluded.level,
            "years": stmt.excluded.years,
            "confidence": stmt.excluded.confidence,
            "evidence": stmt.excluded.evidence,
            "observed_at": stmt.excluded.observed_at,
            "extracted_at": func.now(),
            "run_id": stmt.excluded.run_id,
            "extractor_version": stmt.excluded.extractor_version,
            "content_hash": stmt.excluded.content_hash,
            "source_ref": stmt.excluded.source_ref,
        },
    )
    await db.execute(stmt)


async def record_unmatched(
    db: AsyncSession,
    term: str,
    *,
    candidate_id: int,
    source: str = "traffit",
) -> None:
    """Zarejestruj token spoza taksonomii (wejście pętli kuracji słownika).

    Idempotentne: ``occurrences`` liczy UNIKALNYCH kandydatów. Licznik rośnie
    tylko przy PIERWSZEJ obserwacji danego ``(term, candidate, source)`` — dzięki
    tabeli ``cortex_unmatched_observations``. Ponowny backfill niezmienionych
    danych odświeża tylko ``last_seen_at`` i NIE zawyża licznika (dawny bug).
    """
    term = term.strip().lower()[:200]
    if not term:
        return

    # Upsert obserwacji; ``xmax = 0`` ⇒ świeży INSERT (nowy unikalny kandydat).
    obs = pg_insert(CortexUnmatchedObservation).values(
        term=term, candidate_id=candidate_id, source=source
    )
    obs = obs.on_conflict_do_update(
        constraint="uq_cortex_unmatched_obs",
        set_={"last_seen_at": func.now()},
    ).returning(literal_column("(xmax = 0)"))
    is_new = bool((await db.execute(obs)).scalar())

    # Wiersz kolejki kuracji: inkrementuj occurrences tylko dla nowego kandydata.
    term_stmt = pg_insert(CortexUnmatchedTerm).values(term=term, occurrences=1)
    if is_new:
        term_stmt = term_stmt.on_conflict_do_update(
            constraint="uq_cortex_unmatched_term",
            set_={
                "occurrences": CortexUnmatchedTerm.occurrences + 1,
                "last_seen_at": func.now(),
            },
        )
    else:
        term_stmt = term_stmt.on_conflict_do_update(
            constraint="uq_cortex_unmatched_term",
            set_={"last_seen_at": func.now()},
        )
    await db.execute(term_stmt)


async def normalize_and_upsert(
    db: AsyncSession,
    *,
    candidate_id: int,
    tokens: list[RawSkillToken],
    source: str,
    taxonomy: Taxonomy,
    reconcile: bool = False,
    run_id: Optional[int] = None,
    extractor_version: Optional[str] = None,
    content_hash: Optional[str] = None,
    source_ref: Optional[str] = None,
) -> FactStats:
    """Wspólna ścieżka ekstraktorów: normalizuj tokeny i upsertuj fakty.

    Dwa aliasy tego samego skilla w jednym źródle → jeden fakt (wygrywa pierwszy
    token; duplikaty w obrębie wywołania pomijane). Unmatched → idempotentna
    rejestracja per kandydat.

    ``reconcile=True``: po upsercie usuń fakty tego samego ``(candidate, source)``,
    których NIE ma już w źródle — dzięki temu skill usunięty u kandydata znika z
    fact store (bez tego zostawał na zawsze). Idempotentne: podwójny run na
    niezmienionych danych daje ten sam zestaw faktów.
    """
    stats = FactStats()
    seen_skill_ids: set[int] = set()
    seen_unmatched: set[str] = set()
    for token in tokens:
        skill_id, normalized = normalize_token(taxonomy, token.name)
        if not normalized:
            continue
        if skill_id is None:
            stats.unmatched += 1
            if normalized not in seen_unmatched:
                seen_unmatched.add(normalized)
                await record_unmatched(
                    db, normalized, candidate_id=candidate_id, source=source
                )
            continue
        if skill_id in seen_skill_ids:
            continue
        seen_skill_ids.add(skill_id)
        await upsert_fact(
            db,
            candidate_id=candidate_id,
            skill_id=skill_id,
            source=source,
            level=token.level,
            years=token.years,
            confidence=token.confidence,
            evidence=token.evidence,
            observed_at=token.observed_at,
            run_id=run_id,
            extractor_version=extractor_version,
            content_hash=content_hash,
            source_ref=source_ref,
        )
        stats.matched += 1

    if reconcile:
        stale = delete(CortexSkillFact).where(
            CortexSkillFact.candidate_id == candidate_id,
            CortexSkillFact.source == source,
        )
        if seen_skill_ids:
            # Zostaw tylko fakty dla skilli obecnych w tym źródle teraz.
            stale = stale.where(CortexSkillFact.skill_id.notin_(seen_skill_ids))
        await db.execute(stale)

    return stats
