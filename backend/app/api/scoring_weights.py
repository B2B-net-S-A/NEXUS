"""Scoring weight profiles API (Phase D1).

Admin-only CRUD. Profiles are validated so the layers sum to 100 (six layers;
``champion_fit`` optional and defaults to 0 for backward-compatible payloads).
Scope resolution (user → client → global) is done by the scoring engine; this
module just persists, lists, and returns profiles.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.core.database import get_db
from app.models.scoring_weight_profile import ScoringWeightProfile
from app.models.user import User, UserRole
from app.services.match_score_cache import mark_stale_for_profile

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────────────


class WeightsPayload(BaseModel):
    semantic: int = Field(ge=0, le=100)
    skills: int = Field(ge=0, le=100)
    salary: int = Field(ge=0, le=100)
    location: int = Field(ge=0, le=100)
    availability: int = Field(ge=0, le=100)
    # Sixth engine layer. Optional for backward compatibility: a legacy 5-weight
    # payload (champion_fit defaults to 0) must still sum to 100 exactly as
    # before. New clients send all six. Validated last so the sum sees every
    # layer — this closes the champion-budget-110 gap at the API boundary.
    champion_fit: int = Field(0, ge=0, le=100)

    # `model_validator(mode="after")`, NIE `field_validator("champion_fit")`.
    # Walidator POLA w Pydantic v2 nie odpala się, gdy pola NIE MA w żądaniu
    # i wchodzi wartość domyślna (bez `validate_default=True`) — a `champion_fit`
    # jest opcjonalne właśnie po to, żeby stary, pięciowagowy payload dalej
    # działał. Suma nie była więc sprawdzana DOKŁADNIE w tym przypadku, którego
    # komentarz wyżej broni: `POST /api/scoring-weights` z pięcioma wagami
    # sumującymi się do 99 zwracał 201 i zapisywał profil.
    #
    # To nie jest kosmetyka walidacji: `WeightProfile.from_record` bierze te
    # liczby wprost jako budżety warstw, więc profil o sumie 99 liczy KAŻDY
    # match score względem innego maksimum niż 100, którego oczekują progi
    # i procenty w UI. Bramka API była tu jedynym miejscem, które tego pilnuje.
    @model_validator(mode="after")
    def _sum_to_100(self) -> "WeightsPayload":
        s = (
            self.semantic
            + self.skills
            + self.salary
            + self.location
            + self.availability
            + self.champion_fit
        )
        if s != 100:
            raise ValueError(f"weights must sum to 100, got {s}")
        return self


class ScoringWeightProfileCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    user_id: Optional[int] = None
    client_id: Optional[int] = None
    weights: WeightsPayload
    active: bool = True


class ScoringWeightProfileResponse(BaseModel):
    id: int
    name: str
    user_id: Optional[int]
    client_id: Optional[int]
    weights: dict
    active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("", response_model=list[ScoringWeightProfileResponse])
async def list_profiles(
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.delivery_lead)),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        (
            await db.execute(
                select(ScoringWeightProfile).order_by(ScoringWeightProfile.name.asc())
            )
        )
        .scalars()
        .all()
    )
    return rows


@router.post(
    "", response_model=ScoringWeightProfileResponse, status_code=status.HTTP_201_CREATED
)
async def create_profile(
    payload: ScoringWeightProfileCreate,
    current_user: User = Depends(require_roles(UserRole.admin)),
    db: AsyncSession = Depends(get_db),
):
    if await db.scalar(
        select(ScoringWeightProfile.id).where(ScoringWeightProfile.name == payload.name)
    ):
        raise HTTPException(status_code=409, detail="profile name already exists")
    row = ScoringWeightProfile(
        name=payload.name,
        user_id=payload.user_id,
        client_id=payload.client_id,
        weights=payload.weights.model_dump(),
        active=payload.active,
    )
    db.add(row)
    # The name check above is racy: two concurrent creates both pass it, then
    # the UNIQUE constraint (uq_scoring_weight_profiles_name) rejects the second
    # at commit. Catch it so the loser gets the same 409 as the read path,
    # never a 500.
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="profile name already exists"
        ) from None
    await db.refresh(row)
    return row


@router.patch("/{profile_id}", response_model=ScoringWeightProfileResponse)
async def update_profile(
    profile_id: int,
    payload: ScoringWeightProfileCreate,
    current_user: User = Depends(require_roles(UserRole.admin)),
    db: AsyncSession = Depends(get_db),
):
    row = await db.scalar(
        select(ScoringWeightProfile).where(ScoringWeightProfile.id == profile_id)
    )
    if not row:
        raise HTTPException(status_code=404, detail="not found")
    row.name = payload.name
    row.user_id = payload.user_id
    row.client_id = payload.client_id
    row.weights = payload.weights.model_dump()
    row.active = payload.active
    # Editing weights in place would otherwise keep serving old-weight cached
    # scores for this profile_id (AI-P0-06 a) — invalidate them in the same txn.
    await mark_stale_for_profile(db, profile_id)
    await db.commit()
    await db.refresh(row)
    return row


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_profile(
    profile_id: int,
    current_user: User = Depends(require_roles(UserRole.admin)),
    db: AsyncSession = Depends(get_db),
):
    row = await db.scalar(
        select(ScoringWeightProfile).where(ScoringWeightProfile.id == profile_id)
    )
    if not row:
        raise HTTPException(status_code=404, detail="not found")
    # Drop any cached scores computed under this profile before it disappears
    # (AI-P0-06 a) — otherwise they linger as dead, un-recomputable rows.
    await mark_stale_for_profile(db, profile_id)
    await db.delete(row)
    await db.commit()
