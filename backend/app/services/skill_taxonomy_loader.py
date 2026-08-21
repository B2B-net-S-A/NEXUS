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

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.skill import Skill, SkillAlias
from app.services.scoring_service import set_alias_map
from app.services.skill_normalize import TECH_CATEGORIES, set_tech_taxonomy

logger = logging.getLogger(__name__)


async def refresh_alias_map() -> int:
    """Rebuild the in-memory alias map + tech taxonomy. Returns aliases loaded."""
    async with AsyncSessionLocal() as db:
        skills = (
            await db.execute(select(Skill.id, Skill.canonical_name, Skill.category))
        ).all()
        alias_rows = (
            await db.execute(select(SkillAlias.skill_id, SkillAlias.alias))
        ).all()

    id_to_canon: dict[int, str] = {sid: cn for sid, cn, _cat in skills if cn}
    id_to_cat: dict[int, str] = {sid: (cat or "") for sid, _cn, cat in skills}

    # alias -> canonical (original case; set_alias_map lowercases), plus the
    # canonical name itself as a no-op hit — mirrors the previous behaviour.
    mapping: dict[str, str] = {}
    canonical_to_aliases: dict[str, list[str]] = {}
    for skill_id, alias in alias_rows:
        canon = id_to_canon.get(skill_id)
        if not canon or not alias:
            continue
        mapping[alias] = canon
        canonical_to_aliases.setdefault(canon.lower(), []).append(alias.lower())
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
    )
    logger.debug(
        "Tech taxonomy loaded: %d tech canonicals of %d skills",
        len(tech_canonicals),
        len(id_to_canon),
    )
    return len(scoring_mapping)
