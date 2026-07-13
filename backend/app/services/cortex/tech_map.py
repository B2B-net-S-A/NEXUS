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
    """Agregat: komórki (skill, seniority) → liczba UNIKALNYCH kandydatów.

    Spójny kohort: te same filtry (``source`` + ``employment``) stosujemy do
    komórek, licznika pokrytych, mianownika i rozbicia źródeł — inaczej
    fill-rate i „Σ" wprowadzały w błąd (audyt P1):
    - ``skill_totals`` = PEŁNY total per skill (BEZ ``min_count``), żeby „Σ" w UI
      był prawdziwy, a nie sumą tylko widocznych komórek;
    - ``candidates_covered`` = distinct kandydatów po wszystkich źródłach
      (overlap-aware) — headline; ``sources`` = rozbicie per-źródło (może się
      nakładać, więc NIE sumować go w UI);
    - mianownik (``candidates_total``) respektuje kohort ``employment``.
    """
    seniority = derived_seniority_case().label("seniority")
    emp_pred = _employment_predicate() if employment == "at_client" else None

    def _scoped(q):
        if source:
            q = q.where(CortexSkillFact.source == source)
        if emp_pred is not None:
            q = q.where(emp_pred)
        return q

    # Komórki heatmapy (filtrowane ``min_count``).
    cells_q = _scoped(
        select(
            Skill.canonical_name.label("skill"),
            seniority,
            func.count(distinct(CortexSkillFact.candidate_id)).label("cnt"),
        )
        .select_from(CortexSkillFact)
        .join(Skill, Skill.id == CortexSkillFact.skill_id)
        .join(Candidate, Candidate.id == CortexSkillFact.candidate_id)
    ).group_by(Skill.canonical_name, seniority)
    if min_count > 1:
        cells_q = cells_q.having(
            func.count(distinct(CortexSkillFact.candidate_id)) >= min_count
        )

    # Prawdziwy total per skill — BEZ ``min_count`` (poprawne „Σ").
    totals_q = _scoped(
        select(
            Skill.canonical_name.label("skill"),
            func.count(distinct(CortexSkillFact.candidate_id)).label("cnt"),
        )
        .select_from(CortexSkillFact)
        .join(Skill, Skill.id == CortexSkillFact.skill_id)
        .join(Candidate, Candidate.id == CortexSkillFact.candidate_id)
    ).group_by(Skill.canonical_name)

    covered_q = _scoped(
        select(func.count(distinct(CortexSkillFact.candidate_id)))
        .select_from(CortexSkillFact)
        .join(Candidate, Candidate.id == CortexSkillFact.candidate_id)
    )

    # Mianownik = kohort (respektuje filtr zatrudnienia).
    total_q = select(func.count(Candidate.id))
    if emp_pred is not None:
        total_q = total_q.where(emp_pred)

    # Rozbicie per-źródło (respektuje kohort zatrudnienia; NIE zawężamy do
    # jednego źródła — chcemy pokazać nakładanie się źródeł).
    sources_q = (
        select(
            CortexSkillFact.source,
            func.count(distinct(CortexSkillFact.candidate_id)),
        )
        .select_from(CortexSkillFact)
        .join(Candidate, Candidate.id == CortexSkillFact.candidate_id)
        .group_by(CortexSkillFact.source)
    )
    if emp_pred is not None:
        sources_q = sources_q.where(emp_pred)

    # „Dane na dzień" — najświeższy fakt w kohorcie (discovery: nie udawaj, że
    # liczby są bieżące).
    as_of_q = _scoped(
        select(func.max(CortexSkillFact.extracted_at))
        .select_from(CortexSkillFact)
        .join(Candidate, Candidate.id == CortexSkillFact.candidate_id)
    )

    cell_rows = (await db.execute(cells_q)).all()
    total_rows = (await db.execute(totals_q)).all()
    covered = (await db.execute(covered_q)).scalar() or 0
    total_candidates = (await db.execute(total_q)).scalar() or 0
    per_source_rows = (await db.execute(sources_q)).all()
    data_as_of = (await db.execute(as_of_q)).scalar()

    cells = [
        {"skill": skill, "seniority": seniority_val, "count": cnt}
        for skill, seniority_val, cnt in cell_rows
    ]
    skill_totals = {skill: cnt for skill, cnt in total_rows}
    # Oś = skille z widoczną komórką (po ``min_count``), sortowane wg PEŁNEGO totalu.
    visible = {cell["skill"] for cell in cells}
    skills_axis = [
        skill
        for skill in sorted(skill_totals, key=lambda s: -skill_totals[s])
        if skill in visible
    ]

    return {
        "cells": cells,
        "skills": skills_axis,
        # Prawdziwy total per skill (dla „Σ" w UI — nie sumować komórek).
        "skill_totals": {skill: skill_totals[skill] for skill in skills_axis},
        "seniorities": SENIORITY_ORDER,
        "candidates_covered": covered,
        "candidates_total": total_candidates,
        "fill_rate_pct": (
            round(covered / total_candidates * 100, 1) if total_candidates else 0.0
        ),
        # Rozbicie per-źródło — MOŻE się nakładać (kandydat w 2 źródłach liczony
        # w obu), więc UI pokazuje je osobno, a nie jako sumę.
        "sources": {src: cnt for src, cnt in per_source_rows},
        "employment": employment,
        "min_count": min_count,
        "data_as_of": data_as_of.isoformat() if data_as_of else None,
    }
