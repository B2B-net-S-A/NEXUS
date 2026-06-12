"""Own browser dialer API — token minting, fraud-gated initiate, gateway
webhook, and an authed recording proxy.

All endpoints return HTTP 503 when ``settings.OWN_DIALER_ENABLED`` is False
(kill-switch, mirroring CloudTalk). The webhook stays in DRY-RUN when disabled.

Security note (anti-toll-fraud): outbound destinations are restricted to the
PL allowlist (``settings.dialer_allowed_prefixes_list``) and per-recruiter
daily / concurrent caps are enforced in :func:`initiate_call`. SIP/TURN
credentials minted by :func:`dialer_token` are short-lived.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import logging
import re
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.calls import _parse_started_at, _parse_status, _safe_parse_json
from app.api.deps import CurrentUser, RecruiterPlus
from app.core.config import settings
from app.core.database import get_db
from app.models.call import Call, CallDirection, CallStatus
from app.models.candidate import Candidate
from app.services.dedup_service import _normalize_phone
from app.services.dialer.webhook_verify import verify_dialer_signature

router = APIRouter()
logger = logging.getLogger(__name__)


def _disabled_response() -> Response:
    return Response(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content="Own dialer disabled (OWN_DIALER_ENABLED=false)",
    )


def _breadcrumb(message: str, **data) -> None:
    """Best-effort Sentry breadcrumb (no hard dependency if SDK absent)."""
    try:
        import sentry_sdk

        sentry_sdk.add_breadcrumb(category="dialer", message=message, data=data)
    except Exception:  # noqa: BLE001 — telemetry must never break the request
        pass


# ── Schemas ──────────────────────────────────────────────────────────────────


class IceServer(BaseModel):
    urls: str
    username: Optional[str] = None
    credential: Optional[str] = None


class DialerTokenResponse(BaseModel):
    sip_username: str
    sip_password: str
    sip_realm: str
    websocket_url: str
    ice_servers: list[IceServer]
    expires_at: int  # epoch seconds


class InitiateCallRequest(BaseModel):
    candidate_id: int


class InitiateCallResponse(BaseModel):
    call_id: int
    candidate_id: int
    phone: str


# ── Helpers ──────────────────────────────────────────────────────────────────


def _dialable(phone: str) -> str:
    """Strip a phone to ``+`` and digits for prefix matching."""
    return re.sub(r"[^\d+]", "", phone or "")


def _is_allowed_destination(phone: str) -> bool:
    """PL-only allowlist (anti-toll-fraud). A bare 9-digit number is treated
    as a domestic PL number (allowed); otherwise the dialable form must start
    with one of ``settings.dialer_allowed_prefixes_list``.
    """
    dialable = _dialable(phone)
    if not dialable:
        return False
    digits = dialable.lstrip("+")
    if len(digits) == 9 and dialable == digits:
        return True  # bare domestic PL number
    prefixes = settings.dialer_allowed_prefixes_list
    return any(dialable.startswith(p) for p in prefixes)


def _mint_turn_credentials(username_base: str, ttl: int) -> tuple[str, str, int]:
    """coturn REST-API ephemeral credential (static-secret mode).

    Returns ``(turn_username, turn_credential, expires_at)`` where
    ``turn_username = "<expiry>:<base>"`` and the credential is
    base64(HMAC-SHA1(secret, turn_username)). Standard TURN REST API scheme.
    """
    expires_at = int(time.time()) + ttl
    turn_username = f"{expires_at}:{username_base}"
    secret = settings.COTURN_STATIC_SECRET.encode("utf-8")
    digest = hmac.new(secret, turn_username.encode("utf-8"), hashlib.sha1).digest()
    return turn_username, base64.b64encode(digest).decode("ascii"), expires_at


def _mint_sip_password(username: str, expires_at: int) -> str:
    """Short-lived SIP password = HMAC-SHA256(secret, "<username>:<expiry>").

    The jambonz side validates the same HMAC (configured with the shared
    ``DIALER_WEBHOOK_SECRET``) so registrar credentials are never long-lived.
    """
    secret = settings.DIALER_WEBHOOK_SECRET.encode("utf-8")
    msg = f"{username}:{expires_at}".encode("utf-8")
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()


# ── Endpoints ──────────────────────────────────────────────────────────────────


@router.post("/token", response_model=DialerTokenResponse)
async def dialer_token(current_user: RecruiterPlus):
    """Mint short-lived SIP + ICE/TURN credentials for the browser softphone.

    412 when the recruiter has no ``dialer_sip_username`` (admin must enable
    the user for the dialer first). RBAC: RecruiterPlus.
    """
    if not settings.OWN_DIALER_ENABLED:
        return _disabled_response()
    if not current_user.dialer_sip_username:
        return Response(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            content="Your account is not enabled for the dialer (no SIP username).",
        )

    ttl = settings.DIALER_SIP_CRED_TTL_SECONDS
    expires_at = int(time.time()) + ttl
    sip_password = _mint_sip_password(current_user.dialer_sip_username, expires_at)

    ice_servers: list[IceServer] = []
    for url in settings.coturn_urls_list:
        if url.lower().startswith("turn"):
            tu, tc, _ = _mint_turn_credentials(current_user.dialer_sip_username, ttl)
            ice_servers.append(IceServer(urls=url, username=tu, credential=tc))
        else:
            ice_servers.append(IceServer(urls=url))

    return DialerTokenResponse(
        sip_username=current_user.dialer_sip_username,
        sip_password=sip_password,
        sip_realm=settings.JAMBONZ_SIP_REALM,
        websocket_url=settings.JAMBONZ_BASE_URL,
        ice_servers=ice_servers,
        expires_at=expires_at,
    )


@router.post("/calls/initiate", response_model=InitiateCallResponse)
async def initiate_call(
    payload: InitiateCallRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Fraud-gate pre-flight before the browser dials, then stub the Call row.

    Enforces: PL-only destination allowlist (400), per-user daily cap (429),
    per-user concurrent cap (429). On pass, inserts a
    ``Call(status=initiated, provider_type="dialer")`` and returns its id for
    the widget to correlate; the gateway webhook later UPSERTs by
    ``provider_call_id``.
    """
    if not settings.OWN_DIALER_ENABLED:
        return _disabled_response()

    candidate = await db.scalar(
        select(Candidate).where(Candidate.id == payload.candidate_id)
    )
    if candidate is None:
        return Response(
            status_code=status.HTTP_404_NOT_FOUND, content="Candidate not found"
        )
    if not candidate.phone or not _normalize_phone(candidate.phone):
        return Response(
            status_code=status.HTTP_400_BAD_REQUEST,
            content="Candidate has no phone number",
        )
    if not _is_allowed_destination(candidate.phone):
        _breadcrumb(
            "blocked non-PL destination",
            user_id=current_user.id,
            candidate_id=candidate.id,
        )
        return Response(
            status_code=status.HTTP_400_BAD_REQUEST,
            content="Destination not allowed (PL-only)",
        )

    # ── Anti-toll-fraud caps ──────────────────────────────────────────────
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    today_count = (
        await db.scalar(
            select(func.count(Call.id)).where(
                Call.user_id == current_user.id,
                Call.created_at >= today_start,
            )
        )
    ) or 0
    if today_count >= settings.DIALER_MAX_CALLS_PER_USER_PER_DAY:
        _breadcrumb(
            "daily call cap reached", user_id=current_user.id, count=today_count
        )
        return Response(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content="Daily call limit reached",
        )

    concurrent = (
        await db.scalar(
            select(func.count(Call.id)).where(
                Call.user_id == current_user.id,
                Call.status == CallStatus.initiated,
            )
        )
    ) or 0
    if concurrent >= settings.DIALER_MAX_CONCURRENT_CALLS_PER_USER:
        return Response(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content="Too many concurrent calls",
        )

    call = Call(
        candidate_id=candidate.id,
        user_id=current_user.id,
        direction=CallDirection.outbound,
        status=CallStatus.initiated,
        provider_type="dialer",
    )
    db.add(call)
    await db.commit()
    await db.refresh(call)

    return InitiateCallResponse(
        call_id=call.id, candidate_id=candidate.id, phone=candidate.phone
    )


