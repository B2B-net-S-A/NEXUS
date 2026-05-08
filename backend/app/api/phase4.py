"""
Phase 4 endpoints:

- CRUD  /api/saved-searches       named filter presets per user
- GET   /api/match-history/{job_id}/{candidate_id}   audit row
- POST  /api/match-history         append audit row (internal-use; optional)
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.database import get_db
from app.models.saved_search import MatchHistory, SavedSearch

router = APIRouter()


# ── Saved searches ──────────────────────────────────────────────────────────


class SavedSearchCreate(BaseModel):
    name: str = Field(..., max_length=100)
    entity: str = Field(..., max_length=40)
    filters: dict
    shared: bool = False
    description: Optional[str] = Field(None, max_length=255)
    pinned_to_job_id: Optional[int] = None


class SavedSearchUpdate(BaseModel):
    name: Optional[str] = None
    filters: Optional[dict] = None
    shared: Optional[bool] = None
    description: Optional[str] = None
    # ``None`` means "no change"; pass ``0`` to clear (special-cased below).
    pinned_to_job_id: Optional[int] = None


class SavedSearchOut(BaseModel):
    id: int
    user_id: int
    name: str
    entity: str
    filters: dict
    shared: bool
    description: Optional[str]
    pinned_to_job_id: Optional[int] = None
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


def _ss_to_dict(s: SavedSearch) -> dict:
    return {
        "id": s.id,
        "user_id": s.user_id,
        "name": s.name,
        "entity": s.entity,
        "filters": s.filters or {},
        "shared": s.shared,
        "description": s.description,
        "pinned_to_job_id": s.pinned_to_job_id,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


@router.get("/saved-searches")
async def list_saved_searches(
    current_user: CurrentUser,
    entity: Optional[str] = Query(None),
    pinned_to_job_id: Optional[int] = Query(
        None,
        description=(
            "Filter to searches pinned to this job (plus the user's own global"
            " ones). Used by the 'Wyszukaj manualnie' tab in /jobs/[id]."
        ),
    ),
    only_mine: bool = Query(
        False, description="If true, exclude shared-by-others entries."
    ),
    db: AsyncSession = Depends(get_db),
):
    """List my saved searches + ones shared by others (optionally by entity).

    When ``pinned_to_job_id`` is set, returns the union of:

    * the user's searches with ``pinned_to_job_id == job_id``, plus
    * the user's own global searches (``pinned_to_job_id IS NULL``).

    Other users' shared searches are excluded in this mode — pinning is
    inherently per-user state. Pass ``only_mine=true`` for the same exclusion
    in the global list.
    """
    from sqlalchemy import or_

    q = select(SavedSearch)

    if pinned_to_job_id is not None:
        q = q.where(
            SavedSearch.user_id == current_user.id,
            or_(
                SavedSearch.pinned_to_job_id == pinned_to_job_id,
                SavedSearch.pinned_to_job_id.is_(None),
            ),
        )
    elif only_mine:
        q = q.where(SavedSearch.user_id == current_user.id)
    else:
        q = q.where(
            or_(
                SavedSearch.user_id == current_user.id,
                SavedSearch.shared.is_(True),
            )
        )

    if entity:
        q = q.where(SavedSearch.entity == entity)
    q = q.order_by(SavedSearch.updated_at.desc())
    rows = (await db.execute(q)).scalars().all()
    return [_ss_to_dict(r) for r in rows]


@router.post("/saved-searches", status_code=status.HTTP_201_CREATED)
async def create_saved_search(
    data: SavedSearchCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    # Soft cap so a single user can't fill the table with thousands of saved
    # filter presets — matches the planning brief constraint.
    SAVED_SEARCH_PER_USER_CAP = 50
    from sqlalchemy import func as _func

    existing_count = (
        await db.execute(
            select(_func.count(SavedSearch.id)).where(
                SavedSearch.user_id == current_user.id
            )
        )
    ).scalar() or 0
    if existing_count >= SAVED_SEARCH_PER_USER_CAP:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Limit zapisanych wyszukiwań ({SAVED_SEARCH_PER_USER_CAP})"
                " osiągnięty. Usuń któreś, aby utworzyć nowe."
            ),
        )

    ss = SavedSearch(
        user_id=current_user.id,
        name=data.name,
        entity=data.entity,
        filters=data.filters,
        shared=data.shared,
        description=data.description,
        pinned_to_job_id=data.pinned_to_job_id,
    )
    db.add(ss)
    await db.commit()
    await db.refresh(ss)
    return _ss_to_dict(ss)


@router.patch("/saved-searches/{search_id}")
async def update_saved_search(
    search_id: int,
    data: SavedSearchUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    ss = await db.scalar(
        select(SavedSearch).where(
            SavedSearch.id == search_id, SavedSearch.user_id == current_user.id
        )
    )
    if not ss:
        raise HTTPException(status_code=404, detail="Search not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(ss, k, v)
    await db.commit()
    await db.refresh(ss)
    return _ss_to_dict(ss)


@router.delete("/saved-searches/{search_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_saved_search(
    search_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    ss = await db.scalar(
        select(SavedSearch).where(
            SavedSearch.id == search_id, SavedSearch.user_id == current_user.id
        )
    )
    if not ss:
        raise HTTPException(status_code=404, detail="Search not found")
    await db.delete(ss)
    await db.commit()


# ── Match history ───────────────────────────────────────────────────────────


@router.get("/match-history/{job_id}/{candidate_id}")
async def get_match_history(
    job_id: int,
    candidate_id: int,
    current_user: CurrentUser,
    limit: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    rows = await db.execute(
        select(MatchHistory)
        .where(
            MatchHistory.job_id == job_id,
            MatchHistory.candidate_id == candidate_id,
        )
        .order_by(MatchHistory.created_at.desc())
        .limit(limit)
    )
    return [
        {
            "id": r.id,
            "job_id": r.job_id,
            "candidate_id": r.candidate_id,
            "total_score": r.total_score,
            "breakdown": r.breakdown,
            "triggered_by": r.triggered_by,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows.scalars().all()
    ]


class MatchHistoryCreate(BaseModel):
    job_id: int
    candidate_id: int
    total_score: int
    breakdown: Optional[dict] = None


@router.post("/match-history", status_code=status.HTTP_201_CREATED)
async def log_match(
    data: MatchHistoryCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    mh = MatchHistory(
        job_id=data.job_id,
        candidate_id=data.candidate_id,
        total_score=data.total_score,
        breakdown=data.breakdown,
        triggered_by=current_user.id,
    )
    db.add(mh)
    await db.commit()
    await db.refresh(mh)
    return {
        "id": mh.id,
        "created_at": mh.created_at.isoformat() if mh.created_at else None,
    }
