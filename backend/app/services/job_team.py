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

Osoba z „Poprzedni rekruter” (``job_previous_recruiters``, 14.10.2026 —
zamknięcie albo zejście z P1) NIE pracuje, choć jej wiersze zostają: loader
i klauzule zespołu ją pomijają. Dostęp i historia (``is_member_of_job``,
umowy B2B, metryki) czytają gołe ``working_assignment_job_ids`` /
``manual_collaborator_job_ids`` bez ``exclude_parked`` i jej nie gubią.

Loader (``recruiters_for_jobs``) i klauzule SQL (``jobs_worked_by_clause``,
``jobs_nobody_working_clause``) muszą dawać ten sam zbiór — pilnuje tego
``tests/test_job_team.py``. Zmieniasz jedno, zmień drugie.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from sqlalchemy import and_, exists, not_, or_, select, true
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, load_only

from app.models.activity import Activity
from app.models.job import Job
from app.models.job_collaborator import JobCollaborator, JobCollaboratorSource
from app.models.job_work_assignment import WORK_ROLE, JobWorkAssignment
from app.models.user import User, UserRole
from app.services.job_previous_recruiters import (
    clear_parked,
    load_parked,
    parked_exists,
    parked_job_ids,
)


@dataclass(frozen=True)
class TeamPerson:
    user_id: int
    name: str
    role: str  # zawsze WORK_ROLE
    via: str  # owner | assignment | collaborator
    proposed: bool = False
    assigned_by_name: Optional[str] = None
    # Źródło żywego wiersza przypisania osoby (``auto`` | ``manual``); brak =
    # osoba jest przy rekrutacji bez takiego wiersza (prowadzący, współpracownik).
    assignment_source: Optional[str] = None


# Role, które pracują nad requestem (pulpit „Requesty i obłożenie”, planer).
# Od 0411 jedna rola — rekruter.
WORK_ROLES = (UserRole.recruiter,)


# ── Klauzule SQL (filtry listy, zakres „Moje”, liczniki) ────────────────────


def working_assignment_job_ids(
    user_ids: Optional[list[int]] = None,
    *,
    exclude_parked: bool = False,
    active_only: bool = True,
):
    """Rekrutacje z AKTYWNYM przypisaniem (punkt 2 reguły).

    Propozycja (``proposed``) i lustro prowadzącego (``source = 'owner'``) się
    nie liczą; liczą się wyłącznie aktywne konta. ``exclude_parked`` — reguła
    zespołu (bez „Poprzednich rekruterów”); bez niego — dostęp i historia.
    ``active_only=False`` — także konta wyłączone (przekazanie pracy osoby,
    która odeszła: jej rekrutacje muszą przejść, choć zespół jej nie liczy).
    """
    subq = select(JobWorkAssignment.job_id).where(
        JobWorkAssignment.state == "active",
        JobWorkAssignment.source != "owner",
    )
    if active_only:
        subq = subq.join(User, User.id == JobWorkAssignment.user_id).where(
            User.is_active.is_(True)
        )
    if user_ids is not None:
        subq = subq.where(JobWorkAssignment.user_id.in_(user_ids))
    if exclude_parked:
        subq = subq.where(
            ~parked_exists(JobWorkAssignment.job_id, JobWorkAssignment.user_id)
        )
    return subq


