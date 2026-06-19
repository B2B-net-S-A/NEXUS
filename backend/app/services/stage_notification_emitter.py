"""Emitter powiadomień stage transition.

Wzorzec best-effort:
    - Top-level try/except — funkcja NIGDY nie rzuca w górę.
    - Per-recipient try/except — błąd jednego usera nie blokuje innych.
    - Per-channel try/except — błąd emaila nie blokuje in-app i odwrotnie.

In-app: korzysta z istniejącego ``emit()`` w
``services/notification_triggers.py`` — to daje DB insert + WS push +
dedup `ix_notif_dedup_daily` w jednym wywołaniu.

Email: SMTP via ``services/email.py:send_email`` — sync, no-op gdy
``SMTP_ENABLED=false``. Treść z hardcoded templatu PL.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job
from app.models.notification import NotificationType
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User
from app.services.email import send_email
from app.services.notification_triggers import emit
from app.services.stage_notification_email_template import render_stage_email
from app.services.stage_notification_resolver import (
    ResolvedRecipient,
    resolve_recipients,
)

logger = logging.getLogger(__name__)


def _candidate_full_name(candidate: Candidate) -> str:
    parts = [getattr(candidate, "name", None), getattr(candidate, "lastname", None)]
    return " ".join(p for p in parts if p) or f"#{candidate.id}"


def _candidate_first_name(candidate: Candidate) -> str:
    return getattr(candidate, "name", None) or f"#{candidate.id}"


async def _client_name(db: AsyncSession, job: Job) -> Optional[str]:
    if not job.client_id:
        return None
    return await db.scalar(select(Client.name).where(Client.id == job.client_id))


async def _user_by_id(db: AsyncSession, user_id: int) -> Optional[User]:
    return await db.scalar(select(User).where(User.id == user_id))


async def _send_inapp(
    db: AsyncSession,
    *,
    user_id: int,
    candidate: Candidate,
    candidate_full_name: str,
    stage_display_name: str,
    job: Job,
    new_stage: CandidateStage,
    mover: Optional[User],
) -> None:
    mover_part = f" przez {mover.name}" if mover else ""
    title = f"Kandydat {candidate_full_name} → {stage_display_name}"
    message = (
        f"Kandydat {candidate_full_name} przeszedł na etap "
        f"„{stage_display_name}” w ofercie '{job.title}' (#{job.id}){mover_part}."
    )
    await emit(
        db,
        user_id=user_id,
        title=title,
        message=message,
        ntype=NotificationType.stage_rule,
        related_entity_type="candidate_stage",
        related_entity_id=new_stage.id,
        link=f"/candidates/{candidate.id}",
    )


def _send_email_for_recipient(
    *,
    user: User,
    candidate: Candidate,
    candidate_full_name: str,
    candidate_first_name: str,
    stage_display_name: str,
    client_name: Optional[str],
    job: Job,
    mover: Optional[User],
    new_stage: CandidateStage,
) -> None:
    if not user.email:
        logger.debug("stage_notif: email skipped — user=%s has no email", user.id)
        return
    base_url = (settings.PUBLIC_BASE_URL or "").rstrip("/")
    link = (
        f"{base_url}/candidates/{candidate.id}"
        if base_url
        else f"/candidates/{candidate.id}"
    )

    subject, text_body, html_body = render_stage_email(
        recipient_name=user.name or user.email,
        candidate_full_name=candidate_full_name,
        candidate_first_name=candidate_first_name,
        stage_name=stage_display_name,
        client_name=client_name,
        job_title=job.title,
        job_id=job.id,
        mover_name=(mover.name if mover else "system"),
        moved_at=new_stage.moved_at,
        notes=new_stage.notes,
        link=link,
    )
    send_email(user.email, subject, text_body, html_body)


async def notify_stage_change(
    db: AsyncSession,
    *,
    new_stage: CandidateStage,
    previous_stage: Optional[CandidateStage],
    job: Job,
    candidate: Candidate,
    mover: Optional[User],
    stage_display_name: str,
) -> int:
    """Emit notyfikacje (in-app + email) zgodnie z regułami.

    Zwraca liczbę pomyślnie wyemitowanych in-app notyfikacji (głównie do
    debugowania / monitoringu — caller może to ignorować).

    Best-effort: nigdy nie rzuca. Wszystkie błędy są logowane.
    """
    try:
        recipients: list[ResolvedRecipient] = await resolve_recipients(
            db,
            new_stage=new_stage,
            previous_stage=previous_stage,
            job=job,
            candidate=candidate,
            mover_user_id=mover.id if mover else None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "stage_notif: resolver failed for stage=%s: %s", new_stage.id, exc
        )
        return 0

    if not recipients:
        return 0

    candidate_full = _candidate_full_name(candidate)
    candidate_first = _candidate_first_name(candidate)

    try:
        client_name = await _client_name(db, job)
    except Exception as exc:  # noqa: BLE001
        logger.warning("stage_notif: client name lookup failed: %s", exc)
        client_name = None

    emitted_inapp = 0
    for rec in recipients:
        if rec.notify_inapp:
            try:
                await _send_inapp(
                    db,
                    user_id=rec.user_id,
                    candidate=candidate,
                    candidate_full_name=candidate_full,
                    stage_display_name=stage_display_name,
                    job=job,
                    new_stage=new_stage,
                    mover=mover,
                )
                emitted_inapp += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "stage_notif: in-app emit failed user=%s stage=%s: %s",
                    rec.user_id,
                    new_stage.id,
                    exc,
                )

        if rec.notify_email:
            try:
                user = await _user_by_id(db, rec.user_id)
                if user is None:
                    logger.debug(
                        "stage_notif: email skipped — user=%s not found",
                        rec.user_id,
                    )
                    continue
                # Blocking smtplib send (+ template render) — offload so the
                # per-recipient loop does not block the event loop.
                await run_in_threadpool(
                    _send_email_for_recipient,
                    user=user,
                    candidate=candidate,
                    candidate_full_name=candidate_full,
                    candidate_first_name=candidate_first,
                    stage_display_name=stage_display_name,
                    client_name=client_name,
                    job=job,
                    mover=mover,
                    new_stage=new_stage,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "stage_notif: email failed user=%s stage=%s: %s",
                    rec.user_id,
                    new_stage.id,
                    exc,
                )

    return emitted_inapp


__all__ = ["notify_stage_change"]
