"""Cortex — kuracja taksonomii (domknięcie pętli: unmatched → mapped/ignored).

Etap 1 (Action Layer): dotąd unmatched były tylko do odczytu. Tu admin z UI może:
zmapować term na istniejący skill (dodaje alias), utworzyć nowy canonical,
dodać alias, oznaczyć term jako ignored — z audytem (kto/kiedy). Po każdej zmianie
odświeżamy in-memory ALIAS_MAP scoringu, żeby nowe aliasy działały od razu.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cortex import CortexUnmatchedTerm
from app.models.skill import Skill, SkillAlias
from app.services.skill_taxonomy_loader import refresh_alias_map


class CurationError(Exception):
    """Błąd domenowy kuracji (mapowany na 4xx w API)."""


async def _skill_by_id(db: AsyncSession, skill_id: int) -> Skill:
    skill = await db.get(Skill, skill_id)
    if skill is None:
        raise CurationError(f"Skill {skill_id} nie istnieje")
    return skill


async def _term_by_id(db: AsyncSession, term_id: int) -> CortexUnmatchedTerm:
    term = await db.get(CortexUnmatchedTerm, term_id)
    if term is None:
        raise CurationError(f"Term {term_id} nie istnieje")
    return term


async def _add_alias(db: AsyncSession, skill_id: int, alias: str) -> bool:
    """Dodaj alias (lowercase) do skilla. Zwraca True jeśli wstawiono nowy."""
    alias_lc = alias.strip().lower()
    if not alias_lc:
        raise CurationError("Alias nie może być pusty")
    stmt = (
        pg_insert(SkillAlias)
        .values(skill_id=skill_id, alias=alias_lc)
        .on_conflict_do_nothing(index_elements=["alias"])
        .returning(SkillAlias.id)
    )
    return (await db.execute(stmt)).scalar() is not None


async def map_term_to_skill(
    db: AsyncSession, term_id: int, skill_id: int, *, curated_by: Optional[str]
) -> dict:
    """Zmapuj unmatched term na istniejący skill (dodaj jako alias) + status mapped.

    Fakty dla kandydatów z tym termem powstaną przy następnym backfillu/sync
    (idempotentnie) — nie re-ekstrahujemy tu synchronicznie."""
    term = await _term_by_id(db, term_id)
    await _skill_by_id(db, skill_id)
    await _add_alias(db, skill_id, term.term)
    term.status = "mapped"
    term.curated_by = curated_by
    term.curated_at = func.now()
    await db.commit()
    await refresh_alias_map()
    return {"term": term.term, "status": "mapped", "skill_id": skill_id}


async def ignore_term(
    db: AsyncSession, term_id: int, *, curated_by: Optional[str]
) -> dict:
    term = await _term_by_id(db, term_id)
    term.status = "ignored"
    term.curated_by = curated_by
    term.curated_at = func.now()
    await db.commit()
    return {"term": term.term, "status": "ignored"}


async def create_skill(
    db: AsyncSession,
    *,
    canonical_name: str,
    category: Optional[str] = None,
    aliases: Optional[list[str]] = None,
    curated_by: Optional[str] = None,
    from_term_id: Optional[int] = None,
) -> dict:
    """Utwórz nowy canonical skill (case-insensitive dedup) + opcjonalne aliasy.

    Jeśli ``from_term_id`` podany — oznacz ten unmatched term jako mapped i dodaj
    go jako alias nowego skilla."""
    name = canonical_name.strip()
    if not name:
        raise CurationError("Nazwa kanoniczna nie może być pusta")

    existing = await db.scalar(
        select(Skill).where(func.lower(Skill.canonical_name) == name.lower())
    )
    if existing is not None:
        raise CurationError(f"Skill o nazwie '{name}' już istnieje (id={existing.id})")

    skill = Skill(canonical_name=name, category=category)
    db.add(skill)
    await db.flush()
    skill_id = skill.id

    for alias in aliases or []:
        await _add_alias(db, skill_id, alias)

    term_note = None
    if from_term_id is not None:
        term = await _term_by_id(db, from_term_id)
        await _add_alias(db, skill_id, term.term)
        term.status = "mapped"
        term.curated_by = curated_by
        term.curated_at = func.now()
        term_note = term.term

    await db.commit()
    await refresh_alias_map()
    return {"id": skill_id, "canonical_name": name, "mapped_term": term_note}


async def add_alias(
    db: AsyncSession, skill_id: int, alias: str, *, curated_by: Optional[str] = None
) -> dict:
    await _skill_by_id(db, skill_id)
    inserted = await _add_alias(db, skill_id, alias)
    await db.commit()
    await refresh_alias_map()
    return {"skill_id": skill_id, "alias": alias.strip().lower(), "inserted": inserted}
