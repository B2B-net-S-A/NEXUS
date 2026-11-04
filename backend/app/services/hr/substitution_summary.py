"""Kafelek pulpitu „W zastępstwie” — praca, którą osoba dziś prowadzi za kolegę.

Kto kogo zastępuje, mówi wyłącznie silnik zastępstw (``workforce_context``):
te same delegacje wkładają rekrutacje nieobecnego do „Moich” zastępcy
(``operational_owner_clause``), jego rozmowy do kalendarza zastępcy
(``effective_owner_ids``) i jego karty do zakresu „Moje” na liście. Tu nie ma
własnej reguły „kto przejmuje” — liczymy tylko to, co silnik już przekazał,
tymi samymi warunkami co lista rekrutacji:

* **rekrutacje** — nieobecny jest Rekruterem (i nie jest „Poprzednim
  rekruterem”) albo Delivery Leadem, rekrutacja otwarta albo z otwartym
  zadaniem operacyjnym (``open_operational_job_clause``),
* **rozmowy u klienta** — zaplanowane ``client_interview`` nieobecnego od
  teraz do końca zastępstwa,
* **kandydaci w procesie** — otwarte procesy, których właścicielem jest
  nieobecny.

Przegląd Delivery Leada przed wysłaniem CV NIE idzie za zastępstwem
(``board_tasks.reviews_as_dl`` patrzy na samo konto), więc kafelek go nie
obiecuje.

Ostrzeżenie ``substitute_absent`` (zastępca też jest nieobecny — silnik nie
przekazał wtedy pracy) widzą: wpisany zastępca i przełożony osoby nieobecnej.
Rodzaju nieobecności tu nie ma (D6).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.scheduling import local_day_start_utc
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.recruitment_process import ProcessStatus, RecruitmentProcess
from app.models.user import User
from app.services.hr import people
from app.services.hr.availability_local import availability_enabled
from app.services.job_previous_recruiters import parked_exists
from app.services.job_working_title import job_display_title_expr
from app.services.workforce_availability import (
    Delegation,
    open_operational_job_clause,
    workforce_context,
)

#: Ile pozycji (rekrutacji, rozmów) pokazać z nazwy — reszta to liczba.
PREVIEW_LIMIT = 3
SUBSTITUTE_ABSENT = "substitute_absent"


def _inherited_jobs_clause(owner_id: int):
    """Rekrutacje nieobecnego, które silnik wkłada do „Moich” zastępcy.

    Lustro gałęzi „odziedziczonej” ``operational_owner_clause`` dla tabeli
    ``jobs`` i zakresu ``jobs_mine_working_clause`` (Rekruter bez uśpienia
    albo Delivery Lead).
    """

    return and_(
        or_(
            and_(
                Job.recruiter_id == owner_id,
                ~parked_exists(Job.id, Job.recruiter_id),
            ),
            Job.delivery_lead_id == owner_id,
        ),
        or_(
            and_(Job.is_open.is_(True), Job.status != JobStatus.closed),
            open_operational_job_clause(Job.id, {owner_id}),
        ),
    )


async def _recruitments(db: AsyncSession, owner_id: int) -> dict[str, Any]:
    clause = _inherited_jobs_clause(owner_id)
    count = await db.scalar(select(func.count(Job.id)).where(clause))
    rows = (
        await db.execute(
            select(Job.id, job_display_title_expr(), Client.name)
            .outerjoin(Client, Client.id == Job.client_id)
            .where(clause)
            .order_by(Job.deadline.asc().nulls_last(), Job.id)
            .limit(PREVIEW_LIMIT)
        )
    ).all()
    return {
        "count": int(count or 0),
        "items": [
            {"job_id": job_id, "title": title, "client_name": client_name}
            for job_id, title, client_name in rows
        ],
    }


async def _client_meetings(
    db: AsyncSession, delegation: Delegation, *, now: datetime
) -> dict[str, Any]:
    owner = func.coalesce(CalendarEvent.operational_owner_id, CalendarEvent.created_by)
    window_end = local_day_start_utc(delegation.end_date + timedelta(days=1))
    filters = (
        owner == delegation.owner_id,
        CalendarEvent.status == EventStatus.scheduled,
        CalendarEvent.event_type == EventType.client_interview,
        CalendarEvent.start_time >= now,
        CalendarEvent.start_time < window_end,
    )
    count = await db.scalar(select(func.count(CalendarEvent.id)).where(*filters))
    event_client = aliased(Client)
    job_client = aliased(Client)
    rows = (
        await db.execute(
            select(
                CalendarEvent.id,
                CalendarEvent.start_time,
                func.coalesce(event_client.name, job_client.name),
            )
            .outerjoin(event_client, event_client.id == CalendarEvent.client_id)
            .outerjoin(Job, Job.id == CalendarEvent.job_id)
            .outerjoin(job_client, job_client.id == Job.client_id)
            .where(*filters)
            .order_by(CalendarEvent.start_time, CalendarEvent.id)
            .limit(PREVIEW_LIMIT)
        )
    ).all()
    return {
        "count": int(count or 0),
        "items": [
            {
                "event_id": event_id,
                "starts_at": starts_at.isoformat(),
                "client_name": client_name,
            }
            for event_id, starts_at, client_name in rows
        ],
    }


async def _pipeline_cards(db: AsyncSession, owner_id: int) -> int:
    count = await db.scalar(
        select(func.count(RecruitmentProcess.id)).where(
            RecruitmentProcess.owner_user_id == owner_id,
            RecruitmentProcess.status == ProcessStatus.open,
        )
    )
    return int(count or 0)


async def _names(db: AsyncSession, ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    rows = await db.execute(
        select(User.id, User.name, User.email).where(User.id.in_(ids))
    )
    return {user_id: name or email for user_id, name, email in rows.all()}


async def substitution_summary(
    db: AsyncSession, *, viewer: User, now: datetime | None = None
) -> dict[str, Any]:
    """Zastępstwa osoby na dziś i ostrzeżenia „zastępca nieobecny”."""

    moment = now or datetime.now(timezone.utc)
    context = await workforce_context(db)
    covering = sorted(
        (d for d in context.delegations.values() if d.performer_id == viewer.id),
        key=lambda d: (d.end_date, d.owner_id),
    )
    reports = await people.direct_report_ids(db, viewer.id)
    absent_substitutes = [
        issue
        for issue in context.issues
        if issue.get("code") == SUBSTITUTE_ABSENT
        and (issue.get("substitute_id") == viewer.id or issue.get("user_id") in reports)
    ]
    names = await _names(
        db,
        {d.owner_id for d in covering}
        | {
            int(value)
            for issue in absent_substitutes
            for value in (issue.get("user_id"), issue.get("substitute_id"))
            if value is not None
        },
    )
    items = []
    for delegation in covering:
        items.append(
            {
                "owner_user_id": delegation.owner_id,
                "owner_name": names.get(delegation.owner_id),
                "start_date": delegation.start_date.isoformat(),
                "end_date": delegation.end_date.isoformat(),
                "recruitments": await _recruitments(db, delegation.owner_id),
                "client_meetings": await _client_meetings(db, delegation, now=moment),
                "pipeline_cards": await _pipeline_cards(db, delegation.owner_id),
            }
        )
    warnings = [
        {
            "owner_user_id": issue.get("user_id"),
            "owner_name": names.get(issue.get("user_id")),
            "substitute_user_id": issue.get("substitute_id"),
            "substitute_name": names.get(issue.get("substitute_id")),
            "you_are_substitute": issue.get("substitute_id") == viewer.id,
        }
        for issue in absent_substitutes
    ]
    return {
        "enabled": availability_enabled(),
        "fresh": context.fresh,
        "items": items,
        "warnings": warnings,
    }
