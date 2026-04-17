"""Skill taxonomy loader (Phase B1).

Reads (alias -> canonical_name) pairs from the `skill_aliases` + `skills`
tables and hydrates the in-memory ALIAS_MAP used by the scoring engine.

Called once at startup and after admin edits to the taxonomy so `_score_skills`
can resolve "python3" / "K8s" etc. without an extra DB round-trip.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.skill import Skill, SkillAlias
from app.services.scoring_service import set_alias_map

logger = logging.getLogger(__name__)


async def refresh_alias_map() -> int:
    """Rebuild the in-memory alias → canonical map. Returns row count loaded."""
    async with AsyncSessionLocal() as db:
        stmt = select(SkillAlias.alias, Skill.canonical_name).join(
            Skill, Skill.id == SkillAlias.skill_id
        )
        rows = (await db.execute(stmt)).all()

    mapping: dict[str, str] = {alias: canonical for alias, canonical in rows}
    # Also allow the canonical name itself as a no-op (case-insensitive hit).
    async with AsyncSessionLocal() as db:
        canonicals = (await db.execute(select(Skill.canonical_name))).scalars().all()
    for c in canonicals:
        mapping.setdefault(c.lower(), c.lower())

    set_alias_map(mapping)
    return len(mapping)
