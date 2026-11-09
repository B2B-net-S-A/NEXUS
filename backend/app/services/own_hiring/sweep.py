"""Przebieg pętli: import zgłoszeń, licznik odpowiedzi, ponowienia, przypomnienia."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today
from app.models.candidate import Candidate
from app.models.candidate_source_event import CandidateSourceEvent, SourceChannel
from app.models.m365 import Email, EmailDirection
from app.models.own_hiring import (
    OwnHiringApplication,
    OwnHiringBooking,
    OwnHiringProcess,
)
from app.services.m365 import sender as m365_sender
from app.services.own_hiring import booking as booking_service
from app.services.own_hiring import mail as mail_text
from app.services.own_hiring.candidate_filter import (
    classify,
    normalize_title,
    parse_offer_note,
)
from app.services.own_hiring.service import (
    ENTITY_APPLICATION,
    current_token,
    log_event,
    merged_settings,
    notify,
    now_utc,
    owner_connection,
    public_link,
    set_stage,
)

logger = logging.getLogger(__name__)

INTAKE_BATCH = 2000
INTAKE_BATCHES_PER_RUN = 10
MAX_SYNC_ATTEMPTS = 6
REMINDER_WINDOW = timedelta(hours=24)
REMINDER_MIN_NOTICE = timedelta(hours=6)


async def intake(db: AsyncSession, process: OwnHiringProcess) -> int:
    """Czyta zdarzenia źródeł po kursorze. Scrapery i ich trasy zostają bez zmian."""
    wanted = {normalize_title(title) for title in process.ad_titles or []}
    if not wanted:
        return 0
    added = 0
    today = business_today()
    for _ in range(INTAKE_BATCHES_PER_RUN):
        rows = (
            await db.execute(
                select(
                    CandidateSourceEvent.id,
                    CandidateSourceEvent.candidate_id,
                    CandidateSourceEvent.note,
                    CandidateSourceEvent.captured_at,
                )
                .where(
                    CandidateSourceEvent.id > process.intake_cursor,
                    CandidateSourceEvent.channel == SourceChannel.posting,
                    CandidateSourceEvent.captured_at >= process.intake_since,
                )
                .order_by(CandidateSourceEvent.id)
                .limit(INTAKE_BATCH)
            )
        ).all()
        if not rows:
            break
        for event_id, candidate_id, note, captured_at in rows:
            parsed = parse_offer_note(note)
            if parsed is None or normalize_title(parsed[1]) not in wanted:
                continue
            added += await _add_application(
                db, process, candidate_id, parsed, captured_at, today
            )
        process.intake_cursor = rows[-1][0]
        await db.commit()
        if len(rows) < INTAKE_BATCH:
            break
    return added


async def _add_application(
    db: AsyncSession,
    process: OwnHiringProcess,
    candidate_id: int,
    parsed: tuple[str, str],
    captured_at: Any,
    today: Any,
) -> int:
    candidate = await db.get(Candidate, candidate_id)
    if candidate is None or candidate.blacklisted_at is not None:
        return 0
    verdict = classify(candidate.experience, today)
    source, title = parsed
    inserted = await db.scalar(
        pg_insert(OwnHiringApplication)
        .values(
            process_id=process.id,
            candidate_id=candidate_id,
            bucket=verdict.bucket,
            filter_reason=verdict.reason,
            evidence=verdict.evidence,
            source_label=source[:80],
            ad_title=title[:300],
            applied_at=captured_at,
        )
        .on_conflict_do_nothing(constraint="uq_own_hiring_application")
        .returning(OwnHiringApplication.id)
    )
    return 1 if inserted is not None else 0


async def reclassify_unread(db: AsyncSession, process: OwnHiringProcess) -> int:
    """CV bywa odczytane po imporcie: zakładka „Do sprawdzenia” się wyrównuje."""
    rows = (
        await db.execute(
            select(OwnHiringApplication, Candidate)
            .join(Candidate, Candidate.id == OwnHiringApplication.candidate_id)
            .where(
                OwnHiringApplication.process_id == process.id,
                OwnHiringApplication.stage == "new",
                OwnHiringApplication.filter_reason == "cv_unread",
                case(
                    (
                        func.jsonb_typeof(Candidate.experience) == "array",
                        func.jsonb_array_length(Candidate.experience),
                    ),
                    else_=0,
                )
                > 0,
            )
            .limit(200)
        )
    ).all()
    today = business_today()
    for application, candidate in rows:
        verdict = classify(candidate.experience, today)
        application.bucket = verdict.bucket
        application.filter_reason = verdict.reason
        application.evidence = verdict.evidence
    await db.commit()
    return len(rows)


async def mark_replies(db: AsyncSession, process: OwnHiringProcess) -> int:
    """Mail od osoby zaproszonej zatrzymuje licznik i daje znacznik „Odpisał”."""
    has_content = func.coalesce(Email.body_preview, "") != ""
    rows = (
        await db.execute(
            select(OwnHiringApplication, func.max(Email.received_at))
            .join(Email, Email.candidate_id == OwnHiringApplication.candidate_id)
            .where(
                OwnHiringApplication.process_id == process.id,
                OwnHiringApplication.stage == "invited",
                OwnHiringApplication.replied_at.is_(None),
                Email.user_id == process.owner_user_id,
                Email.direction == EmailDirection.received,
                Email.received_at > OwnHiringApplication.invited_at,
                has_content,
            )
            .group_by(OwnHiringApplication.id)
        )
    ).all()
    for application, received_at in rows:
        application.replied_at = received_at
        log_event(db, application, "replied_by_mail")
        await notify(
            db,
            user_id=process.owner_user_id,
            title="Kandydat odpisał na zaproszenie",
            message=process.title,
            entity_type=ENTITY_APPLICATION,
            entity_id=application.id,
        )
    await db.commit()
    return len(rows)


async def expire_invitations(db: AsyncSession, process: OwnHiringProcess) -> int:
    now = now_utc()
    rows = list(
        await db.scalars(
            select(OwnHiringApplication)
            .where(
                OwnHiringApplication.process_id == process.id,
                OwnHiringApplication.stage == "invited",
                OwnHiringApplication.replied_at.is_(None),
                OwnHiringApplication.response_due_at <= now,
            )
            .with_for_update(skip_locked=True)
        )
    )
    for application in rows:
        set_stage(application, "no_response", now)
        log_event(db, application, "no_response")
    await db.commit()
    return len(rows)


async def retry_calendar(db: AsyncSession, process: OwnHiringProcess) -> int:
    ids = list(
        await db.scalars(
            select(OwnHiringBooking.id).where(
                OwnHiringBooking.process_id == process.id,
                OwnHiringBooking.status == "active",
                OwnHiringBooking.graph_event_id.is_(None),
                OwnHiringBooking.sync_attempts < MAX_SYNC_ATTEMPTS,
                OwnHiringBooking.start_at > now_utc(),
            )
        )
    )
    for booking_id in ids:
        await booking_service.sync_to_calendar(db, booking_id)
    return len(ids)


async def send_reminders(db: AsyncSession, process: OwnHiringProcess) -> int:
    now = now_utc()
    rows = (
        await db.execute(
            select(OwnHiringBooking, OwnHiringApplication, Candidate)
            .join(
                OwnHiringApplication,
                OwnHiringApplication.id == OwnHiringBooking.application_id,
            )
            .join(Candidate, Candidate.id == OwnHiringApplication.candidate_id)
            .where(
                OwnHiringBooking.process_id == process.id,
                OwnHiringBooking.status == "active",
                OwnHiringBooking.reminder_sent_at.is_(None),
                OwnHiringBooking.start_at > now,
                OwnHiringBooking.start_at <= now + REMINDER_WINDOW,
                OwnHiringBooking.created_at <= now - REMINDER_MIN_NOTICE,
                Candidate.email.is_not(None),
            )
        )
    ).all()
    if not rows:
        return 0
    connection = await owner_connection(db, process)
    if connection is None:
        return 0
    sent = 0
    address = str(merged_settings(process).get("office_address") or "")
    for booking, application, candidate in rows:
        token = current_token(application)
        text = mail_text.reminder(
            role_title=process.title,
            start=booking.start_at,
            office_address=address if booking.kind == "office" else "",
            link=public_link(token) if token else "",
        )
        try:
            await m365_sender.send_new(
                db,
                connection,
                to=[candidate.email],
                subject=text.subject,
                body_html=text.body_html,
                client_request_id=f"own-hiring-reminder:{booking.id}",
                commit_reservation=True,
            )
        except Exception as exc:  # noqa: BLE001 — następny przebieg ponowi
            await db.rollback()
            logger.warning(
                "own_hiring.reminder_failed booking=%s error=%s",
                booking.id,
                type(exc).__name__,
            )
            continue
        booking.reminder_sent_at = now_utc()
        await db.commit()
        sent += 1
    return sent


async def run_once(db: AsyncSession) -> dict[str, int]:
    totals = {"imported": 0, "replied": 0, "expired": 0, "synced": 0, "reminded": 0}
    processes = list(
        await db.scalars(
            select(OwnHiringProcess).where(OwnHiringProcess.is_active.is_(True))
        )
    )
    for process in processes:
        totals["imported"] += await intake(db, process)
        await reclassify_unread(db, process)
        totals["replied"] += await mark_replies(db, process)
        totals["expired"] += await expire_invitations(db, process)
        totals["synced"] += await retry_calendar(db, process)
        totals["reminded"] += await send_reminders(db, process)
    return totals
