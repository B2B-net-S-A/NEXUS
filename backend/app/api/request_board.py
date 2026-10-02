"""Pulpit „Requesty i obłożenie” (makieta C6, decyzje Artura 24.09.2026).

Na daily zespół patrzy, nad czym pracuje: requesty „Szukamy kandydatów”
pogrupowane po czterech kategoriach kompetencji (z championem na dole grupy),
kto przy nich jest, ile kto ma i co się zmieniło od wczoraj. Filtry liczy
przeglądarka — requestów w pracy jest kilkadziesiąt, nie tysiące.

Kto pracuje nad requestem, mówi jedna reguła (``services/job_team``):
prowadzący, aktywne przypisanie albo ręcznie dopisany współpracownik.
Propozycja automatu to jeszcze nie praca — pulpit pokazuje ją osobno i nie
wlicza do obłożenia (decyzja Artura 02.10.2026).

Czyta każda rola z odczytem sekcji Rekrutacje. Ręczne dodanie i zdjęcie
osoby: uprawnienie do prowadzenia rekrutacji albo Head of Recruitment
(``require_job_staffing``).
Propozycje automatu akceptuje, zamienia i odrzuca admin albo Head of
Recruitment (``PROPOSAL_DECISION_ROLES``).
"""

import logging
from datetime import date, datetime, timezone
from typing import Annotated, Literal, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.competence_team import operator_clause
from app.api.deps import ROLE_DENIED_DETAIL, OperationalUser, require_roles
from app.api.recruitment_access import PROPOSAL_DECISION_ROLES, require_job_staffing
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.config import settings
from app.core.database import get_db
from app.models.activity import Activity
from app.models.client import Client
from app.models.competence_category import CompetenceCategory, UserCompetenceCategory
from app.models.job import Job, JobStatus
from app.models.job_work_assignment import JobWorkAssignment
from app.models.notification import NotificationType
from app.models.recruitment_allocation import RecruitmentAllocationState
from app.models.user import User, UserRole
from app.schemas.job_team import JobRecruiterOut
from app.services.job_priority import level_of
from app.services.job_similarity import sent_counts
from app.services.job_team import (
    TeamPerson,
    recruiters_for_jobs,
    remove_recruiter,
    work_role_of,
    working,
)
from app.services.job_working_title import display_title, job_display_title_expr
from app.services.notification_triggers import emit
from app.services.recruitment_allocation import allocation_lock
from app.services.request_allocation import (
    accept_proposal,
    changed_since,
    manual_add,
    reject_proposal,
    replace_proposal,
)
from app.services.request_allocation_plan import (
    is_silent_release,
    release_reason_label,
)
from app.services.request_allocation_proposals import pending_pairs
from app.services.workforce_availability import workforce_context

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)

BoardEditor = require_job_staffing
ProposalDecider = require_roles(*PROPOSAL_DECISION_ROLES)

MAX_BULK_ACCEPT = 100
PROPOSAL_GONE = (
    "Ta propozycja jest już nieaktualna — request ma obsadę, zmienił stan "
    "albo automat wycofał propozycję. Odśwież pulpit."
)


class BoardPerson(JobRecruiterOut):
    # Źródło wiersza przypisania (``auto`` | ``manual``); prowadzący bez
    # wiersza to ``owner``, ręcznie dopisany współpracownik — ``manual``.
    source: str


class BoardLead(BaseModel):
    id: int
    name: str


class BoardRequest(BaseModel):
    job_id: int
    title: str
    client_name: Optional[str]
    category_id: Optional[int]
    deadline: Optional[date]
    sent: int
    champion: bool
    people: list[BoardPerson]
    delivery_lead: Optional[BoardLead] = None
    priority_level: Literal["p1", "p2", "accepting"] = "p2"
    # Data otwarcia requestu; dla rekrutacji bez niej — data założenia wiersza.
    opened_effective_at: Optional[datetime] = None


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
    # Requesty, nad którymi osoba pracuje. Propozycje automatu liczą się
    # osobno (``proposed``) — do akceptacji to jeszcze nie praca.
    count: int
    proposed: int = 0
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


# Id spoza zakresu kolumny ``integer`` kończyło się błędem bazy (500) zamiast
# czytelnego 422 — dotyczy ciała żądania i ścieżki.
_PG_INT4_MAX = 2_147_483_647
DbId = Annotated[int, Field(ge=1, le=_PG_INT4_MAX)]
DbIdPath = Annotated[int, Path(ge=1, le=_PG_INT4_MAX)]


