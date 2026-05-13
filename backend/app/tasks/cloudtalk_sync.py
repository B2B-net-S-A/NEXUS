"""Background CloudTalk sync — historical backfill + webhook catch-up.

Runs every ``settings.CLOUDTALK_SYNC_INTERVAL_SECONDS`` (default 1h, clamped
to >=300s in the loop) when ``CLOUDTALK_ENABLED=true``. Exits immediately
otherwise — the kill-switch keeps the background task harmless until the
admin provisions credentials and flips the flag.

Responsibilities:
1. Fetch call history from ``GET /calls/index.json`` for the window
   ``[max(MAX(calls.started_at), now() - BACKFILL_DAYS) → now()]``.
2. Upsert each call by ``cloudtalk_call_id``. New rows get the same
   defensive parsing as the webhook handler; existing rows only receive
   transcript / summary / recording_url updates (first-event wins for
   direction/status to avoid race conditions with the live webhook).
3. Trigger Champion enrichment for rows that arrived without a transcript
   from the webhook but the polling endpoint now has one.

Cancellation-aware: ``asyncio.CancelledError`` exits cleanly during
shutdown (mirrors LinkedIn/Autenti/M365 patterns).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.call import Call, CallDirection, CallStatus
from app.models.candidate import Candidate
from app.models.user import User
from app.services.cloudtalk import CloudTalkClient, CloudTalkConfig, CloudTalkError
from app.services.dedup_service import _normalize_phone

logger = logging.getLogger(__name__)


def _interval_seconds() -> int:
    """Loop cadence — clamped to >=300s to avoid hammering CloudTalk."""
    raw = getattr(settings, "CLOUDTALK_SYNC_INTERVAL_SECONDS", 3600)
    return max(300, int(raw))


def _parse_dt(value: Any) -> Optional[datetime]:
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


def _parse_direction(value: Any) -> CallDirection:
    s = str(value or "").strip().lower()
    if s in {"incoming", "inbound", "in"}:
        return CallDirection.inbound
    return CallDirection.outbound


def _parse_status(value: Any) -> CallStatus:
    s = str(value or "").strip().lower()
    if s in {"missed", "no-answer", "no_answer"}:
        return CallStatus.missed
    if s in {"voicemail", "vm"}:
        return CallStatus.voicemail
    if s in {"failed", "error", "busy", "rejected"}:
        return CallStatus.failed
    return CallStatus.completed


async def _resolve_user_id(db, agent_id: Optional[int]) -> Optional[int]:
    if agent_id is None:
        return None
    return await db.scalar(select(User.id).where(User.cloudtalk_agent_id == agent_id))


async def _resolve_candidate_id(db, phone: str) -> Optional[int]:
    last9 = _normalize_phone(phone)
    if not last9:
        return None
    normalized_col = func.right(
        func.regexp_replace(Candidate.phone, r"[^\d]", "", "g"), 9
    )
    return await db.scalar(
        select(Candidate.id)
        .where(Candidate.phone.isnot(None))
        .where(normalized_col == last9)
        .limit(1)
    )


async def _upsert_call(db, raw: dict) -> int:
    """Insert or update a single Call from the CloudTalk index payload.

    Returns 1 if a row was inserted/updated, 0 if the call was skipped.
    """
    ct_id = str(raw.get("id") or raw.get("call_id") or "").strip()
    if not ct_id:
        return 0

    phone = str(
        raw.get("phone") or raw.get("external_number") or raw.get("caller_number") or ""
    ).strip()

    candidate_id = await _resolve_candidate_id(db, phone) if phone else None
    if candidate_id is None:
        # Phone didn't match — skip to avoid orphaned rows. Webhook
        # behavior is the same (returns ok with candidate_matched=false).
        return 0

    agent_raw = raw.get("agent")
    agent_id: Optional[int] = None
    if isinstance(agent_raw, dict):
        try:
            agent_id = int(agent_raw.get("id"))
        except (TypeError, ValueError):
            agent_id = None
    elif raw.get("agent_id") is not None:
        try:
            agent_id = int(raw.get("agent_id"))
        except (TypeError, ValueError):
            agent_id = None

    duration: Optional[int] = None
    raw_dur = raw.get("duration") or raw.get("talking_time")
    if raw_dur is not None:
        try:
            duration = int(raw_dur)
        except (TypeError, ValueError):
            duration = None

    transcript = str(raw.get("transcript") or raw.get("transcription") or "").strip()
    summary = str(raw.get("summary") or "").strip()
    recording_url = (
        str(raw.get("recording_url") or raw.get("recording") or "").strip() or None
    )
    direction = _parse_direction(raw.get("type") or raw.get("direction"))
    status = _parse_status(raw.get("status"))
    started_at = _parse_dt(raw.get("started_at") or raw.get("created_at"))
    user_id = await _resolve_user_id(db, agent_id)

    existing = await db.scalar(select(Call).where(Call.cloudtalk_call_id == ct_id))

    if existing is None:
        db.add(
            Call(
                candidate_id=candidate_id,
                user_id=user_id,
                direction=direction,
                status=status,
                duration_seconds=duration,
                transcript=transcript or None,
                summary=summary or None,
                recording_url=recording_url,
                cloudtalk_call_id=ct_id,
                cloudtalk_agent_id=agent_id,
                started_at=started_at,
            )
        )
        return 1

    # UPDATE — only backfill nullable fields that webhook may have missed.
    changed = False
    if transcript and not existing.transcript:
        existing.transcript = transcript
        changed = True
    if summary and not existing.summary:
        existing.summary = summary
        changed = True
    if recording_url and not existing.recording_url:
        existing.recording_url = recording_url
        changed = True
    if duration is not None and existing.duration_seconds is None:
        existing.duration_seconds = duration
        changed = True
    if user_id is not None and existing.user_id is None:
        existing.user_id = user_id
        changed = True
    if agent_id is not None and existing.cloudtalk_agent_id is None:
        existing.cloudtalk_agent_id = agent_id
        changed = True
    if started_at is not None and existing.started_at is None:
        existing.started_at = started_at
        changed = True
    return 1 if changed else 0


async def _run_sync_window() -> dict:
    """One sync iteration. Returns counters for logging."""
    async with AsyncSessionLocal() as db:
        latest_started = await db.scalar(
            select(func.max(Call.started_at)).where(Call.started_at.isnot(None))
        )

    backfill_floor = datetime.now(timezone.utc) - timedelta(
        days=max(1, int(settings.CLOUDTALK_HISTORICAL_BACKFILL_DAYS))
    )
    since = max(latest_started or backfill_floor, backfill_floor)
    since_iso = since.strftime("%Y-%m-%d %H:%M:%S")
    until_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    try:
        cfg = CloudTalkConfig.from_settings()
    except RuntimeError as exc:
        logger.warning("CloudTalk sync skipped: %s", exc)
        return {"skipped": True}

    inserted = 0
    updated = 0
    page = 1
    async with CloudTalkClient(cfg) as ct:
        while True:
            try:
                calls = await ct.list_calls(
                    date_from=since_iso, date_to=until_iso, limit=100, page=page
                )
            except CloudTalkError as exc:
                logger.warning("CloudTalk sync page=%d failed: %s", page, exc)
                break
            if not calls:
                break

            async with AsyncSessionLocal() as db:
                for raw in calls:
                    ct_id = str(raw.get("id") or raw.get("call_id") or "").strip()
                    if not ct_id:
                        continue
                    pre_existed = (
                        await db.scalar(
                            select(Call.id).where(Call.cloudtalk_call_id == ct_id)
                        )
                        is not None
                    )
                    touched = await _upsert_call(db, raw)
                    if touched:
                        if pre_existed:
                            updated += 1
                        else:
                            inserted += 1
                await db.commit()

            if len(calls) < 100:
                break
            page += 1
            if page > 50:  # belt-and-braces — never page beyond 5k calls/run
                logger.warning("CloudTalk sync: page cap reached, stopping")
                break

    return {"inserted": inserted, "updated": updated, "since": since_iso}


async def cloudtalk_sync_loop() -> None:
    """Periodic CloudTalk catch-up + backfill. Cancellation-aware."""
    logger.info("CloudTalk sync loop started")
    while True:
        try:
            if not settings.CLOUDTALK_ENABLED:
                await asyncio.sleep(60)
                continue
            try:
                stats = await _run_sync_window()
                if not stats.get("skipped"):
                    logger.info(
                        "CloudTalk sync: inserted=%s updated=%s since=%s",
                        stats.get("inserted"),
                        stats.get("updated"),
                        stats.get("since"),
                    )
            except Exception:  # noqa: BLE001
                logger.exception("CloudTalk sync iteration crashed")
            await asyncio.sleep(_interval_seconds())
        except asyncio.CancelledError:
            logger.info("CloudTalk sync loop cancelled — shutting down")
            return