def owner_is_working_clause(*, active_only: bool = True):
    """Prowadzący (``jobs.recruiter_id``) pracuje nad rekrutacją (punkt 1).

    Liczy się aktywne konto (``active_only=False`` — także wyłączone, jak
    w ``working_assignment_job_ids``); prowadzący zdjęty RĘCZNIE w bieżącym
    stanie requestu nie wraca (lustro ``request_allocation._blocked``), tak samo
    prowadzący wśród „Poprzednich rekruterów”. Klauzula skorelowana
    z zewnętrznym ``Job`` — nie podzapytanie po ``jobs``.
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
    return and_(
        Job.recruiter_id.is_not(None),
        active_owner if active_only else true(),
        not_(released_manually),
        not_(parked_exists(Job.id, Job.recruiter_id)),
    )


def manual_collaborator_job_ids(
    user_ids: Optional[list[int]] = None,
    *,
    exclude_parked: bool = False,
    active_only: bool = True,
):
    """Rekrutacje z RĘCZNIE dopisanym współpracownikiem (punkt 3).

    Wiersze ``auto_cc`` (cała kategoria kompetencji) się nie liczą — to
    informacja, kto może request wziąć, a nie kto nad nim pracuje.
    ``exclude_parked`` i ``active_only`` jak w ``working_assignment_job_ids``.
    """
    subq = select(JobCollaborator.job_id).where(
        JobCollaborator.source == JobCollaboratorSource.manual,
        JobCollaborator.removed_from_auto_cc.is_(False),
    )
    if active_only:
        subq = subq.join(User, User.id == JobCollaborator.user_id).where(
            User.is_active.is_(True)
        )
    if user_ids is not None:
        subq = subq.where(JobCollaborator.user_id.in_(user_ids))
    if exclude_parked:
        subq = subq.where(
            ~parked_exists(JobCollaborator.job_id, JobCollaborator.user_id)
        )
    return subq


def jobs_worked_by_clause(
    user_ids: list[int], *, include_parked: bool = False, active_only: bool = True
):
    """Filtr „Rekruter” — któraś z osób jest Rekruterem rekrutacji.

    ``include_parked`` (zakres „Wszystkie”): także rekrutacje, przy których
    osoba jest wśród „Poprzednich rekruterów” — inaczej po zamknięciu nikt nie
    znalazłby swoich zamkniętych rekrutacji. Jawnie, bo zwolnione przy
    zejściu z P1 przypisanie samo by jej nie znalazło.
    ``active_only=False`` — także osoby z wyłączonym kontem (przekazanie pracy
    po odejściu, ``app/services/hr/handover.py``); listy i liczniki zostają
    przy domyślnym ``True``.
    """
    clause = or_(
        and_(
            Job.recruiter_id.in_(user_ids),
            owner_is_working_clause(active_only=active_only),
        ),
        Job.id.in_(
            working_assignment_job_ids(
                user_ids, exclude_parked=True, active_only=active_only
            )
        ),
        Job.id.in_(
            manual_collaborator_job_ids(
                user_ids, exclude_parked=True, active_only=active_only
            )
        ),
    )
    if include_parked:
        clause = or_(clause, Job.id.in_(parked_job_ids(user_ids)))
    return clause


def jobs_nobody_working_clause():
    """„Bez rekrutera” — nikt nie pracuje; sama propozycja automatu to za mało,
    a cały zespół wśród „Poprzednich rekruterów” też."""
    return and_(
        not_(owner_is_working_clause()),
        Job.id.not_in(working_assignment_job_ids(exclude_parked=True)),
        Job.id.not_in(manual_collaborator_job_ids(exclude_parked=True)),
    )


# ── Loader (pulpit, wiersz listy, panel rekrutacji) ──────────────────────────


async def recruiters_for_jobs(
    db: AsyncSession, job_ids: Iterable[int]
) -> dict[int, list[TeamPerson]]:
    """Osoby w roli „Rekruter” dla wielu rekrutacji naraz (stała liczba zapytań).

    Kolejność: prowadzący, aktywne przypisania (od najstarszego), ręczni
    współpracownicy, na końcu propozycje automatu (``proposed=True``). Każda
    osoba występuje raz. Rekrutacja bez nikogo ma pustą listę. „Poprzedni
    rekruterzy” (``job_previous_recruiters``) nie pracują — pomijamy ich.
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

    parked = await load_parked(db, ids)
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
        asleep = parked.get(job_id, set())
        active = [
            r
            for r in live
            if r.state == "active" and r.source != "owner" and r.user_id not in asleep
        ]

        owner_id = owners.get(job_id)
        owner = users.get(owner_id) if owner_id is not None else None
        if (
            owner is not None
            and owner.is_active
            and (job_id, owner.id) not in released_owners
            and owner.id not in asleep
        ):
            own_row = next((r for r in active if r.user_id == owner.id), None)
            people.append(
                TeamPerson(
                    user_id=owner.id,
                    name=owner.name,
                    role=WORK_ROLE,
                    via="owner",
                    assigned_by_name=own_row.assigner_name if own_row else None,
                    assignment_source=own_row.source if own_row else None,
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
                    role=WORK_ROLE,
                    via="assignment",
                    assigned_by_name=row.assigner_name,
                    assignment_source=row.source,
                )
            )
            seen.add(row.user_id)
        for user_id in collaborators_by_job.get(job_id, []):
            user = users.get(user_id)
            if user is None or user_id in seen or user_id in asleep:
                continue
            people.append(
                TeamPerson(
                    user_id=user_id,
                    name=user.name,
                    role=WORK_ROLE,
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
                    role=WORK_ROLE,
                    via="assignment",
                    proposed=True,
                    assignment_source=row.source,
                )
            )
            seen.add(row.user_id)
        out[job_id] = people
    return out


