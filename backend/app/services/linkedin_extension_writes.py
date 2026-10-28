"""Zapisy z wtyczki LinkedIn: osoba, rekrutacje, firma, kontakt, notatka.

Każdy zapis idzie tą samą drogą co w NEXUSIE (``apply_candidate_create``,
przypisanie do rekrutacji z bramką dopuszczalności i off-limits,
``apply_note_create``), żeby wtyczka nie była bocznym wejściem z własnymi
regułami. Commit robi trasa.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today
from app.models.calendar_event import CalendarEvent, EventType
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User
from app.schemas.candidate import CandidateCreate
from app.schemas.linkedin_extension import ContactRequest, ProfileRead, SkippedJob
from app.schemas.note import NoteCreate
from app.services import client_off_limits
from app.services.linkedin_extension_lookup import (
    CHANNEL_LABELS,
    CONTACT_SOURCE_PREFIX,
    find_person,
    profile_link,
    split_full_name,
    years_from_experience,
)
from app.services.write_author import WriteAuthor

logger = logging.getLogger(__name__)

_WARSAW = ZoneInfo("Europe/Warsaw")
EXTENSION_SOURCE = "linkedin_extension"


@dataclass
class AssignOutcome:
    assigned: list[int] = field(default_factory=list)
    skipped: list[SkippedJob] = field(default_factory=list)


def _experience_entries(profile: ProfileRead) -> list[dict]:
    out: list[dict] = []
    for entry in profile.experience[:20]:
        if not (entry.company or entry.title):
            continue
        out.append(
            {
                "role": entry.title,
                "company": entry.company,
                "start": entry.start,
                "end": "present" if entry.current else entry.end,
                "is_current": bool(entry.current),
                "source": "linkedin",
            }
        )
    return out


def _summary_note(profile: ProfileRead) -> Optional[str]:
    lines: list[str] = []
    if profile.headline:
        lines.append(f"Nagłówek: {profile.headline}")
    for entry in profile.experience[:6]:
        dates = " – ".join(
            p for p in (entry.start, "obecnie" if entry.current else entry.end) if p
        )
        line = " · ".join(p for p in (entry.title, entry.company, dates) if p)
        if line:
            lines.append(f"• {line}")
    if profile.skills:
        lines.append("Umiejętności: " + ", ".join(profile.skills[:30]))
    if not lines:
        return None
    return "Z profilu na LinkedInie (wtyczka):\n" + "\n".join(lines)


async def create_candidate(
    db: AsyncSession, user: User, profile: ProfileRead
) -> tuple[Candidate, bool]:
    """Osoba z LinkedIna → kandydat. ``(osoba, czy_nowa)``; ten sam link = ta
    sama osoba, nawet gdy ktoś inny kliknął „Dodaj” sekundę wcześniej."""
    from app.api.candidates import apply_candidate_create

    match = await find_person(db, profile)
    if match.status == "found" and match.matched_by == "linkedin" and match.candidate:
        return match.candidate, False

    name, lastname = split_full_name(profile.full_name)
    if not name or not lastname:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Wpisz imię i nazwisko osoby — panel nie odczytał ich ze strony.",
        )
    data = CandidateCreate(
        name=name[:100],
        lastname=lastname[:100],
        city=(profile.location or "").split(",")[0].strip()[:120] or None,
        linkedin=profile_link(profile),
        source=EXTENSION_SOURCE,
        years_it_experience=years_from_experience(profile),
        skills=[{"name": s[:80]} for s in profile.skills[:60]] or None,
        experience=_experience_entries(profile) or None,
    )
    candidate = await apply_candidate_create(db, data, author=WriteAuthor.person(user))
    candidate.linkedin_current_company = (profile.current_company or "")[:255] or None
    candidate.linkedin_current_title = (
        profile.current_title or profile.headline or ""
    )[:255] or None
    await db.flush()
    summary = _summary_note(profile)
    if summary:
        await add_note(db, user, candidate.id, summary)
    return candidate, True


async def assign_jobs(
    db: AsyncSession,
    user: User,
    candidate_id: int,
    job_ids: list[int],
    off_limits_how: Optional[str],
) -> AssignOutcome:
    """Do kolumny „Nowi” każdej rekrutacji. Off-limits bez odpowiedzi → 409
    (wtyczka zadaje pytanie i ponawia z ``off_limits_how``); „Nie, to my”
    (``skip``) → osoba zostaje w bazie, bez rekrutacji."""
    from app.api.candidates import _assign_candidate_to_job

    outcome = AssignOutcome()
    if not job_ids:
        return outcome
    if off_limits_how == client_off_limits.SKIP:
        outcome.skipped = [
            SkippedJob(job_id=j, reason="Off-limits — to my chcieliśmy się odezwać.")
            for j in job_ids
        ]
        return outcome
    if off_limits_how:
        client_off_limits.add_confirmation(candidate_id, off_limits_how)

    existing = set(
        (
            await db.execute(
                select(CandidateStage.job_id).where(
                    CandidateStage.candidate_id == candidate_id,
                    CandidateStage.job_id.in_(job_ids),
                )
            )
        ).scalars()
    )
    for job_id in dict.fromkeys(job_ids):
        if job_id in existing:
            outcome.skipped.append(
                SkippedJob(job_id=job_id, reason="Już jest w tej rekrutacji.")
            )
            continue
        job = await db.get(Job, job_id)
        if job is None or not job.is_open:
            outcome.skipped.append(
                SkippedJob(job_id=job_id, reason="Rekrutacja jest zamknięta.")
            )
            continue
        try:
            await _assign_candidate_to_job(
                db=db,
                candidate_id=candidate_id,
                job_id=job_id,
                stage=PipelineStage.new,
                user_id=user.id,
            )
        except HTTPException as exc:
            if exc.status_code != status.HTTP_409_CONFLICT:
                raise
            outcome.skipped.append(SkippedJob(job_id=job_id, reason=str(exc.detail)))
            continue
        outcome.assigned.append(job_id)
    return outcome


async def refresh_from_profile(
    db: AsyncSession, candidate: Candidate, profile: ProfileRead
) -> list[str]:
    updated: list[str] = []
    company = (profile.current_company or "").strip()[:255]
    title = (profile.current_title or profile.headline or "").strip()[:255]
    if company and company != (candidate.linkedin_current_company or ""):
        candidate.linkedin_current_company = company
        updated.append("current_company")
    if title and title != (candidate.linkedin_current_title or ""):
        candidate.linkedin_current_title = title
        updated.append("current_title")
    if not candidate.linkedin:
        link = profile_link(profile)
        if link:
            candidate.linkedin = link
            updated.append("linkedin")
    return updated


async def add_note(
    db: AsyncSession,
    user: User,
    candidate_id: int,
    text: str,
    *,
    job_id: Optional[int] = None,
    kind: Optional[str] = None,
    source_ref: Optional[str] = None,
):
    from app.api.notes import apply_note_create

    created = await apply_note_create(
        db,
        NoteCreate(content=text, candidate_id=candidate_id, job_id=job_id, kind=kind),
        author=WriteAuthor.person(user),
    )
    if source_ref:
        created.note.source_ref = source_ref
    await db.flush()
    return created


def _reminder_start(days: int) -> datetime:
    """9:00 w N-tym dniu roboczym od dziś (kalendarz firmy)."""
    day = business_today()
    left = days
    while left > 0:
        day += timedelta(days=1)
        if day.weekday() < 5:
            left -= 1
    return datetime.combine(day, time(9, 0), tzinfo=_WARSAW)


async def log_contact(
    db: AsyncSession, user: User, candidate: Candidate, data: ContactRequest
):
    """Kontakt jako notatka „próba kontaktu” (widzi ją cały zespół w profilu
    i w panelu) plus opcjonalne przypomnienie w kalendarzu rekrutera."""
    channel = CHANNEL_LABELS[data.channel]
    job_title = None
    if data.job_id is not None:
        job = await db.get(Job, data.job_id)
        job_title = job.title if job else None
    parts = [f"{channel[0].upper()}{channel[1:]} wysłane z LinkedIna"]
    if data.channel == "phone":
        parts = ["Telefon (zapisany z LinkedIna)"]
    if job_title:
        parts.append(f"rekrutacja: {job_title}")
    content = " · ".join(parts)
    if data.note and data.note.strip():
        content += f"\n{data.note.strip()}"
    created = await add_note(
        db,
        user,
        candidate.id,
        content,
        job_id=data.job_id if job_title else None,
        kind="contact_attempt",
        source_ref=f"{CONTACT_SOURCE_PREFIX}{data.channel}",
    )
    reminder_id: Optional[int] = None
    if data.remind_in_days:
        name = " ".join(p for p in (candidate.name, candidate.lastname) if p)
        event = CalendarEvent(
            title=f"Odezwij się: {name} (LinkedIn)",
            description=content,
            event_type=EventType.deadline,
            start_time=_reminder_start(data.remind_in_days),
            all_day=False,
            candidate_id=candidate.id,
            job_id=data.job_id if job_title else None,
            created_by=user.id,
            operational_owner_id=user.id,
            reminder_minutes=0,
        )
        db.add(event)
        await db.flush()
        reminder_id = event.id
    return created, reminder_id
