"""Scoring weight profiles API (Phase D1).

Admin-only CRUD. Profiles are validated so the 5 layers sum to 100.
Scope resolution (user → client → global) is done by the scoring engine; this
module just persists, lists, and returns profiles.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.core.database import get_db
from app.models.scoring_weight_profile import ScoringWeightProfile
from app.models.user import User, UserRole

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────────────


class WeightsPayload(BaseModel):
    semantic: float = Field(ge=0, le=100)
    skills: float = Field(ge=0, le=100)
    salary: float = Field(ge=0, le=100)
    location: float = Field(ge=0, le=100)
    availability: float = Field(ge=0, le=100)
    champion_fit: float = Field(ge=0, le=100)

    @model_validator(mode="before")
    @classmethod
    def _upgrade_legacy_five_weights(cls, data):  # type: ignore[no-untyped-def]
        if not isinstance(data, dict) or "champion_fit" in data:
            return data
        keys = ("semantic", "skills", "salary", "location", "availability")
        try:
            values = [float(data[key]) for key in keys]
        except (KeyError, TypeError, ValueError):
            return data
        if abs(sum(values) - 100.0) > 0.01:
            return data
        upgraded = dict(data)
        first_four = [round(value * 0.9, 2) for value in values[:4]]
        for key, value in zip(keys[:4], first_four, strict=True):
            upgraded[key] = value
        upgraded["availability"] = round(90.0 - sum(first_four), 2)
        upgraded["champion_fit"] = 10.0
        return upgraded

    @model_validator(mode="after")
    def _sum_to_100(self) -> "WeightsPayload":
        total = sum(
            (
                self.semantic,
                self.skills,
                self.salary,
                self.location,
                self.availability,
                self.champion_fit,
            )
        )
        if abs(total - 100.0) > 0.01:
            raise ValueError(f"weights must sum to 100 ±0.01, got {total}")
        return self


class ScoringWeightProfileCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    user_id: Optional[int] = None
    client_id: Optional[int] = None
    weights: WeightsPayload
    active: bool = True

    @model_validator(mode="after")
    def _single_scope(self) -> "ScoringWeightProfileCreate":
        if self.user_id is not None and self.client_id is not None:
            raise ValueError("profile scope must be user, client, or global")
        return self


class ScoringWeightProfileResponse(BaseModel):
    id: int
    name: str
    user_id: Optional[int]
    client_id: Optional[int]
    weights: dict
    active: bool
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Endpoints ────────────────────────────────────────────────────────────────


async def _deactivate_scope_and_invalidate(
    db: AsyncSession, *, user_id: int | None, client_id: int | None
) -> None:
    from app.models.match_score import CandidateJobMatchScore

    scope_filter = (
        ScoringWeightProfile.user_id == user_id,
        ScoringWeightProfile.client_id == client_id,
        ScoringWeightProfile.active.is_(True),
    )
    ids = list(
        (await db.scalars(select(ScoringWeightProfile.id).where(*scope_filter))).all()
    )
    if ids:
        await db.execute(
            update(ScoringWeightProfile)
            .where(ScoringWeightProfile.id.in_(ids))
            .values(active=False)
        )
        await db.execute(
            delete(CandidateJobMatchScore).where(
                CandidateJobMatchScore.profile_id.in_(ids)
            )
        )


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
    if payload.active:
        await _deactivate_scope_and_invalidate(
            db, user_id=payload.user_id, client_id=payload.client_id
        )
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
    if payload.active:
        await _deactivate_scope_and_invalidate(
            db, user_id=payload.user_id, client_id=payload.client_id
        )
    from app.models.match_score import CandidateJobMatchScore

    await db.execute(
        delete(CandidateJobMatchScore).where(
            CandidateJobMatchScore.profile_id == row.id
        )
    )
    row.name = payload.name
    row.user_id = payload.user_id
    row.client_id = payload.client_id
    row.weights = payload.weights.model_dump()
    row.active = payload.active
    row.version += 1
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
    from app.models.match_score import CandidateJobMatchScore

    await db.execute(
        delete(CandidateJobMatchScore).where(
            CandidateJobMatchScore.profile_id == row.id
        )
    )
    await db.delete(row)
    await db.commit()
