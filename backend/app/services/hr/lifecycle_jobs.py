"""Pętla „Wejście i odejście” (``run_once`` co 15 minut).

Jeden przebieg:

1. **Przekazanie pracy** — sprawy odejścia w toku, w których minęła 18:00
   ostatniego dnia pracy (czas Warszawy), a praca jeszcze nie przeszła
   w całości (``handover.execute_handover``).
2. **Wyłączenie konta** — sprawy, w których nadszedł ``deactivate_on``
   (dzień po ostatnim dniu, kalendarz firmy), praca przeszła w całości
   (``handover_executed_at``), a konto nie jest zamknięte
   (``deactivation.close_account``). Sprawa z nieprzekazaną pracą czeka
   (``deactivation_waiting_handover``) — Kadry wskazują przejmującego albo
   wyłączają konto ręcznie „mimo to”. Przebieg, który miałby wyłączyć więcej
   niż ``MAX_DEACTIVATIONS_PER_RUN`` kont, nie wyłącza żadnego: przebieg
   kończy się jako ``failed`` (sonda ``hr_jobs``), a Kadry i admini dostają
   dzwonek raz dziennie (rezerwacja ``hr_lifecycle_mass_exit``).
3. **Przypomnienia** — w poniedziałek (Warszawa), raz w tygodniu: zaległe
   zadania spraw w toku (najwyżej ``REMINDER_GRACE_DAYS`` po terminie) →
   dzwonek ``hr_lifecycle_task`` do wykonawcy; zadanie bez wykonawcy →
   przełożony, a bez niego Kadry. Compass przypominał mailem bez śladu
   wysyłki (dzień tygodnia był jedynym zabezpieczeniem) — tu tydzień
   rezerwuje ``hr_job_runs``.

Rezerwacje: ``hr_job_runs`` (``hr_lifecycle`` per kwadrans, ``hr_lifecycle_reminders``
per tydzień ISO, ``hr_lifecycle_mass_exit`` per dzień) i blokada wiersza sprawy (``FOR UPDATE SKIP LOCKED``) —
dwa kontenery przy nocnym wdrożeniu nie przekażą pracy dwa razy. Każda
sprawa w osobnym commicie: błąd jednej nie cofa pozostałych.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import local_now
from app.models.hr_lifecycle import LifecycleCase, LifecycleTask
from app.models.notification import NotificationType
from app.services.hr import job_runs
from app.services.hr import modules as hr_modules
from app.services.hr.deactivation import (
    MASS_EXIT_ERROR,
    MAX_DEACTIVATIONS_PER_RUN,
    close_account,
    mass_exit_suspected,
)
from app.services.hr.handover import execute_handover
from app.services.hr.lifecycle_access import pool_member_ids
from app.services.hr.lifecycle_dates import HANDOVER_HOUR, handover_due
from app.services.hr.lifecycle_hooks import lifecycle_integrations
from app.services.hr.lifecycle_service import notify_assignees
from app.services.hr.modules import HrModule
from app.services.hr.notify import notify_each

logger = logging.getLogger(__name__)

JOB_KIND = "hr_lifecycle"
REMINDERS_KIND = "hr_lifecycle_reminders"
MASS_EXIT_ALERT_KIND = "hr_lifecycle_mass_exit"
INTERVAL_SECONDS = 15 * 60
#: Zadanie przeterminowane dłużej nie wraca w dzwonku (zostaje na liście).
REMINDER_GRACE_DAYS = 30


def slot_key(now: datetime) -> str:
    """Kwadrans, w którym wypada przebieg (czas Warszawy)."""

    minute = now.minute - now.minute % 15
    return now.replace(minute=minute, second=0, microsecond=0).strftime(
        "%Y-%m-%dT%H:%M"
    )


def week_key(day: date) -> str:
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


async def _lock_case(db: AsyncSession, case_id: int) -> Optional[LifecycleCase]:
    return await db.scalar(
        select(LifecycleCase)
        .where(LifecycleCase.id == case_id)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )


async def run_handovers(db: AsyncSession, now: datetime) -> dict[str, int]:
    """Przekazanie pracy w sprawach, w których minęła 18:00 ostatniego dnia."""

    candidate_ids = list(
        await db.scalars(
            select(LifecycleCase.id)
            .where(
                LifecycleCase.kind == "offboarding",
                LifecycleCase.status == "active",
                LifecycleCase.handover_executed_at.is_(None),
                LifecycleCase.last_working_day <= now.date(),
            )
            .order_by(LifecycleCase.id)
        )
    )
    counts = {"handover_cases": 0, "handover_done": 0, "handover_failed": 0}
    for case_id in candidate_ids:
        try:
            case = await _lock_case(db, case_id)
            if (
                case is None
                or case.status != "active"
                or case.handover_executed_at is not None
                or not handover_due(case.last_working_day, now)
            ):
                await db.rollback()
                continue
            outcome = await execute_handover(db, case, now=now)
            await db.commit()
            counts["handover_cases"] += 1
            counts["handover_done"] += outcome.done
            counts["handover_failed"] += outcome.failed
        except Exception:  # noqa: BLE001 — jedna sprawa nie blokuje reszty
            await db.rollback()
            logger.exception("hr_lifecycle handover failed case=%s", case_id)
            counts["handover_failed"] += 1
    return counts


async def _deactivation_candidates(
    db: AsyncSession, today: date
) -> list[tuple[int, Optional[datetime]]]:
    return list(
        (
            await db.execute(
                select(LifecycleCase.id, LifecycleCase.handover_executed_at)
                .where(
                    LifecycleCase.kind == "offboarding",
                    LifecycleCase.status == "active",
                    LifecycleCase.account_closed_at.is_(None),
                    LifecycleCase.deactivate_on <= today,
                )
                .order_by(LifecycleCase.id)
            )
        ).all()
    )


async def due_deactivation_ids(db: AsyncSession, today: date) -> list[int]:
    """Sprawy gotowe do wyłączenia konta: termin nadszedł, praca przeszła."""

    return [
        case_id
        for case_id, handed_over in await _deactivation_candidates(db, today)
        if handed_over is not None
    ]


async def _alert_mass_exit(db: AsyncSession, now: datetime, planned: int) -> int:
    """Dzwonek do Kadr i adminów: bezpiecznik wstrzymał wyłączenie kont.

    Raz dziennie (rezerwacja ``hr_lifecycle_mass_exit``), a nie co kwadrans —
    pętla trafia na ten sam stan przy każdym przebiegu, dopóki Kadry nie
    wyłączą kont po jednym.
    """

    alert_id = await job_runs.claim(
        db, MASS_EXIT_ALERT_KIND, now.date().isoformat(), now
    )
    if alert_id is None:
        return 0
    recipients = set(await pool_member_ids(db, "people_admin")) | set(
        await pool_member_ids(db, "it")
    )
    sent = await notify_each(
        db,
        sorted(recipients),
        title=f"Wyłączenie kont wstrzymane: {planned} odejść naraz",
        message=(
            f"Automat nie wyłącza więcej niż {MAX_DEACTIVATIONS_PER_RUN} "
            "kont w jednym przebiegu. Sprawdź odejścia i wyłącz konta "
            "po jednym („Wyłącz konto teraz”)."
        ),
        ntype=NotificationType.hr_lifecycle_task,
        link="/people",
        related_entity_type="hr_job_run",
        related_entity_id=alert_id,
        log_tag="hr_lifecycle",
    )
    await job_runs.finish(
        db, alert_id, status="done", counts={"planned": planned, "notified": sent}
    )
    return sent


async def run_deactivations(db: AsyncSession, now: datetime) -> dict[str, Any]:
    """Wyłączenie kont w dniu po ostatnim dniu pracy (z bezpiecznikami)."""

    today = now.date()
    candidates = await _deactivation_candidates(db, today)
    due = [case_id for case_id, handed_over in candidates if handed_over is not None]
    counts: dict[str, Any] = {"deactivation_due": len(due)}
    waiting = len(candidates) - len(due)
    if waiting:
        # Konto bez przekazanej pracy zostaje włączone — inaczej rekrutacje
        # zostałyby przy wyłączonym koncie (Kadry dostały dzwonek o porażce).
        counts["deactivation_waiting_handover"] = waiting
    if mass_exit_suspected(len(due)):
        # Zero zmian: Kadry wyłączają konta po jednym („Wyłącz konto teraz”).
        logger.warning(
            "hr_lifecycle refused: %s deactivations due in one run — nothing changed",
            len(due),
        )
        counts["deactivation_error"] = MASS_EXIT_ERROR
        counts["mass_exit_notified"] = await _alert_mass_exit(db, now, len(due))
        return counts
    results: dict[str, int] = {}
    for case_id in due:
        try:
            case = await _lock_case(db, case_id)
            if (
                case is None
                or case.account_closed_at is not None
                or case.status != "active"
            ):
                await db.rollback()
                continue
            result = await close_account(db, case, now=now)
            await lifecycle_integrations(db, case, "exit_executed")
            await db.commit()
            results[result] = results.get(result, 0) + 1
        except Exception:  # noqa: BLE001
            await db.rollback()
            logger.exception("hr_lifecycle deactivation failed case=%s", case_id)
            results["failed"] = results.get("failed", 0) + 1
    counts.update({f"account_{key}": value for key, value in results.items()})
    return counts


async def run_reminders(db: AsyncSession, now: datetime) -> dict[str, Any]:
    """Poniedziałkowe przypomnienia o zaległych zadaniach (raz w tygodniu)."""

    today = now.date()
    if today.weekday() != 0:
        return {"reminders": "not_monday"}
    run_id = await job_runs.claim(db, REMINDERS_KIND, week_key(today), now)
    if run_id is None:
        return {"reminders": "claimed"}
    sent = 0
    try:
        rows = (
            await db.execute(
                select(LifecycleTask, LifecycleCase)
                .join(LifecycleCase, LifecycleCase.id == LifecycleTask.case_id)
                .where(
                    LifecycleCase.status == "active",
                    LifecycleTask.status == "open",
                    LifecycleTask.due_date < today,
                    LifecycleTask.due_date
                    >= today - timedelta(days=REMINDER_GRACE_DAYS),
                )
                .order_by(LifecycleCase.id, LifecycleTask.due_date)
            )
        ).all()
        by_case: dict[int, tuple[LifecycleCase, list[LifecycleTask]]] = {}
        for task, case in rows:
            by_case.setdefault(case.id, (case, []))[1].append(task)
        for case, tasks in by_case.values():
            for task in tasks:
                # Zadanie przełożonego bez przełożonego → Kadry (pula), a każde
                # inne bez osoby zostaje w swojej puli.
                if task.assignee_kind == "manager" and task.assignee_user_id is None:
                    task.assignee_user_id = case.manager_user_id
            sent += await notify_assignees(
                db, case, tasks, actor_id=None, reminder=True
            )
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        logger.exception("hr_lifecycle reminders failed")
        await job_runs.finish(
            db, run_id, status="failed", counts={"sent": sent}, error=type(exc).__name__
        )
        return {"reminders": "failed"}
    await job_runs.finish(db, run_id, status="done", counts={"sent": sent})
    return {"reminders_sent": sent}


async def run_once(
    db: AsyncSession, *, now: Optional[datetime] = None
) -> dict[str, Any]:
    """Jeden przebieg pętli (idempotentny; ``now`` w czasie Warszawy)."""

    modules = await hr_modules.load_modules(db)
    if not modules.get(HrModule.lifecycle):
        return {"status": "disabled"}
    now = now or local_now()
    run_id = await job_runs.claim(db, JOB_KIND, slot_key(now), now)
    if run_id is None:
        return {"skipped": "claimed"}
    counts: dict[str, Any] = {}
    try:
        counts.update(await run_handovers(db, now))
        counts.update(await run_deactivations(db, now))
        counts.update(await run_reminders(db, now))
    except Exception as exc:  # noqa: BLE001 — stempel błędu, pętla żyje dalej
        await db.rollback()
        logger.exception("hr_lifecycle run failed")
        await job_runs.finish(
            db, run_id, status="failed", counts=counts, error=type(exc).__name__
        )
        return {**counts, "error": type(exc).__name__}
    # Odmowa przy masowym odejściu to porażka przebiegu (sonda `hr_jobs`),
    # a nie cichy sukces — konta osób, które odeszły, zostały włączone.
    refused = counts.get("deactivation_error")
    await job_runs.finish(
        db,
        run_id,
        status="failed" if refused else "done",
        counts=counts,
        error=refused,
    )
    return counts


__all__ = ["HANDOVER_HOUR", "INTERVAL_SECONDS", "run_once"]
