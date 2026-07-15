"""Cortex — fakty rozwiązane (resolved facts): jeden fakt per (kandydat, skill).

Etap 2: mając wiele źródeł na ten sam skill (traffit / cv_llm / screening),
wybieramy zwycięzcę po PRECEDENCJI źródła (screening > cv_llm > traffit —
weryfikacja człowieka > LLM > ręczne pole), a przy remisie po
``confidence × freshness_decay``. To warstwa, którą zasila się scoring/profil/
matching (dziś fakty nie zasilają niczego).

Świeżość: ``observed_at`` (data sygnału) → decay. NULL (nie wiemy) = neutralny
0.7 — nie ufamy w pełni, ale nie zerujemy.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cortex import CortexSkillFact
from app.models.skill import Skill

_YEAR = 365.25

# screening > cv_llm > traffit
_PRECEDENCE = case(
    (CortexSkillFact.source == "screening", 3),
    (CortexSkillFact.source == "cv_llm", 2),
    else_=1,
)

_AGE_DAYS = func.extract("epoch", func.now() - CortexSkillFact.observed_at) / 86400.0

_DECAY = case(
    (CortexSkillFact.observed_at.is_(None), 0.7),
    (_AGE_DAYS < _YEAR, 1.0),
    (_AGE_DAYS < 3 * _YEAR, 0.8),
    else_=0.5,
)

_EFFECTIVE_CONFIDENCE = CortexSkillFact.confidence * _DECAY


def resolved_subquery(candidate_id: Optional[int] = None):
    """DISTINCT ON (candidate, skill) — zwycięski fakt per para.

    Kolumny: candidate_id, skill_id, source, effective_confidence, precedence,
    level, years, observed_at. Zwraca CTE/subquery do dalszych joinów (scoring,
    supply/demand, profil)."""
    q = select(
        CortexSkillFact.candidate_id.label("candidate_id"),
        CortexSkillFact.skill_id.label("skill_id"),
        CortexSkillFact.source.label("source"),
        _EFFECTIVE_CONFIDENCE.label("effective_confidence"),
        _PRECEDENCE.label("precedence"),
        CortexSkillFact.level.label("level"),
        CortexSkillFact.years.label("years"),
        CortexSkillFact.observed_at.label("observed_at"),
    ).distinct(CortexSkillFact.candidate_id, CortexSkillFact.skill_id)
    if candidate_id is not None:
        q = q.where(CortexSkillFact.candidate_id == candidate_id)
    # DISTINCT ON wymaga, by ORDER BY zaczynał się od kolumn distinct.
    q = q.order_by(
        CortexSkillFact.candidate_id,
        CortexSkillFact.skill_id,
        _PRECEDENCE.desc(),
        _EFFECTIVE_CONFIDENCE.desc(),
    )
    return q.subquery()


async def resolve_candidate_skills(db: AsyncSession, candidate_id: int) -> list[dict]:
    """Rozwiązane skille jednego kandydata (dla profilu / API), z nazwą kanoniczną."""
    r = resolved_subquery(candidate_id)
    rows = (
        await db.execute(
            select(
                r.c.skill_id,
                Skill.canonical_name,
                r.c.source,
                r.c.effective_confidence,
                r.c.level,
                r.c.years,
                r.c.observed_at,
            )
            .select_from(r)
            .join(Skill, Skill.id == r.c.skill_id)
            .order_by(r.c.effective_confidence.desc(), Skill.canonical_name)
        )
    ).all()
    return [
        {
            "skill_id": row.skill_id,
            "skill": row.canonical_name,
            "source": row.source,
            "effective_confidence": round(float(row.effective_confidence), 3),
            "level": row.level,
            "years": row.years,
            "observed_at": row.observed_at.isoformat() if row.observed_at else None,
        }
        for row in rows
    ]


async def resolved_canonical_names(
    db: AsyncSession, candidate_id: int, *, min_confidence: float = 0.0
) -> set[str]:
    """Zbiór lowercase nazw kanonicznych rozwiązanych skilli — pod augmentację
    scoringu (dodatkowy sygnał obok ``candidate.skills`` JSONB)."""
    r = resolved_subquery(candidate_id)
    q = (
        select(func.lower(Skill.canonical_name))
        .select_from(r)
        .join(Skill, Skill.id == r.c.skill_id)
    )
    if min_confidence > 0:
        q = q.where(r.c.effective_confidence >= min_confidence)
    return {name for (name,) in (await db.execute(q)).all()}
