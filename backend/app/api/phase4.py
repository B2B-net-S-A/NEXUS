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

from app.api.candidate_access import CandidateSearchAccess
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
    # Alert subscription — wymaga ``filters["api"]`` (parametry GET
    # /api/candidates wyliczone przez FE), bo skaner w tle odtwarza search
    # przez realny endpoint. Patrz app/tasks/saved_search_alerts.py.
    notify_new_matches: bool = False


class SavedSearchUpdate(BaseModel):
    name: Optional[str] = None
    filters: Optional[dict] = None
    shared: Optional[bool] = None
    description: Optional[str] = None
    # ``None`` means "no change"; pass ``0`` to clear (special-cased below).
    pinned_to_job_id: Optional[int] = None
    notify_new_matches: Optional[bool] = None


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
        "notify_new_matches": s.notify_new_matches,
        "unseen_count": s.unseen_count or 0,
        "last_viewed_at": s.last_viewed_at.isoformat() if s.last_viewed_at else None,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


def _has_api_params(filters: Optional[dict]) -> bool:
    return isinstance((filters or {}).get("api"), dict)


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
    * the user's own global searches (``pinned_to_job_id IS NULL``), plus
    * OTHER users' **shared** searches pinned to this job — this is how the
      DL-approved "rekomendowane wyszukiwanie" (champion profile) reaches
      every recruiter opening the job.

    Pass ``only_mine=true`` for the my-rows-only view in the global list.
    """
    from sqlalchemy import and_, or_

    q = select(SavedSearch)

    if pinned_to_job_id is not None:
        q = q.where(
            or_(
                and_(
                    SavedSearch.user_id == current_user.id,
                    or_(
                        SavedSearch.pinned_to_job_id == pinned_to_job_id,
                        SavedSearch.pinned_to_job_id.is_(None),
                    ),
                ),
                and_(
                    SavedSearch.shared.is_(True),
                    SavedSearch.pinned_to_job_id == pinned_to_job_id,
                ),
            )
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
        notify_new_matches=data.notify_new_matches,
    )
    if data.notify_new_matches:
        if not _has_api_params(data.filters):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Alert wymaga parametrów API w filters.api — zapisz"
                    " wyszukiwanie ponownie z aktualnej wersji aplikacji."
                ),
            )
        # V2: leave ``last_scanned_at`` NULL → the scanner's first pass seeds the
        # dedup log with current matchers (no alert) so only genuine transitions
        # into the match set fire later. Anchor the "Nowy" highlight to now so
        # the first notification click highlights exactly the alerted rows.
        from datetime import datetime, timezone

        ss.last_scanned_at = None
        ss.last_viewed_at = datetime.now(timezone.utc)
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
    payload = data.model_dump(exclude_unset=True)
    for k, v in payload.items():
        setattr(ss, k, v)
    # Validate only when THIS request turns alerts on — a rename of an old
    # search (filters without `api`) must not 400. A stale enabled search
    # without api params is simply skipped by the scanner.
    if payload.get("notify_new_matches") is True:
        if not _has_api_params(ss.filters):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Alert wymaga parametrów API w filters.api — włącz dzwonek"
                    " ponownie z aktualnej wersji aplikacji."
                ),
            )
        # V2: re-baseline on every enable — clear the watermark so the scanner
        # re-seeds the dedup log with current matchers (idempotent: ON CONFLICT
        # DO NOTHING) and never floods about candidates that already match.
        ss.last_scanned_at = None
        if ss.last_viewed_at is None:
            from datetime import datetime, timezone

            ss.last_viewed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(ss)
    return _ss_to_dict(ss)


@router.post("/saved-searches/{search_id}/viewed")
async def mark_saved_search_viewed(
    search_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Owner opened the saved search — reset the unseen badge and roll
    ``last_viewed_at`` forward. Returns the PREVIOUS ``last_viewed_at`` so the
    FE can highlight candidates created after it as "Nowy" (comparing against
    the new value would instantly un-highlight everything)."""
    from datetime import datetime, timezone

    ss = await db.scalar(
        select(SavedSearch).where(
            SavedSearch.id == search_id, SavedSearch.user_id == current_user.id
        )
    )
    if not ss:
        raise HTTPException(status_code=404, detail="Search not found")
    previous = ss.last_viewed_at.isoformat() if ss.last_viewed_at else None
    ss.last_viewed_at = datetime.now(timezone.utc)
    ss.unseen_count = 0
    await db.commit()
    return {"previous_viewed_at": previous}


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
    current_user: CandidateSearchAccess,
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
