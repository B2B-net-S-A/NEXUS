"""Endpoints for reviewing & applying Champion Profile AI suggestions.

Write endpoints require TacPlus (admin + delivery_lead + tac). Finance receives
GET-only organization oversight. Matching router prefix is
`/champion-suggestions` — the suggestions carry their own `job_id` so operations
do not need to walk through the Jobs router.

Rola nie wystarcza za zakres zapisu: `ensure_champion_job_visible` zawęża
Delivery Leada do jego par klient×TAC, a TAC-a do ofert, w których `Job.tac_id`
wskazuje na niego. Osobny read guard omija ten membership wyłącznie dla Finance.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import TacPlus, require_roles
from app.api.recruitment_access import (
    ensure_champion_job_read_visible,
    ensure_champion_job_visible,
)
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.champion_suggestion import ChampionProfileSuggestion
from app.models.job import Job
from app.models.user import User, UserRole
from app.schemas.champion_suggestion import (
    ApplyPayload,
    ChampionProfileSuggestionOut,
    RatePayload,
    patches_from_payload,
)
from app.services.champion_draft_service import apply_suggestion, reject_suggestion

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/champion-suggestions",
    tags=["champion-suggestions"],
    dependencies=PIPELINE_SECTION_DEPENDENCIES,
)


ChampionSuggestionReadUser = Annotated[
    User,
    Depends(
        require_roles(
            UserRole.admin,
            UserRole.delivery_lead,
            UserRole.tac,
            UserRole.finance,
        )
    ),
]


def _to_out(suggestion: ChampionProfileSuggestion) -> ChampionProfileSuggestionOut:
    out = ChampionProfileSuggestionOut.model_validate(suggestion)
    out.patches = patches_from_payload(suggestion.payload or {})
    return out


async def _load_scoped_suggestion(
    db: AsyncSession,
    suggestion_id: int,
    current_user: User,
    *,
    read_only: bool = False,
) -> ChampionProfileSuggestion:
    """Load a suggestion and verify the caller may see ITS JOB.

    The single entry point for every route in this module — deliberately one
    function rather than a guard repeated in four handlers, because the
    repeated-guard shape is exactly what let this gap open: the twin routes in
    the Jobs router call ``ensure_delivery_lead_job_visible``, these did not.

    Until now the role check was the only check. Suggestion ids are sequential,
    so any Delivery Lead could read another client's Champion draft by
    incrementing an integer — and ``apply`` does not merely read it, it MERGES
    the draft into that job's ``champion_profile``. A scope leak that writes.

    Everything unreachable answers **404**, never 403. Suggestion ids are
    sequential and the resource is addressed by that id alone, so a 403 for
    "exists but not yours" versus a 404 for "does not exist" is an enumeration
    oracle: it confirms which ids are real Champion drafts of other clients.
    The three cases — no such suggestion, its job is gone, its job is outside
    the caller's scope — are deliberately indistinguishable from outside.
    """
    suggestion = await db.scalar(
        select(ChampionProfileSuggestion).where(
            ChampionProfileSuggestion.id == suggestion_id
        )
    )
    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    job = await db.get(Job, suggestion.job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    try:
        if read_only:
            await ensure_champion_job_read_visible(job, current_user, db)
        else:
            await ensure_champion_job_visible(job, current_user, db)
    except HTTPException as exc:
        if exc.status_code == 403:
            raise HTTPException(status_code=404, detail="Suggestion not found") from exc
        raise
    return suggestion


@router.get("/{suggestion_id}", response_model=ChampionProfileSuggestionOut)
async def get_suggestion(
    suggestion_id: int,
    current_user: ChampionSuggestionReadUser,
    db: AsyncSession = Depends(get_db),
) -> ChampionProfileSuggestionOut:
    suggestion = await _load_scoped_suggestion(
        db,
        suggestion_id,
        current_user,
        read_only=True,
    )
    return _to_out(suggestion)


@router.post("/{suggestion_id}/apply", response_model=ChampionProfileSuggestionOut)
async def apply_suggestion_endpoint(
    suggestion_id: int,
    payload: ApplyPayload,
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
) -> ChampionProfileSuggestionOut:
    """Merge the accepted sections into `jobs.champion_profile` and finalise.

    Invalid section names are silently ignored (treated as not accepted).
    Raises 404 / 409 / 500 on persistence failures.
    """
    await _load_scoped_suggestion(db, suggestion_id, current_user)
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
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
) -> ChampionProfileSuggestionOut:
    await _load_scoped_suggestion(db, suggestion_id, current_user)
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
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
) -> ChampionProfileSuggestionOut:
    """Phase 15 / Phase C — persist DL feedback on a terminated suggestion.

    Allowed only on terminal statuses (accepted / partially_accepted /
    rejected / superseded). Rating on a pending draft would be nonsensical;
    we return 409 in that case so the UI can hide the rating buttons until
    apply/reject has happened.
    """
    from app.models.champion_suggestion import SuggestionStatus

    suggestion = await _load_scoped_suggestion(db, suggestion_id, current_user)
    if suggestion.status == SuggestionStatus.pending:
        raise HTTPException(
            status_code=409,
            detail="Rate only after apply/reject — suggestion is still pending.",
        )
    suggestion.rating = int(payload.rating)
    suggestion.rating_comment = payload.comment.strip() if payload.comment else None
    await db.commit()
    await db.refresh(suggestion)
    logger.info(
        "champion_draft: rated suggestion id=%s rating=%s by user=%s",
        suggestion.id,
        suggestion.rating,
        current_user.id,
    )
    return _to_out(suggestion)