def working(people: Iterable[TeamPerson]) -> list[TeamPerson]:
    """Osoby, które pracują — bez propozycji czekających na akceptację."""
    return [person for person in people if not person.proposed]


# ── Dopisanie i zdjęcie osoby w roli „Rekruter” ──────────────────────────────


async def add_manual_member(
    db: AsyncSession,
    *,
    job_id: int,
    user_id: int,
    actor_id: Optional[int],
    unpark: bool = True,
) -> bool:
    """Trwały wpis osoby w roli „Rekruter” (punkt 3 reguły) — lustro ``remove_recruiter``.

    Zgłoszenie Head of Recruitment 12.10.2026: osoba dodana z pulpitu miała samo
    przypisanie (``job_work_assignments``), które automat zwalnia, gdy request
    wychodzi z „Szukamy” — znikała wtedy z filtra „Rekruter”, choć prowadzący
    i osoby dopisane w panelu „Zespół” zostawały. Każda ścieżka, którą człowiek
    dopisuje osobę (pulpit, panel, okno edycji, akceptacja propozycji), woła tę
    funkcję; przypisanie niesie już tylko obłożenie w puli.

    Prowadzący (``jobs.recruiter_id``) wiersza nie dostaje — jest przy
    rekrutacji z urzędu. Wiersz ``auto_cc`` (cała kategoria) albo zdjęty
    wcześniej staje się ``manual``. Zwraca ``True``, gdy wiersz powstał albo
    zmienił się na ręczny, albo osoba wróciła z „Poprzednich rekruterów”.
    Bez commitu.

    Człowiek, który dodaje osobę z „Poprzednich rekruterów”, przywraca ją
    (``unpark``) — także prowadzącego, który wiersza nie dostaje. Wyjątek:
    powrót ludzi po zdjęciu championa (``unpark=False``) to nie decyzja
    o tej osobie.
    """
    # Sesja nie robi autoflush: prowadzący wpisany chwilę wcześniej na obiekcie
    # rekrutacji musi być w bazie, zanim go odczytamy.
    await db.flush()
    unparked = (
        await clear_parked(
            db, job_id=job_id, user_id=user_id, reason="readded", actor_id=actor_id
        )
        if unpark
        else False
    )
    owner_id = await db.scalar(select(Job.recruiter_id).where(Job.id == job_id))
    if owner_id == user_id:
        return unparked
    previous_source = await db.scalar(
        select(JobCollaborator.source).where(
            JobCollaborator.job_id == job_id, JobCollaborator.user_id == user_id
        )
    )
    changed = await db.scalar(
        pg_insert(JobCollaborator)
        .values(job_id=job_id, user_id=user_id, added_by=actor_id)
        .on_conflict_do_update(
            index_elements=["job_id", "user_id"],
            set_={
                "source": JobCollaboratorSource.manual,
                "removed_from_auto_cc": False,
                "removed_at": None,
                "added_by": actor_id,
            },
            where=or_(
                JobCollaborator.source != JobCollaboratorSource.manual,
                JobCollaborator.removed_from_auto_cc.is_(True),
            ),
        )
        .returning(JobCollaborator.id)
    )
    if changed is None:
        return unparked
    details: dict = {"collaborator_id": user_id}
    if previous_source is not None:
        details["promoted_from"] = "auto_cc"
    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action="collaborator_added",
            user_id=actor_id,
            details=details,
        )
    )
    await db.flush()
    return True


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
    # Zdjęta osoba nie wraca przy powrocie na P1.
    await clear_parked(
        db, job_id=job.id, user_id=user_id, reason="removed", actor_id=actor_id
    )
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
                db, job_id=job.id, user_id=user_id, role=WORK_ROLE
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


