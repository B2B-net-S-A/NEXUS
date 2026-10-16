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
from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy import func, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today, local_now
from app.models.hr_ops import HrJobRun
from app.services.hr import modules as hr_modules
from app.services.hr.bonus_rules import load_rules
from app.services.hr.league_bonuses import sync_league
from app.services.hr.placement_bonuses import sync_placements

logger = logging.getLogger(__name__)

JOB_KIND = "hr_bonus_proposals"
INTERVAL_SECONDS = 6 * 60 * 60
STALE_CLAIM = timedelta(hours=1)


async def _claim(db: AsyncSession, period_key: str) -> Optional[int]:
    row = await db.execute(
        text(
            "INSERT INTO hr_job_runs (kind, period_key, status) "
            "VALUES (:kind, :period, 'claimed') "
            "ON CONFLICT (kind, period_key) DO UPDATE "
            "SET status = 'claimed', claimed_at = now(), error = NULL, finished_at = NULL "
            "WHERE hr_job_runs.status = 'failed' "
            "OR (hr_job_runs.status = 'claimed' AND hr_job_runs.claimed_at < :stale) "
            "RETURNING id"
        ),
        {"kind": JOB_KIND, "period": period_key, "stale": local_now() - STALE_CLAIM},
    )
    claimed = row.scalar_one_or_none()
    await db.commit()
    return claimed


async def _finish(
    db: AsyncSession,
    run_id: int,
    *,
    status: str,
    counts: dict[str, Any],
    error: Optional[str] = None,
) -> None:
    await db.execute(
        update(HrJobRun)
        .where(HrJobRun.id == run_id)
        .values(status=status, counts=counts, error=error, finished_at=func.now())
    )
    await db.commit()


async def refresh_proposals(db: AsyncSession, *, today: date) -> dict[str, Any]:
    """Placementy + Liga (bez rezerwacji i bez commita) — także z przycisku Płac."""

    rules = await load_rules(db)
    placements = await sync_placements(db, today=today, rules=rules)
    league = await sync_league(db, today=today, rules=rules)
    return {
        **{f"placement_{k}": v for k, v in placements.items()},
        **{f"league_{k}": v for k, v in league.items()},
    }


async def run_once(db: AsyncSession, *, today: Optional[date] = None) -> dict[str, Any]:
    """Jeden dzienny przebieg (idempotentny w obrębie dnia)."""

    modules = await hr_modules.load_modules(db)
    if not modules.get("payroll"):
        return {"skipped": "module_off"}
    today = today or business_today()
    run_id = await _claim(db, today.isoformat())
    if run_id is None:
        return {"skipped": "claimed"}
    try:
        counts = await refresh_proposals(db, today=today)
        await db.commit()
    except Exception as exc:  # noqa: BLE001 — stempel błędu, pętla żyje dalej
        await db.rollback()
        logger.exception("hr_bonus_proposals run failed")
        await _finish(db, run_id, status="failed", counts={}, error=type(exc).__name__)
        return {"error": type(exc).__name__}
    await _finish(db, run_id, status="done", counts=counts)
    return counts


__all__ = ["INTERVAL_SECONDS", "JOB_KIND", "refresh_proposals", "run_once"]
