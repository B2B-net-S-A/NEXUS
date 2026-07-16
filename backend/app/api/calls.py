"""Calls API — rejestr rozmów telefonicznych z kandydatami.

Inbound CloudTalk events arrive via :func:`cloudtalk_webhook`. When
``settings.CLOUDTALK_ENABLED`` is False the endpoint stays in DRY-RUN mode
(returns 200 with ``{"status":"dry-run"}`` and never writes). When enabled it
verifies the HMAC signature, upserts the ``Call`` row, and dispatches Champion
Profile enrichment for transcripts.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import CandidatePIIAccess
from app.api.deps import CurrentUser
from app.core.config import settings
from app.core.database import get_db
from app.models.call import Call, CallDirection, CallStatus
from app.services.cloudtalk import verify_signature
from app.services.dedup_service import _normalize_phone

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


@router.post("/calls", response_model=CallResponse, status_code=status.HTTP_201_CREATED)
async def log_call(
    data: CallCreate,
    current_user: CandidatePIIAccess,
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
        "cloudtalk_status": "live" if settings.CLOUDTALK_ENABLED else "disabled",
    }


# ── CloudTalk webhook ────────────────────────────────────────────────────────


def _parse_direction(value: Any) -> CallDirection:
    """Map CloudTalk ``call.type`` / ``direction`` to our enum.

    CloudTalk uses ``incoming`` / ``outgoing`` (and historically ``in`` / ``out``).
    Defaults to ``outbound`` since most ATS-initiated calls are outbound.
    """
    if not value:
        return CallDirection.outbound
    s = str(value).strip().lower()
    if s in {"incoming", "inbound", "in"}:
        return CallDirection.inbound
    return CallDirection.outbound


def _parse_status(value: Any) -> CallStatus:
    """Map CloudTalk call status to our enum. Defaults to completed."""
    if not value:
        return CallStatus.completed
    s = str(value).strip().lower()
    if s in {"missed", "no-answer", "no_answer"}:
        return CallStatus.missed
    if s in {"voicemail", "vm"}:
        return CallStatus.voicemail
    if s in {"failed", "error", "busy", "rejected"}:
        return CallStatus.failed
    return CallStatus.completed


def _parse_started_at(value: Any) -> Optional[datetime]:
    """Parse ISO-8601 timestamp; tolerate ``Z`` suffix and missing tz."""
    if not value:
        return None
    try:
        s = str(value).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None


def _extract_call_fields(call_info: dict) -> dict:
    """Pull the fields we care about from a CloudTalk webhook payload.

    Defensive — CloudTalk payload shape varies across plan tiers and event
    types (call-ended, transcript-ready, recording-ready). We accept the
    union of observed field names and let missing fields be None.
    """
    if not isinstance(call_info, dict):
        return {}

    agent = call_info.get("agent")
    agent_id: Optional[int] = None
    if isinstance(agent, dict):
        raw_aid = agent.get("id")
        try:
            agent_id = int(raw_aid) if raw_aid is not None else None
        except (TypeError, ValueError):
            agent_id = None
    elif call_info.get("agent_id") is not None:
        try:
            agent_id = int(call_info.get("agent_id"))
        except (TypeError, ValueError):
            agent_id = None

    raw_duration = (
        call_info.get("duration")
        or call_info.get("talking_time")
        or call_info.get("duration_seconds")
    )
    duration_seconds: Optional[int] = None
    if raw_duration is not None:
        try:
            duration_seconds = int(raw_duration)
        except (TypeError, ValueError):
            duration_seconds = None

    return {
        "ct_id": str(call_info.get("id") or call_info.get("call_id") or "").strip()
        or None,
        "phone": str(
            call_info.get("phone")
            or call_info.get("caller_number")
            or call_info.get("external_number")
            or ""
        ).strip(),
        "transcript": str(
            call_info.get("transcript") or call_info.get("transcription") or ""
        ).strip(),
        "summary": str(call_info.get("summary") or "").strip(),
        "recording_url": (
            str(
                call_info.get("recording_url") or call_info.get("recording") or ""
            ).strip()
            or None
        ),
        "direction": _parse_direction(
            call_info.get("type") or call_info.get("direction")
        ),
        "status": _parse_status(call_info.get("status")),
        "duration_seconds": duration_seconds,
        "agent_id": agent_id,
        "started_at": _parse_started_at(
            call_info.get("started_at") or call_info.get("created_at")
        ),
    }


async def _process_cloudtalk_payload(
    raw_body: bytes,
    db: AsyncSession,
    logger,
) -> dict:
    """Parse a verified CloudTalk webhook body, upsert Call, run enrichment.

    Shared between the HMAC-authenticated ``/api/calls/webhook`` endpoint
    (used when CloudTalk signs requests with the shared secret) and the
    URL-token ``/api/calls/webhook/{token}`` endpoint (used by CloudTalk
    Workflow Automations, which cannot compute an HMAC over the body).
    Both auth strategies funnel into this function with raw_body already
    trusted.
    """
    try:
        payload = await _safe_parse_json(raw_body)
    except Exception:
        logger.warning("CloudTalk webhook: non-JSON payload, ignoring")
        return {"status": "skipped", "reason": "non-json"}

    # CloudTalk wraps the body either under {"call": {...}} or flat.
    call_info = payload.get("call") if isinstance(payload, dict) else None
    if not isinstance(call_info, dict):
        call_info = payload if isinstance(payload, dict) else {}

    fields = _extract_call_fields(call_info)
    ct_id = fields["ct_id"]
    phone = fields["phone"]
    transcript = fields["transcript"]
    summary = fields["summary"]

    call_row: Optional[Call] = None
    if ct_id:
        call_row = await db.scalar(select(Call).where(Call.cloudtalk_call_id == ct_id))

    from app.models.candidate import Candidate

    candidate: Optional[Candidate] = None
    last9 = _normalize_phone(phone)
    if last9:
        normalized_col = func.right(
            func.regexp_replace(Candidate.phone, r"[^\d]", "", "g"), 9
        )
        candidate = await db.scalar(
            select(Candidate)
            .where(Candidate.phone.isnot(None))
            .where(normalized_col == last9)
            .limit(1)
        )
        if candidate is None:
            logger.info(
                "CloudTalk webhook: no candidate match for phone last-9=%s (ct_id=%s)",
                last9,
                ct_id,
            )

    from app.models.user import User

    mapped_user_id: Optional[int] = None
    if fields["agent_id"] is not None:
        mapped_user = await db.scalar(
            select(User).where(User.cloudtalk_agent_id == fields["agent_id"])
        )
        if mapped_user is not None:
            mapped_user_id = mapped_user.id
        else:
            logger.info(
                "CloudTalk webhook: agent_id=%s has no Nexus user mapping",
                fields["agent_id"],
            )

    if call_row is None and candidate is not None:
        call_row = Call(
            candidate_id=candidate.id,
            user_id=mapped_user_id,
            direction=fields["direction"],
            status=fields["status"],
            duration_seconds=fields["duration_seconds"],
            transcript=transcript or None,
            summary=summary or None,
            recording_url=fields["recording_url"],
            cloudtalk_call_id=ct_id,
            cloudtalk_agent_id=fields["agent_id"],
            started_at=fields["started_at"],
        )
        db.add(call_row)
    elif call_row is not None:
        if transcript:
            call_row.transcript = transcript
        if summary:
            call_row.summary = summary
        if fields["recording_url"]:
            call_row.recording_url = fields["recording_url"]
        if fields["duration_seconds"] is not None:
            call_row.duration_seconds = fields["duration_seconds"]
        if fields["agent_id"] is not None and call_row.cloudtalk_agent_id is None:
            call_row.cloudtalk_agent_id = fields["agent_id"]
        if mapped_user_id is not None and call_row.user_id is None:
            call_row.user_id = mapped_user_id
        if fields["started_at"] is not None and call_row.started_at is None:
            call_row.started_at = fields["started_at"]
        if (
            call_row.status == CallStatus.initiated
            and fields["status"] != CallStatus.initiated
        ):
            call_row.status = fields["status"]

    await db.commit()
    if call_row is not None:
        await db.refresh(call_row)

    if transcript and candidate is not None:
        from app.models.recruitment_pipeline import CandidateStage
        from app.services.champion_draft_service import enrich_from_call

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
        "candidate_matched": candidate is not None,
        "enriched": bool(transcript and candidate),
    }


@router.post("/calls/webhook/{token}")
async def cloudtalk_webhook_url_token(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """CloudTalk inbound webhook authenticated by a URL-path token.

    Used by CloudTalk Workflow Automations → "API request" action, which
    cannot compute an HMAC signature over the request body. The token in
    the URL must match ``settings.CLOUDTALK_WEBHOOK_SECRET`` constant-time;
    the rest of the processing is identical to the HMAC-signed variant.

    Use HTTPS exclusively — the URL is private and never logged with the
    full token (FastAPI access logs strip path query string but NOT path
    segments, so prefer signed-HMAC where possible).
    """
    import hmac as _hmac
    import logging

    logger = logging.getLogger(__name__)
    raw_body = await request.body()

    if not settings.CLOUDTALK_ENABLED:
        return {"status": "dry-run", "enabled": False}

    if not settings.CLOUDTALK_WEBHOOK_SECRET:
        logger.warning(
            "CloudTalk webhook (URL-token): secret empty while enabled; rejecting"
        )
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)

    if not _hmac.compare_digest(token, settings.CLOUDTALK_WEBHOOK_SECRET):
        logger.warning("CloudTalk webhook (URL-token): token mismatch")
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)

    return await _process_cloudtalk_payload(raw_body, db, logger)


@router.post("/calls/webhook")
async def cloudtalk_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """CloudTalk inbound webhook (HMAC-signed).

    Flow:
      1. When ``settings.CLOUDTALK_ENABLED`` is False — DRY-RUN: returns 200
         with ``{"status":"dry-run"}`` and logs payload keys. No DB writes,
         no HMAC check (the secret may not be configured yet).
      2. When enabled — verifies ``X-CloudTalk-Signature`` HMAC-SHA256 against
         ``settings.CLOUDTALK_WEBHOOK_SECRET``. Rejects with 401 on mismatch.
      3. Parses payload defensively (call-ended / transcript-ready / recording-
         ready may differ slightly); failures to decode return 204.
      4. Looks up Candidate by phone (last-9-digits, reusing
         :func:`app.services.dedup_service._normalize_phone`).
      5. Upserts ``Call`` by ``cloudtalk_call_id``. UPDATE on existing
         (transcript may arrive later than call-ended).
      6. If transcript is present and the call maps to a Candidate with an
         active Job, dispatches LLM enrichment (Champion Profile suggestion).

    See :func:`cloudtalk_webhook_url_token` for the Workflow Automations
    variant (URL-token auth instead of HMAC).
    """
    import logging

    logger = logging.getLogger(__name__)

    raw_body = await request.body()

    # ── Dry-run mode — don't touch DB, don't require HMAC ──────────────────
    if not settings.CLOUDTALK_ENABLED:
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

    # ── HMAC verification (enabled path) ────────────────────────────────────
    signature_header = request.headers.get("X-CloudTalk-Signature", "")
    if not settings.CLOUDTALK_WEBHOOK_SECRET:
        logger.warning(
            "CloudTalk webhook: CLOUDTALK_WEBHOOK_SECRET empty while enabled; rejecting"
        )
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)
    if not verify_signature(
        raw_body, signature_header, settings.CLOUDTALK_WEBHOOK_SECRET
    ):
        logger.warning("CloudTalk webhook: signature mismatch")
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)

    return await _process_cloudtalk_payload(raw_body, db, logger)


async def _safe_parse_json(raw_body: bytes) -> Any:
    """Parse JSON, accepting empty bytes as empty dict."""
    import json

    if not raw_body:
        return {}
    return json.loads(raw_body.decode("utf-8"))
