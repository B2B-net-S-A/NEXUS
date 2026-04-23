"""Endpoints for reviewing & applying Champion Profile AI suggestions.

All endpoints require DeliveryLeadPlus (admin + delivery_lead). Matching
router prefix is `/champion-suggestions` — the suggestions carry their own
`job_id` so operations do not need to walk through the Jobs router.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DeliveryLeadPlus
from app.core.database import get_db
from app.models.champion_suggestion import ChampionProfileSuggestion
from app.schemas.champion_suggestion import (
    ApplyPayload,
    ChampionProfileSuggestionOut,
    RatePayload,
    patches_from_payload,
)
from app.services.champion_draft_service import apply_suggestion, reject_suggestion

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/champion-suggestions", tags=["champion-suggestions"])


def _to_out(suggestion: ChampionProfileSuggestion) -> ChampionProfileSuggestionOut:
    out = ChampionProfileSuggestionOut.model_validate(suggestion)
    out.patches = patches_from_payload(suggestion.payload or {})
    return out


@router.get("/{suggestion_id}", response_model=ChampionProfileSuggestionOut)
async def get_suggestion(
    suggestion_id: int,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
) -> ChampionProfileSuggestionOut:
    result = await db.execute(
        select(ChampionProfileSuggestion).where(
            ChampionProfileSuggestion.id == suggestion_id
        )
    )
    suggestion = result.scalar_one_or_none()
    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    return _to_out(suggestion)


@router.post("/{suggestion_id}/apply", response_model=ChampionProfileSuggestionOut)
async def apply_suggestion_endpoint(
    suggestion_id: int,
    payload: ApplyPayload,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
) -> ChampionProfileSuggestionOut:
    """Merge the accepted sections into `jobs.champion_profile` and finalise.

    Invalid section names are silently ignored (treated as not accepted).
    Raises 404 / 409 / 500 on persistence failures.
    """
    suggestion = await apply_suggestion(
        db,
        suggestion_id=suggestion_id,
        accepted_sections=payload.accepted_sections,
        user_id=current_user.id,
    )
    return _to_out(suggestion)


@router.post("/{suggestion_id}/reject", response_model=ChampionProfileSuggestionOut)
async def reject_suggestion_endpoint(
    suggestion_id: int,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
) -> ChampionProfileSuggestionOut:
    suggestion = await reject_suggestion(
        db,
        suggestion_id=suggestion_id,
        user_id=current_user.id,
    )
    return _to_out(suggestion)


@router.post("/{suggestion_id}/rate", response_model=ChampionProfileSuggestionOut)
async def rate_suggestion_endpoint(
    suggestion_id: int,
    payload: RatePayload,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
) -> ChampionProfileSuggestionOut:
    """Phase 15 / Phase C — persist DL feedback on a terminated suggestion.

    Allowed only on terminal statuses (accepted / partially_accepted /
    rejected / superseded). Rating on a pending draft would be nonsensical;
    we return 409 in that case so the UI can hide the rating buttons until
    apply/reject has happened.
    """
    from app.models.champion_suggestion import SuggestionStatus

    result = await db.execute(
        select(ChampionProfileSuggestion).where(
            ChampionProfileSuggestion.id == suggestion_id
        )
    )
    suggestion = result.scalar_one_or_none()
    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    if suggestion.status == SuggestionStatus.pending:
        raise HTTPException(
            status_code=409,
            detail="Rate only after apply/reject — suggestion is still pending.",
        )
    suggestion.rating = int(payload.rating)
    suggestion.rating_comment = (
        payload.comment.strip() if payload.comment else None
    )
    await db.commit()
    await db.refresh(suggestion)
    logger.info(
        "champion_draft: rated suggestion id=%s rating=%s by user=%s",
        suggestion.id,
        suggestion.rating,
        current_user.id,
    )
    return _to_out(suggestion)
