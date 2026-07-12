"""Cortex — mapa technologiczna bazy (skill × derived-seniority).

Seniority kandydata NIE istnieje jako kolumna (discovery §1.2) — liczymy
w query CASE-em o ustalonej precedencji: dokładne ``years_it_experience``
(konwencja scoringu: ≥7 senior, ≥3 mid, <3 junior) → bucket Traffita
(``Poniżej 2``/``2-5``/``5+``, ten sam mapping co filtr doświadczenia w
candidates.py) → ``unknown``. Od PR2 dojdzie najwyższy priorytet: seniority
z profilu LLM (``cortex_candidate_profiles``).

Każda odpowiedź niesie ``fill_rate_pct`` — widok ma jawnie mówić, na jakim
procencie bazy stoi (discovery, pułapka #1: nie agregujemy pustki po cichu).
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import case, distinct, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.cortex import CortexSkillFact
from app.models.skill import Skill

SENIORITY_ORDER = ["junior", "mid", "senior", "unknown"]


def derived_seniority_case():
    """CASE: years_it_experience → bucket Traffita → 'unknown'."""
    traffit_exp = Candidate.cv_extracted_data.op("->>")("traffit_experience")
    return case(
        (
            Candidate.years_it_experience.is_not(None),
            case(
                (Candidate.years_it_experience >= 7, literal("senior")),
                (Candidate.years_it_experience >= 3, literal("mid")),
                else_=literal("junior"),
            ),
        ),
        (traffit_exp == "Poniżej 2", literal("junior")),
        (traffit_exp == "2-5", literal("mid")),
        (traffit_exp == "5+", literal("senior")),
        else_=literal("unknown"),
    )


def _employment_predicate():
    # Import lokalny: reuse derived-predykatu „siedzi u klienta" (kontrakt ∪
    # aktywny konflikt current_employment ∪ hired-latest). Świadomy wyjątek od
    # warstwowania services→api — duplikacja predykatu groziłaby dryfem.
    from app.api.candidates import _at_client_predicate

    return _at_client_predicate()


async def compute_tech_map(
    db: AsyncSession,
    *,
    source: Optional[str] = None,
    employment: Optional[str] = None,
    min_count: int = 2,
) -> dict:
    """Agregat: komórki (skill, seniority) → liczba UNIKALNYCH kandydatów."""
    seniority = derived_seniority_case().label("seniority")

    base = (
        select(
            Skill.canonical_name.label("skill"),
            seniority,
            func.count(distinct(CortexSkillFact.candidate_id)).label("cnt"),
        )
        .select_from(CortexSkillFact)
        .join(Skill, Skill.id == CortexSkillFact.skill_id)
        .join(Candidate, Candidate.id == CortexSkillFact.candidate_id)
    )
    covered_q = (
        select(func.count(distinct(CortexSkillFact.candidate_id)))
        .select_from(CortexSkillFact)
        .join(Candidate, Candidate.id == CortexSkillFact.candidate_id)
    )
    if source:
        base = base.where(CortexSkillFact.source == source)
        covered_q = covered_q.where(CortexSkillFact.source == source)
    if employment == "at_client":
        base = base.where(_employment_predicate())
        covered_q = covered_q.where(_employment_predicate())

    base = base.group_by(Skill.canonical_name, seniority)
    if min_count > 1:
        base = base.having(
            func.count(distinct(CortexSkillFact.candidate_id)) >= min_count
        )

    rows = (await db.execute(base)).all()
    covered = (await db.execute(covered_q)).scalar() or 0
    total_candidates = (
        await db.execute(select(func.count(Candidate.id)))
    ).scalar() or 0

    per_source_rows = (
        await db.execute(
            select(
                CortexSkillFact.source,
                func.count(distinct(CortexSkillFact.candidate_id)),
            ).group_by(CortexSkillFact.source)
        )
    ).all()

    cells = [
        {"skill": skill, "seniority": seniority_val, "count": cnt}
        for skill, seniority_val, cnt in rows
    ]
    skill_totals: dict[str, int] = {}
    for cell in cells:
        skill_totals[cell["skill"]] = skill_totals.get(cell["skill"], 0) + cell["count"]
    skills_axis = sorted(skill_totals, key=lambda s: -skill_totals[s])

    return {
        "cells": cells,
        "skills": skills_axis,
        "seniorities": SENIORITY_ORDER,
        "candidates_covered": covered,
        "candidates_total": total_candidates,
        "fill_rate_pct": (
            round(covered / total_candidates * 100, 1) if total_candidates else 0.0
        ),
        "sources": {src: cnt for src, cnt in per_source_rows},
        "min_count": min_count,
    }
