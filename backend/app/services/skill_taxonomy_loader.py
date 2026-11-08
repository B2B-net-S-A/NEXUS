"""Skill taxonomy loader (Phase B1).

Reads the `skills` + `skill_aliases` tables and hydrates two in-memory views:
  - the scoring engine's ALIAS_MAP (alias -> canonical) via ``set_alias_map``;
  - the CV generator's technology taxonomy (tech canonicals + alias forms,
    filtered by category) via ``skill_normalize.set_tech_taxonomy``.

Called once at startup and after admin edits so both `_score_skills` and the
CV bolding classifier resolve "python3" / "K8s" / "Postgres" without an extra
DB round-trip.
"""

from __future__ import annotations

import logging
from typing import Optional
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.app_setting import AppSetting
from app.models.skill import Skill, SkillAlias
from app.models.skill_relation import SkillRelation
from app.services.scoring_service import set_alias_map
from app.services.skill_normalize import (
    TECH_CATEGORIES,
    alias_counts_in_text,
    set_relations,
    set_tech_taxonomy,
)

logger = logging.getLogger(__name__)

# Audyt 2, W5 (08.11.2026): słownik żyje w pamięci procesu, a zmienia go też
# nocny bieg i skrypty. Wersja w bazie mówi pozostałym procesom, że mapa jest
# stara. Sam token losowy, bo porównujemy tylko równość.
DICTIONARY_VERSION_KEY = "skill_dictionary_version"
_NO_VERSION_YET = "0"
_loaded_version: Optional[str] = None


def loaded_dictionary_version() -> Optional[str]:
    """Wersja słownika w pamięci tego procesu; ``None`` przed pierwszym wczytaniem."""
    return _loaded_version


async def bump_dictionary_version(db: AsyncSession) -> None:
    """Zapisz nową wersję słownika. Nie commituje."""
    value = {"version": uuid4().hex}
    await db.execute(
        insert(AppSetting)
        .values(key=DICTIONARY_VERSION_KEY, value=value)
        .on_conflict_do_update(index_elements=[AppSetting.key], set_={"value": value})
    )


async def _stored_dictionary_version() -> str:
    async with AsyncSessionLocal() as db:
        value = await db.scalar(
            select(AppSetting.value).where(AppSetting.key == DICTIONARY_VERSION_KEY)
        )
    return (value or {}).get("version") or _NO_VERSION_YET


async def sync_dictionary_version() -> Optional[int]:
    """Przeładuj mapę, gdy baza ma inną wersję niż ten proces.

    Zwraca liczbę aliasów albo ``None``, gdy nic się nie zmieniło. Wersję czytamy
    przed przeładowaniem: zmiana zapisana w trakcie da przy następnym sprawdzeniu
    inną wersję i jeszcze jedno przeładowanie, a nie przepadnie."""
    global _loaded_version
    version = await _stored_dictionary_version()
    if version == _loaded_version:
        return None
    count = await refresh_alias_map()
    _loaded_version = version
    return count


