"""Public (auth-less) endpoint for Outlook Actionable Messages confirmation.

Phase 7.5 of the M365 expansion plan (.claude/plans/elegant-percolating-thimble.md).

When a candidate clicks the "Potwierdzam interview" button in their Outlook
inbox, Microsoft's Actionable Email service POSTs straight here on their
behalf — the candidate never leaves the email client. Authentication is the
JWT carried in the URL: short-lived (7 days), purpose-scoped
(`interview_confirmation`), pinned to one `event_id` + `candidate_id`.

The handler is idempotent: clicking twice is fine (the second call returns
the same thank-you payload without changing the timestamp). Wrong/expired
tokens return 4xx without leaking which of (token, event, candidate) was
invalid — Outlook surfaces the response inline in the message body, so we
return JSON with a friendly message either way.

Rate limited per IP via slowapi to make brute-force token guessing
prohibitively slow.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rate_limit import limiter
from app.models.calendar_event import CalendarEvent
from app.services.m365.actionable_messages import (
    ActionableMessageError,
    verify_confirmation_token,
)


logger = logging.getLogger(__name__)
router = APIRouter()


# Whitelist of accepted `source` values for `CalendarEvent.candidate_confirmation_source`.
# Free-form column in the DB so future channels (SMS, etc.) don't need a
# migration, but the endpoint pins what it accepts to keep provenance clean.
_VALID_CONFIRMATION_SOURCES = {
    "outlook_actionable",
    "manual_email_reply",
    "phone",
}
_DEFAULT_CONFIRMATION_SOURCE = "outlook_actionable"


class InterviewConfirmationResponse(BaseModel):
    success: bool
    message: str
    confirmed_at: datetime


@router.post(
    "/public/interview-confirmation",
    response_model=InterviewConfirmationResponse,
)
@limiter.limit("10/hour")
async def confirm_interview(
    request: Request,  # required by slowapi limiter
    token: str = Query(..., min_length=10, max_length=4096),
    source: Optional[str] = Query(default=None, max_length=50),
    db: AsyncSession = Depends(get_db),
) -> InterviewConfirmationResponse:
    """Accept the candidate's confirmation click from Outlook.

    Validation order matters — token first (cheap, no DB), then event lookup,
    then cross-check the candidate id pinned in the JWT. Each failure returns
    403 without distinguishing which check failed (stops a probe from learning
    "this token decodes but the event is wrong").
    """
    try:
        payload = verify_confirmation_token(token)
    except ActionableMessageError as exc:
        logger.info("interview confirmation token rejected: %s", exc)
        raise HTTPException(status_code=403, detail="Link nieprawidłowy lub wygasł.")

    if payload.get("action") != "confirm_interview":
        logger.info(
            "interview confirmation action mismatch: got %r", payload.get("action")
        )
        raise HTTPException(status_code=403, detail="Link nieprawidłowy lub wygasł.")

    event_id = int(payload["event_id"])
    candidate_id = int(payload["candidate_id"])

    event = await db.scalar(select(CalendarEvent).where(CalendarEvent.id == event_id))
    if event is None:
        logger.info("interview confirmation: event %s not found", event_id)
        raise HTTPException(status_code=403, detail="Link nieprawidłowy lub wygasł.")

    if event.candidate_id != candidate_id:
        # Defence-in-depth: even if our own JWT mint were buggy or replayed
        # against a re-assigned event, the candidate pinned in the token must
        # still own the event row.
        logger.warning(
            "interview confirmation candidate mismatch: token=%s event_owner=%s",
            candidate_id,
            event.candidate_id,
        )
        raise HTTPException(status_code=403, detail="Link nieprawidłowy lub wygasł.")

    chosen_source = (source or _DEFAULT_CONFIRMATION_SOURCE).strip().lower()
    if chosen_source not in _VALID_CONFIRMATION_SOURCES:
        chosen_source = _DEFAULT_CONFIRMATION_SOURCE

    # Idempotent: a second click returns the original confirmation timestamp.
    # We don't overwrite, otherwise users see "you confirmed at 14:02" change
    # to 14:05 on the second click, which is confusing.
    if event.candidate_confirmed_at is None:
        now = datetime.now(timezone.utc)
        event.candidate_confirmed_at = now
        event.candidate_confirmation_source = chosen_source
        await db.commit()
        confirmed_at = now
    else:
        confirmed_at = event.candidate_confirmed_at

    return InterviewConfirmationResponse(
        success=True,
        message="Dziękujemy za potwierdzenie. Do zobaczenia!",
        confirmed_at=confirmed_at,
    )
