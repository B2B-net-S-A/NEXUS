"""
Talent Pools API — zarządzanie pulami talentów.
"""
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.models.candidate import Candidate
from app.models.talent_pool import TalentPool, TalentPoolMembership

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class TalentPoolCreate(BaseModel):
    name: str
    description: Optional[str] = None
    criteria: Optional[dict] = None


class TalentPoolOut(BaseModel):
    id: int
    name: str
    description: Optional[str]
    criteria: Optional[dict]
    created_by: Optional[int]
    created_at: datetime
    candidate_count: int

    class Config:
        from_attributes = True


class AddCandidateRequest(BaseModel):
    candidate_id: int


class CandidateInPoolOut(BaseModel):
    id: int
    name: str
    lastname: str
    email: Optional[str]
    location: Optional[str]
    competence_category: Optional[str]
    skills: Optional[list]
    status: str
    added_at: datetime

    class Config:
        from_attributes = True


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_pool_or_404(pool_id: int, db: AsyncSession) -> TalentPool:
    result = await db.execute(
        select(TalentPool)
        .options(selectinload(TalentPool.memberships))
        .where(TalentPool.id == pool_id)
    )
    pool = result.scalar_one_or_none()
    if not pool:
        raise HTTPException(status_code=404, detail="Pula talentów nie istnieje")
    return pool


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/talent-pools", response_model=list[TalentPoolOut])
async def list_talent_pools(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(TalentPool)
        .options(selectinload(TalentPool.memberships))
        .order_by(TalentPool.created_at.desc())
    )
    pools = result.scalars().all()

    return [
        TalentPoolOut(
            id=p.id,
            name=p.name,
            description=p.description,
            criteria=p.criteria,
            created_by=p.created_by,
            created_at=p.created_at,
            candidate_count=len(p.memberships),
        )
        for p in pools
    ]


@router.post("/talent-pools", response_model=TalentPoolOut, status_code=201)
async def create_talent_pool(
    data: TalentPoolCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    pool = TalentPool(
        name=data.name,
        description=data.description,
        criteria=data.criteria or {},
        created_by=current_user.id,
    )
    db.add(pool)
    await db.commit()
    await db.refresh(pool)

    return TalentPoolOut(
        id=pool.id,
        name=pool.name,
        description=pool.description,
        criteria=pool.criteria,
        created_by=pool.created_by,
        created_at=pool.created_at,
        candidate_count=0,
    )


@router.post("/talent-pools/{pool_id}/add", status_code=201)
async def add_candidate_to_pool(
    pool_id: int,
    data: AddCandidateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Verify pool exists
    pool = await _get_pool_or_404(pool_id, db)

    # Verify candidate exists
    cand_result = await db.execute(select(Candidate).where(Candidate.id == data.candidate_id))
    candidate = cand_result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Kandydat nie istnieje")

    # Check if already member
    existing = await db.execute(
        select(TalentPoolMembership).where(
            TalentPoolMembership.talent_pool_id == pool_id,
            TalentPoolMembership.candidate_id == data.candidate_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Kandydat jest już w tej puli")

    membership = TalentPoolMembership(
        talent_pool_id=pool_id,
        candidate_id=data.candidate_id,
        added_by=current_user.id,
    )
    db.add(membership)
    await db.commit()

    return {"message": "Kandydat dodany do puli", "pool_id": pool_id, "candidate_id": data.candidate_id}


@router.delete("/talent-pools/{pool_id}/remove/{candidate_id}", status_code=200)
async def remove_candidate_from_pool(
    pool_id: int,
    candidate_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(TalentPoolMembership).where(
            TalentPoolMembership.talent_pool_id == pool_id,
            TalentPoolMembership.candidate_id == candidate_id,
        )
    )
    membership = result.scalar_one_or_none()
    if not membership:
        raise HTTPException(status_code=404, detail="Kandydat nie jest w tej puli")

    await db.delete(membership)
    await db.commit()

    return {"message": "Kandydat usunięty z puli"}


@router.get("/talent-pools/{pool_id}/candidates")
async def list_pool_candidates(
    pool_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Verify pool
    pool_result = await db.execute(select(TalentPool).where(TalentPool.id == pool_id))
    pool = pool_result.scalar_one_or_none()
    if not pool:
        raise HTTPException(status_code=404, detail="Pula talentów nie istnieje")

    # Get memberships with candidates
    result = await db.execute(
        select(TalentPoolMembership, Candidate)
        .join(Candidate, TalentPoolMembership.candidate_id == Candidate.id)
        .where(TalentPoolMembership.talent_pool_id == pool_id)
        .order_by(TalentPoolMembership.added_at.desc())
    )
    rows = result.all()

    candidates = []
    for membership, candidate in rows:
        candidates.append({
            "id": candidate.id,
            "name": candidate.name,
            "lastname": candidate.lastname,
            "email": candidate.email,
            "location": candidate.location,
            "competence_category": candidate.competence_category,
            "skills": candidate.skills,
            "status": candidate.status.value if hasattr(candidate.status, 'value') else candidate.status,
            "added_at": membership.added_at.isoformat(),
        })

    return {
        "pool": {
            "id": pool.id,
            "name": pool.name,
            "description": pool.description,
            "candidate_count": len(candidates),
        },
        "candidates": candidates,
    }


@router.get("/talent-pools/for-candidate/{candidate_id}")
async def get_pools_for_candidate(
    candidate_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Zwraca listę pul, do których należy kandydat (do dropdownu)."""
    result = await db.execute(
        select(TalentPoolMembership.talent_pool_id)
        .where(TalentPoolMembership.candidate_id == candidate_id)
    )
    pool_ids = [r[0] for r in result.all()]
    return {"pool_ids": pool_ids}
