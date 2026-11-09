"""Calls API — rejestr rozmów telefonicznych z kandydatami."""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import (
    CandidatePIIAccess,
    CandidateSearchAccess,
    CandidateWriteAccess,
)
from app.core.database import get_db
from app.models.call import Call, CallDirection, CallStatus

router = APIRouter()


# ── Schemas ─────────────────────────────────────────────────────────────────


class CallCreate(BaseModel):
    candidate_id: int
    direction: CallDirection = CallDirection.outbound
    duration_seconds: Optional[int] = None
    status: CallStatus = CallStatus.completed
    transcript: Optional[str] = None
    summary: Optional[str] = None
    recording_url: Optional[str] = None
    cloudtalk_call_id: Optional[str] = None


class CallResponse(BaseModel):
    id: int
    candidate_id: Optional[int]
    user_id: Optional[int]
    direction: CallDirection
    duration_seconds: Optional[int]
    status: CallStatus
    transcript: Optional[str]
    summary: Optional[str]
    recording_url: Optional[str]
    cloudtalk_call_id: Optional[str]
    cloudtalk_agent_id: Optional[int]
    started_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Helpers ──────────────────────────────────────────────────────────────────


def format_duration(seconds: Optional[int]) -> str:
    if not seconds:
        return "—"
    minutes = seconds // 60
    secs = seconds % 60
    return f"{minutes}:{secs:02d}"


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/candidates/{candidate_id}/calls", response_model=list[CallResponse])
async def list_candidate_calls(
    candidate_id: int,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
):
    """Pobierz listę rozmów dla danego kandydata.

    P0.11: calls carry transcripts + recording URLs (candidate PII). This is
    gated to internal operational roles (viewer excluded), consistent with the
    rest of the candidate surface.
    """
    result = await db.execute(
        select(Call)
        .where(Call.candidate_id == candidate_id)
        .order_by(Call.created_at.desc())
    )
    return result.scalars().all()


@router.get("/candidates/{candidate_id}/calls/{call_id}", response_model=CallResponse)
async def get_candidate_call(
    candidate_id: int,
    call_id: int,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
):
    """Read one call after checking its candidate; used by follow-up history."""
    call = await db.get(Call, call_id)
    if call is None or call.candidate_id != candidate_id:
        raise HTTPException(status_code=404, detail="Rozmowa nie znaleziona")
    return call


@router.post("/calls", response_model=CallResponse, status_code=status.HTTP_201_CREATED)
async def log_call(
    data: CallCreate,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
):
    """Ręczne zalogowanie rozmowy (np. po kliknięciu 'Zadzwoń')."""
    call = Call(
        candidate_id=data.candidate_id,
        user_id=current_user.id,
        direction=data.direction,
        duration_seconds=data.duration_seconds,
        status=data.status,
        transcript=data.transcript,
        summary=data.summary,
        recording_url=data.recording_url,
        cloudtalk_call_id=data.cloudtalk_call_id,
    )
    db.add(call)
    await db.commit()
    await db.refresh(call)
    return call


@router.get("/calls/stats")
async def call_stats(
    current_user: CandidateSearchAccess,
    db: AsyncSession = Depends(get_db),
):
    """
    Statystyki rozmów na użytkownika.
    Zwraca: total calls, avg duration, calls this week, calls this month.
    """
    # Tydzień i miesiąc w kalendarzu firmy, nie od północy UTC (runda 2 audytu
    # 25.09.2026 — rozmowy z poniedziałku 00:00–02:00 wypadały z tygodnia).
    from app.core.scheduling import (  # noqa: PLC0415
        business_today,
        local_day_start_utc,
        local_month_bounds,
    )

    today = business_today()
    start_of_week = local_day_start_utc(today - timedelta(days=today.weekday()))
    start_of_month = local_month_bounds(today).start_utc

    # Total calls by this user
    total = (
        await db.execute(
            select(func.count(Call.id)).where(Call.user_id == current_user.id)
        )
    ).scalar() or 0

    # Avg duration
    avg_duration = (
        await db.execute(
            select(func.avg(Call.duration_seconds)).where(
                Call.user_id == current_user.id,
                Call.duration_seconds.isnot(None),
            )
        )
    ).scalar()

    # This week
    this_week = (
        await db.execute(
            select(func.count(Call.id)).where(
                Call.user_id == current_user.id,
                Call.created_at >= start_of_week,
            )
        )
    ).scalar() or 0

    # This month
    this_month = (
        await db.execute(
            select(func.count(Call.id)).where(
                Call.user_id == current_user.id,
                Call.created_at >= start_of_month,
            )
        )
    ).scalar() or 0

    # Global stats (all users) — this week
    all_this_week = (
        await db.execute(
            select(func.count(Call.id)).where(Call.created_at >= start_of_week)
        )
    ).scalar() or 0

    all_avg_duration = (
        await db.execute(
            select(func.avg(Call.duration_seconds)).where(
                Call.created_at >= start_of_week,
                Call.duration_seconds.isnot(None),
            )
        )
    ).scalar()

    return {
        "user": {
            "total_calls": total,
            "avg_duration_seconds": round(avg_duration) if avg_duration else None,
            "avg_duration_formatted": format_duration(
                round(avg_duration) if avg_duration else None
            ),
            "calls_this_week": this_week,
            "calls_this_month": this_month,
        },
        "global": {
            "calls_this_week": all_this_week,
            "avg_duration_seconds": round(all_avg_duration)
            if all_avg_duration
            else None,
            "avg_duration_formatted": format_duration(
                round(all_avg_duration) if all_avg_duration else None
            ),
        },
    }
