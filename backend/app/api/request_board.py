"""Pulpit „Requesty i obłożenie” (makieta C6, decyzje Artura 24.09.2026).

Na daily zespół patrzy, nad czym pracuje: requesty „Szukamy kandydatów”
pogrupowane po czterech kategoriach kompetencji (z championem na dole grupy),
kto przy nich jest, ile kto ma i co się zmieniło od wczoraj. Filtry liczy
przeglądarka — requestów w pracy jest kilkadziesiąt, nie tysiące.

Czyta każda rola z odczytem sekcji Rekrutacje. Ręczne dodanie i zdjęcie
osoby: admin, Delivery Lead, Head of Recruitment.
"""

from datetime import date, datetime, timezone
from typing import Literal, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.competence_team import operator_clause
from app.api.deps import OperationalUser, require_roles
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.config import settings
from app.core.database import get_db
from app.models.activity import Activity
from app.models.client import Client
from app.models.competence_category import CompetenceCategory, UserCompetenceCategory
from app.models.job import Job, JobStatus
from app.models.job_work_assignment import JobWorkAssignment
from app.models.recruitment_allocation import RecruitmentAllocationState
from app.models.user import User, UserRole
from app.services.job_similarity import sent_counts
from app.services.job_working_title import display_title, job_display_title_expr
from app.services.recruitment_allocation import allocation_lock
from app.services.request_allocation import (
    changed_since,
    manual_add,
    manual_remove,
)
from app.services.request_allocation_plan import RELEASE_REASONS
from app.services.workforce_availability import workforce_context

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)

BoardEditor = require_roles(UserRole.delivery_lead, UserRole.head_of_recruitment)


class BoardPerson(BaseModel):
    user_id: int
    name: str
    role: str
    proposed: bool
    source: str


class BoardRequest(BaseModel):
    job_id: int
    title: str
    client_name: Optional[str]
    category_id: Optional[int]
    deadline: Optional[date]
    sent: int
    champion: bool
    people: list[BoardPerson]


class BoardGroup(BaseModel):
    category_id: Optional[int]
    name: str
    slug: Optional[str]
    total: int
    searching: int
    champion: int


class LoadRequest(BaseModel):
    job_id: int
    title: str
    client_name: Optional[str]
    deadline: Optional[date]
    proposed: bool


class LoadPerson(BaseModel):
    user_id: int
    name: str
    count: int
    leave_until: Optional[date]
    requests: list[LoadRequest]


class BoardChange(BaseModel):
    at: datetime
    kind: Literal["assigned", "released", "champion"]
    job_id: int
    title: str
    client_name: Optional[str]
    user_name: Optional[str]
    reason: Optional[str]


class BoardResponse(BaseModel):
    mode: str
    availability_known: bool
    groups: list[BoardGroup]
    requests: list[BoardRequest]
    load: list[LoadPerson]
    changes: list[BoardChange]


class PersonPayload(BaseModel):
    user_id: int
    role: Literal["recruiter", "sourcer"]


def _today() -> date:
    return datetime.now(ZoneInfo(settings.BUSINESS_TZ)).date()


