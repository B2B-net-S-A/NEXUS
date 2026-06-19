"""
Talent Pools API — zarządzanie pulami talentów.
"""

from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_user
from app.models.user import User, UserRole
from app.models.candidate import Candidate
from app.models.talent_pool import TalentPool, TalentPoolMembership
from app.services.talent_pool_cc import (
    classify_pool_name_to_cc_slug,
    resolve_cc_id_for_pool_name,
)

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────


class TalentPoolCreate(BaseModel):
    name: str
    description: Optional[str] = None
    criteria: Optional[dict] = None
    # Pula osobista (migracja 0137). True = pula indywidualna usera (widoczna
    # dla zespołu, zarządzana tylko przez właściciela). False = pula firmowa.
    is_personal: bool = False


class TalentPoolOut(BaseModel):
    id: int
    name: str
    description: Optional[str]
    criteria: Optional[dict]
    created_by: Optional[int]
    created_at: datetime
    candidate_count: int
    # Phase 10 A2 — Competence Category (nullable for legacy pools).
    competence_category_id: Optional[int] = None
    competence_category_slug: Optional[str] = None
    # Pule osobiste (migracja 0137). `owner_id`/`owner_name` = właściciel puli
    # (czytane z relacji `creator`), używane przez zakładkę „Pule osobiste"
    # żeby pogrupować pule po właścicielu i oznaczyć je „pula <imię>".
    is_personal: bool = False
    owner_id: Optional[int] = None
    owner_name: Optional[str] = None

    class Config:
        from_attributes = True


class AddCandidateRequest(BaseModel):
    candidate_id: int


class BulkAddCandidatesRequest(BaseModel):
    candidate_ids: list[int]


class BulkAddResponse(BaseModel):
    pool_id: int
    requested: int
    added: int
    already_in_pool: int
    not_found: int


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


def _assert_can_modify_pool(pool: TalentPool, user: User) -> None:
    """Kto może zmieniać zawartość puli (dodawać/usuwać kandydatów).

    * Pula firmowa (``is_personal=False``) — każdy zalogowany user (zachowanie
      historyczne, pule są wspólnym zasobem zespołu).
    * Pula osobista (``is_personal=True``) — tylko właściciel (``created_by``)
      lub admin. Reszta zespołu widzi pulę, ale jej nie edytuje.
    """
    if (
        pool.is_personal
        and pool.created_by != user.id
        and not user.has_role(UserRole.admin)
    ):
        raise HTTPException(
            status_code=403,
            detail="To pula osobista innego użytkownika — możesz ją tylko przeglądać.",
        )


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("/talent-pools", response_model=list[TalentPoolOut])
async def list_talent_pools(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(TalentPool)
        .options(
            selectinload(TalentPool.memberships),
            selectinload(TalentPool.competence_category),
            selectinload(TalentPool.creator),
        )
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
            competence_category_id=p.competence_category_id,
            competence_category_slug=(
                p.competence_category.slug if p.competence_category else None
            ),
            is_personal=p.is_personal,
            owner_id=p.created_by,
            owner_name=(p.creator.name if p.creator else None),
        )
        for p in pools
    ]