def _extract_jambonz_fields(payload: dict) -> dict:
    """Normalize a jambonz call/recording webhook into our common shape.

    jambonz uses ``call_sid``, ``from``/``to``, ``direction``, ``call_status``,
    ``duration``, and a recording URL. Candidate phone is ``to`` for outbound,
    ``from`` for inbound.
    """
    direction = CallDirection.inbound
    if str(payload.get("direction") or "outbound").lower() != "inbound":
        direction = CallDirection.outbound
    phone = (
        payload.get("to")
        if direction == CallDirection.outbound
        else payload.get("from")
    )
    phone = str(phone or payload.get("from") or payload.get("to") or "").strip()

    raw_duration = payload.get("duration") or payload.get("duration_seconds")
    duration_seconds: Optional[int] = None
    if raw_duration is not None:
        try:
            duration_seconds = int(raw_duration)
        except (TypeError, ValueError):
            duration_seconds = None

    return {
        "provider_call_id": str(
            payload.get("call_sid") or payload.get("callSid") or ""
        ).strip()
        or None,
        "phone": phone,
        "direction": direction,
        "status": _parse_status(payload.get("call_status") or payload.get("status")),
        "duration_seconds": duration_seconds,
        "recording_url": (
            str(
                payload.get("recording_url")
                or payload.get("recording_public_url")
                or ""
            ).strip()
            or None
        ),
        "started_at": _parse_started_at(
            payload.get("started_at") or payload.get("start_time")
        ),
    }


