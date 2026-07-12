"""Cortex fact store — normalizacja tokenów i upserty faktów kompetencyjnych.

Zasady (docs/cortex/00-discovery.md §4):
- fakt zawsze wskazuje skill KANONICZNY z taksonomii (``skills`` + aliasy);
- dopasowanie WYŁĄCZNIE exact-token po lowercase/trim — nigdy substring-scan
  po prozie (alias „go" jest bezpieczny w tokenie CSV, w prozie nie byłby);
- token spoza taksonomii ląduje w ``cortex_unmatched_terms`` (pętla kuracji);
- UNIQUE(candidate_id, skill_id, source) → upsert = idempotentny re-run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cortex import CortexSkillFact, CortexUnmatchedTerm
from app.models.skill import Skill, SkillAlias

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
    """Zbuduj mapy alias→canonical(lower) i canonical(lower)→skill_id."""
    canonical_rows = (await db.execute(select(Skill.id, Skill.canonical_name))).all()
    canonical_to_id = {name.lower(): sid for sid, name in canonical_rows}

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


def normalize_token(taxonomy: Taxonomy, raw: str) -> tuple[Optional[int], str]:
    """Zwróć ``(skill_id | None, znormalizowany_token)`` dla surowego tokenu.

    Exact match po lowercase/trim (+ ścięcie końcowego nawiasu). Brak
    dopasowania → ``(None, token)`` — wołający rejestruje unmatched term.
    """
    token = raw.strip().lower().strip(".")
    stripped = _TRAILING_PARENTHETICAL_RE.sub("", token).strip()
    if stripped:
        token = stripped
    if not token:
        return None, token
    canonical = taxonomy.alias_to_canonical.get(token, token)
    return taxonomy.canonical_to_id.get(canonical), token


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
        },
    )
    await db.execute(stmt)


async def record_unmatched(db: AsyncSession, term: str, count: int = 1) -> None:
    """Zlicz token spoza taksonomii (wejście pętli kuracji słownika)."""
    term = term.strip().lower()[:200]
    if not term:
        return
    stmt = pg_insert(CortexUnmatchedTerm).values(term=term, occurrences=count)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_cortex_unmatched_term",
        set_={
            "occurrences": CortexUnmatchedTerm.occurrences + count,
            "last_seen_at": func.now(),
        },
    )
    await db.execute(stmt)


async def normalize_and_upsert(
    db: AsyncSession,
    *,
    candidate_id: int,
    tokens: list[RawSkillToken],
    source: str,
    taxonomy: Taxonomy,
    unmatched_counter: Optional[dict[str, int]] = None,
) -> FactStats:
    """Wspólna ścieżka obu ekstraktorów: normalizuj tokeny i upsertuj fakty.

    Dwa aliasy tego samego skilla w jednym CV → jeden fakt (wygrywa pierwszy
    token; kolejne duplikaty w obrębie wywołania są pomijane). Unmatched
    trafiają do ``unmatched_counter`` (jeśli podany — batchowanie zapisów)
    albo od razu do tabeli.
    """
    stats = FactStats()
    seen_skill_ids: set[int] = set()
    for token in tokens:
        skill_id, normalized = normalize_token(taxonomy, token.name)
        if not normalized:
            continue
        if skill_id is None:
            stats.unmatched += 1
            if unmatched_counter is not None:
                unmatched_counter[normalized] = unmatched_counter.get(normalized, 0) + 1
            else:
                await record_unmatched(db, normalized)
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
        )
        stats.matched += 1
    return stats
