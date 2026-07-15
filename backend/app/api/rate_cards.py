"""API for rate cards (per client × role × seniority price lists)."""

from datetime import date as _date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DeliveryLeadPlus
from app.core.database import get_db
from app.models.client import Client
from app.models.rate_card import RateCard
from app.schemas.rate_card import (
    RateCardCreate,
    RateCardResponse,
    RateCardSuggestion,
    RateCardUpdate,
)

router = APIRouter()


def _midpoint(lo: Optional[int], hi: Optional[int]) -> Optional[int]:
    if lo is None and hi is None:
        return None
    if lo is None:
        return hi
    if hi is None:
        return lo
    return (lo + hi) // 2


@router.get("", response_model=List[RateCardResponse])
async def list_rate_cards(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    client_id: Optional[int] = Query(None),
    role: Optional[str] = Query(None),
    seniority: Optional[str] = Query(None),
    active_only: bool = Query(
        False, description="Return only cards whose validity window contains today."
    ),
):
    query = select(RateCard)
    if client_id is not None:
        query = query.where(RateCard.client_id == client_id)
    if role:
        query = query.where(func.lower(RateCard.role) == role.lower())
    if seniority:
        query = query.where(RateCard.seniority == seniority)
    if active_only:
        today = _date.today()
        query = query.where(
            (RateCard.valid_from.is_(None)) | (RateCard.valid_from <= today),
            (RateCard.valid_to.is_(None)) | (RateCard.valid_to >= today),
        )
    query = query.order_by(RateCard.role, RateCard.seniority)
    res = await db.execute(query)
    return list(res.scalars().all())


@router.post("", response_model=RateCardResponse, status_code=status.HTTP_201_CREATED)
async def create_rate_card(
    data: RateCardCreate,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
):
    client = await db.scalar(select(Client).where(Client.id == data.client_id))
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    card = RateCard(**data.model_dump())
    db.add(card)
    await db.flush()
    await db.refresh(card)
    return card


@router.get("/suggest", response_model=RateCardSuggestion)
async def suggest_rate(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    client_id: int = Query(...),
    role: str = Query(...),
    seniority: Optional[str] = Query(None),
):
    """Return suggested mid-point rates for a client × role × seniority."""
    today = _date.today()
    query = (
        select(RateCard)
        .where(
            RateCard.client_id == client_id,
            func.lower(RateCard.role) == role.lower(),
            (RateCard.valid_from.is_(None)) | (RateCard.valid_from <= today),
            (RateCard.valid_to.is_(None)) | (RateCard.valid_to >= today),
        )
        .order_by(RateCard.valid_from.desc().nulls_last())
    )
    if seniority:
        query = query.where(
            (RateCard.seniority == seniority) | (RateCard.seniority.is_(None))
        )
    res = await db.execute(query)
    card = res.scalars().first()
    if not card:
        return RateCardSuggestion(matched=False)

    return RateCardSuggestion(
        matched=True,
        rate_card_id=card.id,
        rate_candidate_suggestion=_midpoint(
            card.rate_candidate_min, card.rate_candidate_max
        ),
        rate_client_suggestion=_midpoint(card.rate_client_min, card.rate_client_max),
        currency=card.currency,
        rate_unit=card.rate_unit,
        source_role=card.role,
        source_seniority=card.seniority,
    )


@router.get("/{card_id}", response_model=RateCardResponse)
async def get_rate_card(
    card_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    card = await db.scalar(select(RateCard).where(RateCard.id == card_id))
    if not card:
        raise HTTPException(status_code=404, detail="Rate card not found")
    return card


@router.patch("/{card_id}", response_model=RateCardResponse)
async def update_rate_card(
    card_id: int,
    data: RateCardUpdate,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
):
    card = await db.scalar(select(RateCard).where(RateCard.id == card_id))
    if not card:
        raise HTTPException(status_code=404, detail="Rate card not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(card, k, v)
    await db.flush()
    await db.refresh(card)
    return card


@router.delete("/{card_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rate_card(
    card_id: int,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
):
    card = await db.scalar(select(RateCard).where(RateCard.id == card_id))
    if not card:
        raise HTTPException(status_code=404, detail="Rate card not found")
    await db.delete(card)
