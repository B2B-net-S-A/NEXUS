"""„Champion po ludzku” — widok rekrutacji i wybór roli (migracja 0403).

* ``GET /api/jobs/{job_id}/plain-brief`` — blok „Po ludzku” i ściąga do rozmowy:
  teksty rekrutacji, słowniczek stacku, rola ze statystykami (bez stawek)
  i opis klienta. Tylko odczyt: nic nie zapisuje i nie woła AI; ``stale``
  mówi, że profil zmienił się od generacji.
* ``PUT /api/jobs/{job_id}/role-profile`` — admin i Head of Recruitment
  przypinają rolę z biblioteki ręcznie (automat jej potem nie zmienia).

Odświeżenie (płatny model) jest w ``plain_brief_refresh.py`` — osobny moduł
z limitem żądań.

Uwaga: moduł bez ``from __future__ import annotations`` — FastAPI czyta
adnotacje ciała w czasie rejestracji trasy.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, HeadOfRecruitmentPlus, get_db
from app.api.recruitment_access import ensure_job_read_access
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.models.job import Job
from app.models.plain_knowledge import RoleProfile
from app.models.user import UserRole
from app.services.plain_knowledge import view

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)


def is_previewing(request: Request) -> bool:
    return getattr(request.state, "impersonator_id", None) is not None


def can_change_role(user) -> bool:  # noqa: ANN001
    return user.has_any_role(UserRole.admin, UserRole.head_of_recruitment)


async def load_job(db: AsyncSession, user, job_id: int) -> Job:  # noqa: ANN001
    await ensure_job_read_access(db, user, job_id)
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Rekrutacja nie istnieje.")
    return job


@router.get("/jobs/{job_id}/plain-brief")
async def get_plain_brief(
    job_id: int,
    request: Request,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    job = await load_job(db, current_user, job_id)
    return await view.build_view(
        db,
        job,
        can_refresh=not is_previewing(request),
        can_change_role=can_change_role(current_user) and not is_previewing(request),
    )


class RoleProfileAssignment(BaseModel):
    role_profile_id: Optional[int] = None


@router.put("/jobs/{job_id}/role-profile")
async def set_job_role_profile(
    job_id: int,
    payload: RoleProfileAssignment,
    request: Request,
    current_user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    job = await load_job(db, current_user, job_id)
    if payload.role_profile_id is not None:
        role = await db.get(RoleProfile, payload.role_profile_id)
        if role is None:
            raise HTTPException(
                status_code=422, detail="Nie ma takiej roli w bibliotece."
            )
    job = await db.get(Job, job_id, with_for_update=True, populate_existing=True)
    job.role_profile_id = payload.role_profile_id
    # Wyczyszczenie roli oddaje wybór automatowi.
    job.role_profile_source = "manual" if payload.role_profile_id else None
    await db.commit()
    job = await db.get(Job, job_id, populate_existing=True)
    return await view.build_view(
        db, job, can_refresh=not is_previewing(request), can_change_role=True
    )
