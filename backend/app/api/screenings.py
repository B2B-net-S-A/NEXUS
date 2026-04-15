from typing import Optional
from datetime import datetime
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.core.database import get_db
from app.models.screening_note import ScreeningNote, ScreeningType, MotivationType, CounterOfferRisk
from app.models.candidate import Candidate
from app.api.deps import CurrentUser

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────────────

class VerifiedSkill(BaseModel):
    skill: str
    level: str  # confirmed, basic, none
    notes: Optional[str] = None


class ScreeningNoteCreate(BaseModel):
    candidate_id: int
    job_id: Optional[int] = None
    screening_type: ScreeningType = ScreeningType.initial_screening
    motivation_primary: Optional[MotivationType] = None
    motivation_secondary: Optional[MotivationType] = None
    salary_expectation: Optional[int] = None
    salary_currency: str = "PLN"
    salary_negotiable: bool = False
    verified_skills: Optional[list[VerifiedSkill]] = None
    red_flags: Optional[str] = None
    personality_notes: Optional[str] = None
    readiness_to_change: Optional[int] = None
    counteroffer_risk: Optional[CounterOfferRisk] = None
    closing_strategy: Optional[str] = None
    overall_impression: Optional[int] = None


class ScreeningNoteResponse(BaseModel):
    id: int
    candidate_id: int
    job_id: Optional[int]
    author_id: int
    screening_type: ScreeningType
    motivation_primary: Optional[MotivationType]
    motivation_secondary: Optional[MotivationType]
    salary_expectation: Optional[int]
    salary_currency: Optional[str]
    salary_negotiable: bool
    verified_skills: Optional[list]
    red_flags: Optional[str]
    personality_notes: Optional[str]
    readiness_to_change: Optional[int]
    counteroffer_risk: Optional[CounterOfferRisk]
    closing_strategy: Optional[str]
    overall_impression: Optional[int]
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/candidates/{candidate_id}/screenings", response_model=list[ScreeningNoteResponse])
async def list_candidate_screenings(
    candidate_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Candidate).where(Candidate.id == candidate_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Candidate not found")

    result = await db.execute(
        select(ScreeningNote)
        .where(ScreeningNote.candidate_id == candidate_id)
        .order_by(ScreeningNote.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("/screenings", response_model=ScreeningNoteResponse, status_code=status.HTTP_201_CREATED)
async def create_screening_note(
    data: ScreeningNoteCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Candidate).where(Candidate.id == data.candidate_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Candidate not found")

    skills_data = [s.model_dump() for s in data.verified_skills] if data.verified_skills else []

    note = ScreeningNote(
        candidate_id=data.candidate_id,
        job_id=data.job_id,
        author_id=current_user.id,
        screening_type=data.screening_type,
        motivation_primary=data.motivation_primary,
        motivation_secondary=data.motivation_secondary,
        salary_expectation=data.salary_expectation,
        salary_currency=data.salary_currency,
        salary_negotiable=data.salary_negotiable,
        verified_skills=skills_data,
        red_flags=data.red_flags,
        personality_notes=data.personality_notes,
        readiness_to_change=data.readiness_to_change,
        counteroffer_risk=data.counteroffer_risk,
        closing_strategy=data.closing_strategy,
        overall_impression=data.overall_impression,
    )
    db.add(note)
    await db.flush()
    await db.refresh(note)
    return note


@router.get("/candidates/{candidate_id}/ai-profile")
async def get_candidate_ai_profile(
    candidate_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Candidate).where(Candidate.id == candidate_id))
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    result = await db.execute(
        select(ScreeningNote)
        .where(ScreeningNote.candidate_id == candidate_id)
        .order_by(ScreeningNote.created_at.asc())
    )
    screenings = list(result.scalars().all())

    if not screenings:
        return {
            "candidate_id": candidate_id,
            "screening_count": 0,
            "motivation_trend": [],
            "salary_trend": [],
            "verified_skills_aggregate": [],
            "warnings": [],
            "overall_impression_avg": None,
            "readiness_avg": None,
            "counteroffer_risk_distribution": {},
        }

    # Motivation trend
    motivation_trend = [
        {
            "date": s.created_at.isoformat(),
            "primary": s.motivation_primary,
            "secondary": s.motivation_secondary,
            "type": s.screening_type,
        }
        for s in screenings
        if s.motivation_primary
    ]

    # Salary trend
    salary_trend = [
        {
            "date": s.created_at.isoformat(),
            "expectation": s.salary_expectation,
            "currency": s.salary_currency,
            "negotiable": s.salary_negotiable,
        }
        for s in screenings
        if s.salary_expectation
    ]

    # Skills aggregate — collect confirmed/basic skills
    skills_map: dict[str, dict] = {}
    for s in screenings:
        if s.verified_skills:
            for sk in s.verified_skills:
                skill_name = sk.get("skill", "")
                if skill_name and sk.get("level") in ("confirmed", "basic"):
                    if skill_name not in skills_map or sk.get("level") == "confirmed":
                        skills_map[skill_name] = sk

    verified_skills_aggregate = list(skills_map.values())

    # Warnings — red flags accumulation
    warnings = []
    red_flags = [s.red_flags for s in screenings if s.red_flags]
    if red_flags:
        warnings.extend(red_flags)

    high_risk = [s for s in screenings if s.counteroffer_risk and s.counteroffer_risk.value == "high"]
    if high_risk:
        warnings.append(f"Wysokie ryzyko counteroffer ({len(high_risk)}x odnotowane)")

    # Averages
    impressions = [s.overall_impression for s in screenings if s.overall_impression]
    impression_avg = round(sum(impressions) / len(impressions), 1) if impressions else None

    readiness = [s.readiness_to_change for s in screenings if s.readiness_to_change]
    readiness_avg = round(sum(readiness) / len(readiness), 1) if readiness else None

    # Counteroffer risk distribution
    risks = [s.counteroffer_risk.value for s in screenings if s.counteroffer_risk]
    risk_dist = dict(Counter(risks))

    return {
        "candidate_id": candidate_id,
        "screening_count": len(screenings),
        "motivation_trend": motivation_trend,
        "salary_trend": salary_trend,
        "verified_skills_aggregate": verified_skills_aggregate,
        "warnings": warnings,
        "overall_impression_avg": impression_avg,
        "readiness_avg": readiness_avg,
        "counteroffer_risk_distribution": risk_dist,
    }
