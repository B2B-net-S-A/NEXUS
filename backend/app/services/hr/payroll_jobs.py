"""Pętla „Premie liczą się same” (``run_once`` raz dziennie).

Jeden przebieg: propozycje z placementów (``placement_bonuses.sync_placements``)
i z Ligi (``league_bonuses.sync_league``). Rezerwacja dnia w ``hr_job_runs``
(``hr_bonus_proposals`` + data w kalendarzu firmy) — restart przy nocnym
wdrożeniu nie liczy dnia drugi raz, a przebieg przerwany (rezerwacja starsza
niż godzina albo ``failed``) można powtórzyć. Liczby przebiegu nie niosą kwot.

Wyłączony moduł ``payroll`` = nic się nie dzieje.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today, local_now
from app.services.hr import job_runs
from app.services.hr import modules as hr_modules
from app.services.hr.bonus_decisions import notify_ready
from app.services.hr.bonus_rules import load_rules
from app.services.hr.league_bonuses import sync_league
from app.services.hr.modules import HrModule
from app.services.hr.placement_bonuses import sync_placements

logger = logging.getLogger(__name__)

JOB_KIND = "hr_bonus_proposals"
INTERVAL_SECONDS = 6 * 60 * 60


async def refresh_proposals(db: AsyncSession, *, today: date) -> dict[str, Any]:
    """Placementy + Liga (bez rezerwacji i bez commita) — także z przycisku Płac."""

    rules = await load_rules(db)
    placements = await sync_placements(db, today=today, rules=rules)
    league = await sync_league(db, today=today, rules=rules)
    ready = await notify_ready(db, today=today)
    return {
        **{f"placement_{k}": v for k, v in placements.items()},
        **{f"league_{k}": v for k, v in league.items()},
        "ready_notified": ready,
    }


async def run_once(db: AsyncSession, *, today: Optional[date] = None) -> dict[str, Any]:
    """Jeden dzienny przebieg (idempotentny w obrębie dnia)."""

    modules = await hr_modules.load_modules(db)
    if not modules.get(HrModule.payroll):
        return {"status": "disabled"}
    today = today or business_today()
    run_id = await job_runs.claim(db, JOB_KIND, today.isoformat(), local_now())
    if run_id is None:
        return {"skipped": "claimed"}
    try:
        counts = await refresh_proposals(db, today=today)
        await db.commit()
    except Exception as exc:  # noqa: BLE001 — stempel błędu, pętla żyje dalej
        await db.rollback()
        # Klasa wyjątku, nie treść: DETAIL Postgresa przy naruszeniu CHECK-a
        # („Failing row contains (…)”) niesie kwoty z wiersza, a ``hide_parameters``
        # go nie ukrywa (wzór R7-X2-9, audyt A2 19.10.2026).
        logger.error("hr_bonus_proposals run failed (%s)", type(exc).__name__)
        await job_runs.finish(
            db, run_id, status="failed", counts={}, error=type(exc).__name__
        )
        return {"error": type(exc).__name__}
    await job_runs.finish(db, run_id, status="done", counts=counts)
    return counts


__all__ = ["INTERVAL_SECONDS", "JOB_KIND", "refresh_proposals", "run_once"]