@router.get("", response_model=BoardResponse)
async def get_request_board(
    _user: OperationalUser, db: AsyncSession = Depends(get_db)
) -> BoardResponse:
    now = datetime.now(timezone.utc)
    jobs = list(
        (
            await db.scalars(
                select(Job)
                .where(Job.status == JobStatus.published, Job.work_state == "searching")
                .order_by(Job.deadline.asc().nulls_last(), Job.id)
            )
        ).all()
    )
    ids = [job.id for job in jobs]
    clients = dict(
        (
            await db.execute(
                select(Client.id, Client.name).where(
                    Client.id.in_({j.client_id for j in jobs if j.client_id} or {0})
                )
            )
        ).all()
    )
    sent = await sent_counts(db, ids)
    assignments = (
        (
            await db.execute(
                select(JobWorkAssignment, User.name)
                .join(User, User.id == JobWorkAssignment.user_id)
                .where(
                    JobWorkAssignment.job_id.in_(ids or [0]),
                    JobWorkAssignment.state != "released",
                    # Martwe konto nie pracuje przy requeście — automat zwalnia
                    # jego wiersz przy najbliższym przebiegu (runda 4).
                    User.is_active.is_(True),
                )
                .order_by(JobWorkAssignment.assigned_at)
            )
        ).all()
        if ids
        else []
    )
    by_job: dict[int, list[BoardPerson]] = {}
    for row, name in assignments:
        by_job.setdefault(row.job_id, []).append(
            BoardPerson(
                user_id=row.user_id,
                name=name,
                role=row.role,
                proposed=row.state == "proposed",
                source=row.source,
            )
        )

    requests = [
        BoardRequest(
            job_id=job.id,
            title=display_title(job),
            client_name=clients.get(job.client_id),
            category_id=job.competence_category_id,
            deadline=job.deadline,
            sent=int(sent.get(job.id, 0)),
            champion=job.champion_found_at is not None,
            people=by_job.get(job.id, []),
        )
        for job in jobs
    ]

    categories = list(
        (
            await db.scalars(
                select(CompetenceCategory)
                .where(CompetenceCategory.is_active.is_(True))
                .order_by(CompetenceCategory.display_order, CompetenceCategory.id)
            )
        ).all()
    )
    groups = []
    known = {c.id for c in categories}
    for category in [*categories, None]:
        cid = category.id if category else None
        members = [
            r
            for r in requests
            if (r.category_id == cid if cid else r.category_id not in known)
        ]
        if category is None and not members:
            continue
        groups.append(
            BoardGroup(
                category_id=cid,
                name=category.name_pl if category else "Bez kategorii",
                slug=category.slug if category else None,
                total=len(members),
                searching=sum(1 for r in members if not r.champion),
                champion=sum(1 for r in members if r.champion),
            )
        )

    context = await workforce_context(db)
    today = _today()
    load_map: dict[int, LoadPerson] = {}
    for request in requests:
        if request.champion:
            continue
        for person in request.people:
            entry = load_map.setdefault(
                person.user_id,
                LoadPerson(
                    user_id=person.user_id,
                    name=person.name,
                    count=0,
                    leave_until=None,
                    requests=[],
                ),
            )
            entry.count += 1
            entry.requests.append(
                LoadRequest(
                    job_id=request.job_id,
                    title=request.title,
                    client_name=request.client_name,
                    deadline=request.deadline,
                    proposed=person.proposed,
                )
            )
    # Osoby z kategorią i bez requestów też widać — „kto ma miejsce” to pytanie
    # z daily. Osoby „Poza przydziałem” pomijamy.
    idle = (
        await db.execute(
            select(User.id, User.name)
            .where(
                User.is_active.is_(True),
                User.allocation_excluded.is_(False),
                operator_clause(),
                User.id.in_(select(UserCompetenceCategory.user_id)),
                User.id.not_in(list(load_map) or [0]),
            )
            .order_by(User.name)
        )
    ).all()
    for user_id, name in idle:
        load_map[user_id] = LoadPerson(
            user_id=user_id, name=name, count=0, leave_until=None, requests=[]
        )
    for user_id, availability in context.people.items():
        ends = [
            a.end_date
            for a in availability.absences
            if a.start_date <= today <= a.end_date
        ]
        if ends and user_id in load_map:
            load_map[user_id].leave_until = max(ends)
    load = sorted(load_map.values(), key=lambda p: (-p.count, p.name))

    since = changed_since(now)
    change_rows = (
        await db.execute(
            select(
                JobWorkAssignment, User.name, job_display_title_expr(), Job.client_id
            )
            .join(User, User.id == JobWorkAssignment.user_id)
            .join(Job, Job.id == JobWorkAssignment.job_id)
            .where(
                # Wiersz prowadzącego to nie decyzja automatu ani DL-a.
                JobWorkAssignment.source != "owner",
                or_(
                    and_(
                        JobWorkAssignment.state != "released",
                        JobWorkAssignment.assigned_at >= since,
                    ),
                    and_(
                        JobWorkAssignment.state == "released",
                        JobWorkAssignment.released_at >= since,
                    ),
                ),
            )
        )
    ).all()
    all_clients = dict(clients)
    missing = {cid for *_x, cid in change_rows if cid and cid not in all_clients}
    if missing:
        all_clients.update(
            (
                await db.execute(
                    select(Client.id, Client.name).where(Client.id.in_(missing))
                )
            ).all()
        )
    changes = []
    for row, name, title, client_id in change_rows:
        released = row.state == "released"
        changes.append(
            BoardChange(
                at=row.released_at if released else row.assigned_at,
                kind="released" if released else "assigned",
                job_id=row.job_id,
                title=title,
                client_name=all_clients.get(client_id),
                user_name=name,
                reason=RELEASE_REASONS.get(row.release_reason or "")
                if released
                else ("propozycja automatu" if row.state == "proposed" else None),
            )
        )
    champions = (
        await db.execute(
            select(Activity.created_at, Job.id, job_display_title_expr(), Job.client_id)
            .join(Job, Job.id == Activity.entity_id)
            .where(
                Activity.entity_type == "job",
                Activity.action == "champion_found_changed",
                Activity.created_at >= since,
                Activity.details["found"].as_boolean().is_(True),
            )
        )
    ).all()
    for created, job_id, title, client_id in champions:
        changes.append(
            BoardChange(
                at=created,
                kind="champion",
                job_id=job_id,
                title=title,
                client_name=all_clients.get(client_id) or clients.get(client_id),
                user_name=None,
                reason="Mamy championa",
            )
        )
    changes.sort(key=lambda c: c.at, reverse=True)

    state = await db.get(RecruitmentAllocationState, 1)
    return BoardResponse(
        mode=(state.mode if state else "shadow")
        if settings.RECRUITMENT_ALLOCATION_ENABLED
        else "off",
        availability_known=bool(
            settings.COMPASS_AVAILABILITY_ENABLED and context.fresh
        ),
        groups=groups,
        requests=requests,
        load=load,
        changes=changes[:30],
    )


