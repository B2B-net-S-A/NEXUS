"""Championi rekrutacji — lista pod plakietką statusu (decyzje Artura D1–D9, 15.10.2026).

* ``GET /api/jobs/{id}/champions`` — kto jest championem, ile miejsc, a dla
  Delivery Leada (admina, Head of Recruitment) także lista osób do wyboru
  (od „CV wysłane” wzwyż).
* ``PUT /api/jobs/{id}/champions`` — Delivery Lead zapisuje PEŁNĄ listę
  championów (pusta = zdejmij). Skutki liczy ``services/job_champions``.

Reguły: ``docs/claude/rekrutacja-tablica/podobne-rekrutacje-przepiecia-i-status-requestu.md``.

Uwaga: moduł bez ``from __future__ import annotations`` — FastAPI czyta
adnotacje ciała w czasie rejestracji trasy.
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RecruiterPlus, get_db
from app.api.job_similar import _CHAMPION_ROLES, _job
from app.api.recruitment_access import ensure_job_membership
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.models.job import Job
from app.services import job_champions
from app.services.recruitment_allocation import allocation_lock

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)

# Jedna rekrutacja ma najwyżej kilka osób u klienta; limit chroni przed
# przypadkowo wklejoną listą tysięcy identyfikatorów.
MAX_CHAMPIONS_PER_SAVE = 50


class JobChampionPersonOut(BaseModel):
    candidate_id: int
    name: str
    column: Optional[str] = None
    stage_label: Optional[str] = None
    marked_by_name: Optional[str] = None
    marked_at: Optional[datetime] = None


class JobChampionEligibleOut(BaseModel):
    candidate_id: int
    name: str
    column: Optional[str] = None
    stage_label: Optional[str] = None
    is_champion: bool = False


class JobChampionsViewOut(BaseModel):
    job_id: int
    can_edit: bool
    seats: int
    hired_count: int
    search_stopped: bool
    legacy_flag: bool
    work_state: Optional[str] = None
    champions: list[JobChampionPersonOut]
    eligible: list[JobChampionEligibleOut]
    changed: Optional[bool] = None
    work_state_changed: Optional[bool] = None


class JobChampionsSaveBody(BaseModel):
    # Pole wymagane: puste ciało nie może po cichu zdjąć wszystkich championów.
    candidate_ids: list[int] = Field(max_length=MAX_CHAMPIONS_PER_SAVE)


def _can_edit(user) -> bool:
    return user.has_any_role(*_CHAMPION_ROLES)


@router.get("/jobs/{job_id}/champions", response_model=JobChampionsViewOut)
async def get_job_champions(
    job_id: int,
    user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    job = await _job(db, user, job_id)
    return await job_champions.view(db, job, can_edit=_can_edit(user))


@router.put("/jobs/{job_id}/champions", response_model=JobChampionsViewOut)
async def save_job_champions(
    job_id: int,
    body: JobChampionsSaveBody,
    user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    if not _can_edit(user):
        raise HTTPException(
            403,
            "Championów wskazuje Delivery Lead (albo admin / Head of Recruitment).",
        )
    await _job(db, user, job_id)
    await ensure_job_membership(db, user, job_id)
    # Kolejność blokad jak na pulpicie i w automacie: przydział → rekrutacja.
    await allocation_lock(db)
    # `_job` wczytał wiersz przed blokadą — odczyt pod blokadą ma być świeży.
    job = await db.get(Job, job_id, with_for_update=True, populate_existing=True)
    if job is None:
        raise HTTPException(404, "Rekrutacja nie istnieje")
    try:
        result = await job_champions.set_champions(
            db, job, body.candidate_ids, actor_id=user.id
        )
    except job_champions.ChampionsError as exc:
        await db.rollback()
        raise HTTPException(exc.status, exc.detail) from exc
    await job_champions.notify_after_save(db, job=job, result=result, actor_id=user.id)
    await db.commit()
    await db.refresh(job)
    payload = await job_champions.view(db, job, can_edit=True)
    payload["changed"] = result.changed
    payload["work_state_changed"] = result.work_state_changed
    return payload
