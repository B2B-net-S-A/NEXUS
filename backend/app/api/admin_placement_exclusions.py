"""Admin: lista wykluczonych placementów (0343, decyzja C z 22.09.2026).

Tylko odczyt, wyłącznie admin (admin ma dostęp do każdej sekcji, więc trasa
spełnia kontrakt bramki sekcji). Wykluczenia powstają regułą — ręcznego
dodawania ani zdejmowania świadomie nie ma; reguła i jej uzasadnienie żyją
w ``app/services/placement_exclusions.py``.
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser
from app.core.database import get_db
from app.services.placement_exclusions import (
    REASON_LABELS_PL,
    SERIES_THRESHOLD,
    list_exclusions,
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
