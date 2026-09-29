"""Biblioteka ról „po ludzku” (migracja 0403).

* ``GET /api/role-profiles`` — lista ról z liczbą rekrutacji.
* ``GET /api/role-profiles/{id}`` — rola, statystyki z historii (bez stawek)
  i historia poprawek.
* ``PUT /api/role-profiles/{id}`` — poprawka opisu: admin i Head of
  Recruitment (decyzja Artura 29.09.2026). Zapis ustawia ``origin=manual``.

Uwaga: moduł bez ``from __future__ import annotations``.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, HeadOfRecruitmentPlus, get_db
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.models.job import Job
from app.models.plain_knowledge import RoleProfile
from app.services.plain_knowledge import library, view

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)


@router.get("/role-profiles")
async def list_role_profiles(
    current_user: CurrentUser,
    q: Optional[str] = Query(None, max_length=100),
    db: AsyncSession = Depends(get_db),
):
    jobs = (
        select(Job.role_profile_id, func.count(Job.id).label("n"))
        .where(Job.role_profile_id.is_not(None))
        .group_by(Job.role_profile_id)
        .subquery()
    )
    stmt = (
        select(RoleProfile, func.coalesce(jobs.c.n, 0))
        .outerjoin(jobs, jobs.c.role_profile_id == RoleProfile.id)
        .order_by(func.coalesce(jobs.c.n, 0).desc(), RoleProfile.name)
    )
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(RoleProfile.name.ilike(like), RoleProfile.slug.ilike(like))
        )
    rows = (await db.execute(stmt.limit(500))).all()
    return {
        "items": [
            {
                "id": role.id,
                "slug": role.slug,
                "name": role.name,
                "summary": role.summary,
                "origin": role.origin,
                "status": role.status,
                "jobs": int(n or 0),
                "updated_at": role.updated_at,
            }
            for role, n in rows
        ]
    }


async def _role_detail(db: AsyncSession, role: RoleProfile) -> dict:
    return {
        **view.role_payload(role),
        "stats": await view.role_stats(db, role.id),
        "history": await library.history(db, "role", role.id),
    }


@router.get("/role-profiles/{role_id}")
async def get_role_profile(
    role_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    role = await db.get(RoleProfile, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Nie ma takiej roli.")
    return await _role_detail(db, role)


class RoleProfileUpdate(BaseModel):
    name: Optional[str] = None
    summary: Optional[str] = None
    example: Optional[str] = None
    day_to_day: Optional[list[str]] = None
    candidate_questions: Optional[list[str]] = None
    typical_skills: Optional[list[str]] = None


@router.put("/role-profiles/{role_id}")
async def update_role_profile(
    role_id: int,
    payload: RoleProfileUpdate,
    current_user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    role = await db.get(RoleProfile, role_id, with_for_update=True)
    if role is None:
        raise HTTPException(status_code=404, detail="Nie ma takiej roli.")
    changed = await library.apply_changes(
        db,
        role,
        "role",
        library.ROLE_FIELDS,
        payload.model_dump(exclude_unset=True),
        current_user,
    )
    if changed:
        await db.commit()
    role = await db.get(RoleProfile, role_id, populate_existing=True)
    return await _role_detail(db, role)
