"""Cortex — client × stack × konsultanci + następcy dla kończących się kontraktów.

Etap 1 (Action Layer), wartości biznesowe z discovery:
- **client × stack:** kto z naszych konsultantów siedzi u klienta X i jaki ma
  stack (cross-sell, przygotowanie do spotkania sprzedażowego);
- **następcy:** dla kontraktów kończących się w N dni — dostępni kandydaci z
  nakładającym się stackiem.

„Osadzenie u klienta" derivujemy z aktywnego/kończącego kontraktu LUB z ostatniego
etapu ``hired`` (job → client) — bo tabela ``contracts`` jest słabo wypełniona
(~1 z ~700), a sygnał ``hired`` niesie realną populację (patrz
``candidates._at_client_predicate``).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from sqlalchemy import and_, distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.candidate import AvailabilityStatus, Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus
from app.models.cortex import CortexSkillFact
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.skill import Skill

_ACTIVE_STATUSES = (ContractStatus.active, ContractStatus.ending)


def _placed_pairs():
    """Subquery (candidate_id, client_id) — konsultanci osadzeni u klienta.

    Unia: aktywny/kończący kontrakt ∪ ostatni etap ``hired`` (job→client)."""
    contract_pairs = select(
        Contract.candidate_id.label("candidate_id"),
        Contract.client_id.label("client_id"),
    ).where(Contract.status.in_(_ACTIVE_STATUSES))

    later = aliased(CandidateStage)
    hired_pairs = (
        select(
            CandidateStage.candidate_id.label("candidate_id"),
            Job.client_id.label("client_id"),
        )
        .join(Job, Job.id == CandidateStage.job_id)
        .where(
            and_(
                CandidateStage.stage == PipelineStage.hired,
                ~(
                    select(1)
                    .where(
                        and_(
                            later.candidate_id == CandidateStage.candidate_id,
                            later.job_id == CandidateStage.job_id,
                            or_(
                                later.moved_at > CandidateStage.moved_at,
                                and_(
                                    later.moved_at == CandidateStage.moved_at,
                                    later.id > CandidateStage.id,
                                ),
                            ),
                        )
                    )
                    .exists()
                ),
            )
        )
    )
    return contract_pairs.union(hired_pairs).subquery()


async def client_stack(
    db: AsyncSession, *, client_id: Optional[int] = None, min_count: int = 1
) -> dict:
    """Macierz klient × skill → liczba UNIKALNYCH osadzonych konsultantów."""
    placed = _placed_pairs()
    client_name = func.coalesce(Client.display_name, Client.name)

    q = (
        select(
            Client.id.label("client_id"),
            client_name.label("client"),
            Skill.canonical_name.label("skill"),
            func.count(distinct(placed.c.candidate_id)).label("cnt"),
        )
        .select_from(placed)
        .join(Client, Client.id == placed.c.client_id)
        .join(CortexSkillFact, CortexSkillFact.candidate_id == placed.c.candidate_id)
        .join(Skill, Skill.id == CortexSkillFact.skill_id)
        .group_by(Client.id, client_name, Skill.canonical_name)
    )
    if client_id is not None:
        q = q.where(Client.id == client_id)
    if min_count > 1:
        q = q.having(func.count(distinct(placed.c.candidate_id)) >= min_count)

    rows = (await db.execute(q)).all()

    # Konsultanci osadzeni per klient (mianownik / headline).
    consultants_q = (
        select(
            Client.id.label("client_id"),
            func.count(distinct(placed.c.candidate_id)).label("cnt"),
        )
        .select_from(placed)
        .join(Client, Client.id == placed.c.client_id)
        .group_by(Client.id)
    )
    if client_id is not None:
        consultants_q = consultants_q.where(Client.id == client_id)
    consultants = {r.client_id: r.cnt for r in (await db.execute(consultants_q)).all()}

    cells = [
        {
            "client_id": r.client_id,
            "client": r.client,
            "skill": r.skill,
            "count": r.cnt,
        }
        for r in rows
    ]
    clients = sorted(
        {(r.client_id, r.client) for r in rows},
        key=lambda c: -consultants.get(c[0], 0),
    )
    return {
        "cells": cells,
        "clients": [
            {"id": cid, "name": name, "consultants": consultants.get(cid, 0)}
            for cid, name in clients
        ],
        "min_count": min_count,
    }


async def contract_successors(
    db: AsyncSession, *, now: date, days: int = 30, top_per_contract: int = 5
) -> dict:
    """Dla kontraktów kończących się w ``days`` dni — dostępni następcy z
    nakładającym się stackiem (ranking po liczbie wspólnych skilli).

    Liczba kończących się kontraktów jest mała, więc per-kontrakt robimy 2 lekkie
    zapytania (skille osadzonego + dopasowani dostępni) — czytelne, nie N+1 problem.
    """
    cutoff = now + timedelta(days=days)
    client_name = func.coalesce(Client.display_name, Client.name)
    ending = (
        await db.execute(
            select(
                Contract.id,
                Contract.candidate_id,
                Contract.client_id,
                Contract.end_date,
                Contract.client_order_end_date,
                Candidate.name,
                Candidate.lastname,
                client_name.label("client_name"),
            )
            .select_from(Contract)
            .outerjoin(Candidate, Candidate.id == Contract.candidate_id)
            .outerjoin(Client, Client.id == Contract.client_id)
            .where(
                and_(
                    Contract.status.in_(_ACTIVE_STATUSES),
                    or_(
                        and_(
                            Contract.end_date.is_not(None),
                            Contract.end_date <= cutoff,
                        ),
                        and_(
                            Contract.client_order_end_date.is_not(None),
                            Contract.client_order_end_date <= cutoff,
                        ),
                    ),
                )
            )
        )
    ).all()

    results = []
    for c in ending:
        skill_ids = [
            r[0]
            for r in (
                await db.execute(
                    select(distinct(CortexSkillFact.skill_id)).where(
                        CortexSkillFact.candidate_id == c.candidate_id
                    )
                )
            ).all()
        ]
        successors = []
        if skill_ids:
            succ_rows = (
                await db.execute(
                    select(
                        Candidate.id,
                        Candidate.name,
                        Candidate.lastname,
                        Candidate.availability_status,
                        func.count(distinct(CortexSkillFact.skill_id)).label("overlap"),
                    )
                    .select_from(CortexSkillFact)
                    .join(Candidate, Candidate.id == CortexSkillFact.candidate_id)
                    .where(
                        and_(
                            CortexSkillFact.skill_id.in_(skill_ids),
                            Candidate.id != c.candidate_id,
                            Candidate.availability_status != AvailabilityStatus.unknown,
                        )
                    )
                    .group_by(Candidate.id)
                    .order_by(func.count(distinct(CortexSkillFact.skill_id)).desc())
                    .limit(top_per_contract)
                )
            ).all()
            successors = [
                {
                    "id": s.id,
                    "name": s.name,
                    "lastname": s.lastname,
                    "availability_status": (
                        s.availability_status.value
                        if s.availability_status is not None
                        else None
                    ),
                    "overlap": s.overlap,
                }
                for s in succ_rows
            ]
        end = c.client_order_end_date or c.end_date
        results.append(
            {
                "contract_id": c.id,
                "candidate_id": c.candidate_id,
                "candidate_name": c.name,
                "candidate_lastname": c.lastname,
                "client_id": c.client_id,
                "client_name": c.client_name,
                "end_date": end.isoformat() if end else None,
                "skill_count": len(skill_ids),
                "successors": successors,
            }
        )

    return {"days": days, "ending_contracts": results}
