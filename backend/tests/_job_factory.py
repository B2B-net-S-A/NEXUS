"""Komplet do ``POST /api/jobs`` — rekrutacja bez szkiców (04.10.2026).

Od 04.10.2026 utworzenie rekrutacji = przekazanie do searchu = publikacja
w jednej transakcji: żądanie bez kompletu (Profil Championa, decyzja
o hiring managerze i terminie, kategoria, przekazanie) kończy się 422
``job_not_ready``. Testy, które zakładają rekrutację przez API, biorą ładunek
stąd i nadpisują tylko to, co sprawdzają.

``purge_job`` usuwa rekrutację razem z wierszami Priority Work, które zakłada
przekazanie do rekrutera (``ON DELETE RESTRICT`` na ``jobs``).
"""

from __future__ import annotations

import copy
import uuid
from typing import Any, Optional

from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal

READY_CHAMPION: dict[str, Any] = {
    "project": {"about": "Platforma płatności B2B dla banku — rozwój usług."},
    "screening_questions": [
        {
            "id": "q1",
            "question": "Doświadczenie z Pythonem?",
            "deal_breaker": "Brak komercyjnego projektu w Pythonie.",
        },
        {
            "id": "q2",
            "question": "Doświadczenie z Postgres?",
            "deal_breaker": "Nie pracował z relacyjną bazą.",
        },
    ],
    # Wiersz wymagań „musi mieć” (02.10.2026) — serwer wyprowadza z niego
    # stack MUST i kolumnę `must_skills`. „Brak krytycznych” to decyzja.
    "stack": {"rows": [{"words": ["Python"], "level": "must"}], "critical": []},
    "basics": {"rate_value": 150, "work_mode": "zdalnie"},
    "search": {"requirements": [["Python"]]},
}


def ready_champion() -> dict[str, Any]:
    return copy.deepcopy(READY_CHAMPION)


async def competence_category_id() -> int:
    """Kategoria kompetencji z zasiewu (0033) — bramka wymaga kategorii."""
    from app.models.competence_category import CompetenceCategory

    async with AsyncSessionLocal() as db:
        found = await db.scalar(
            select(CompetenceCategory.id)
            .where(CompetenceCategory.is_active.is_(True))
            .order_by(CompetenceCategory.id)
            .limit(1)
        )
        if found is not None:
            return found
        category = CompetenceCategory(
            slug=f"job-factory-{uuid.uuid4().hex[:8]}",
            name_pl="Kategoria testowa",
            name_en="Test category",
            description="CI fixture",
        )
        db.add(category)
        await db.commit()
        return category.id


async def new_recruiter() -> int:
    """Aktywny rekruter — odbiorca przekazania do searchu."""
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    async with AsyncSessionLocal() as db:
        user = User(
            email=f"job-factory-rec-{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("not-a-login"),
            name="Job Factory Recruiter",
            role=UserRole.recruiter,
            roles=["recruiter"],
            is_active=True,
        )
        db.add(user)
        await db.commit()
        return user.id


async def complete_job_payload(
    client_id: int,
    *,
    recruiter_id: Optional[int] = None,
    **over: Any,
) -> dict[str, Any]:
    """Ładunek ``POST /api/jobs``, który przechodzi bramkę przekazania.

    ``over`` nadpisuje pola najwyższego poziomu (np. ``title``, ``tac_id``,
    ``champion_profile``). Bez ``recruiter_id`` zakłada świeżego rekrutera.
    """
    if recruiter_id is None:
        recruiter_id = await new_recruiter()
    payload: dict[str, Any] = {
        "title": f"Python Developer {uuid.uuid4().hex[:6]}",
        "client_id": client_id,
        "auto_suggest_cc": False,
        "competence_category_id": await competence_category_id(),
        "remote_policy": "remote",
        "rate_budget_hourly": 150,
        "headcount": 1,
        "deadline_not_provided": True,
        "hiring_manager": {"not_provided": True},
        "champion_profile": ready_champion(),
        "handoff": {"assignment_mode": "manual", "recruiter_id": recruiter_id},
    }
    payload.update(over)
    return payload


async def purge_job(job_id: int) -> None:
    """Usuń rekrutację z testu razem z wierszami Priority Work (RESTRICT)."""
    from app.models.job import Job
    from app.models.recruitment_priority import (
        RecruitmentPriorityAssignment,
        RecruitmentPriorityDemand,
        RecruitmentPriorityException,
    )

    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(RecruitmentPriorityException).where(
                RecruitmentPriorityException.job_id == job_id
            )
        )
        await db.execute(
            delete(RecruitmentPriorityAssignment).where(
                RecruitmentPriorityAssignment.job_id == job_id
            )
        )
        await db.execute(
            delete(RecruitmentPriorityDemand).where(
                RecruitmentPriorityDemand.job_id == job_id
            )
        )
        job = await db.get(Job, job_id)
        if job is not None:
            await db.delete(job)
        await db.commit()


# Profil Championa w kształcie ZAPISANYM (bez wierszy wymagań) — dla rekrutacji
# zakładanych wprost w bazie, które test potem otwiera ponownie albo
# przekazuje do searchu.
READY_STORED_CHAMPION: dict[str, Any] = {
    "project": {"about": "Platforma płatności B2B dla banku — rozwój usług."},
    "screening_questions": copy.deepcopy(READY_CHAMPION["screening_questions"]),
    "stack": {"must": [{"name": "Python"}], "critical": []},
    "basics": {"rate_value": 150, "work_mode": "zdalnie"},
    "search": {"requirements": [["Python"]]},
}


async def make_job_ready(job_id: int) -> None:
    """Domknij bramkę przekazania na rekrutacji założonej wprost w bazie:
    Champion, rubryki i decyzje (hiring manager, termin, kategoria)."""
    from app.models.job import Job, RemotePolicy

    category_id = await competence_category_id()
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        job.champion_profile = copy.deepcopy(READY_STORED_CHAMPION)
        job.remote_policy = RemotePolicy.remote
        job.rate_budget_hourly = 150
        job.must_skills = [{"name": "Python"}]
        job.competence_category_id = job.competence_category_id or category_id
        job.hiring_manager_not_provided = True
        job.deadline_not_provided = True
        job.headcount = job.headcount or 1
        await db.commit()