async def _candidate_by_phone(db: AsyncSession, phone: str) -> Optional[Candidate]:
    last9 = _normalize_phone(phone)
    if not last9:
        return None
    normalized_col = func.right(
        func.regexp_replace(Candidate.phone, r"[^\d]", "", "g"), 9
    )
    return await db.scalar(
        select(Candidate)
        .where(Candidate.phone.isnot(None))
        .where(normalized_col == last9)
        .limit(1)
    )


@router.post("/webhook")
async def dialer_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """jambonz → NEXUS call/recording callbacks.

    DRY-RUN (200, no writes) when disabled. Otherwise HMAC-verifies the body
    (``X-Dialer-Signature`` against ``DIALER_WEBHOOK_SECRET``), upserts the
    ``Call`` by ``provider_call_id`` (candidate matched by phone last-9), and —
    when a recording is present — schedules background transcription →
    Polish note. Returns 200 on unknown/duplicate so the gateway won't retry.
    """
    raw_body = await request.body()

    if not settings.OWN_DIALER_ENABLED:
        return {"status": "dry-run", "enabled": False}

    signature = request.headers.get("X-Dialer-Signature", "")
    if not settings.DIALER_WEBHOOK_SECRET:
        logger.warning("dialer webhook: DIALER_WEBHOOK_SECRET empty while enabled")
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)
    if not verify_dialer_signature(raw_body, signature, settings.DIALER_WEBHOOK_SECRET):
        logger.warning("dialer webhook: signature mismatch")
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)

    try:
        payload = await _safe_parse_json(raw_body)
    except Exception:
        logger.warning("dialer webhook: non-JSON payload")
        return {"status": "skipped", "reason": "non-json"}
    if not isinstance(payload, dict):
        return {"status": "skipped", "reason": "non-object"}

    fields = _extract_jambonz_fields(payload)
    provider_call_id = fields["provider_call_id"]

    call_row: Optional[Call] = None
    if provider_call_id:
        call_row = await db.scalar(
            select(Call).where(Call.provider_call_id == provider_call_id)
        )
    candidate = await _candidate_by_phone(db, fields["phone"])

    if call_row is None and candidate is not None:
        call_row = Call(
            candidate_id=candidate.id,
            direction=fields["direction"],
            status=fields["status"],
            duration_seconds=fields["duration_seconds"],
            recording_url=fields["recording_url"],
            provider_call_id=provider_call_id,
            provider_type="dialer",
            started_at=fields["started_at"],
        )
        db.add(call_row)
    elif call_row is not None:
        if fields["recording_url"]:
            call_row.recording_url = fields["recording_url"]
        if fields["duration_seconds"] is not None:
            call_row.duration_seconds = fields["duration_seconds"]
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

    # Recording present → transcribe + summarize in the background (never block
    # the webhook on network). Deferred import to avoid a heavy module at load.
    if call_row is not None and fields["recording_url"]:
        from app.services.dialer.transcription import schedule_transcription

        schedule_transcription(call_row.id, fields["recording_url"])

    return {
        "status": "ok",
        "call_id": call_row.id if call_row else None,
        "candidate_matched": candidate is not None,
    }


@router.get("/calls/{call_id}/recording")
async def get_call_recording(
    call_id: int,
    current_user: CurrentUser,  # noqa: ARG001 — auth gate (candidate PII)
    db: AsyncSession = Depends(get_db),
):
    """Authed proxy for a call recording (candidate PII — never a public URL).

    Mirrors the CV proxy pattern (StreamingResponse from Object Storage). 404
    when the call has no ``recording_storage_key``.
    """
    call = await db.get(Call, call_id)
    if call is None or not call.recording_storage_key:
        return Response(status_code=status.HTTP_404_NOT_FOUND, content="No recording")

    from app.services.object_storage import download_cv, is_available

    if not is_available():
        return Response(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content="Object storage not configured",
        )
    content = download_cv(call.recording_storage_key)
    return StreamingResponse(
        io.BytesIO(content),
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": f'inline; filename="call-{call_id}.mp3"',
            "Content-Length": str(len(content)),
        },
    )
