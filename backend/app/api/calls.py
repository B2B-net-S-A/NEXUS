"""
Calls API — rejestr rozmów telefonicznych z kandydatami.
Integracja z CloudTalk: PLACEHOLDER — webhooks w przygotowaniu po uzyskaniu klucza API.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request, Response, status
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
    """CloudTalk webhook (Phase 14).

    Flow:
      1. When `CLOUDTALK_WEBHOOK_ENABLED=false` — runs in DRY-RUN mode: returns
         204 and logs payload keys only (no DB writes, no HMAC check).
      2. When enabled — verifies `X-CloudTalk-Signature` HMAC using
         `CLOUDTALK_WEBHOOK_SECRET`. Rejects with 401 on mismatch.
      3. Parses payload defensively; failures to decode JSON return 204.
      4. Upserts `Call` by `cloudtalk_call_id`.
      5. If a transcript is present and the call maps to a Candidate with an
         active Job, dispatches LLM enrichment (Champion Profile suggestion).
    """
    import hashlib
    import hmac
    import logging
    import os

    logger = logging.getLogger(__name__)

    enabled = os.environ.get("CLOUDTALK_WEBHOOK_ENABLED", "false").lower() == "true"
    secret = os.environ.get("CLOUDTALK_WEBHOOK_SECRET", "")

    raw_body = await request.body()

    # Dry-run mode — don't touch DB, don't require HMAC.
    if not enabled:
        try:
            payload_preview = await _safe_parse_json(raw_body)
        except Exception:
            payload_preview = {}
        logger.info(
            "CloudTalk webhook (DRY-RUN): received %d bytes, keys=%s",
            len(raw_body or b""),
            list(payload_preview.keys())[:10]
            if isinstance(payload_preview, dict)
            else [],
        )
        return {"status": "dry-run", "enabled": False}

    # HMAC verification (enabled path).
    signature_header = request.headers.get("X-CloudTalk-Signature", "")
    if not secret:
        logger.warning(
            "CloudTalk webhook: CLOUDTALK_WEBHOOK_SECRET empty while enabled; rejecting"
        )
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)
    expected = hmac.new(
        secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, signature_header):
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)

    try:
        payload = await _safe_parse_json(raw_body)
    except Exception:
        logger.warning("CloudTalk webhook: non-JSON payload, ignoring")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    call_info = payload.get("call") if isinstance(payload, dict) else {}
    if not isinstance(call_info, dict):
        call_info = {}

    ct_id = str(call_info.get("id") or "").strip() or None
    phone = str(call_info.get("phone") or call_info.get("caller_number") or "").strip()
    transcript = str(call_info.get("transcript") or "").strip()
    summary = str(call_info.get("summary") or "").strip()
    recording_url = str(call_info.get("recording_url") or "").strip() or None

    # Dedup by cloudtalk_call_id.
    from app.models.candidate import Candidate

    call_row: Optional[Call] = None
    if ct_id:
        call_row = await db.scalar(
            select(Call).where(Call.cloudtalk_call_id == ct_id)
        )

    # Find candidate by phone (lookup once).
    candidate: Optional[Candidate] = None
    if phone:
        normalized = "".join(c for c in phone if c.isdigit() or c == "+")
        candidate = await db.scalar(
            select(Candidate).where(Candidate.phone == normalized)
        )

    if call_row is None and candidate is not None:
        call_row = Call(
            candidate_id=candidate.id,
            direction=CallDirection.outbound,
            status=CallStatus.completed,
            transcript=transcript or None,
            summary=summary or None,
            recording_url=recording_url,
            cloudtalk_call_id=ct_id,
        )
        db.add(call_row)
    elif call_row is not None:
        # Update transcript / summary if webhook arrives late with AI fields.
        if transcript:
            call_row.transcript = transcript
        if summary:
            call_row.summary = summary
        if recording_url:
            call_row.recording_url = recording_url

    await db.commit()
    if call_row is not None:
        await db.refresh(call_row)

    # Enrichment — find a plausible Job for this candidate and trigger LLM.
    if transcript and candidate is not None:
        from app.models.recruitment_pipeline import CandidateStage
        from app.services.champion_draft_service import enrich_from_call

        # Pick the candidate's most recent active pipeline stage → job_id
        stage_res = await db.execute(
            select(CandidateStage)
            .where(CandidateStage.candidate_id == candidate.id)
            .order_by(CandidateStage.updated_at.desc())
            .limit(1)
        )
        stage = stage_res.scalar_one_or_none()
        if stage and stage.job_id:
            try:
                await enrich_from_call(
                    db,
                    job_id=stage.job_id,
                    call_participants=phone or "?",
                    call_summary=summary,
                    call_transcript=transcript,
                    source_ref=ct_id,
                    user_id=None,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("CloudTalk webhook enrichment failed: %s", exc)

    return {
        "status": "ok",
        "call_id": call_row.id if call_row else None,
        "enriched": bool(transcript and candidate),
    }


async def _safe_parse_json(raw_body: bytes) -> Any:
    """Parse JSON, accepting empty bytes as empty dict."""
    import json

    if not raw_body:
        return {}
    return json.loads(raw_body.decode("utf-8"))
