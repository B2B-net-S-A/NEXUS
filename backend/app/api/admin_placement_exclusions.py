"""Admin: wykluczone placementy (0343, decyzja C z 22.09.2026).

Wyłącznie admin (admin ma dostęp do każdej sekcji, więc trasy spełniają
kontrakt bramki sekcji). Większość wykluczeń powstaje regułą, a reguła i jej
uzasadnienie żyją w ``app/services/placement_exclusions.py``. Od 0650
(decyzja Artura 05.11.2026) admin dodaje też pojedynczą parę ręcznie, z
powodem, i tylko takie wykluczenie może zdjąć.
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser
from app.core.database import get_db
from app.services.placement_exclusions import (
    NOTE_MAX_LENGTH,
    REASON_LABELS_PL,
    SERIES_THRESHOLD,
    ManualExclusionError,
    add_manual_exclusion,
    invalidate_placement_caches,
    list_exclusions,
    remove_manual_exclusion,
)

router = APIRouter()


class PlacementExclusionItem(BaseModel):
    id: int
    candidate_id: int
    candidate_name: str
    job_id: int
    job_title: Optional[str] = None
    client_id: Optional[int] = None
    client_name: Optional[str] = None
    hired_at: Optional[datetime] = None
    moved_by_user_id: Optional[int] = None
    moved_by_name: Optional[str] = None
    reason: str
    reason_label: str
    had_cv_sent: Optional[bool] = None
    series_day: Optional[str] = None
    series_size: Optional[int] = None
    rule_version: int
    detected_at: datetime
    note: Optional[str] = None
    added_by_name: Optional[str] = None


class PlacementExclusionList(BaseModel):
    items: list[PlacementExclusionItem]
    total: int
    series_threshold: int
    reasons: dict[str, str]


@router.get("/placement-exclusions", response_model=PlacementExclusionList)
async def get_placement_exclusions(
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> PlacementExclusionList:
    items = [PlacementExclusionItem(**row) for row in await list_exclusions(db)]
    return PlacementExclusionList(
        items=items,
        total=len(items),
        series_threshold=SERIES_THRESHOLD,
        reasons=dict(REASON_LABELS_PL),
    )


class ManualExclusionIn(BaseModel):
    candidate_id: int = Field(gt=0)
    job_id: int = Field(gt=0)
    note: str = Field(min_length=1, max_length=NOTE_MAX_LENGTH)


class ManualExclusionOut(BaseModel):
    id: int


@router.post(
    "/placement-exclusions", response_model=ManualExclusionOut, status_code=201
)
async def post_placement_exclusion(
    body: ManualExclusionIn,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> ManualExclusionOut:
    try:
        exclusion_id = await add_manual_exclusion(
            db,
            candidate_id=body.candidate_id,
            job_id=body.job_id,
            actor_id=admin.id,
            note=body.note,
        )
    except ManualExclusionError as err:
        raise HTTPException(status_code=err.status_code, detail=err.message)
    await db.commit()
    await invalidate_placement_caches()
    return ManualExclusionOut(id=exclusion_id)


@router.delete("/placement-exclusions/{exclusion_id}", status_code=204)
async def delete_placement_exclusion(
    exclusion_id: int,
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        await remove_manual_exclusion(db, exclusion_id)
    except ManualExclusionError as err:
        raise HTTPException(status_code=err.status_code, detail=err.message)
    await db.commit()
    await invalidate_placement_caches()
