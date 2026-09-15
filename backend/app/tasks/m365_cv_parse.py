"""Durable worker for CV attachments downloaded by the Microsoft 365 sync."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from uuid import uuid4

from sqlalchemy import or_, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.operation_telemetry import record_job_outcome
from app.models.m365 import Email, EmailAttachment
from app.services.m365 import attachment_handler

logger = logging.getLogger(__name__)


async def run_m365_cv_parse_once() -> bool:
    """Claim and process one committed attachment; return whether work existed.

    ``FOR UPDATE SKIP LOCKED`` prevents duplicate paid parsing when more than
    one app process runs the lifespan task.  The transaction remains open until
    the parser result is committed, so a process crash releases the claim and
    leaves an unattempted row eligible for recovery.
    """
    if not (settings.M365_INTEGRATION_ENABLED and settings.M365_AUTO_PARSE_CV):
        return False

    async with AsyncSessionLocal() as db:
        attachment = await db.scalar(
            select(EmailAttachment)
            .join(Email, Email.id == EmailAttachment.email_id)
            .where(
                EmailAttachment.is_cv_candidate.is_(True),
                EmailAttachment.storage_path.is_not(None),
                Email.candidate_id.is_not(None),
                # SQL NULL-safe comparison. Without this predicate, legacy
                # rows already applied to their current candidate but lacking
                # an attempt timestamp would be claimed forever.
                EmailAttachment.parsed_candidate_id.is_distinct_from(
                    Email.candidate_id
                ),
                or_(
                    # First attempt. A completed error is terminal because the
                    # parser already performs provider retry/fallback internally.
                    EmailAttachment.cv_parse_attempted_at.is_(None),
                    # Candidate rematch: apply the same source to its new owner.
                    EmailAttachment.parsed_candidate_id.is_not(None),
                ),
            )
            .order_by(EmailAttachment.id.asc())
            # Lock only the work row. Locking the joined email as well would
            # let a slow parser stall the next Graph delta page for that mail.
            .with_for_update(skip_locked=True, of=EmailAttachment)
            .limit(1)
        )
        if attachment is None:
            return False

        email_row = await db.get(Email, attachment.email_id)
        if email_row is None or email_row.candidate_id is None:
            return False

        operation_id = str(uuid4())
        started = time.monotonic()
        logger.info(
            "m365_cv_parse_started",
            extra={
                "event_kind": "m365_cv_parse_progress",
                "operation": "m365_cv_parse",
                "operation_id": operation_id,
                "subject_id": attachment.id,
                "phase": "started",
                "release": os.getenv("GIT_SHA", "unknown"),
                "environment": os.getenv("SENTRY_ENVIRONMENT", "production"),
            },
        )
        await attachment_handler.try_parse_cv(db, attachment, email_row)
        success = attachment.parsed_candidate_id == email_row.candidate_id
        await db.commit()
        logger.info(
            "m365_cv_parse_completed",
            extra={
                "event_kind": "m365_cv_parse_progress",
                "operation": "m365_cv_parse",
                "operation_id": operation_id,
                "subject_id": attachment.id,
                "phase": "completed",
                "outcome": "success" if success else "failure",
                "elapsed_ms": round((time.monotonic() - started) * 1000),
                "release": os.getenv("GIT_SHA", "unknown"),
                "environment": os.getenv("SENTRY_ENVIRONMENT", "production"),
            },
        )
        record_job_outcome(
            "m365_cv_parse",
            success,
            interval_seconds=max(60, settings.M365_CV_PARSE_INTERVAL_SECONDS),
            subject_id=attachment.id,
        )
        return True


async def m365_cv_parse_loop() -> None:
    """Continuously drain committed CV attachments in bounded transactions."""
    if not (settings.M365_INTEGRATION_ENABLED and settings.M365_AUTO_PARSE_CV):
        logger.info("m365_cv_parse_loop disabled")
        return

    interval = max(5, min(settings.M365_CV_PARSE_INTERVAL_SECONDS, 3600))
    logger.info("m365_cv_parse_loop started: interval=%ds", interval)
    await asyncio.sleep(45)
    while True:
        try:
            processed = await run_m365_cv_parse_once()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("m365_cv_parse_loop iteration failed")
            processed = False
        await asyncio.sleep(interval if not processed else 1)


__all__ = ["m365_cv_parse_loop", "run_m365_cv_parse_once"]
