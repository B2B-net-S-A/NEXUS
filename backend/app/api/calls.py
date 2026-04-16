"""
Calls API — rejestr rozmów telefonicznych z kandydatami.
Integracja z CloudTalk: PLACEHOLDER — webhooks w przygotowaniu po uzyskaniu klucza API.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
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
    candidate_id: int
    user_id: Optional[int]
    direction: CallDirection
    duration_seconds: Optional[int]
    status: CallStatus
    transcript: Optional[str]
    summary: Optional[str]
    recording_url: Optional[str]
    cloudtalk_call_id: Optional[str]
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
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Pobierz listę rozmów dla danego kandydata."""
    result = await db.execute(
        select(Call)
        .where(Call.candidate_id == candidate_id)
        .order_by(Call.created_at.desc())
    )
    return result.scalars().all()


@router.post("/calls", response_model=CallResponse, status_code=status.HTTP_201_CREATED)
async def log_call(
    data: CallCreate,
    current_user: CurrentUser,
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
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Statystyki rozmów na użytkownika.
    Zwraca: total calls, avg duration, calls this week, calls this month.
    """
    now = datetime.now(timezone.utc)
    start_of_week = now - timedelta(days=now.weekday())
    start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

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
        "cloudtalk_status": "placeholder",  # zmienić po podłączeniu CloudTalk
    }


@router.post("/calls/webhook")
async def cloudtalk_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Placeholder dla webhooków CloudTalk.
    Integracja z CloudTalk w przygotowaniu — po uzyskaniu klucza API zostanie aktywowany.
    Na razie przyjmuje i loguje payload.
    """
    try:
        payload: Any = await request.json()
    except Exception:
        payload = {}

    # TODO: Zaimplementować po uzyskaniu klucza API CloudTalk
    # 1. Weryfikacja sygnatury webhook (HMAC)
    # 2. Mapowanie pól CloudTalk → Call model
    # 3. Deduplikacja po cloudtalk_call_id
    # 4. Powiązanie z kandydatem po numerze telefonu

    return {
        "status": "received",
        "message": "Integracja z CloudTalk w przygotowaniu. Webhook zarejestrowany.",
        "payload_keys": list(payload.keys()) if isinstance(payload, dict) else [],
    }