async def _locked_job(db: AsyncSession, job_id: int) -> Job:
    job = await db.scalar(select(Job).where(Job.id == job_id).with_for_update())
    if job is None:
        raise HTTPException(404, "Nie ma takiego requestu.")
    return job


async def _searching_job(db: AsyncSession, job_id: int) -> Job:
    """Dodać można tylko do requestu w pracy — inaczej automat zwolni osobę."""
    job = await _locked_job(db, job_id)
    if (
        job.status != JobStatus.published
        or job.work_state != "searching"
        or job.champion_found_at is not None
    ):
        raise HTTPException(
            409,
            "Osobę można dodać tylko do requestu w stanie „Szukamy kandydatów” "
            "bez championa.",
        )
    return job


@router.post("/jobs/{job_id}/people")
async def add_person(
    job_id: int,
    payload: PersonPayload,
    current_user: User = Depends(BoardEditor),
    db: AsyncSession = Depends(get_db),
) -> dict:
    # Ta sama blokada co przebieg automatu, i PRZED blokadą rekrutacji
    # (kolejność z ``allocation_lock``) — inaczej równoległy przebieg dodający
    # tę samą parę kończył się naruszeniem unikalności.
    await allocation_lock(db)
    await _searching_job(db, job_id)
    person = await db.get(User, payload.user_id)
    if person is None or not person.is_active:
        raise HTTPException(404, "Nie ma takiej aktywnej osoby.")
    if not person.has_any_role(UserRole.recruiter, UserRole.sourcer, UserRole.tac):
        raise HTTPException(
            422, "Do requestu można dodać rekrutera, sourcera albo TAC."
        )
    await manual_add(
        db,
        job_id=job_id,
        user_id=person.id,
        role=payload.role,
        actor_id=current_user.id,
    )
    await db.commit()
    return {"ok": True}


@router.delete("/jobs/{job_id}/people/{user_id}")
async def remove_person(
    job_id: int,
    user_id: int,
    _current_user: User = Depends(BoardEditor),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await allocation_lock(db)
    await _locked_job(db, job_id)
    removed = await manual_remove(db, job_id=job_id, user_id=user_id)
    await db.commit()
    return {"removed": removed}