async def refresh_alias_map() -> int:
    """Rebuild the in-memory alias map + tech taxonomy. Returns aliases loaded."""
    async with AsyncSessionLocal() as db:
        skills = (
            await db.execute(select(Skill.id, Skill.canonical_name, Skill.category))
        ).all()
        alias_rows = (
            await db.execute(
                select(SkillAlias.skill_id, SkillAlias.alias, SkillAlias.in_text)
            )
        ).all()
        relation_rows = (
            await db.execute(
                select(
                    SkillRelation.from_skill_id,
                    SkillRelation.to_skill_id,
                    SkillRelation.kind,
                ).where(SkillRelation.status == "accepted")
            )
        ).all()

    from app.services import keyword_suggest

    keyword_suggest.load_catalog(
        skills, [(skill_id, alias) for skill_id, alias, _in_text in alias_rows]
    )

    id_to_canon: dict[int, str] = {sid: cn for sid, cn, _cat in skills if cn}
    id_to_cat: dict[int, str] = {sid: (cat or "") for sid, _cn, cat in skills}

    # alias -> canonical (original case; set_alias_map lowercases), plus the
    # canonical name itself as a no-op hit — mirrors the previous behaviour.
    mapping: dict[str, str] = {}
    canonical_to_aliases: dict[str, list[str]] = {}
    text_aliases: dict[str, list[str]] = {}
    for skill_id, alias, in_text in alias_rows:
        canon = id_to_canon.get(skill_id)
        if not canon or not alias:
            continue
        mapping[alias] = canon
        canonical_to_aliases.setdefault(canon.lower(), []).append(alias.lower())
        if alias_counts_in_text(alias, canon, id_to_cat.get(skill_id), in_text):
            text_aliases.setdefault(canon.lower(), []).append(alias.lower())
    for canon in id_to_canon.values():
        mapping.setdefault(canon.lower(), canon.lower())

    scoring_mapping = dict(mapping)
    if settings.SKILL_ALIAS_EXTENDED_ENABLED:
        # Eksperyment 4a: rozszerzone rodziny wchodzą WYŁĄCZNIE do mapy
        # scoringu (baza wygrywa na kolizjach — setdefault). Taksonomia
        # boldowania CV niżej dostaje mapę BEZ rozszerzenia — eksperyment
        # rankingowy nie może zmieniać wyglądu generowanych CV.
        from app.services.skill_taxonomy_extended import extended_alias_mapping

        added = 0
        for alias, canon in extended_alias_mapping().items():
            if alias not in scoring_mapping:
                scoring_mapping[alias] = canon
                added += 1
        logger.info("Extended alias families merged: +%d entries", added)

    set_alias_map(scoring_mapping)

    # Technology taxonomy for CV bolding: canonicals whose category is a tech
    # bucket (excludes methodology / role_* so Agile/Scrum/roles never bold).
    tech_canonicals = {
        id_to_canon[skill_id].lower()
        for skill_id, cat in id_to_cat.items()
        if id_to_canon.get(skill_id) and cat.lower() in TECH_CATEGORIES
    }
    set_tech_taxonomy(
        tech_canonicals=tech_canonicals,
        alias_to_canonical={a.lower(): c.lower() for a, c in mapping.items()},
        canonical_to_aliases=canonical_to_aliases,
        categories={
            canon: id_to_cat.get(skill_id, "")
            for skill_id, canon in id_to_canon.items()
        },
        text_aliases=text_aliases,
    )
    _load_relations(relation_rows, id_to_canon)
    # Reguła bramki must czyta kategorie — wyniki sprzed przeładowania są stare.
    from app.services import must_gate_terms

    must_gate_terms.clear_cache()
    from app.services import must_text_evidence

    must_text_evidence.clear_cache()
    from app.services import dz_review

    dz_review.clear_pattern_cache()
    logger.debug(
        "Tech taxonomy loaded: %d tech canonicals of %d skills",
        len(tech_canonicals),
        len(id_to_canon),
    )
    return len(scoring_mapping)


def _load_relations(rows, id_to_canon: dict[int, str]) -> None:
    """Mapa wiedzy IT (0660): zatwierdzone powiązania do ``skill_normalize``.
    „Wynika z” i „część” spełniają wymaganie, zamiennik działa w obie strony,
    „typowe” zapisujemy od strony wymagania (Maven ← Java)."""
    implied_by: dict[str, set[str]] = {}
    alternatives: dict[str, set[str]] = {}
    typical_by: dict[str, set[str]] = {}
    for from_id, to_id, kind in rows:
        src = (id_to_canon.get(from_id) or "").lower()
        dst = (id_to_canon.get(to_id) or "").lower()
        if not src or not dst or src == dst:
            continue
        if kind in ("implies", "part_of"):
            implied_by.setdefault(dst, set()).add(src)
        elif kind == "alternative":
            alternatives.setdefault(dst, set()).add(src)
            alternatives.setdefault(src, set()).add(dst)
        elif kind == "typical":
            typical_by.setdefault(dst, set()).add(src)
    set_relations(
        implied_by=implied_by, alternatives=alternatives, typical_by=typical_by
    )
