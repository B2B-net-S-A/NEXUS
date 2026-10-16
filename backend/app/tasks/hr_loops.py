"""Pętle w tle modułów „Ludzi w NEXUSIE”.

Każda pętla to ten sam przebieg: kill-switch ``HR_LOOPS_ENABLED`` (przed
rejestracją heartbeatu — wyłączona pętla jest ``exited_cleanly``), tick na
początku iteracji, zadanie we własnej sesji, wyjątek logowany bez zabijania
pętli. Zadania same pilnują przełączników modułów (``app_settings``)
i idempotencji (rezerwacje w ``hr_job_runs``), więc częste budzenie jest tanie.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.services import loop_heartbeat

logger = logging.getLogger(__name__)

Job = Callable[[AsyncSession], Awaitable[dict[str, Any] | None]]


def loops_enabled(name: str) -> bool:
    if settings.HR_LOOPS_ENABLED:
        return True
    logger.info("%s disabled (HR_LOOPS_ENABLED=false) — pętla nie startuje", name)
    return False


async def run_periodic(
    name: str, beat: loop_heartbeat.Beat, interval_seconds: float, job: Job
) -> None:
    """Wspólna iteracja. Heartbeat rejestruje każda pętla dosłowną nazwą —
    strażnik ``test_loop_heartbeat`` czyta nazwy z kodu."""
    while True:
        beat.tick()
        try:
            async with AsyncSessionLocal() as db:
                result = await job(db)
            if result:
                logger.info("%s done %s", name, result)
        except Exception:  # noqa: BLE001 — jedno złe przejście nie zabija pętli
            logger.exception("%s failed", name)
        await asyncio.sleep(interval_seconds)


# ── Dni robocze z urlopów NEXUSA (krok 6) ───────────────────────────────────
WORKDAYS_LOOKBACK_MONTHS = 3
WORKDAYS_WEEKS_BACK = 6


async def workdays_job(db: AsyncSession) -> dict[str, Any] | None:
    """Wiersze ``user_workday_periods`` ze źródłem ``nexus``.

    Tylko gdy dostępność liczy się z urlopów NEXUSA — do przełączenia robi to
    synchronizacja z Compassa (``compass_workdays_sync``).
    """
    from app.services.hr.availability_local import local_source_active, refresh_source
    from app.services.insights_workdays import sync_workdays

    await refresh_source(db, force=True)
    if not local_source_active():
        return None
    today = business_today()
    month_to = today.replace(day=1)
    total = month_to.year * 12 + month_to.month - 1 - (WORKDAYS_LOOKBACK_MONTHS - 1)
    month_from = month_to.replace(year=total // 12, month=total % 12 + 1)
    months = await sync_workdays(db, month_from, month_to, "month", source="nexus")
    weeks = await sync_workdays(
        db, today - timedelta(weeks=WORKDAYS_WEEKS_BACK), today, "week", source="nexus"
    )
    return {"months": months.rows_written, "weeks": weeks.rows_written}


WORKDAYS_INTERVAL_SECONDS = 6 * 3600


async def hr_workdays_loop() -> None:
    if not loops_enabled("hr_workdays"):
        return
    beat = loop_heartbeat.register(
        "hr_workdays", max_silence_seconds=WORKDAYS_INTERVAL_SECONDS + 1800
    )
    await run_periodic("hr_workdays", beat, WORKDAYS_INTERVAL_SECONDS, workdays_job)


# ── Sprawy administracja@: czytnik skrzynki (E6) ───────────────────────────
ADMIN_CASES_MAIL_INTERVAL_SECONDS = 5 * 60


async def admin_cases_mail_job(db: AsyncSession) -> dict[str, Any] | None:
    from app.services.admin_cases.mail_ingest import run_once

    result = await run_once(db)
    return None if result.get("status") == "disabled" else result


async def admin_cases_mail_ingest_loop() -> None:
    if not loops_enabled("admin_cases_mail_ingest"):
        return
    beat = loop_heartbeat.register(
        "admin_cases_mail_ingest",
        max_silence_seconds=ADMIN_CASES_MAIL_INTERVAL_SECONDS + 1800,
    )
    await run_periodic(
        "admin_cases_mail_ingest",
        beat,
        ADMIN_CASES_MAIL_INTERVAL_SECONDS,
        admin_cases_mail_job,
    )
