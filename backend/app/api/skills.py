"""Skill taxonomy API (Phase B1).

Exposes canonical skills + aliases for UI autocomplete. Read-only for now;
admin CRUD can be added later (matches existing JSONB seed flow).
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.database import get_db
from app.models.skill import Skill, SkillAlias

router = APIRouter()


@router.get("/autocomplete")
async def autocomplete_skills(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    q: str = Query("", description="Prefix/substring, matched case-insensitively."),
    limit: int = Query(20, ge=1, le=50),
) -> dict:
    """
    Return up to `limit` canonical skill names that match `q`.

    Matches either the canonical_name or any alias via case-insensitive LIKE.
    When `q` is empty, returns the first `limit` skills alphabetically — handy
    when the UI wants to seed a dropdown without typing.
    """
    query = select(Skill.id, Skill.canonical_name, Skill.category).distinct()

    if q.strip():
        pattern = f"%{q.strip().lower()}%"
        query = query.outerjoin(SkillAlias, SkillAlias.skill_id == Skill.id).where(
            or_(
                func.lower(Skill.canonical_name).like(pattern),
                func.lower(SkillAlias.alias).like(pattern),
            )
        )

    query = query.order_by(Skill.canonical_name.asc()).limit(limit)
    rows = (await db.execute(query)).all()

    return {
        "items": [
            {"id": sid, "name": name, "category": category}
            for sid, name, category in rows
        ]
    }


@router.get("")
async def list_skills(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(100, ge=1, le=500),
) -> dict:
    """List canonical skills with their aliases — read-only reference view."""
    stmt = select(Skill).order_by(Skill.canonical_name.asc()).limit(limit)
    skills = (await db.execute(stmt)).scalars().all()

    items: List[dict] = []
    for s in skills:
        items.append(
            {
                "id": s.id,
                "name": s.canonical_name,
                "category": s.category,
                "aliases": [a.alias for a in s.aliases],
            }
        )
    return {"items": items, "total": len(items)}
