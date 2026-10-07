"""„Nowe rekrutacje — kto prowadzi” na pulpicie Head of Recruitment.

Lista informacyjna: rekrutacje przekazane do searchu w ostatnich dniach
i osoba, która je prowadzi — z automatu albo wskazana przez człowieka. Liczona
przy odczycie, bez własnej tabeli: stan requestu daje ``jobs.work_state``,
a prowadzącego ta sama reguła co wszędzie (``job_team.recruiters_for_jobs``).

Audyt 06.10.2026 (H7): opublikowane rekrutacje, których nikt nigdy nie
przekazał do searchu (``is_open`` puste — automat ich nie widzi, bo nie są
w puli), dochodzą na koniec listy z powodem ``not_handed_off``. Bez tego żyły
poza każdym ekranem pracy (5 takich na produkcji).

Lista ma koniec (decyzja Artura 07.10.2026): gdy Head of Recruitment albo admin
potwierdzi prowadzącego („Potwierdź”) albo go zmieni, wiersz znika. Ślad to
``Activity`` ``new_job_lead_confirmed`` na rekrutacji z osobą, którą
potwierdzono. Liczy się wyłącznie potwierdzenie z bieżącego przekazania
(po ``work_state_changed_at``) i tej samej osoby — gdy automat albo ktoś inny
zmieni potem prowadzącego, rekrutacja wraca na listę.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.activity import Activity
from app.models.client import Client
from app.models.competence_category import CompetenceCategory
from app.models.job import Job, JobStatus
from app.models.job_collaborator import JobCollaborator, JobCollaboratorSource
from app.models.user import User
from app.services.job_priority import level_of
from app.services.job_team import recruiters_for_jobs, working
from app.services.job_working_title import job_display_title_expr

logger = logging.getLogger(__name__)

WINDOW_DAYS = 7
MAX_ROWS = 30
# Automat rusza po zdarzeniu z przekazania; do tego czasu „nikt nie prowadzi”
# znaczy „właśnie przydziela”.
ASSIGNING_GRACE = timedelta(minutes=2)
CONFIRMED_ACTION = "new_job_lead_confirmed"


def record_confirmation(
    db: AsyncSession, *, job_id: int, lead_user_id: int, actor_id: int, via: str
) -> None:
    """Head of Recruitment / admin zgadza się z prowadzącym (``via``:
    ``confirm`` — przycisk, ``owner_change`` — wybrał inną osobę,
    ``proposal`` — rozstrzygnął propozycję automatu)."""
    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action=CONFIRMED_ACTION,
            user_id=actor_id,
            details={"lead_user_id": lead_user_id, "via": via},
        )
    )


async def _confirmed_leads(
    db: AsyncSession, since_by_job: dict[int, datetime]
) -> dict[int, int]:
    """Osoba z ostatniego potwierdzenia bieżącego przekazania, per rekrutacja."""
    if not since_by_job:
        return {}
    rows = (
        await db.execute(
            select(Activity.entity_id, Activity.created_at, Activity.details)
            .where(
                Activity.entity_type == "job",
                Activity.action == CONFIRMED_ACTION,
                Activity.entity_id.in_(list(since_by_job)),
            )
            .order_by(Activity.created_at.asc(), Activity.id.asc())
        )
    ).all()
    out: dict[int, int] = {}
    for job_id, created_at, details in rows:
        since = since_by_job.get(job_id)
        lead = (details or {}).get("lead_user_id")
        if since is None or created_at is None or created_at < since:
            continue
        if isinstance(lead, int):
            out[job_id] = lead
    return out


@dataclass(frozen=True)
class NewJobLead:
    job_id: int
    title: str
    client_name: Optional[str]
    category_id: Optional[int]
    category_name: Optional[str]
    category_slug: Optional[str]
    participants: int
    priority_level: str
    delivery_lead_name: Optional[str]
    handed_off_at: datetime
    lead_user_id: Optional[int] = None
    lead_name: Optional[str] = None
    lead_role: Optional[str] = None
    lead_source: Optional[str] = None
    assigned_by_name: Optional[str] = None
    proposed: bool = False
    pending_reason: Optional[str] = None


async def _participants(db: AsyncSession, job_ids: list[int]) -> dict[int, int]:
    """Ilu uczestników z kategorii ma rekrutacja (bez osób zdjętych)."""
    return {
        job_id: int(count)
        for job_id, count in (
            await db.execute(
                select(JobCollaborator.job_id, func.count(JobCollaborator.id))
                .where(
                    JobCollaborator.job_id.in_(job_ids),
                    JobCollaborator.source == JobCollaboratorSource.auto_cc,
                    JobCollaborator.removed_from_auto_cc.is_(False),
                )
                .group_by(JobCollaborator.job_id)
            )
        ).all()
    }


async def load_new_job_leads(db: AsyncSession, *, now: datetime) -> list[NewJobLead]:
    """Rekrutacje przekazane do searchu w ostatnich ``WINDOW_DAYS`` dniach,
    od najnowszej. Stała liczba zapytań."""
    from app.services.recruitment_allocation import (  # noqa: PLC0415
        effective_allocation_mode,
    )
    from app.services.request_allocation import (  # noqa: PLC0415
        _last_assignment_was_auto,
    )

    delivery_lead = aliased(User)
    jobs = (
        await db.execute(
            select(
                Job.id,
                job_display_title_expr().label("title"),
                Client.name.label("client_name"),
                Job.competence_category_id,
                CompetenceCategory.name_pl.label("category_name"),
                CompetenceCategory.slug.label("category_slug"),
                Job.priority,
                delivery_lead.name.label("delivery_lead_name"),
                Job.work_state_changed_at,
            )
            .outerjoin(Client, Client.id == Job.client_id)
            .outerjoin(
                CompetenceCategory,
                CompetenceCategory.id == Job.competence_category_id,
            )
            .outerjoin(delivery_lead, delivery_lead.id == Job.delivery_lead_id)
            .where(
                Job.status == JobStatus.published,
                Job.work_state == "searching",
                Job.work_state_changed_at >= now - timedelta(days=WINDOW_DAYS),
            )
            .order_by(Job.work_state_changed_at.desc(), Job.id.desc())
            .limit(MAX_ROWS)
        )
    ).all()
    not_handed_off = await _not_handed_off(db, exclude=[row.id for row in jobs])
    if not jobs:
        return not_handed_off
    job_ids = [row.id for row in jobs]
    participants = await _participants(db, job_ids)
    teams = await recruiters_for_jobs(db, job_ids)

    # Osoba pracująca, a bez niej propozycja automatu czekająca na akceptację.
    leads = {}
    for job_id in job_ids:
        people = teams.get(job_id, [])
        lead = next(iter(working(people)), None) or next(iter(people), None)
        if lead is not None:
            leads[job_id] = lead
    # Prowadzący bez wiersza przypisania: automat wpisał go wcześniej, jeśli
    # tak mówi najnowszy zamknięty wiersz pary.
    confirmed = await _confirmed_leads(
        db, {row.id: row.work_state_changed_at for row in jobs}
    )
    auto_owned = await _last_assignment_was_auto(
        db,
        [
            (job_id, lead.user_id)
            for job_id, lead in leads.items()
            if lead.via == "owner" and lead.assignment_source is None
        ],
    )
    mode: Optional[str] = None
    out: list[NewJobLead] = []
    for row in jobs:
        level = level_of(row.priority)
        base = dict(
            job_id=row.id,
            title=row.title,
            client_name=row.client_name,
            category_id=row.competence_category_id,
            category_name=row.category_name,
            category_slug=row.category_slug,
            participants=participants.get(row.id, 0),
            priority_level=level,
            delivery_lead_name=row.delivery_lead_name,
            handed_off_at=row.work_state_changed_at,
        )
        lead = leads.get(row.id)
        if lead is None:
            if level == "accepting":
                reason = "passive"
            elif now - row.work_state_changed_at < ASSIGNING_GRACE:
                if mode is None:
                    mode = await effective_allocation_mode(db)
                reason = "assigning" if mode == "auto" else "none"
            else:
                reason = "none"
            out.append(NewJobLead(**base, pending_reason=reason))
            continue
        if not lead.proposed and confirmed.get(row.id) == lead.user_id:
            continue
        by_automat = (
            lead.assignment_source == "auto" or (row.id, lead.user_id) in auto_owned
        )
        out.append(
            NewJobLead(
                **base,
                lead_user_id=lead.user_id,
                lead_name=lead.name,
                lead_role=lead.role,
                lead_source="auto" if by_automat else "manual",
                assigned_by_name=lead.assigned_by_name,
                proposed=lead.proposed,
            )
        )
    return out + not_handed_off


async def _not_handed_off(db: AsyncSession, *, exclude: list[int]) -> list[NewJobLead]:
    """Opublikowane rekrutacje bez przekazania do searchu (H7) — od najstarszej.

    ``handed_off_at`` niesie wtedy datę założenia rekrutacji (przekazania nie
    było). Rekrutacje z Traffita są archiwum (zamknięte), więc tu trafiają
    wyłącznie rekrutacje NEXUSA.
    """
    delivery_lead = aliased(User)
    rows = (
        await db.execute(
            select(
                Job.id,
                job_display_title_expr().label("title"),
                Client.name.label("client_name"),
                Job.competence_category_id,
                CompetenceCategory.name_pl.label("category_name"),
                CompetenceCategory.slug.label("category_slug"),
                Job.priority,
                delivery_lead.name.label("delivery_lead_name"),
                Job.created_at,
            )
            .outerjoin(Client, Client.id == Job.client_id)
            .outerjoin(
                CompetenceCategory,
                CompetenceCategory.id == Job.competence_category_id,
            )
            .outerjoin(delivery_lead, delivery_lead.id == Job.delivery_lead_id)
            .where(
                Job.status == JobStatus.published,
                Job.is_open.is_not(True),
                *((Job.id.not_in(exclude),) if exclude else ()),
            )
            .order_by(Job.created_at.asc(), Job.id.asc())
            .limit(MAX_ROWS)
        )
    ).all()
    participants = await _participants(db, [row.id for row in rows]) if rows else {}
    return [
        NewJobLead(
            job_id=row.id,
            title=row.title,
            client_name=row.client_name,
            category_id=row.competence_category_id,
            category_name=row.category_name,
            category_slug=row.category_slug,
            participants=participants.get(row.id, 0),
            priority_level=level_of(row.priority),
            delivery_lead_name=row.delivery_lead_name,
            handed_off_at=row.created_at,
            pending_reason="not_handed_off",
        )
        for row in rows
    ]


async def load_safely(db: AsyncSession, *, now: datetime) -> list[NewJobLead]:
    """Lista dla pulpitu: awaria = pusta lista + log.

    ``GET /api/board-tasks`` zasila każdy pulpit — padnięte zapytanie o listę
    informacyjną nie może dawać 500 całej kolejki „Czeka na Ciebie”.
    Savepoint, bo sesja żądania jedzie dalej.
    """
    try:
        async with db.begin_nested():
            return await load_new_job_leads(db, now=now)
    except Exception:  # noqa: BLE001
        logger.exception("new_job_leads: nie udało się policzyć listy")
        return []