class PersonPayload(BaseModel):
    user_id: DbId
    role: Literal["recruiter", "sourcer"]


class ProposalDecision(BaseModel):
    decision: Literal["accept", "reject", "replace"]
    # Tylko przy ``replace``: kto ma pracować zamiast proponowanej osoby.
    replacement_user_id: Optional[DbId] = None
    replacement_role: Optional[Literal["recruiter", "sourcer"]] = None


class ProposalRef(BaseModel):
    job_id: DbId
    user_id: DbId


class BulkAcceptPayload(BaseModel):
    items: list[ProposalRef] = Field(min_length=1, max_length=MAX_BULK_ACCEPT)


class BulkAcceptResult(BaseModel):
    job_id: int
    user_id: int
    status: Literal["accepted", "gone"]


class BulkAcceptResponse(BaseModel):
    results: list[BulkAcceptResult]


def _today() -> date:
    return datetime.now(ZoneInfo(settings.BUSINESS_TZ)).date()


def _board_person(person: TeamPerson, row_source: Optional[str]) -> BoardPerson:
    if person.via == "owner":
        source = "owner"
    elif person.via == "collaborator":
        source = "manual"
    else:
        source = row_source or "auto"
    return BoardPerson(
        user_id=person.user_id,
        name=person.name,
        role=person.role,
        via=person.via,
        proposed=person.proposed,
        assigned_by_name=person.assigned_by_name,
        source=source,
    )


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
    leads = dict(
        (
            await db.execute(
                select(User.id, User.name).where(
                    User.id.in_(
                        {j.delivery_lead_id for j in jobs if j.delivery_lead_id} or {0}
                    )
                )
            )
        ).all()
    )
    sent = await sent_counts(db, ids)
    # Jedna reguła „kto pracuje” — także prowadzący i ręczny współpracownik,
    # których w ``job_work_assignments`` nie ma (do 02.10.2026 pulpit czytał
    # samą tabelę przypisań i przy 19 z 20 requestów pokazywał „nikt”).
    team = await recruiters_for_jobs(db, ids)
    row_sources = {
        (job_id, user_id): source
        for job_id, user_id, source in (
            (
                await db.execute(
                    select(
                        JobWorkAssignment.job_id,
                        JobWorkAssignment.user_id,
                        JobWorkAssignment.source,
                    ).where(
                        JobWorkAssignment.job_id.in_(ids),
                        JobWorkAssignment.state != "released",
                    )
                )
            ).all()
            if ids
            else []
        )
    }

    requests = [
        BoardRequest(
            job_id=job.id,
            title=display_title(job),
            client_name=clients.get(job.client_id),
            category_id=job.competence_category_id,
            deadline=job.deadline,
            sent=int(sent.get(job.id, 0)),
            champion=job.champion_found_at is not None,
            people=[
                _board_person(person, row_sources.get((job.id, person.user_id)))
                for person in team.get(job.id, [])
            ],
            delivery_lead=(
                BoardLead(id=job.delivery_lead_id, name=leads[job.delivery_lead_id])
                if job.delivery_lead_id in leads
                else None
            ),
            priority_level=level_of(job.priority),
            opened_effective_at=job.opened_at or job.created_at,
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
            if person.proposed:
                entry.proposed += 1
            else:
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
        if released and is_silent_release(row.release_reason):
            # Odrzucona albo wycofana propozycja nigdy nie była pracą —
            # „zwolnione: …” przy nazwisku byłoby nieprawdą na ekranie, który
            # zespół ogląda razem na daily.
            continue
        changes.append(
            BoardChange(
                at=row.released_at if released else row.assigned_at,
                kind="released" if released else "assigned",
                job_id=row.job_id,
                title=title,
                client_name=all_clients.get(client_id),
                user_name=name,
                reason=release_reason_label(row.release_reason)
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


async def _assignable_person(db: AsyncSession, user_id: int) -> User:
    person = await db.get(User, user_id)
    if person is None or not person.is_active:
        raise HTTPException(404, "Nie ma takiej aktywnej osoby.")
    if not person.has_any_role(UserRole.recruiter, UserRole.sourcer, UserRole.tac):
        raise HTTPException(
            422, "Do requestu można dodać rekrutera, sourcera albo TAC."
        )
    return person


def _record_decision(
    db: AsyncSession,
    *,
    job_id: int,
    user_id: int,
    actor_id: int,
    decision: str,
    replacement_user_id: Optional[int] = None,
) -> None:
    """Ślad decyzji o propozycji w historii rekrutacji — same identyfikatory."""
    details = {"user_id": user_id, "decision": decision}
    if replacement_user_id is not None:
        details["replacement_user_id"] = replacement_user_id
    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action="allocation_proposal_decided",
            user_id=actor_id,
            details=details,
        )
    )


async def _notify_assigned(
    db: AsyncSession, *, job: Job, client_name: Optional[str], user_id: int
) -> None:
    """Dzwonek dla osoby, która właśnie dostała request.

    Do akceptacji propozycja nikogo nie budzi; od akceptacji osoba pracuje,
    więc musi się dowiedzieć. Savepoint: nieudane powiadomienie nie cofa
    decyzji.
    """
    title = display_title(job)
    try:
        async with db.begin_nested():
            await emit(
                db,
                user_id=user_id,
                title="Nowy request do pracy",
                message=f"{title} · {client_name}" if client_name else title,
                ntype=NotificationType.request_assignment_changed,
                related_entity_type="job",
                related_entity_id=job.id,
                link=f"/jobs/{job.id}",
            )
    except Exception:  # noqa: BLE001 — dzwonek nie może cofnąć decyzji
        logger.exception(
            "[request_board] powiadomienie o przydziale nie wyszło job=%s", job.id
        )


async def _client_names(db: AsyncSession, jobs: list[Job]) -> dict[int, str]:
    ids = {job.client_id for job in jobs if job.client_id}
    if not ids:
        return {}
    return dict(
        (
            await db.execute(select(Client.id, Client.name).where(Client.id.in_(ids)))
        ).all()
    )


@router.post("/jobs/{job_id}/people")
async def add_person(
    job_id: DbIdPath,
    payload: PersonPayload,
    current_user: User = Depends(BoardEditor),
    db: AsyncSession = Depends(get_db),
) -> dict:
    # Ta sama blokada co przebieg automatu, i PRZED blokadą rekrutacji
    # (kolejność z ``allocation_lock``) — inaczej równoległy przebieg dodający
    # tę samą parę kończył się naruszeniem unikalności.
    await allocation_lock(db)
    await _searching_job(db, job_id)
    person = await _assignable_person(db, payload.user_id)
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
    job_id: DbIdPath,
    user_id: DbIdPath,
    current_user: User = Depends(BoardEditor),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Zdejmuje osobę z requestu albo odrzuca jej propozycję.

    Osoba, która pracuje (prowadzący, przypisanie, współpracownik), schodzi ze
    wszystkich trzech miejsc naraz (``job_team.remove_recruiter``). Sama
    propozycja automatu to decyzja Head of Recruitment — Delivery Lead jej nie
    odrzuca.
    """
    await allocation_lock(db)
    job = await _locked_job(db, job_id)
    has_proposal = (
        await db.scalar(
            select(JobWorkAssignment.id).where(
                JobWorkAssignment.job_id == job_id,
                JobWorkAssignment.user_id == user_id,
                JobWorkAssignment.state == "proposed",
            )
        )
    ) is not None
    if has_proposal:
        team = await recruiters_for_jobs(db, [job_id])
        if not any(person.user_id == user_id for person in working(team[job_id])):
            if not current_user.has_any_role(*PROPOSAL_DECISION_ROLES):
                raise HTTPException(403, ROLE_DENIED_DETAIL)
            removed = await reject_proposal(db, job_id=job_id, user_id=user_id)
            _record_decision(
                db,
                job_id=job_id,
                user_id=user_id,
                actor_id=current_user.id,
                decision="reject",
            )
            await db.commit()
            return {"removed": removed}
    if job.status == JobStatus.closed:
        # Zamknięta rekrutacja jest historią: prowadzący zostaje przy niej
        # w statystykach, więc nie zdejmujemy go po fakcie.
        raise HTTPException(
            409, "Rekrutacja jest zamknięta — jej obsady już się nie zmienia."
        )
    removed = await remove_recruiter(
        db, job=job, user_id=user_id, actor_id=current_user.id
    )
    if has_proposal:
        # Człowiek przypisał tę samą osobę, zanim automat wycofał propozycję.
        # Zdjęcie z requestu zabiera też propozycję — inaczej osoba wracałaby
        # na pulpit jako „propozycja automatu”.
        await reject_proposal(db, job_id=job_id, user_id=user_id)
    await db.commit()
    return {"removed": removed}


@router.post("/jobs/{job_id}/proposals/{user_id}")
async def decide_proposal(
    job_id: DbIdPath,
    user_id: DbIdPath,
    payload: ProposalDecision,
    current_user: User = Depends(ProposalDecider),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Decyzja o propozycji automatu: akceptacja, odrzucenie albo inna osoba."""
    if payload.decision == "replace":
        if payload.replacement_user_id is None:
            raise HTTPException(
                422, "Wskaż osobę, która ma pracować zamiast proponowanej."
            )
        if payload.replacement_user_id == user_id:
            raise HTTPException(
                422, "To ta sama osoba — zaakceptuj propozycję zamiast ją zmieniać."
            )
    await allocation_lock(db)
    job = await _locked_job(db, job_id)
    assigned_user_id: Optional[int] = None
    if payload.decision == "reject":
        # Odrzucić można też propozycję, która przestała być aktualna —
        # to niczego nie przydziela.
        done = await reject_proposal(db, job_id=job_id, user_id=user_id)
    elif (job_id, user_id) not in await pending_pairs(db, [job_id]):
        done = False
    elif payload.decision == "accept":
        done = await accept_proposal(
            db, job_id=job_id, user_id=user_id, actor_id=current_user.id
        )
        assigned_user_id = user_id
    else:
        replacement = await _assignable_person(db, payload.replacement_user_id)
        done = await replace_proposal(
            db,
            job_id=job_id,
            user_id=user_id,
            replacement_id=replacement.id,
            role=payload.replacement_role or work_role_of(replacement),
            actor_id=current_user.id,
        )
        assigned_user_id = replacement.id
    if not done:
        raise HTTPException(409, PROPOSAL_GONE)
    _record_decision(
        db,
        job_id=job_id,
        user_id=user_id,
        actor_id=current_user.id,
        decision=payload.decision,
        replacement_user_id=payload.replacement_user_id
        if payload.decision == "replace"
        else None,
    )
    if assigned_user_id is not None:
        clients = await _client_names(db, [job])
        await _notify_assigned(
            db,
            job=job,
            client_name=clients.get(job.client_id),
            user_id=assigned_user_id,
        )
    await db.commit()
    return {"decision": payload.decision, "assigned_user_id": assigned_user_id}


@router.post("/proposals/accept", response_model=BulkAcceptResponse)
async def accept_proposals(
    payload: BulkAcceptPayload,
    current_user: User = Depends(ProposalDecider),
    db: AsyncSession = Depends(get_db),
) -> BulkAcceptResponse:
    """„Zaakceptuj wszystkie” — jedna blokada, jeden commit.

    Propozycja, która w międzyczasie przestała być aktualna, wraca jako
    ``gone`` i nie zatrzymuje pozostałych.
    """
    pairs = list(dict.fromkeys((item.job_id, item.user_id) for item in payload.items))
    await allocation_lock(db)
    # Rekrutacje blokujemy w stałej kolejności (rosnąco po id).
    jobs = {
        job.id: job
        for job in (
            await db.scalars(
                select(Job)
                .where(Job.id.in_({job_id for job_id, _user_id in pairs}))
                .order_by(Job.id)
                .with_for_update()
            )
        ).all()
    }
    pending = await pending_pairs(db, jobs)
    clients = await _client_names(db, list(jobs.values()))
    results = []
    # Request, który w tej paczce dostał już osobę, ma obsadę — druga
    # propozycja przy nim jest nieaktualna jak każda inna.
    staffed: set[int] = set()
    for job_id, user_id in pairs:
        accepted = (
            job_id not in staffed
            and (job_id, user_id) in pending
            and await accept_proposal(
                db, job_id=job_id, user_id=user_id, actor_id=current_user.id
            )
        )
        if accepted:
            staffed.add(job_id)
            job = jobs[job_id]
            _record_decision(
                db,
                job_id=job_id,
                user_id=user_id,
                actor_id=current_user.id,
                decision="accept",
            )
            await _notify_assigned(
                db, job=job, client_name=clients.get(job.client_id), user_id=user_id
            )
        results.append(
            BulkAcceptResult(
                job_id=job_id,
                user_id=user_id,
                status="accepted" if accepted else "gone",
            )
        )
    await db.commit()
    return BulkAcceptResponse(results=results)
