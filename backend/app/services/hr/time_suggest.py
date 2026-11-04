"""Podpowiedź opisu dnia z pracy w NEXUSIE (bez AI).

Źródła z jednego dnia kalendarza firmy, wyłącznie dla zalogowanej osoby:
rozmowy telefoniczne (``calls``), zmiany etapów kart w rekrutacjach
(``candidate_stages.moved_by``; osobno weryfikacje i CV do klienta), rozmowy
u klienta (``calendar_events``), notatki. Podpowiedź niesie same liczby,
godziny i nazwy rekrutacji — nigdy imion kandydatów ani tytułów wydarzeń
(te potrafią zawierać nazwisko). Wstawia się dopiero po kliknięciu.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import DEFAULT_TZ, local_day_start_utc
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.call import Call, CallStatus
from app.models.job import Job
from app.models.note import Note
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.services.job_working_title import job_display_title_expr

MAX_JOBS = 3


def plural(count: int, one: str, few: str, many: str) -> str:
    if count == 1:
        return one
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return few
    return many


def _counted(count: int, one: str, few: str, many: str) -> Optional[str]:
    return f"{count} {plural(count, one, few, many)}" if count else None


async def day_activity(db: AsyncSession, *, user_id: int, day: date) -> dict[str, Any]:
    start = local_day_start_utc(day)
    end = local_day_start_utc(day + timedelta(days=1))

    calls = await db.scalar(
        select(func.count(Call.id)).where(
            Call.user_id == user_id,
            Call.status == CallStatus.completed,
            func.coalesce(Call.started_at, Call.created_at) >= start,
            func.coalesce(Call.started_at, Call.created_at) < end,
        )
    )
    moves = (
        await db.execute(
            select(CandidateStage.stage, CandidateStage.job_id).where(
                CandidateStage.moved_by == user_id,
                CandidateStage.moved_at >= start,
                CandidateStage.moved_at < end,
            )
        )
    ).all()
    interviews = (
        await db.execute(
            select(CalendarEvent.start_time, CalendarEvent.job_id)
            .where(
                CalendarEvent.event_type == EventType.client_interview,
                CalendarEvent.status != EventStatus.cancelled,
                (CalendarEvent.operational_owner_id == user_id)
                | (CalendarEvent.created_by == user_id),
                CalendarEvent.start_time >= start,
                CalendarEvent.start_time < end,
            )
            .order_by(CalendarEvent.start_time)
        )
    ).all()
    notes = await db.scalar(
        select(func.count(Note.id)).where(
            Note.author_id == user_id,
            Note.created_at >= start,
            Note.created_at < end,
        )
    )

    job_ids: list[int] = []
    for _, job_id in [*moves, *interviews]:
        if job_id is not None and job_id not in job_ids:
            job_ids.append(job_id)
    titles: dict[int, str] = {}
    if job_ids:
        titles = dict(
            (
                await db.execute(
                    select(Job.id, job_display_title_expr()).where(Job.id.in_(job_ids))
                )
            ).all()
        )

    verified = sum(1 for stage, _ in moves if stage == PipelineStage.verified)
    cv_sent = sum(1 for stage, _ in moves if stage == PipelineStage.cv_sent)
    counts = {
        "calls": int(calls or 0),
        "stage_moves": len(moves),
        "verifications": verified,
        "cv_sent": cv_sent,
        "client_interviews": len(interviews),
        "notes": int(notes or 0),
    }
    zone = ZoneInfo(DEFAULT_TZ)
    meetings = [
        {
            "time": start_time.astimezone(zone).strftime("%H:%M"),
            "job": titles.get(job_id) if job_id else None,
        }
        for start_time, job_id in interviews
    ]
    jobs = [titles[job_id] for job_id in job_ids if job_id in titles][:MAX_JOBS]
    return {
        "day": day.isoformat(),
        "counts": counts,
        "jobs": jobs,
        "client_interviews": meetings,
        "text": suggestion_text(counts, jobs, meetings),
    }


def suggestion_text(
    counts: dict[str, int], jobs: list[str], meetings: list[dict[str, Any]]
) -> Optional[str]:
    parts = [
        _counted(counts["calls"], "rozmowa", "rozmowy", "rozmów"),
        _counted(counts["verifications"], "weryfikacja", "weryfikacje", "weryfikacji"),
        f"{counts['cv_sent']} CV do klienta" if counts["cv_sent"] else None,
        _counted(
            counts["stage_moves"] - counts["verifications"] - counts["cv_sent"],
            "zmiana etapu",
            "zmiany etapów",
            "zmian etapów",
        ),
        _counted(counts["notes"], "notatka", "notatki", "notatek"),
    ]
    for meeting in meetings:
        label = f"rozmowa u klienta {meeting['time']}"
        parts.append(f"{label} ({meeting['job']})" if meeting["job"] else label)
    activity = ", ".join(part for part in parts if part)
    if not activity and not jobs:
        return None
    if jobs:
        lead = f"Rekrutacje: {', '.join(jobs)}"
        return f"{lead} — {activity}" if activity else lead
    return activity[0].upper() + activity[1:]
