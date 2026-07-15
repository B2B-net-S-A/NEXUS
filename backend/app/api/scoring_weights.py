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
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.core.database import get_db
from app.models.scoring_weight_profile import ScoringWeightProfile
from app.models.user import User, UserRole

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

    @field_validator("champion_fit")
    @classmethod
    def _sum_to_100(cls, v: int, info) -> int:  # type: ignore[no-untyped-def]
        s = (
            info.data.get("semantic", 0)
            + info.data.get("skills", 0)
            + info.data.get("salary", 0)
            + info.data.get("location", 0)
            + info.data.get("availability", 0)
            + v
        )
        if s != 100:
            raise ValueError(f"weights must sum to 100, got {s}")
        return v


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
    await db.commit()
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
    await db.delete(row)
    await db.commit()
