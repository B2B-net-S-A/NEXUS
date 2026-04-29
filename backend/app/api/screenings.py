from typing import Optional
from datetime import datetime
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.core.database import get_db
from app.models.screening_note import (
    ScreeningNote,
    ScreeningType,
    MotivationType,
    CounterOfferRisk,
)
from app.models.candidate import Candidate
from app.models.screening_note_mention import ScreeningNoteMention
from app.api.deps import CurrentUser
from app.services.mention_dispatch import (
    build_screening_note_deep_link,
    enqueue_mention_notifications,
    send_mention_side_effects,
    trim_snippet,
)
from app.services.mention_parser import parse_mentions, parse_mentions_global


def _concat_screening_text(data: "ScreeningNoteCreate") -> str:
    """Łączy 3 tekstowe pola żeby parsować mentions w jednym przebiegu.

    Pomija pola opcjonalne które są None lub pusty string.
    Separator `\n\n` żeby niespodzianki w regex'ie (np. mention w red_flags
    + mention w personality_notes) nie zlewały się do jednego tokenu.
    """
    parts = [
        data.red_flags or "",
        data.personality_notes or "",
        data.closing_strategy or "",
    ]
    return "\n\n".join(p for p in parts if p)


def _screening_snippet(data: "ScreeningNoteCreate") -> str:
    """Pierwszy non-empty z 3 pól → trimmed snippet do 140 znaków."""
    raw = data.red_flags or data.personality_notes or data.closing_strategy or ""
    return trim_snippet(raw)


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


@router.get(
    "/candidates/{candidate_id}/screenings", response_model=list[ScreeningNoteResponse]
)
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


@router.post(
    "/screenings",
    response_model=ScreeningNoteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_screening_note(
    data: ScreeningNoteCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Candidate).where(Candidate.id == data.candidate_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Candidate not found")

    skills_data = (
        [s.model_dump() for s in data.verified_skills] if data.verified_skills else []
    )

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
    await db.flush()  # need note.id

    # @mentions — parsuj concat'owaną treść 3 pól tekstowych. Scope:
    # job_id obecny (z filtru members), inaczej global (każdy aktywny user).
    combined = _concat_screening_text(data)
    if data.job_id:
        mentioned_ids = await parse_mentions(db, combined, data.job_id)
    else:
        mentioned_ids = await parse_mentions_global(db, combined)
    mentioned_ids = [uid for uid in mentioned_ids if uid != current_user.id]
    for uid in mentioned_ids:
        db.add(ScreeningNoteMention(screening_note_id=note.id, user_id=uid))

    snippet = _screening_snippet(data)
    deep_link = build_screening_note_deep_link(data.candidate_id, note.id)
    context_label = "notatce ze screeningu"
    notification_title = f"{current_user.name or current_user.email} oznaczył(a) Cię w notatce ze screeningu"

    pairs = await enqueue_mention_notifications(
        db,
        mentioned_user_ids=mentioned_ids,
        author=current_user,
        deep_link_path=deep_link,
        snippet=snippet,
        notification_title=notification_title,
        related_entity_type="screening_note",
        related_entity_id=note.id,
    )

    await db.commit()

    if pairs:
        await send_mention_side_effects(
            pairs,
            author_name=current_user.name or current_user.email,
            snippet=snippet,
            deep_link_path=deep_link,
            context_label=context_label,
            notification_title=notification_title,
        )

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
            "motivation_top": None,
            "salary_trend": [],
            "salary_summary": None,
            "verified_skills_aggregate": [],
            "warnings": [],
            "red_flags_unique": [],
            "overall_impression_avg": None,
            "readiness_avg": None,
            "counteroffer_risk_distribution": {},
            "counteroffer_risk_dominant": None,
            "last_screening": None,
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

    # Motivation top — most frequent primary across all screenings
    primary_values = [
        s.motivation_primary.value for s in screenings if s.motivation_primary
    ]
    motivation_top = (
        Counter(primary_values).most_common(1)[0][0] if primary_values else None
    )

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

    # Salary summary — min/max/latest for quick glance
    salaries = [s for s in screenings if s.salary_expectation]
    if salaries:
        amounts = [s.salary_expectation for s in salaries]
        latest_salary = salaries[-1]
        salary_summary = {
            "min": min(amounts),
            "max": max(amounts),
            "latest": latest_salary.salary_expectation,
            "currency": latest_salary.salary_currency or "PLN",
            "negotiable": any(s.salary_negotiable for s in salaries),
        }
    else:
        salary_summary = None

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

    # Red flags — dedup case-insensitive, split by newline/comma, preserve original casing
    red_flags_raw: list[str] = []
    for s in screenings:
        if s.red_flags:
            for rf in s.red_flags.replace(",", "\n").split("\n"):
                rf_clean = rf.strip()
                if rf_clean:
                    red_flags_raw.append(rf_clean)

    seen_rf: set[str] = set()
    red_flags_unique: list[str] = []
    for rf in red_flags_raw:
        key = rf.lower()
        if key not in seen_rf:
            seen_rf.add(key)
            red_flags_unique.append(rf)

    # Warnings — legacy compat: red flags + counteroffer summary (kept for backwards compat)
    warnings: list[str] = list(red_flags_unique)

    high_risk = [
        s
        for s in screenings
        if s.counteroffer_risk and s.counteroffer_risk.value == "high"
    ]
    if high_risk:
        warnings.append(f"Wysokie ryzyko counteroffer ({len(high_risk)}x odnotowane)")

    # Averages
    impressions = [s.overall_impression for s in screenings if s.overall_impression]
    impression_avg = (
        round(sum(impressions) / len(impressions), 1) if impressions else None
    )

    readiness = [s.readiness_to_change for s in screenings if s.readiness_to_change]
    readiness_avg = round(sum(readiness) / len(readiness), 1) if readiness else None

    # Counteroffer risk distribution + dominant
    risks = [s.counteroffer_risk.value for s in screenings if s.counteroffer_risk]
    risk_dist = dict(Counter(risks))
    risk_dominant = Counter(risks).most_common(1)[0][0] if risks else None

    # Last screening meta (screenings are ordered ASC → last is most recent)
    last = screenings[-1]
    last_screening = {
        "id": last.id,
        "created_at": last.created_at.isoformat(),
        "author_id": last.author_id,
        "screening_type": last.screening_type.value if last.screening_type else None,
        "overall_impression": last.overall_impression,
    }

    return {
        "candidate_id": candidate_id,
        "screening_count": len(screenings),
        "motivation_trend": motivation_trend,
        "motivation_top": motivation_top,
        "salary_trend": salary_trend,
        "salary_summary": salary_summary,
        "verified_skills_aggregate": verified_skills_aggregate,
        "warnings": warnings,
        "red_flags_unique": red_flags_unique,
        "overall_impression_avg": impression_avg,
        "readiness_avg": readiness_avg,
        "counteroffer_risk_distribution": risk_dist,
        "counteroffer_risk_dominant": risk_dominant,
        "last_screening": last_screening,
    }