@router.post("/talent-pools", response_model=TalentPoolOut, status_code=201)
async def create_talent_pool(
    data: TalentPoolCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Derive the Competence Category from the pool name so the /talents category
    # filter works for manually-created pools too (the create form doesn't ask
    # for a CC). Deterministic + dependency-free — see services/talent_pool_cc.
    # Pule osobiste grupujemy po właścicielu, nie po CC — pomijamy klasyfikację
    # (nazwy są dowolne: „Moi React seniorzy", „Do zaproszenia na meetup").
    cc_id = (
        None if data.is_personal else await resolve_cc_id_for_pool_name(db, data.name)
    )

    pool = TalentPool(
        name=data.name,
        description=data.description,
        criteria=data.criteria or {},
        competence_category_id=cc_id,
        is_personal=data.is_personal,
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
        competence_category_id=pool.competence_category_id,
        competence_category_slug=(
            classify_pool_name_to_cc_slug(pool.name)
            if pool.competence_category_id is not None
            else None
        ),
        is_personal=pool.is_personal,
        owner_id=pool.created_by,
        owner_name=current_user.name,
    )


@router.post("/talent-pools/{pool_id}/add", status_code=201)
async def add_candidate_to_pool(
    pool_id: int,
    data: AddCandidateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Verify pool exists + the user is allowed to modify it (osobiste = owner/admin)
    pool = await _get_pool_or_404(pool_id, db)
    _assert_can_modify_pool(pool, current_user)

    # Verify candidate exists
    cand_result = await db.execute(
        select(Candidate).where(Candidate.id == data.candidate_id)
    )
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

    return {
        "message": "Kandydat dodany do puli",
        "pool_id": pool_id,
        "candidate_id": data.candidate_id,
    }


@router.post(
    "/talent-pools/{pool_id}/bulk-add",
    status_code=200,
    response_model=BulkAddResponse,
)
async def bulk_add_candidates_to_pool(
    pool_id: int,
    data: BulkAddCandidatesRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Bulk-add wielu kandydatów do puli — idempotentne (skip already-in-pool).

    Zwraca summary z liczbą rzeczywiście dodanych vs duplikatów vs nieistniejących
    kandydatów. Używane przez floating bulk-action bar na liście /candidates
    (Phase „Otwartość na dodatkowe projekty" Faza 2.5).
    """
    pool = await _get_pool_or_404(pool_id, db)
    _assert_can_modify_pool(pool, current_user)

    if not data.candidate_ids:
        raise HTTPException(status_code=422, detail="candidate_ids cannot be empty")

    requested_ids = list(set(data.candidate_ids))

    # 1. Sprawdź którzy z requested_ids istnieją w bazie.
    existing_cand_result = await db.execute(
        select(Candidate.id).where(Candidate.id.in_(requested_ids))
    )
    existing_cand_ids = {row[0] for row in existing_cand_result.all()}
    not_found = len(requested_ids) - len(existing_cand_ids)

    # 2. Sprawdź którzy z istniejących już są w puli.
    already_member_result = await db.execute(
        select(TalentPoolMembership.candidate_id).where(
            TalentPoolMembership.talent_pool_id == pool_id,
            TalentPoolMembership.candidate_id.in_(existing_cand_ids),
        )
    )
    already_member_ids = {row[0] for row in already_member_result.all()}

    # 3. Dodaj brakujące memberships.
    to_add = existing_cand_ids - already_member_ids
    for cid in to_add:
        db.add(
            TalentPoolMembership(
                talent_pool_id=pool_id,
                candidate_id=cid,
                added_by=current_user.id,
            )
        )
    await db.commit()

    return BulkAddResponse(
        pool_id=pool_id,
        requested=len(requested_ids),
        added=len(to_add),
        already_in_pool=len(already_member_ids),
        not_found=not_found,
    )


@router.delete("/talent-pools/{pool_id}/remove/{candidate_id}", status_code=200)
async def remove_candidate_from_pool(
    pool_id: int,
    candidate_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Pula osobista — tylko właściciel/admin może usuwać kandydatów.
    pool = await _get_pool_or_404(pool_id, db)
    _assert_can_modify_pool(pool, current_user)

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


@router.delete("/talent-pools/{pool_id}", status_code=200)
async def delete_talent_pool(
    pool_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Usuń całą pulę talentów (kaskada usuwa memberships).

    * Pula osobista — właściciel lub admin.
    * Pula firmowa — tylko admin (ochrona wspólnego zasobu zespołu).
    * Pula Targu (``is_marketplace``) — nieusuwalna (singleton zarządzany przez
      marketplace_service).
    """
    pool = await _get_pool_or_404(pool_id, db)
    is_admin = current_user.has_role(UserRole.admin)

    if pool.is_marketplace:
        raise HTTPException(
            status_code=409, detail="Puli Targu kandydatów nie można usunąć."
        )

    if pool.is_personal:
        if pool.created_by != current_user.id and not is_admin:
            raise HTTPException(
                status_code=403,
                detail="Tylko właściciel lub admin może usunąć tę pulę.",
            )
    elif not is_admin:
        raise HTTPException(
            status_code=403,
            detail="Pulę firmową może usunąć tylko administrator.",
        )

    await db.delete(pool)
    await db.commit()

    return {"message": "Pula usunięta", "pool_id": pool_id}


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
        candidates.append(
            {
                "id": candidate.id,
                "name": candidate.name,
                "lastname": candidate.lastname,
                "email": candidate.email,
                "location": candidate.location,
                "competence_category": candidate.competence_category,
                "skills": candidate.skills,
                "status": candidate.status.value
                if hasattr(candidate.status, "value")
                else candidate.status,
                "added_at": membership.added_at.isoformat(),
                "source_event": membership.source_event,
                "source_job_id": membership.source_job_id,
            }
        )

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
        select(TalentPoolMembership.talent_pool_id).where(
            TalentPoolMembership.candidate_id == candidate_id
        )
    )
    pool_ids = [r[0] for r in result.all()]
    return {"pool_ids": pool_ids}
