"""Public (no-auth) endpoints for externally shareable artifacts (Phase 12).

Only routes registered here should be exempt from auth. Each route validates
its own unguessable token and honours `revoked` + `expires_at`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.candidate import Candidate
from app.models.champion_share import ChampionCardShareToken
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage

router = APIRouter()


@router.get("/champion-card/{token}")
async def get_public_champion_card(
    token: str, db: AsyncSession = Depends(get_db)
) -> dict:
    """Client-facing read of a filled Champion card.

    Returns 404 when the token is unknown, revoked, or expired. The response
    shape is slimmed down — no internal fields (scores, stage ids) — so that
    the client only sees what the recruiter meant to share.
    """
    row: Optional[ChampionCardShareToken] = await db.scalar(
        select(ChampionCardShareToken).where(ChampionCardShareToken.token == token)
    )
    if row is None or row.revoked:
        raise HTTPException(status_code=404, detail="Share link not found or revoked")
    if row.expires_at is not None and row.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=404, detail="Share link expired")

    stage = await db.scalar(
        select(CandidateStage).where(CandidateStage.id == row.candidate_stage_id)
    )
    if stage is None:
        raise HTTPException(status_code=404, detail="Stage disappeared")
    candidate = await db.scalar(
        select(Candidate).where(Candidate.id == stage.candidate_id)
    )
    job = await db.scalar(select(Job).where(Job.id == stage.job_id))

    return {
        "candidate": {
            "name": candidate.name if candidate else None,
            "lastname": candidate.lastname if candidate else None,
            "competence_category": candidate.competence_category if candidate else None,
            "location": candidate.location if candidate else None,
            "years_it_experience": candidate.years_it_experience if candidate else None,
        },
        "job": {
            "title": job.title if job else None,
            "location": job.location if job else None,
            "seniority": job.seniority.value if job and job.seniority else None,
        },
        "champion_profile": (job.champion_profile if job else None) or {},
        "screening_answers": stage.screening_answers or None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
    }
