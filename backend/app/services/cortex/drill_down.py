"""Cortex — drill-down: od komórki heatmapy do konkretnych kandydatów + lista skilli.

Etap 1 (Action Layer): heatmapa (agregat) prowadzi teraz do listy osób z evidence/
confidence/freshness — moduł przestaje być tylko diagnostyczny. Widoki nazwiskowe
są RODO-gated do tych samych ról co reszta listy kandydatów (admin/HoR/DL/TAC).
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Integer, and_, distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.cortex import CortexSkillFact
from app.models.skill import Skill, SkillAlias
from app.services.cortex.tech_map import derived_seniority_case

_FRESHNESS_YEAR = 365.25


def _freshness_bucket(observed_at) -> str:
    """Wiek sygnału → kubełek świeżości (parytet z coverage/CoverageView)."""
    if observed_at is None:
        return "unknown"
    from datetime import datetime, timezone

    age_days = (datetime.now(timezone.utc) - observed_at).days
    if age_days < _FRESHNESS_YEAR:
        return "lt_1y"
    if age_days < 3 * _FRESHNESS_YEAR:
        return "y1_3"
    return "gt_3y"


def _employment_predicate():
    from app.api.candidates import _at_client_predicate

    return _at_client_predicate()


async def list_skills(
    db: AsyncSession,
    *,
    q: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Pełna, przeszukiwalna, paginowana lista skilli MAJĄCYCH fakty (koniec top-40).

    ``q`` matchuje canonical LUB alias (case-insensitive). Zwraca też ``total``
    dla paginacji.
    """
    base = (
        select(
            Skill.id.label("id"),
            Skill.canonical_name.label("canonical_name"),
            Skill.category.label("category"),
            func.count(distinct(CortexSkillFact.candidate_id)).label("candidates"),
        )
        .select_from(CortexSkillFact)
        .join(Skill, Skill.id == CortexSkillFact.skill_id)
        .group_by(Skill.id)
    )
    if source:
        base = base.where(CortexSkillFact.source == source)
    if q:
        needle = f"%{q.strip().lower()}%"
        alias_match = (
            select(1)
            .where(
                and_(
                    SkillAlias.skill_id == Skill.id,
                    func.lower(SkillAlias.alias).like(needle),
                )
            )
            .exists()
        )
        base = base.where(
            or_(func.lower(Skill.canonical_name).like(needle), alias_match)
        )

    total = (
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar() or 0

    rows = (
        await db.execute(
            base.order_by(
                func.count(distinct(CortexSkillFact.candidate_id)).desc(),
                Skill.canonical_name,
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()

    return {
        "skills": [
            {
                "id": r.id,
                "canonical_name": r.canonical_name,
                "category": r.category,
                "candidates": r.candidates,
            }
            for r in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


async def skill_candidates(
    db: AsyncSession,
    skill_id: int,
    *,
    seniorities: Optional[list[str]] = None,
    source: Optional[str] = None,
    employment: Optional[str] = None,
    min_confidence: Optional[float] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Kandydaci z faktem dla danego skilla — jeden wiersz na osobę (best fact).

    Filtry: ``seniorities`` (lista), ``source``, ``employment`` (at_client|available),
    ``min_confidence``. Zwraca evidence/confidence/freshness/seniority + status
    zatrudnienia — czyli to, czego brakowało, by przejść od mapy do działania.
    """
    fact_scope = select(
        CortexSkillFact.candidate_id.label("cid"),
        func.max(CortexSkillFact.confidence).label("confidence"),
        func.max(CortexSkillFact.observed_at).label("observed_at"),
        func.max(CortexSkillFact.level).label("level"),
        func.max(CortexSkillFact.years).label("years"),
        func.max(CortexSkillFact.evidence).label("evidence"),
        func.array_agg(distinct(CortexSkillFact.source)).label("sources"),
    ).where(CortexSkillFact.skill_id == skill_id)
    if source:
        fact_scope = fact_scope.where(CortexSkillFact.source == source)
    fact_scope = fact_scope.group_by(CortexSkillFact.candidate_id)
    if min_confidence is not None:
        fact_scope = fact_scope.having(
            func.max(CortexSkillFact.confidence) >= min_confidence
        )
    agg = fact_scope.subquery()

    seniority_expr = derived_seniority_case()
    at_client_expr = _employment_predicate()

    q = (
        select(
            Candidate.id.label("id"),
            Candidate.name.label("name"),
            Candidate.lastname.label("lastname"),
            Candidate.availability_status.label("availability_status"),
            seniority_expr.label("seniority"),
            agg.c.confidence.label("confidence"),
            agg.c.observed_at.label("observed_at"),
            agg.c.level.label("level"),
            agg.c.years.label("years"),
            agg.c.evidence.label("evidence"),
            agg.c.sources.label("sources"),
            at_client_expr.cast(Integer).label("at_client"),
        )
        .select_from(agg)
        .join(Candidate, Candidate.id == agg.c.cid)
    )
    if seniorities:
        q = q.where(seniority_expr.in_(seniorities))
    if employment == "at_client":
        q = q.where(at_client_expr)
    elif employment == "available":
        q = q.where(~at_client_expr)

    total = (
        await db.execute(select(func.count()).select_from(q.subquery()))
    ).scalar() or 0

    rows = (
        await db.execute(
            q.order_by(agg.c.confidence.desc(), Candidate.lastname, Candidate.id)
            .limit(limit)
            .offset(offset)
        )
    ).all()

    def _serialize(r) -> dict:
        return {
            "id": r.id,
            "name": r.name,
            "lastname": r.lastname,
            "availability_status": (
                r.availability_status.value
                if r.availability_status is not None
                else None
            ),
            "seniority": r.seniority,
            "confidence": r.confidence,
            "level": r.level,
            "years": r.years,
            "evidence": r.evidence,
            "sources": list(r.sources or []),
            "at_client": bool(r.at_client),
            "observed_at": r.observed_at.isoformat() if r.observed_at else None,
            "freshness": _freshness_bucket(r.observed_at),
        }

    return {
        "candidates": [_serialize(r) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }
