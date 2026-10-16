"""Odejście = przekazanie pracy: co osoba ma w NEXUSIE i kto to przejmuje.

Podsumowanie liczy osiem rodzajów pracy z tych samych danych co lista
rekrutacji, „Moi ludzie”, portfel Delivery Leada i kalendarz. Cztery rodzaje
przechodzą na przejmującego (``TRANSFER_KINDS``), każdy ISTNIEJĄCĄ ścieżką
zapisu — nie ma tu nowej drogi zmiany właściciela:

* **rekrutacje** — ``job_team.remove_recruiter`` (zdjęcie z trzech miejsc
  naraz, blokada ``allocation_lock`` przed wierszem rekrutacji) +
  ``job_team.add_manual_member`` (trwały wpis przejmującego w zespole) —
  te same funkcje co „Zdejmij” i „+ Dodaj osobę” w panelu „Zespół”;
  przejmujący musi mieć rolę rekrutera,
* **Delivery Lead rekrutacji** — ``jobs.delivery_lead_id`` jak w oknie edycji
  (ręczna zmiana zdejmuje ``delivery_lead_auto_filled``, wpis ``updated``),
  role jak w PATCH rekrutacji,
* **klienci Delivery Leada** — wiersze ``delivery_lead_client_assignments``
  jak w Ustawieniach → Struktura zespołu (główny opiekun zostaje głównym,
  unieważnienie zakresu DL-a),
* **„Moi ludzie”** — przypięcie osób u przejmującego (``my_people_overrides``
  ``pinned``, jak „Przypnij”); jego własnych uśpień nie nadpisujemy.

Pozostałe rodzaje (karty w procesie, rozmowy u klienta po ostatnim dniu,
umówione kontakty z kandydatami, zastępstwa w urlopach) idą z rekrutacjami
albo wymagają decyzji w innym miejscu — podsumowanie je pokazuje, przekazanie
ich nie rusza.

Przekazanie wykonuje pętla po 18:00 ostatniego dnia pracy; każdy rodzaj
w osobnym savepoincie i idempotentnie (ponowny przebieg nie ma już czego
przenieść). Wynik to same liczby.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import local_day_start_utc
from app.models.activity import Activity
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.candidate_followup import CandidateFollowup
from app.models.hr_leave import LeaveRequest
from app.models.hr_lifecycle import LifecycleCase, WorkHandover
from app.models.job import Job, JobStatus
from app.models.my_people import MyPeopleOverride
from app.models.notification import NotificationType
from app.models.recruitment_process import ProcessStatus, RecruitmentProcess
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole
from app.services.hr_lifecycle_schema import TRANSFER_KINDS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkKind:
    key: str
    label: str
    transferable: bool
    note: str


#: Kolejność jak w makiecie „Co osoba ma w NEXUSIE”.
WORK_KINDS: tuple[WorkKind, ...] = (
    WorkKind(
        "recruitments",
        "Rekrutacje, w których pracuje jako rekruter",
        True,
        "Przejmujący wchodzi do zespołu rekrutacji, odchodzący z niego schodzi.",
    ),
    WorkKind(
        "pipeline_cards",
        "Karty w procesie",
        False,
        "Idą z rekrutacjami.",
    ),
    WorkKind(
        "client_meetings",
        "Rozmowy u klienta po ostatnim dniu",
        False,
        "Idą z rekrutacjami — termin zostaje w kalendarzu rekrutacji.",
    ),
    WorkKind(
        "followups",
        "Umówione kontakty z kandydatami",
        False,
        "Kandydaci prosili o telefon po ostatnim dniu — idą z rekrutacjami.",
    ),
    WorkKind(
        "my_people",
        "„Moi ludzie”",
        True,
        "Osoby trafiają na listę przejmującego jako przypięte.",
    ),
    WorkKind(
        "delivery_lead_jobs",
        "Rekrutacje, w których jest Delivery Leadem",
        True,
        "Przejmujący zostaje Delivery Leadem tych rekrutacji.",
    ),
    WorkKind(
        "dl_clients",
        "Klienci Delivery Leada",
        True,
        "Przejmujący dostaje klientów do portfela (główny opiekun zostaje główny).",
    ),
    WorkKind(
        "substitutions",
        "Zastępstwa w urlopach po ostatnim dniu",
        False,
        "Zastępcę zmienia osoba na urlopie albo Kadry we wniosku.",
    ),
)
WORK_KIND_BY_KEY: dict[str, WorkKind] = {kind.key: kind for kind in WORK_KINDS}

#: Kto może przejąć dany rodzaj pracy (lustra reguł istniejących ścieżek).
RECEIVER_ROLES: dict[str, frozenset[UserRole]] = {
    # `job_team.WORK_ROLES` — rekruterem rekrutacji jest tylko rola rekrutera.
    "recruitments": frozenset({UserRole.recruiter}),
    # PATCH rekrutacji (`delivery_lead_id`).
    "delivery_lead_jobs": frozenset(
        {UserRole.delivery_lead, UserRole.admin, UserRole.head_of_recruitment}
    ),
    # Ustawienia → Struktura zespołu (`must reference role=delivery_lead`).
    "dl_clients": frozenset({UserRole.delivery_lead}),
    "my_people": frozenset(
        {
            UserRole.recruiter,
            UserRole.delivery_lead,
            UserRole.head_of_recruitment,
            UserRole.admin,
        }
    ),
}

RECEIVER_ERRORS: dict[str, str] = {
    "no_receiver": "Nie wskazano przejmującego.",
    "receiver_inactive": "Przejmujący nie ma aktywnego konta.",
    "receiver_not_eligible": "Przejmujący nie ma roli, której wymaga ta praca.",
    "receiver_is_leaver": "Osoba odchodząca nie może przejąć własnej pracy.",
    "error": "Przekazanie nie wyszło — szczegóły w logu serwera.",
}


def receiver_problem(
    receiver: Optional[User], work_kind: str, leaver_id: Optional[int]
) -> Optional[str]:
    """Kod powodu, dla którego konto nie przejmie pracy (``None`` = może)."""

    if receiver is None:
        return "no_receiver"
    if leaver_id is not None and receiver.id == leaver_id:
        return "receiver_is_leaver"
    if not receiver.is_active:
        return "receiver_inactive"
    if not receiver.has_any_role(*RECEIVER_ROLES[work_kind]):
        return "receiver_not_eligible"
    return None


# ── Podsumowanie: co osoba ma w NEXUSIE ─────────────────────────────────────


async def my_people_ids(db: AsyncSession, user_id: int) -> set[int]:
    """Lista „Moi ludzie” osoby: wyliczeni + przypięci − uśpieni."""

    from app.services.my_people import owned_candidate_ids  # noqa: PLC0415

    ids = await owned_candidate_ids(db, user_id)
    overrides = (
        await db.execute(
            select(MyPeopleOverride.candidate_id, MyPeopleOverride.kind).where(
                MyPeopleOverride.user_id == user_id
            )
        )
    ).all()
    for candidate_id, kind in overrides:
        if kind == "snoozed":
            ids.discard(candidate_id)
        else:
            ids.add(candidate_id)
    return ids


def _open_jobs_worked_by(user_id: int):
    from app.services.job_team import jobs_worked_by_clause  # noqa: PLC0415

    return select(Job.id).where(
        Job.status != JobStatus.closed, jobs_worked_by_clause([user_id])
    )


async def _count(db: AsyncSession, statement) -> int:
    return int(
        await db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    )


async def work_summary(
    db: AsyncSession, user_id: int, *, last_working_day: date
) -> dict[str, int]:
    """Liczba pozycji per rodzaj pracy (stan na teraz)."""

    after_last_day = local_day_start_utc(last_working_day + timedelta(days=1))
    counts: dict[str, int] = {
        "recruitments": await _count(db, _open_jobs_worked_by(user_id)),
        "pipeline_cards": await _count(
            db,
            select(RecruitmentProcess.id).where(
                RecruitmentProcess.owner_user_id == user_id,
                RecruitmentProcess.status == ProcessStatus.open,
            ),
        ),
        "client_meetings": await _count(
            db,
            select(CalendarEvent.id).where(
                CalendarEvent.status == EventStatus.scheduled,
                CalendarEvent.event_type.in_(
                    (EventType.client_interview, EventType.interview)
                ),
                CalendarEvent.start_time >= after_last_day,
                func.coalesce(
                    CalendarEvent.operational_owner_id, CalendarEvent.created_by
                )
                == user_id,
            ),
        ),
        "followups": await _count(
            db,
            select(CandidateFollowup.id).where(
                CandidateFollowup.user_id == user_id,
                CandidateFollowup.outcome == "callback",
                CandidateFollowup.callback_on > last_working_day,
            ),
        ),
        "my_people": len(await my_people_ids(db, user_id)),
        "delivery_lead_jobs": await _count(
            db,
            select(Job.id).where(
                Job.status != JobStatus.closed, Job.delivery_lead_id == user_id
            ),
        ),
        "dl_clients": await _count(
            db,
            select(DeliveryLeadClientAssignment.id).where(
                DeliveryLeadClientAssignment.delivery_lead_user_id == user_id
            ),
        ),
        "substitutions": await _count(
            db,
            select(LeaveRequest.id).where(
                LeaveRequest.substitute_user_id == user_id,
                LeaveRequest.status.in_(("pending", "approved")),
                LeaveRequest.end_date > last_working_day,
            ),
        ),
    }
    return counts


async def eligible_receivers(
    db: AsyncSession, work_kind: str, *, leaver_id: Optional[int]
) -> list[dict[str, Any]]:
    users = await db.scalars(
        select(User).where(User.is_active.is_(True)).order_by(User.name, User.id)
    )
    return [
        {"user_id": user.id, "name": user.name}
        for user in users
        if receiver_problem(user, work_kind, leaver_id) is None
    ]


async def plan_handovers(db: AsyncSession, case: LifecycleCase) -> list[WorkHandover]:
    """Wiersze przekazania dla rodzajów przenoszonych (domyślnie przełożony).

    Istniejące wiersze zachowują wybranego przejmującego; liczby się odświeżają,
    dopóki przekazanie nie zostało wykonane.
    """

    assert case.user_id is not None and case.last_working_day is not None
    counts = await work_summary(
        db, case.user_id, last_working_day=case.last_working_day
    )
    existing = {
        row.work_kind: row
        for row in await db.scalars(
            select(WorkHandover).where(WorkHandover.case_id == case.id)
        )
    }
    manager = await db.get(User, case.manager_user_id) if case.manager_user_id else None
    rows: list[WorkHandover] = []
    for work_kind in TRANSFER_KINDS:
        row = existing.get(work_kind)
        if row is None:
            default = (
                manager.id
                if receiver_problem(manager, work_kind, case.user_id) is None
                else None
            )
            row = WorkHandover(
                case_id=case.id,
                work_kind=work_kind,
                receiver_user_id=default,
                item_count=counts[work_kind],
            )
            db.add(row)
        elif row.status != "done":
            row.item_count = counts[work_kind]
        rows.append(row)
    await db.flush()
    return rows


# ── Wykonanie ────────────────────────────────────────────────────────────────


Executor = Callable[..., Awaitable[dict[str, int]]]


async def _transfer_recruitments(
    db: AsyncSession,
    *,
    leaver_id: int,
    receiver: User,
    actor_id: Optional[int],
    case_id: int,
) -> dict[str, int]:
    from app.services.job_team import add_manual_member, remove_recruiter  # noqa: PLC0415
    from app.services.recruitment_allocation import allocation_lock  # noqa: PLC0415

    # Ta sama kolejność blokad co `/owner` i przebieg automatu przydziału.
    await allocation_lock(db)
    job_ids = list(await db.scalars(_open_jobs_worked_by(leaver_id).order_by(Job.id)))
    moved = 0
    for job_id in job_ids:
        job = await db.scalar(select(Job).where(Job.id == job_id).with_for_update())
        if job is None:
            continue
        await remove_recruiter(db, job=job, user_id=leaver_id, actor_id=actor_id)
        await add_manual_member(
            db, job_id=job_id, user_id=receiver.id, actor_id=actor_id
        )
        moved += 1
    return {"jobs": moved}


async def _transfer_delivery_lead_jobs(
    db: AsyncSession,
    *,
    leaver_id: int,
    receiver: User,
    actor_id: Optional[int],
    case_id: int,
) -> dict[str, int]:
    jobs = list(
        await db.scalars(
            select(Job)
            .where(Job.status != JobStatus.closed, Job.delivery_lead_id == leaver_id)
            .order_by(Job.id)
            .with_for_update()
        )
    )
    for job in jobs:
        job.delivery_lead_id = receiver.id
        # Ręczna zmiana DL-a (jak w oknie edycji): od teraz nietykalny dla
        # automatycznego uzupełniania DL-a z klienta.
        job.delivery_lead_auto_filled = False
        db.add(
            Activity(
                entity_type="job",
                entity_id=job.id,
                action="updated",
                user_id=actor_id,
                details={
                    "delivery_lead_id": receiver.id,
                    "source": "hr_work_handover",
                    "lifecycle_case_id": case_id,
                },
            )
        )
    await db.flush()
    return {"jobs": len(jobs)}


async def _transfer_dl_clients(
    db: AsyncSession,
    *,
    leaver_id: int,
    receiver: User,
    actor_id: Optional[int],
    case_id: int,
) -> dict[str, int]:
    from app.services.authorization_invalidation import (  # noqa: PLC0415
        invalidate_delivery_lead_scope_for_users,
    )

    rows = list(
        await db.scalars(
            select(DeliveryLeadClientAssignment)
            .where(DeliveryLeadClientAssignment.delivery_lead_user_id == leaver_id)
            .order_by(DeliveryLeadClientAssignment.id)
            .with_for_update()
        )
    )
    if not rows:
        return {"clients": 0, "heads": 0}
    receiver_rows = {
        row.client_id: row
        for row in await db.scalars(
            select(DeliveryLeadClientAssignment)
            .where(
                DeliveryLeadClientAssignment.delivery_lead_user_id == receiver.id,
                DeliveryLeadClientAssignment.client_id.in_([r.client_id for r in rows]),
            )
            .with_for_update()
        )
    }
    heads = 0
    promote: list[DeliveryLeadClientAssignment] = []
    for row in rows:
        heads += int(row.is_head)
        existing = receiver_rows.get(row.client_id)
        if existing is None:
            row.delivery_lead_user_id = receiver.id
            continue
        if row.is_head and not existing.is_head:
            promote.append(existing)
        await db.delete(row)
    # Najpierw zniknąć musi wiersz odchodzącego — klient ma najwyżej jednego
    # głównego opiekuna (`uq_dl_client_head`).
    await db.flush()
    for existing in promote:
        existing.is_head = True
    await db.flush()
    await invalidate_delivery_lead_scope_for_users(db, {leaver_id, receiver.id})
    db.add(
        Activity(
            entity_type="user",
            entity_id=leaver_id,
            action="dl_clients_handed_over",
            user_id=actor_id,
            details={
                "receiver_user_id": receiver.id,
                "clients": len(rows),
                "lifecycle_case_id": case_id,
            },
        )
    )
    return {"clients": len(rows), "heads": heads}


async def _transfer_my_people(
    db: AsyncSession,
    *,
    leaver_id: int,
    receiver: User,
    actor_id: Optional[int],
    case_id: int,
) -> dict[str, int]:
    ids = sorted(await my_people_ids(db, leaver_id))
    if not ids:
        return {"people": 0, "pinned": 0}
    pinned = 0
    for start in range(0, len(ids), 500):
        chunk = ids[start : start + 500]
        result = await db.execute(
            pg_insert(MyPeopleOverride)
            .values(
                [
                    {"user_id": receiver.id, "candidate_id": cid, "kind": "pinned"}
                    for cid in chunk
                ]
            )
            # Osoba już na liście przejmującego (przypięta albo przez niego
            # uśpiona) zostaje tak, jak ją zostawił.
            .on_conflict_do_nothing(constraint="uq_my_people_overrides_user_candidate")
            .returning(MyPeopleOverride.id)
        )
        pinned += len(result.all())
    return {"people": len(ids), "pinned": pinned}


EXECUTORS: dict[str, Executor] = {
    "recruitments": _transfer_recruitments,
    "delivery_lead_jobs": _transfer_delivery_lead_jobs,
    "dl_clients": _transfer_dl_clients,
    "my_people": _transfer_my_people,
}

_RESULT_LABELS: dict[str, str] = {
    "recruitments": "rekrutacje",
    "delivery_lead_jobs": "rekrutacje jako Delivery Lead",
    "dl_clients": "klienci",
    "my_people": "„Moi ludzie”",
}


def _moved(work_kind: str, result: dict[str, int]) -> int:
    key = {
        "recruitments": "jobs",
        "delivery_lead_jobs": "jobs",
        "dl_clients": "clients",
        "my_people": "people",
    }[work_kind]
    return int(result.get(key, 0))


@dataclass
class HandoverRun:
    done: int = 0
    failed: int = 0
    moved: dict[str, int] | None = None


async def execute_handover(
    db: AsyncSession, case: LifecycleCase, *, now: datetime
) -> HandoverRun:
    """Przekazuje pracę wszystkich rodzajów, które jeszcze nie przeszły.

    Wołający trzyma blokadę wiersza sprawy i commituje. Rodzaj bez pozycji
    przechodzi bez przejmującego (nic do przekazania). Rodzaj z błędem zostaje
    ``failed`` i wraca w następnym przebiegu — Kadry dostają dzwonek raz,
    przy pierwszym niepowodzeniu.
    """

    assert case.user_id is not None
    rows = await plan_handovers(db, case)
    actor_id = case.owner_user_id or case.created_by
    outcome = HandoverRun(moved={})
    per_receiver: dict[int, list[tuple[str, int]]] = {}
    newly_failed: list[str] = []
    for row in rows:
        if row.status == "done":
            continue
        receiver = (
            await db.get(User, row.receiver_user_id) if row.receiver_user_id else None
        )
        problem = receiver_problem(receiver, row.work_kind, case.user_id)
        if problem is not None and row.item_count == 0:
            row.status = "done"
            row.executed_at = now
            row.result = {"moved": 0}
            row.error = None
            outcome.done += 1
            continue
        if problem is None:
            try:
                async with db.begin_nested():
                    result = await EXECUTORS[row.work_kind](
                        db,
                        leaver_id=case.user_id,
                        receiver=receiver,
                        actor_id=actor_id,
                        case_id=case.id,
                    )
            except Exception:  # noqa: BLE001 — jeden rodzaj nie blokuje reszty
                logger.exception(
                    "hr_handover failed case=%s kind=%s", case.id, row.work_kind
                )
                problem = "error"
        if problem is not None:
            if row.status != "failed":
                newly_failed.append(row.work_kind)
            row.status = "failed"
            row.error = problem
            outcome.failed += 1
            continue
        row.status = "done"
        row.executed_at = now
        row.result = result
        row.error = None
        outcome.done += 1
        moved = _moved(row.work_kind, result)
        outcome.moved[row.work_kind] = moved
        if moved:
            per_receiver.setdefault(receiver.id, []).append((row.work_kind, moved))
    if outcome.failed == 0:
        case.handover_executed_at = now
    await db.flush()
    await _notify_receivers(db, case, per_receiver)
    if newly_failed:
        await _notify_failure(db, case, newly_failed)
    return outcome


async def _person_name(db: AsyncSession, user_id: Optional[int]) -> str:
    if user_id is None:
        return "osoby"
    name = await db.scalar(select(User.name).where(User.id == user_id))
    return name or "osoby"


async def _notify_receivers(
    db: AsyncSession,
    case: LifecycleCase,
    per_receiver: dict[int, list[tuple[str, int]]],
) -> None:
    from app.services.notification_triggers import emit  # noqa: PLC0415

    if not per_receiver:
        return
    name = await _person_name(db, case.user_id)
    for receiver_id, items in per_receiver.items():
        summary = ", ".join(f"{_RESULT_LABELS[kind]}: {count}" for kind, count in items)
        link = "/jobs" if any(k == "recruitments" for k, _ in items) else "/dashboard"
        try:
            async with db.begin_nested():
                await emit(
                    db,
                    user_id=receiver_id,
                    title=f"Przejmujesz pracę: {name}",
                    message=f"Od dziś prowadzisz po tej osobie — {summary}.",
                    ntype=NotificationType.hr_work_handover,
                    related_entity_type="lifecycle_case",
                    related_entity_id=case.id,
                    link=link,
                )
        except Exception:  # noqa: BLE001 — dzwonek nie cofa przekazania
            logger.exception(
                "hr_handover notification failed case=%s user=%s", case.id, receiver_id
            )


async def _notify_failure(
    db: AsyncSession, case: LifecycleCase, kinds: list[str]
) -> None:
    from app.services.notification_triggers import emit  # noqa: PLC0415

    recipient = case.owner_user_id or case.created_by
    if recipient is None:
        return
    name = await _person_name(db, case.user_id)
    labels = ", ".join(_RESULT_LABELS[kind] for kind in kinds)
    try:
        async with db.begin_nested():
            await emit(
                db,
                user_id=recipient,
                title=f"Przekazanie pracy nie wyszło: {name}",
                message=f"Do poprawienia: {labels}. Wskaż przejmującego w sprawie odejścia.",
                ntype=NotificationType.hr_lifecycle_task,
                related_entity_type="lifecycle_case",
                related_entity_id=case.id,
                link=f"/people/{case.user_id}/offboarding",
            )
    except Exception:  # noqa: BLE001
        logger.exception("hr_handover failure notification failed case=%s", case.id)
