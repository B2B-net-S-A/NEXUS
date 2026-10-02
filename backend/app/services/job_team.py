"""Kto jest „Rekruterem” rekrutacji — jedna reguła dla listy, pulpitu i panelu.

Decyzja Artura 02.10.2026 (feedback Head of Recruitment): przy rekrutacji są
trzy role — Delivery Lead (``jobs.delivery_lead_id``), Rekruter (jedna lub kilka
osób, które faktycznie pracują) i Kategoria (ludzie z kategorii kompetencji,
informacyjnie).
Do tego dnia lista ``/jobs`` liczyła „Kto pracuje” jedną regułą, pulpit
„Requesty i obłożenie” drugą (same ``job_work_assignments`` — przy wyłączonym
automacie zero u każdego, choć 19 z 20 requestów miało prowadzącego), a panel
rekrutacji trzecią („Właściciel” + „Współpracownicy” razem z całą kategorią).

Rekruterem jest:

1. prowadzący rekrutacji (``jobs.recruiter_id``) — aktywne konto, niezdjęte
   ręcznie w bieżącym stanie requestu;
2. osoba z aktywnym przypisaniem (``job_work_assignments.state = 'active'``).
   Wiersze ``source = 'owner'`` to lustro punktu 1 (żyją do 30 s po zmianie
   prowadzącego), więc osobno się nie liczą;
3. współpracownik dopisany ręcznie (``job_collaborators.source = 'manual'``).

Propozycja automatu (``state = 'proposed'``) NIE jest pracą: dopóki Head of
Recruitment jej nie zaakceptuje, nikt nie jest przypisany. Loader oddaje ją
osobno (``proposed=True``), klauzule SQL jej nie liczą.

Loader (``recruiters_for_jobs``) i klauzule SQL (``jobs_worked_by_clause``,
``jobs_nobody_working_clause``) muszą dawać ten sam zbiór — pilnuje tego
``tests/test_job_team.py``. Zmieniasz jedno, zmień drugie.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from sqlalchemy import and_, exists, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, load_only

from app.models.activity import Activity
from app.models.job import Job
from app.models.job_collaborator import JobCollaborator, JobCollaboratorSource
from app.models.job_work_assignment import JobWorkAssignment
from app.models.user import User, UserRole


@dataclass(frozen=True)
class TeamPerson:
    user_id: int
    name: str
    role: str  # recruiter | sourcer
    via: str  # owner | assignment | collaborator
    proposed: bool = False
    assigned_by_name: Optional[str] = None


# Role, które pracują nad requestem (pulpit „Requesty i obłożenie”, planer).
WORK_ROLES = (UserRole.recruiter, UserRole.sourcer, UserRole.tac)


def work_role_of(user: User) -> str:
    """Rola przy requeście dla osoby bez wiersza przypisania (prowadzący,
    współpracownik): sourcer tylko wtedy, gdy nie jest też rekruterem ani TAC."""
    roles = {str(getattr(r, "value", r)) for r in (user.roles or [])}
    roles.add(str(getattr(user.role, "value", user.role)))
    if "sourcer" in roles and not roles & {"recruiter", "tac"}:
        return "sourcer"
    return "recruiter"


# ── Klauzule SQL (filtry listy, zakres „Moje”, liczniki) ────────────────────


def working_assignment_job_ids(user_ids: Optional[list[int]] = None):
    """Rekrutacje z AKTYWNYM przypisaniem (punkt 2 reguły).

    Propozycja (``proposed``) i lustro prowadzącego (``source = 'owner'``) się
    nie liczą; liczą się wyłącznie aktywne konta.
    """
    subq = (
        select(JobWorkAssignment.job_id)
        .join(User, User.id == JobWorkAssignment.user_id)
        .where(
            JobWorkAssignment.state == "active",
            JobWorkAssignment.source != "owner",
            User.is_active.is_(True),
        )
    )
    if user_ids is not None:
        subq = subq.where(JobWorkAssignment.user_id.in_(user_ids))
    return subq


def owner_is_working_clause():
    """Prowadzący (``jobs.recruiter_id``) pracuje nad rekrutacją (punkt 1).

    Liczy się aktywne konto; prowadzący zdjęty RĘCZNIE w bieżącym stanie
    requestu nie wraca (lustro ``request_allocation._blocked``). Klauzula
    skorelowana z zewnętrznym ``Job`` — nie podzapytanie po ``jobs``.
    """
    active_owner = exists(
        select(User.id).where(User.id == Job.recruiter_id, User.is_active.is_(True))
    )
    released_manually = exists(
        select(JobWorkAssignment.id).where(
            JobWorkAssignment.job_id == Job.id,
            JobWorkAssignment.user_id == Job.recruiter_id,
            JobWorkAssignment.state == "released",
            JobWorkAssignment.release_reason == "manual",
            or_(
                Job.work_state_changed_at.is_(None),
                JobWorkAssignment.released_at >= Job.work_state_changed_at,
            ),
        )
    )
    return and_(Job.recruiter_id.is_not(None), active_owner, not_(released_manually))


def manual_collaborator_job_ids(user_ids: Optional[list[int]] = None):
    """Rekrutacje z RĘCZNIE dopisanym współpracownikiem (punkt 3).

    Wiersze ``auto_cc`` (cała kategoria kompetencji) się nie liczą — to
    informacja, kto może request wziąć, a nie kto nad nim pracuje.
    """
    subq = (
        select(JobCollaborator.job_id)
        .join(User, User.id == JobCollaborator.user_id)
        .where(
            JobCollaborator.source == JobCollaboratorSource.manual,
            JobCollaborator.removed_from_auto_cc.is_(False),
            User.is_active.is_(True),
        )
    )
    if user_ids is not None:
        subq = subq.where(JobCollaborator.user_id.in_(user_ids))
    return subq


def jobs_worked_by_clause(user_ids: list[int]):
    """Filtr „Rekruter” — któraś z osób jest Rekruterem rekrutacji."""
    return or_(
        and_(Job.recruiter_id.in_(user_ids), owner_is_working_clause()),
        Job.id.in_(working_assignment_job_ids(user_ids)),
        Job.id.in_(manual_collaborator_job_ids(user_ids)),
    )


def jobs_nobody_working_clause():
    """„Bez rekrutera” — nikt nie pracuje; sama propozycja automatu to za mało."""
    return and_(
        not_(owner_is_working_clause()),
        Job.id.not_in(working_assignment_job_ids()),
        Job.id.not_in(manual_collaborator_job_ids()),
    )


# ── Loader (pulpit, wiersz listy, panel rekrutacji) ──────────────────────────


async def recruiters_for_jobs(
    db: AsyncSession, job_ids: Iterable[int]
) -> dict[int, list[TeamPerson]]:
    """Osoby w roli „Rekruter” dla wielu rekrutacji naraz (stała liczba zapytań).

    Kolejność: prowadzący, aktywne przypisania (od najstarszego), ręczni
    współpracownicy, na końcu propozycje automatu (``proposed=True``). Każda
    osoba występuje raz. Rekrutacja bez nikogo ma pustą listę.
    """
    ids = sorted({int(job_id) for job_id in job_ids})
    out: dict[int, list[TeamPerson]] = {job_id: [] for job_id in ids}
    if not ids:
        return out

    owners = dict(
        (
            await db.execute(select(Job.id, Job.recruiter_id).where(Job.id.in_(ids)))
        ).all()
    )
    assigner = aliased(User)
    live_rows = (
        await db.execute(
            select(
                JobWorkAssignment.job_id,
                JobWorkAssignment.user_id,
                JobWorkAssignment.role,
                JobWorkAssignment.source,
                JobWorkAssignment.state,
                User.name.label("user_name"),
                assigner.name.label("assigner_name"),
            )
            .join(User, User.id == JobWorkAssignment.user_id)
            .outerjoin(assigner, assigner.id == JobWorkAssignment.assigned_by)
            .where(
                JobWorkAssignment.job_id.in_(ids),
                JobWorkAssignment.state != "released",
                User.is_active.is_(True),
            )
            .order_by(JobWorkAssignment.assigned_at, JobWorkAssignment.id)
        )
    ).all()
    # Prowadzący zdjęty ręcznie w bieżącym stanie requestu — lustro
    # ``owner_is_working_clause``.
    released_owners = set(
        (
            await db.execute(
                select(JobWorkAssignment.job_id, JobWorkAssignment.user_id)
                .join(Job, Job.id == JobWorkAssignment.job_id)
                .where(
                    JobWorkAssignment.job_id.in_(ids),
                    JobWorkAssignment.user_id == Job.recruiter_id,
                    JobWorkAssignment.state == "released",
                    JobWorkAssignment.release_reason == "manual",
                    or_(
                        Job.work_state_changed_at.is_(None),
                        JobWorkAssignment.released_at >= Job.work_state_changed_at,
                    ),
                )
            )
        ).all()
    )
    collaborator_rows = (
        await db.execute(
            select(JobCollaborator.job_id, JobCollaborator.user_id)
            .join(User, User.id == JobCollaborator.user_id)
            .where(
                JobCollaborator.job_id.in_(ids),
                JobCollaborator.source == JobCollaboratorSource.manual,
                JobCollaborator.removed_from_auto_cc.is_(False),
                User.is_active.is_(True),
            )
            .order_by(JobCollaborator.id)
        )
    ).all()

    wanted = {uid for uid in owners.values() if uid is not None}
    wanted.update(user_id for _job_id, user_id in collaborator_rows)
    users: dict[int, User] = {}
    if wanted:
        users = {
            user.id: user
            for user in (
                await db.scalars(
                    select(User)
                    .where(User.id.in_(wanted))
                    .options(
                        load_only(
                            User.id, User.name, User.is_active, User.role, User.roles
                        )
                    )
                )
            ).all()
        }

    rows_by_job: dict[int, list] = {}
    for row in live_rows:
        rows_by_job.setdefault(row.job_id, []).append(row)
    collaborators_by_job: dict[int, list[int]] = {}
    for job_id, user_id in collaborator_rows:
        collaborators_by_job.setdefault(job_id, []).append(user_id)

    for job_id in ids:
        people: list[TeamPerson] = []
        seen: set[int] = set()
        live = rows_by_job.get(job_id, [])
        active = [r for r in live if r.state == "active" and r.source != "owner"]

        owner_id = owners.get(job_id)
        owner = users.get(owner_id) if owner_id is not None else None
        if (
            owner is not None
            and owner.is_active
            and (job_id, owner.id) not in released_owners
        ):
            own_row = next((r for r in active if r.user_id == owner.id), None)
            people.append(
                TeamPerson(
                    user_id=owner.id,
                    name=owner.name,
                    role=own_row.role if own_row else work_role_of(owner),
                    via="owner",
                    assigned_by_name=own_row.assigner_name if own_row else None,
                )
            )
            seen.add(owner.id)
        for row in active:
            if row.user_id in seen:
                continue
            people.append(
                TeamPerson(
                    user_id=row.user_id,
                    name=row.user_name,
                    role=row.role,
                    via="assignment",
                    assigned_by_name=row.assigner_name,
                )
            )
            seen.add(row.user_id)
        for user_id in collaborators_by_job.get(job_id, []):
            user = users.get(user_id)
            if user is None or user_id in seen:
                continue
            people.append(
                TeamPerson(
                    user_id=user_id,
                    name=user.name,
                    role=work_role_of(user),
                    via="collaborator",
                )
            )
            seen.add(user_id)
        for row in live:
            if row.state != "proposed" or row.user_id in seen:
                continue
            people.append(
                TeamPerson(
                    user_id=row.user_id,
                    name=row.user_name,
                    role=row.role,
                    via="assignment",
                    proposed=True,
                )
            )
            seen.add(row.user_id)
        out[job_id] = people
    return out


def working(people: Iterable[TeamPerson]) -> list[TeamPerson]:
    """Osoby, które pracują — bez propozycji czekających na akceptację."""
    return [person for person in people if not person.proposed]


# ── Zdjęcie osoby z roli „Rekruter” ──────────────────────────────────────────


async def remove_recruiter(
    db: AsyncSession, *, job: Job, user_id: int, actor_id: int
) -> bool:
    """Zdejmuje osobę z roli „Rekruter” — ze wszystkich trzech miejsc naraz.

    Osoba bywa w dwóch miejscach jednocześnie (zaakceptowana propozycja to
    aktywne przypisanie ORAZ ``jobs.recruiter_id``), a dotychczasowe zdjęcie
    z pulpitu czyściło tylko przypisanie — panel dalej mówił „prowadzi X”,
    a X miał rekrutację w „Moje”.

    Wołający trzyma ``allocation_lock`` i blokadę wiersza rekrutacji (w tej
    kolejności) i sam commituje. Propozycji (``proposed``) nie rusza — tę się
    odrzuca (``request_allocation.reject_proposal``). Zwraca ``True``, gdy
    cokolwiek zdjęto.
    """
    from app.services.recruitment_allocation import release_operator  # noqa: PLC0415
    from app.services.request_allocation import (  # noqa: PLC0415
        job_in_pool,
        manual_remove,
        remember_manual_release,
    )

    removed = False
    was_owner = job.recruiter_id == user_id
    # Prowadzący PRZED przypisaniem: ``manual_remove`` zdejmuje prowadzącego
    # wpisanego przez automat UPDATE-em, który sesja od razu odbija na obiekcie
    # ``job`` (``recruiter_id`` puste) — po nim ten warunek byłby fałszywy,
    # plan pracy tej osoby zostałby nietknięty, a historia bez wpisu.
    if job.recruiter_id == user_id:
        await release_operator(db, job=job)
        db.add(
            Activity(
                entity_type="job",
                entity_id=job.id,
                action="owner_released",
                user_id=actor_id,
                details={"previous_owner_id": user_id},
            )
        )
        removed = True

    has_active_row = await db.scalar(
        select(JobWorkAssignment.id)
        .where(
            JobWorkAssignment.job_id == job.id,
            JobWorkAssignment.user_id == user_id,
            JobWorkAssignment.state == "active",
        )
        .limit(1)
    )
    if has_active_row is not None:
        # Powód ``manual``: osoba nie wraca z automatu ani jako prowadzący,
        # dopóki request nie zmieni stanu.
        removed = await manual_remove(db, job_id=job.id, user_id=user_id) or removed
    elif was_owner and job_in_pool(job):
        # Prowadzący bez wiersza przypisania (sprzed włączenia automatu albo
        # sprzed jego najbliższego przebiegu): bez śladu planer zaproponowałby
        # tę samą osobę do tego samego requestu zaraz po zdjęciu. Poza pulą
        # i dla ról, których planer nie proponuje, nie ma czego pamiętać.
        person = await db.get(User, user_id)
        if person is not None and person.has_any_role(*WORK_ROLES):
            await remember_manual_release(
                db, job_id=job.id, user_id=user_id, role=work_role_of(person)
            )

    link = await db.scalar(
        select(JobCollaborator).where(
            JobCollaborator.job_id == job.id,
            JobCollaborator.user_id == user_id,
            JobCollaborator.source == JobCollaboratorSource.manual,
        )
    )
    if link is not None:
        await db.delete(link)
        db.add(
            Activity(
                entity_type="job",
                entity_id=job.id,
                action="collaborator_removed",
                user_id=actor_id,
                details={"collaborator_id": user_id, "source": "manual"},
            )
        )
        removed = True
    await db.flush()
    return removed
