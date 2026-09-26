"""Durable worker for CV attachments downloaded by the Microsoft 365 sync."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import or_, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.operation_telemetry import record_job_outcome
from app.models.m365 import Email, EmailAttachment, M365Connection
from app.services.m365 import attachment_handler
from app.services.m365.graph_client import GraphClient

# INT-08 — przerwa między próbami pobrania tego samego załącznika. Liczona od
# ``updated_at`` wiersza (każda porażka go podbija).
DOWNLOAD_RETRY_BACKOFF = timedelta(minutes=15)
# Wiersze z 1–4 porażkami; piąta jest ostateczna (MAX_DOWNLOAD_ATTEMPTS).
_RETRYABLE_DOWNLOAD_ERROR = r"^download_failed(\[[1-4]\])?:"

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
            return await _create_from_unknown_sender_once(db)

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
        attachment_id = attachment.id
        candidate_id = email_row.candidate_id
        try:
            await attachment_handler.try_parse_cv(db, attachment, email_row)
            success = attachment.parsed_candidate_id == candidate_id
            if not success:
                # Runda 6 audytu: nieudana próba jest końcowa. Bez tego wiersz
                # po rematchu (``parsed_candidate_id`` = poprzedni kandydat) był
                # brany ponownie co sekundę razem z płatnym ``parse_cv``.
                attachment.parsed_candidate_id = None
            await db.commit()
        except Exception as exc:  # noqa: BLE001
            # Runda 6 audytu: wyjątek (np. naruszenie więzu przy zapisie
            # profilu) cofał transakcję RAZEM ze znacznikiem próby, więc ten sam
            # załącznik wracał co kilka sekund na płatny odczyt, a reszta
            # kolejki stała. Próbę znaczymy we własnej transakcji — lustro
            # ścieżki nieznanego nadawcy niżej. Log bez danych osobowych.
            await db.rollback()
            logger.error(
                "m365 CV parse failed attachment=%s (%s)",
                attachment_id,
                type(exc).__name__,
            )
            await _mark_parse_failed(attachment_id, exc)
            success = False
        logger.info(
            "m365_cv_parse_completed",
            extra={
                "event_kind": "m365_cv_parse_progress",
                "operation": "m365_cv_parse",
                "operation_id": operation_id,
                "subject_id": attachment_id,
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
            subject_id=attachment_id,
        )
        return True


async def _mark_parse_failed(attachment_id: int, exc: BaseException) -> None:
    """Oznacz próbę jako końcową w osobnej transakcji (runda 6 audytu)."""
    async with AsyncSessionLocal() as mark_db:
        row = await mark_db.get(EmailAttachment, attachment_id)
        if row is None:
            return
        row.cv_parse_attempted_at = datetime.now(timezone.utc)
        row.parsed_candidate_id = None
        row.parse_error = f"parse_failed: {type(exc).__name__}"[:500]
        await mark_db.commit()


async def _create_from_unknown_sender_once(db) -> bool:
    """CV z maila od nadawcy spoza bazy (decyzja Artura, 17.09.2026).

    Osobne zapytanie po kolejce znanych kandydatów: najpierw odświeżamy profile
    osób, które już są w bazie, potem zakładamy nowe. Okno czasu
    (`M365_AUTO_CREATE_LOOKBACK_DAYS`) chroni przed założeniem kandydatów
    z całej historii skrzynek w pierwszym biegu po wdrożeniu.
    """
    if not settings.M365_AUTO_CREATE_CANDIDATE_FROM_CV:
        return False
    from app.models.m365 import EmailDirection

    since = datetime.now(timezone.utc) - timedelta(
        days=max(1, settings.M365_AUTO_CREATE_LOOKBACK_DAYS)
    )
    attachment = await db.scalar(
        select(EmailAttachment)
        .join(Email, Email.id == EmailAttachment.email_id)
        .where(
            EmailAttachment.is_cv_candidate.is_(True),
            EmailAttachment.storage_path.is_not(None),
            EmailAttachment.cv_parse_attempted_at.is_(None),
            EmailAttachment.parse_error.is_(None),
            Email.candidate_id.is_(None),
            # Runda 6 audytu: ręcznie odpięty mail nie wraca do kandydata z CV.
            Email.matched_by_user_id.is_(None),
            Email.direction == EmailDirection.received,
            Email.is_private_filtered.is_(False),
            Email.received_at >= since,
        )
        .order_by(EmailAttachment.id.asc())
        .with_for_update(skip_locked=True, of=EmailAttachment)
        .limit(1)
    )
    if attachment is None:
        return False
    email_row = await db.get(Email, attachment.email_id)
    if email_row is None:
        return False
    attachment_id = attachment.id
    try:
        candidate_id = await attachment_handler.try_create_candidate_from_cv(
            db, attachment, email_row
        )
        if candidate_id is None and attachment.parse_error is None:
            attachment.parse_error = "unknown_sender_skipped"
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        # Bez tego wyjątek cofał transakcję razem ze znacznikiem próby i ten sam
        # załącznik wracał co kilka sekund na pełny, płatny odczyt CV.
        await db.rollback()
        logger.exception("m365 unknown-sender CV failed attachment=%s", attachment_id)
        async with AsyncSessionLocal() as mark_db:
            row = await mark_db.get(EmailAttachment, attachment_id)
            if row is not None:
                row.parse_error = f"unknown_sender_failed: {type(exc).__name__}"[:500]
                await mark_db.commit()
        return True
    logger.info(
        "m365_cv_unknown_sender_processed",
        extra={
            "event_kind": "m365_cv_parse_progress",
            "operation": "m365_cv_create",
            "subject_id": attachment.id,
            "outcome": "linked_or_created" if candidate_id else "skipped",
            "reason": attachment.parse_error,
        },
    )
    return True


async def run_m365_attachment_retry_once() -> bool:
    """Ponów jedno nieudane pobranie załącznika (INT-08). ``True`` = była praca.

    Do 09.2026 załącznik, którego pobranie raz padło, zostawał bez pliku na
    zawsze: parser wymaga ``storage_path``, a delta maila była już
    potwierdzona. Najwyżej ``MAX_DOWNLOAD_ATTEMPTS`` prób, co
    ``DOWNLOAD_RETRY_BACKOFF``; sukces czyści ``parse_error`` i załącznik
    trafia do zwykłej kolejki parsera.
    """
    if not settings.M365_INTEGRATION_ENABLED:
        return False
    cutoff = datetime.now(timezone.utc) - DOWNLOAD_RETRY_BACKOFF
    async with AsyncSessionLocal() as db:
        attachment = await db.scalar(
            select(EmailAttachment)
            .join(Email, Email.id == EmailAttachment.email_id)
            .join(M365Connection, M365Connection.user_id == Email.user_id)
            .where(
                EmailAttachment.storage_path.is_(None),
                EmailAttachment.parse_error.regexp_match(_RETRYABLE_DOWNLOAD_ERROR),
                EmailAttachment.updated_at < cutoff,
                M365Connection.is_active.is_(True),
            )
            .order_by(EmailAttachment.is_cv_candidate.desc(), EmailAttachment.id)
            .with_for_update(skip_locked=True, of=EmailAttachment)
            .limit(1)
        )
        if attachment is None:
            return False
        email_row = await db.get(Email, attachment.email_id)
        connection = await db.scalar(
            select(M365Connection).where(M365Connection.user_id == email_row.user_id)
        )
        attachment_id = attachment.id
        try:
            async with GraphClient(connection, db) as gc:
                ok = await attachment_handler.retry_attachment_download(
                    gc, email_row, attachment
                )
        except Exception as exc:  # noqa: BLE001 — właściciel/token/Graph
            ok = False
            attachment_handler.mark_download_failed(attachment, exc)
        await db.commit()
        logger.info(
            "m365_attachment_download_retry",
            extra={
                "event_kind": "m365_cv_parse_progress",
                "operation": "m365_attachment_download_retry",
                "subject_id": attachment_id,
                "outcome": "success" if ok else "failure",
            },
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
            if not processed:
                processed = await run_m365_attachment_retry_once()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("m365_cv_parse_loop iteration failed")
            processed = False
        await asyncio.sleep(interval if not processed else 1)


__all__ = [
    "m365_cv_parse_loop",
    "run_m365_attachment_retry_once",
    "run_m365_cv_parse_once",
]
