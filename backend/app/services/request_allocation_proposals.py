"""Propozycje automatu przydziału czekające na decyzję (02.10.2026).

Automat w trybie podglądu proponuje jedną osobę do requestu bez obsady, a
Head of Recruitment albo admin ją akceptuje, zamienia albo odrzuca. Ten moduł
jest jednym źródłem dla panelu „Czeka na Ciebie” (``GET /api/board-tasks``),
dzwonka (``request_allocation_notices.send_proposal_notices``) i bramki przed
akceptacją (``pending_pairs``).

Propozycja czeka na decyzję, gdy:

* wiersz ``job_work_assignments`` jest ``proposed``,
* request jest w puli automatu (opublikowany, „Szukamy kandydatów”, bez
  championa),
* konto proponowanej osoby jest aktywne,
* nad requestem NIKT nie pracuje według reguły zespołu
  (``job_team.recruiters_for_jobs``). Gdy Delivery Lead przypisał rekrutera
  albo rekruter wziął request sam, propozycja znika z panelu od razu, a
  automat zwalnia ją przy najbliższym przebiegu.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.config import settings
from app.core.scheduling import business_today
from app.models.client import Client
from app.models.competence_category import CompetenceCategory, UserCompetenceCategory
from app.models.job import Job
from app.models.job_work_assignment import JobWorkAssignment
from app.models.user import User
from app.services.job_priority import level_of
from app.services.job_team import recruiters_for_jobs, working
from app.services.job_working_title import display_title
from app.services.request_allocation import _pool_clause, _requests
from app.services.request_allocation_plan import category_fit
from app.services.workforce_availability import WorkforceContext, workforce_context

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PendingProposal:
    job_id: int
    title: str
    client_name: Optional[str]
    category_id: Optional[int]
    category_name: Optional[str]
    category_slug: Optional[str]
    delivery_lead_name: Optional[str]
    priority_level: str  # p1 | p2 | accepting
    deadline: Optional[date]
    # Ile osób z tego requestu dotarło już do klienta.
    sent: int
    user_id: int
    user_name: str
    role: str  # recruiter | sourcer
    # Jak kategorie osoby mają się do requestu: first | second | other.
    fit: str
    # Ile requestów „Szukamy” bez championa osoba ma teraz w pracy.
    load: int
    # Do kiedy osoba jest dziś na urlopie; ``None`` = pracuje albo nie wiadomo.
    leave_until: Optional[date]
    # Pasujący w bazie z nocnego przeglądu — od tej liczby zależy, czy automat
    # proponuje sourcera. ``None`` = przeglądu nie było.
    base_matches: Optional[int]
    proposed_at: datetime


def leave_until(context: WorkforceContext, user_id: int, today: date) -> Optional[date]:
    person = context.people.get(user_id)
    if person is None:
        return None
    ends = [
        absence.end_date
        for absence in person.absences
        if absence.start_date <= today <= absence.end_date
    ]
    return max(ends) if ends else None


async def _live_proposals(db: AsyncSession, job_ids: Optional[Iterable[int]] = None):
    """Żywe propozycje aktywnych kont przy requestach z puli — od najstarszej."""
    lead = aliased(User)
    query = (
        select(
            JobWorkAssignment.job_id,
            JobWorkAssignment.user_id,
            JobWorkAssignment.role,
            JobWorkAssignment.assigned_at,
            User.name.label("user_name"),
            Job.title,
            Job.working_title,
            Job.priority,
            Job.deadline,
            Job.competence_category_id,
            Client.name.label("client_name"),
            CompetenceCategory.name_pl.label("category_name"),
            CompetenceCategory.slug.label("category_slug"),
            lead.name.label("delivery_lead_name"),
        )
        .join(User, User.id == JobWorkAssignment.user_id)
        .join(Job, Job.id == JobWorkAssignment.job_id)
        .outerjoin(Client, Client.id == Job.client_id)
        .outerjoin(
            CompetenceCategory, CompetenceCategory.id == Job.competence_category_id
        )
        .outerjoin(lead, lead.id == Job.delivery_lead_id)
        .where(
            JobWorkAssignment.state == "proposed",
            User.is_active.is_(True),
            _pool_clause(),
        )
        .order_by(JobWorkAssignment.assigned_at, JobWorkAssignment.id)
    )
    if job_ids is not None:
        query = query.where(JobWorkAssignment.job_id.in_(sorted(set(job_ids))))
    return (await db.execute(query)).all()


async def pending_pairs(
    db: AsyncSession, job_ids: Iterable[int]
) -> set[tuple[int, int]]:
    """Pary (request, osoba), o których można jeszcze zdecydować.

    Ta sama reguła co ``load_pending``, bez danych do wyświetlenia — bramka
    przed akceptacją i zamianą. Spóźnione kliknięcie w propozycję, przy
    której ktoś już pracuje, nie może dołożyć drugiej osoby.
    """
    rows = await _live_proposals(db, job_ids)
    if not rows:
        return set()
    team = await recruiters_for_jobs(db, {row.job_id for row in rows})
    return {(row.job_id, row.user_id) for row in rows if not working(team[row.job_id])}


async def load_pending(db: AsyncSession) -> list[PendingProposal]:
    """Propozycje do decyzji: najpierw P1, potem od najdłużej czekającej."""
    rows = await _live_proposals(db)
    if not rows:
        return []
    requests = {request.job_id: request for request in await _requests(db)}
    # Cała pula, nie tylko requesty z propozycją: z tego samego odczytu liczy
    # się obłożenie proponowanej osoby.
    team = await recruiters_for_jobs(db, list(requests))
    rows = [
        row for row in rows if row.job_id in requests and not working(team[row.job_id])
    ]
    if not rows:
        return []
    load = Counter(
        person.user_id for people in team.values() for person in working(people)
    )
    first: dict[int, set[int]] = {}
    second: dict[int, set[int]] = {}
    for user_id, category_id, priority in (
        await db.execute(
            select(
                UserCompetenceCategory.user_id,
                UserCompetenceCategory.competence_category_id,
                UserCompetenceCategory.priority,
            ).where(UserCompetenceCategory.user_id.in_({row.user_id for row in rows}))
        )
    ).all():
        (first if priority == 1 else second).setdefault(user_id, set()).add(category_id)
    context = await workforce_context(db)
    today = business_today(settings.BUSINESS_TZ)
    pending = [
        PendingProposal(
            job_id=row.job_id,
            title=display_title(row),
            client_name=row.client_name,
            category_id=row.competence_category_id,
            category_name=row.category_name,
            category_slug=row.category_slug,
            delivery_lead_name=row.delivery_lead_name,
            priority_level=level_of(row.priority),
            deadline=row.deadline,
            sent=requests[row.job_id].sent,
            user_id=row.user_id,
            user_name=row.user_name,
            role=row.role,
            fit=category_fit(
                requests[row.job_id].categories,
                first.get(row.user_id, ()),
                second.get(row.user_id, ()),
            ),
            load=load.get(row.user_id, 0),
            leave_until=leave_until(context, row.user_id, today),
            base_matches=requests[row.job_id].base_matches,
            proposed_at=row.assigned_at,
        )
        for row in rows
    ]
    pending.sort(key=lambda p: (p.priority_level != "p1", p.proposed_at, p.job_id))
    return pending


async def leave_data_known(db: AsyncSession) -> bool:
    """Czy urlopy z Compassa są włączone i świeże — bez tego panel nie może
    twierdzić, że proponowana osoba jest dziś w pracy."""
    if not settings.COMPASS_AVAILABILITY_ENABLED:
        return False
    return bool((await workforce_context(db)).fresh)


async def load_panel_safely(db: AsyncSession) -> tuple[list[PendingProposal], bool]:
    """Propozycje i świeżość urlopów dla pulpitu: awaria = pusta lista + log.

    ``GET /api/board-tasks`` zasila każdy pulpit — padnięte zapytanie
    o propozycje nie może dawać 500 całej kolejki „Czeka na Ciebie”.
    Savepoint, bo sesja żądania jedzie dalej.
    """
    try:
        async with db.begin_nested():
            return await load_pending(db), await leave_data_known(db)
    except Exception:  # noqa: BLE001
        logger.exception(
            "request_allocation_proposals: nie udało się policzyć propozycji"
        )
        return [], False
