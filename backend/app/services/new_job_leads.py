"""„Nowe rekrutacje P1 — kto prowadzi” na pulpicie Head of Recruitment.

Lista informacyjna: rekrutacje P1 przekazane do searchu w ostatnich dniach
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
potwierdzono. Liczy się wyłącznie potwierdzenie z bieżącego cyklu i tej samej
osoby — gdy automat albo ktoś inny zmieni potem prowadzącego, rekrutacja wraca
na listę i mówi, kto był wcześniej (``returned_from_*``).

Uwagi Head of Recruitment 14.10.2026 (decyzje Artura D1–D3, reguły
w ``docs/claude/rekrutacja-tablica/przydzial-ludzi-do-requestow-stany-requestu-i.md``,
sekcja „Nowe rekrutacje P1 — kto prowadzi” i obłożenie P1):

* **Tylko P1, bez championa.** Rekrutacja bez priorytetu i „Przyjmujemy” nie
  czeka na decyzję o prowadzącym — automat jej nie obsadza. Wejście na P1
  zaczyna nowy cykl (wpis ``priority_changed`` z ``job_priority``).
* **Decyzja z każdego ekranu.** Zespół ustawiony przez Head of Recruitment albo
  admina na pulpicie, w panelu rekrutacji, na liście czy w oknie edycji zapisuje
  potwierdzenie (``record_team_decision``). Przy odczycie liczy się też wiersz
  przypisania prowadzącego wpisany przez taką osobę w bieżącym cyklu — dane
  sprzed tej reguły i ścieżki, których nikt nie dopisał.
* **Własny początek cyklu**, nie ``jobs.work_state_changed_at``: tę kolumnę
  przesuwa też „Mamy championa” (blokady automatu w ``request_allocation``),
  a potwierdzenie sprzed championa ma obowiązywać dalej. Na produkcji champion
  przywracał potwierdzone wiersze jako „przekazano dziś”.
* **Limit po odrzuceniu potwierdzonych.** 12.10.2026 ponowne otwarcie 185
  rekrutacji wypchnęło za limit 4 z 5 nierozstrzygniętych P1.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, load_only

from app.models.activity import Activity
from app.models.client import Client
from app.models.competence_category import CompetenceCategory
from app.models.job import Job, JobStatus
from app.models.job_collaborator import JobCollaborator, JobCollaboratorSource
from app.models.job_work_assignment import JobWorkAssignment
from app.models.user import User
from app.services.job_priority import (
    PRIORITY_CHANGED_ACTION,
    level_of,
    priorities_for_levels,
)
from app.services.job_team import TeamPerson, recruiters_for_jobs, working
from app.services.job_working_title import job_display_title_expr

logger = logging.getLogger(__name__)

WINDOW_DAYS = 7
# Bezpiecznik, nie strona: listę zawęża okno dni i P1, a filtry na pulpicie
# działają w przeglądarce na tym, co tu wróci. Liczony na wyniku, po
# odrzuceniu potwierdzonych — nigdy na zapytaniu.
MAX_ROWS = 100
# Automat rusza po zdarzeniu z przekazania; do tego czasu „nikt nie prowadzi”
# znaczy „właśnie przydziela”.
ASSIGNING_GRACE = timedelta(minutes=2)
CONFIRMED_ACTION = "new_job_lead_confirmed"
# Wpis ``request_work_state.set_work_state``.
_WORK_STATE_CHANGED = "work_state_changed"
# Powrót z „Klient milczy” to ciąg tego samego cyklu (D2).
_SAME_CYCLE_FROM = "client_silent"


def record_confirmation(
    db: AsyncSession, *, job_id: int, lead_user_id: int, actor_id: int, via: str
) -> None:
    """Head of Recruitment / admin zgadza się z prowadzącym (``via``:
    ``confirm`` — przycisk, ``owner_change`` — wybrał inną osobę,
    ``proposal`` — rozstrzygnął propozycję automatu, ``team_change`` —
    zmienił zespół na innym ekranie)."""
    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action=CONFIRMED_ACTION,
            user_id=actor_id,
            details={"lead_user_id": lead_user_id, "via": via},
        )
    )


def _decides(user: User) -> bool:
    from app.api.recruitment_access import PROPOSAL_DECISION_ROLES  # noqa: PLC0415

    return user.has_any_role(*PROPOSAL_DECISION_ROLES)


async def record_team_decision(
    db: AsyncSession, *, job_id: int, actor: User, via: str
) -> None:
    """Zespół rekrutacji ustawił Head of Recruitment albo admin — na dowolnym
    ekranie (D1, 14.10.2026). Zapisuje potwierdzenie osoby, która prowadzi PO
    zmianie. Bez prowadzącego nic: rekrutacja P1 bez nikogo ma zostać na liście.

    Wołający trzyma transakcję zmiany i commituje sam; pozostałe role nic tu nie
    zapisują (lista pokazuje Head of Recruitment, co ustawili inni).
    """
    if not _decides(actor):
        return
    await db.flush()
    people = (await recruiters_for_jobs(db, [job_id])).get(job_id, [])
    lead = next(iter(working(people)), None)
    if lead is None:
        return
    record_confirmation(
        db, job_id=job_id, lead_user_id=lead.user_id, actor_id=actor.id, via=via
    )


async def _confirmations(
    db: AsyncSession, since_by_job: dict[int, datetime]
) -> dict[int, int]:
    """Osoba z ostatniego potwierdzenia bieżącego cyklu, per rekrutacja."""
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
class _Cycle:
    since: datetime
    # ``handoff`` (przekazanie, także ręczna zmiana stanu), ``reopen``
    # (ponowne otwarcie) albo ``p1`` (wejście na P1).
    reason: str


async def _cycle_starts(
    db: AsyncSession, fallback: dict[int, Optional[datetime]]
) -> dict[int, _Cycle]:
    """Początek bieżącego cyklu: późniejsze z wejścia do „Szukamy” i wejścia
    na P1 (D2, D3).

    Daty z dziennika (``created_at`` = początek transakcji), tak jak daty
    potwierdzeń i wierszy przypisania — potwierdzenie zapisane w tej samej
    transakcji co przekazanie liczy się. Rekrutacja bez wpisu wejścia
    (sprzed dziennika stanów) bierze ``work_state_changed_at`` z ``fallback``.
    """
    if not fallback:
        return {}
    rows = (
        await db.execute(
            select(
                Activity.entity_id,
                Activity.action,
                Activity.created_at,
                Activity.details,
            ).where(
                Activity.entity_type == "job",
                Activity.entity_id.in_(list(fallback)),
                Activity.action.in_((_WORK_STATE_CHANGED, PRIORITY_CHANGED_ACTION)),
            )
        )
    ).all()
    entered: dict[int, tuple[datetime, str]] = {}
    raised: dict[int, datetime] = {}
    for job_id, action, created_at, details in rows:
        details = details or {}
        if created_at is None:
            continue
        if action == _WORK_STATE_CHANGED:
            if (
                details.get("to") != "searching"
                or details.get("from") == _SAME_CYCLE_FROM
            ):
                continue
            if job_id not in entered or created_at > entered[job_id][0]:
                reason = "reopen" if details.get("reason") == "reopen" else "handoff"
                entered[job_id] = (created_at, reason)
        elif details.get("to") == "p1":
            if job_id not in raised or created_at > raised[job_id]:
                raised[job_id] = created_at
    out: dict[int, _Cycle] = {}
    for job_id, default in fallback.items():
        since, reason = entered.get(job_id, (default, "handoff"))
        raised_at = raised.get(job_id)
        if raised_at is not None and (since is None or raised_at > since):
            since, reason = raised_at, "p1"
        if since is not None:
            out[job_id] = _Cycle(since=since, reason=reason)
    return out


async def _placed_by_decider(
    db: AsyncSession, leads: dict[int, tuple[int, datetime]]
) -> set[int]:
    """Rekrutacje, których prowadzącego Head of Recruitment albo admin wpisał
    w bieżącym cyklu (``leads``: job → (prowadzący, początek cyklu))."""
    if not leads:
        return set()
    rows = (
        await db.execute(
            select(
                JobWorkAssignment.job_id,
                JobWorkAssignment.user_id,
                JobWorkAssignment.assigned_at,
                JobWorkAssignment.assigned_by,
            ).where(
                JobWorkAssignment.job_id.in_(list(leads)),
                JobWorkAssignment.state == "active",
                JobWorkAssignment.assigned_by.is_not(None),
            )
        )
    ).all()
    rows = [
        row
        for row in rows
        if leads[row.job_id][0] == row.user_id
        and row.assigned_at is not None
        and row.assigned_at >= leads[row.job_id][1]
    ]
    if not rows:
        return set()
    deciders = {
        user.id
        for user in (
            await db.scalars(
                select(User)
                .where(User.id.in_({row.assigned_by for row in rows}))
                .options(load_only(User.id, User.role, User.roles))
            )
        ).all()
        if _decides(user)
    }
    return {row.job_id for row in rows if row.assigned_by in deciders}


async def _names(db: AsyncSession, user_ids: Iterable[int]) -> dict[int, str]:
    ids = set(user_ids)
    if not ids:
        return {}
    return dict(
        (await db.execute(select(User.id, User.name).where(User.id.in_(ids)))).all()
    )


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
    since_reason: str = "handoff"
    lead_user_id: Optional[int] = None
    lead_name: Optional[str] = None
    lead_role: Optional[str] = None
    lead_source: Optional[str] = None
    assigned_by_name: Optional[str] = None
    proposed: bool = False
    pending_reason: Optional[str] = None
    returned_from_user_id: Optional[int] = None
    returned_from_name: Optional[str] = None


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


def _lead_of(people: list[TeamPerson]) -> Optional[TeamPerson]:
    """Osoba pracująca, a bez niej propozycja automatu czekająca na akceptację."""
    return next(iter(working(people)), None) or next(iter(people), None)


async def load_new_job_leads(db: AsyncSession, *, now: datetime) -> list[NewJobLead]:
    """Rekrutacje P1, których cykl zaczął się w ostatnich ``WINDOW_DAYS`` dniach,
    od najnowszej. Stała liczba zapytań."""
    from app.services.recruitment_allocation import (  # noqa: PLC0415
        effective_allocation_mode,
    )
    from app.services.request_allocation import (  # noqa: PLC0415
        _last_assignment_was_auto,
    )

    delivery_lead = aliased(User)
    pool = (
        await db.execute(
            select(
                Job.id,
                job_display_title_expr().label("title"),
                Client.name.label("client_name"),
                Job.competence_category_id,
                CompetenceCategory.name_pl.label("category_name"),
                CompetenceCategory.slug.label("category_slug"),
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
                Job.champion_found_at.is_(None),
                Job.priority.in_(priorities_for_levels(["p1"])),
            )
        )
    ).all()
    cycles = await _cycle_starts(
        db, {row.id: row.work_state_changed_at for row in pool}
    )
    window_start = now - timedelta(days=WINDOW_DAYS)
    jobs = sorted(
        (
            row
            for row in pool
            if row.id in cycles and cycles[row.id].since >= window_start
        ),
        key=lambda row: (cycles[row.id].since, row.id),
        reverse=True,
    )
    not_handed_off = await _not_handed_off(db, exclude=[row.id for row in pool])
    if not jobs:
        return not_handed_off[:MAX_ROWS]
    job_ids = [row.id for row in jobs]
    since_by_job = {job_id: cycles[job_id].since for job_id in job_ids}
    participants = await _participants(db, job_ids)
    teams = await recruiters_for_jobs(db, job_ids)

    leads = {}
    for job_id in job_ids:
        lead = _lead_of(teams.get(job_id, []))
        if lead is not None:
            leads[job_id] = lead
    confirmed = await _confirmations(db, since_by_job)
    placed = await _placed_by_decider(
        db,
        {
            job_id: (lead.user_id, since_by_job[job_id])
            for job_id, lead in leads.items()
            if not lead.proposed
        },
    )
    # Prowadzący bez wiersza przypisania: automat wpisał go wcześniej, jeśli
    # tak mówi najnowszy zamknięty wiersz pary.
    auto_owned = await _last_assignment_was_auto(
        db,
        [
            (job_id, lead.user_id)
            for job_id, lead in leads.items()
            if lead.via == "owner" and lead.assignment_source is None
        ],
    )
    # Kto prowadził przy ostatniej decyzji, gdy dziś prowadzi ktoś inny.
    returned_from = {
        job_id: user_id
        for job_id, user_id in confirmed.items()
        if (leads.get(job_id) is None or leads[job_id].user_id != user_id)
    }
    returned_names = await _names(db, returned_from.values())
    mode: Optional[str] = None
    out: list[NewJobLead] = []
    for row in jobs:
        cycle = cycles[row.id]
        previous = returned_from.get(row.id)
        base = dict(
            job_id=row.id,
            title=row.title,
            client_name=row.client_name,
            category_id=row.competence_category_id,
            category_name=row.category_name,
            category_slug=row.category_slug,
            participants=participants.get(row.id, 0),
            priority_level="p1",
            delivery_lead_name=row.delivery_lead_name,
            handed_off_at=cycle.since,
            since_reason=cycle.reason,
            returned_from_user_id=previous,
            returned_from_name=returned_names.get(previous) if previous else None,
        )
        lead = leads.get(row.id)
        if lead is None:
            reason = "none"
            if now - cycle.since < ASSIGNING_GRACE:
                if mode is None:
                    mode = await effective_allocation_mode(db)
                if mode == "auto":
                    reason = "assigning"
            out.append(NewJobLead(**base, pending_reason=reason))
            continue
        if not lead.proposed and (
            confirmed.get(row.id) == lead.user_id or row.id in placed
        ):
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
    return (out + not_handed_off)[:MAX_ROWS]


async def _not_handed_off(db: AsyncSession, *, exclude: list[int]) -> list[NewJobLead]:
    """Opublikowane rekrutacje P1 bez przekazania do searchu (H7) — od najstarszej.

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
                Job.priority.in_(priorities_for_levels(["p1"])),
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
