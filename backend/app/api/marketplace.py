"""Targ kandydatów — HTTP API.

Endpoints:
- GET    /api/marketplace/pool                       — metadata singletona
- GET    /api/marketplace/candidates                 — paginowana lista
- POST   /api/marketplace/candidates/{id}/add        — ręczny wrzut
- DELETE /api/marketplace/candidates/{id}            — zdjęcie z targu
- GET    /api/marketplace/candidates/{id}/matches    — top-K current matchów

Auth:
- Read (GET)        → CandidateSearchAccess (role operacyjne; viewer 403 — M2 PR1)
- Write (POST/DELETE) → RecruiterPlus (admin / delivery_lead / tac / recruiter /
  sourcer). Wrzut na targ to akcja sourcingowa — rekruter/sourcer, który ma
  wolnego kandydata, musi móc go wystawić (read-only `user`/klient/QC nie).
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import CandidateSearchAccess
from app.api.deps import RecruiterPlus, get_db
from app.api.section_access import SOURCING_SECTION_DEPENDENCIES
from app.core.config import settings
from app.services.marketplace_service import (
    add_candidate_to_marketplace,
    ensure_marketplace_pool,
    list_marketplace_candidates,
    remove_candidate_from_marketplace,
    scan_candidate_for_top_jobs,
)

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=SOURCING_SECTION_DEPENDENCIES)


# ── Schemas ──────────────────────────────────────────────────────────────


class UserBrief(BaseModel):
    id: int
    name: str
    email: str

    class Config:
        from_attributes = True


class MarketplaceCandidateOut(BaseModel):
    id: int
    name: str
    lastname: str
    email: Optional[str] = None
    avatar_url: Optional[str] = None
    location: Optional[str] = None
    competence_category: Optional[str] = None
    availability_status: str
    skills: Optional[list] = None
    added_at: datetime
    marketplace_until: Optional[date] = None
    source_event: Optional[str] = None
    owner: Optional[UserBrief] = None


class MarketplaceListResponse(BaseModel):
    items: list[MarketplaceCandidateOut]
    total: int
    page: int
    page_size: int


class AddToMarketplaceRequest(BaseModel):
    marketplace_until: Optional[date] = Field(
        default=None,
        description=(
            "Data wygaśnięcia ręcznego wrzutu. Domyślnie = dziś + "
            "MARKETPLACE_DEFAULT_DURATION_DAYS (30)."
        ),
    )


class AddToMarketplaceResponse(BaseModel):
    candidate_id: int
    marketplace_until: date
    source_event: str


class MatchRow(BaseModel):
    job_id: int
    title: str
    client_id: Optional[int] = None
    total_score: float
    seniority: Optional[str] = None
    matching_must: list[str] = []
    gap_must: list[str] = []


class MarketplaceMatchesResponse(BaseModel):
    candidate_id: int
    computed_at: datetime
    matches: list[MatchRow]


class MarketplacePoolOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    candidate_count: int
    is_marketplace: bool
    created_at: datetime
    # Próg alertowania, wystawiony NA ZEWNĄTRZ zamiast powtarzany w UI.
    # Frontend miał go zahardkodowanego w dwóch miejscach jako 70, gdy backend
    # od dawna używał 80 — rekruter czytał obietnicę, której system nie
    # dotrzymywał, i nie miał jak tego zauważyć.
    score_threshold: int


# ── Routes ───────────────────────────────────────────────────────────────


@router.get("/marketplace/pool", response_model=MarketplacePoolOut)
async def get_marketplace_pool(
    current_user: CandidateSearchAccess,
    db: AsyncSession = Depends(get_db),
):
    """Metadata singletona targu (debug/admin)."""
    pool = await ensure_marketplace_pool(db)
    await db.commit()
    # Policz członków (bez ładowania wszystkich)
    from sqlalchemy import func, select
    from app.models.talent_pool import TalentPoolMembership

    count = await db.execute(
        select(func.count(TalentPoolMembership.id)).where(
            TalentPoolMembership.talent_pool_id == pool.id
        )
    )
    return MarketplacePoolOut(
        id=pool.id,
        name=pool.name,
        description=pool.description,
        candidate_count=count.scalar_one() or 0,
        is_marketplace=pool.is_marketplace,
        created_at=pool.created_at,
        score_threshold=int(settings.MARKETPLACE_SCORE_THRESHOLD),
    )


@router.get("/marketplace/candidates", response_model=MarketplaceListResponse)
async def list_candidates(
    current_user: CandidateSearchAccess,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    q: Optional[str] = Query(None, description="Szukaj po imieniu/nazwisku/email"),
    source_event: Optional[str] = Query(
        None,
        description=(
            "Filtruj po źródle wpisu: 'manual' (ręczny wrzut z TTL), "
            "'auto_availability' (auto-sync z availability_status). "
            "Pomiń żeby dostać wszystkie."
        ),
    ),
):
    """Paginowana lista kandydatów w targu."""
    limit = page_size
    offset = (page - 1) * page_size
    rows, total = await list_marketplace_candidates(
        db, limit=limit, offset=offset, q=q, source_event=source_event
    )
    await db.commit()

    # Hydratacja ownerów
    from sqlalchemy import select
    from app.models.user import User

    owner_ids = {c.created_by for _, c in rows if c.created_by is not None}
    owner_map: dict[int, UserBrief] = {}
    if owner_ids:
        res = await db.execute(select(User).where(User.id.in_(owner_ids)))
        for u in res.scalars().all():
            owner_map[u.id] = UserBrief(id=u.id, name=u.name, email=u.email)

    items = [
        MarketplaceCandidateOut(
            id=c.id,
            name=c.name,
            lastname=c.lastname,
            email=c.email,
            avatar_url=c.avatar_url,
            location=c.location,
            competence_category=c.competence_category,
            availability_status=(
                c.availability_status.value
                if hasattr(c.availability_status, "value")
                else c.availability_status
            ),
            skills=c.skills if isinstance(c.skills, list) else None,
            added_at=m.added_at,
            marketplace_until=m.marketplace_until,
            source_event=m.source_event,
            owner=owner_map.get(c.created_by) if c.created_by else None,
        )
        for m, c in rows
    ]
    return MarketplaceListResponse(
        items=items, total=total, page=page, page_size=page_size
    )


@router.post(
    "/marketplace/candidates/{candidate_id}/add",
    response_model=AddToMarketplaceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_to_marketplace(
    candidate_id: int,
    data: AddToMarketplaceRequest,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    """Ręczny wrzut kandydata na targ."""
    try:
        membership = await add_candidate_to_marketplace(
            db,
            candidate_id=candidate_id,
            added_by=current_user.id,
            marketplace_until=data.marketplace_until,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    await db.commit()
    assert membership.marketplace_until is not None
    return AddToMarketplaceResponse(
        candidate_id=candidate_id,
        marketplace_until=membership.marketplace_until,
        source_event=membership.source_event or "manual",
    )


@router.delete(
    "/marketplace/candidates/{candidate_id}",
    status_code=status.HTTP_200_OK,
)
async def remove_from_marketplace(
    candidate_id: int,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    """Zdjęcie kandydata z targu."""
    removed = await remove_candidate_from_marketplace(db, candidate_id=candidate_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Kandydat nie jest na targu")
    await db.commit()
    return {"message": "Kandydat zdjęty z targu", "candidate_id": candidate_id}


@router.get(
    "/marketplace/candidates/{candidate_id}/matches",
    response_model=MarketplaceMatchesResponse,
)
async def get_candidate_matches(
    candidate_id: int,
    current_user: CandidateSearchAccess,
    db: AsyncSession = Depends(get_db),
):
    """Top-K aktualnych matchów dla kandydata w targu (UI expansion row)."""
    from datetime import timezone

    matches = await scan_candidate_for_top_jobs(candidate_id, db)
    rows = [
        MatchRow(
            job_id=m.job_id,
            title=m.title,
            client_id=m.client_id,
            total_score=m.total_score,
            seniority=m.seniority,
            matching_must=m.matching_must,
            gap_must=m.gap_must,
        )
        for m in matches
    ]
    return MarketplaceMatchesResponse(
        candidate_id=candidate_id,
        computed_at=datetime.now(timezone.utc),
        matches=rows,
    )