async def settle_team_without_recruiter_role(
    db: AsyncSession, *, job: Job, actor_id: Optional[int]
) -> dict:
    """Zdejmuje z roli „Rekruter” osoby bez roli rekrutera — przed otwarciem.

    Rekruterem jest tylko rola rekrutera, główna albo dodatkowa (decyzja Artura
    14.10.2026). W zamkniętych rekrutacjach z Traffita ``jobs.recruiter_id``
    to zwykle „osoba odpowiedzialna” — Delivery Lead (14.10.2026: 1 017
    zamkniętych rekrutacji z DL-em, 158 z adminem, 53 z Finansami). „Otwórz
    ponownie” z zachowaniem zespołu robiło z niej Rekrutera: 13.10.2026 DL
    otworzyła dwie rekrutacje Credit Agricole i stała przy nich jako
    rekruterka, dopóki Head of Recruitment jej nie zdjął.

    Prowadzący bez roli rekrutera z rolą Delivery Leada trafia na miejsce DL-a,
    jeśli jest puste albo wypełnił je automat; DL-a wpisanego przez człowieka
    nie ruszamy. Rekrutacja zostaje bez rekrutera — nikogo nowego nie
    wskazujemy. Ręcznie dopisane osoby bez roli rekrutera schodzą tak samo.
    Wołają: ponowne otwarcie z zachowaniem zespołu i przeniesienie z Traffita.
    Bez commitu.
    """
    settled: dict = {}
    if job.recruiter_id is not None:
        owner = await db.get(User, job.recruiter_id)
        if (
            owner is not None
            and owner.is_active
            and not owner.has_any_role(*WORK_ROLES)
        ):
            settled["owner_without_recruiter_role"] = owner.id
            # DL-a wpisanego przez automat (główny DL klienta) zastępujemy: u
            # klienta z kilkoma Delivery Leadami rekrutację prowadzi ten
            # z Traffita, a automat wpisywał wszystkim jednego.
            lead_slot_free = job.delivery_lead_id is None or bool(
                job.delivery_lead_auto_filled
            )
            if owner.has_any_role(UserRole.delivery_lead) and lead_slot_free:
                if job.delivery_lead_id != owner.id:
                    settled["owner_moved_to_delivery_lead"] = True
                job.delivery_lead_id = owner.id
                job.delivery_lead_auto_filled = False
            job.recruiter_id = None
            # Inaczej DL zostałby „Poprzednim rekruterem” tej rekrutacji.
            await clear_parked(
                db, job_id=job.id, user_id=owner.id, reason="skipped", actor_id=actor_id
            )

    links = (
        await db.scalars(
            select(JobCollaborator).where(
                JobCollaborator.job_id == job.id,
                JobCollaborator.source == JobCollaboratorSource.manual,
            )
        )
    ).all()
    dropped: list[int] = []
    for link in links:
        person = await db.get(User, link.user_id)
        if person is None or person.has_any_role(*WORK_ROLES):
            continue
        dropped.append(link.user_id)
        await clear_parked(
            db, job_id=job.id, user_id=link.user_id, reason="skipped", actor_id=actor_id
        )
        await db.delete(link)
        db.add(
            Activity(
                entity_type="job",
                entity_id=job.id,
                action="collaborator_removed",
                user_id=actor_id,
                details={
                    "collaborator_id": link.user_id,
                    "source": "manual",
                    "reason": "no_recruiter_role",
                },
            )
        )
    if dropped:
        settled["collaborators_without_recruiter_role"] = dropped
    await db.flush()
    return settled
