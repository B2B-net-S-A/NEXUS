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


# ── Microsoft 365 dla urlopów (krok 7) ─────────────────────────────────────
HR_M365_OUTBOX_INTERVAL_SECONDS = 60
HR_M365_RECONCILE_INTERVAL_SECONDS = 15 * 60


async def hr_m365_outbox_job(db: AsyncSession) -> dict[str, Any] | None:
    from app.services.hr.m365 import executor

    result = await executor.run_once(db)
    return result if result.get("claimed") else None


async def hr_m365_outbox_loop() -> None:
    from app.services.hr.m365.executor import current_mode

    if not loops_enabled("hr_m365_outbox"):
        return
    if current_mode() == "off":
        logger.info("hr_m365_outbox disabled (HR_M365_MODE=off) — pętla nie startuje")
        return
    beat = loop_heartbeat.register(
        "hr_m365_outbox", max_silence_seconds=HR_M365_OUTBOX_INTERVAL_SECONDS + 600
    )
    await run_periodic(
        "hr_m365_outbox", beat, HR_M365_OUTBOX_INTERVAL_SECONDS, hr_m365_outbox_job
    )


async def hr_m365_reconcile_job(db: AsyncSession) -> dict[str, Any] | None:
    """Sam pilnuje 07:00 Warszawy i jednego przebiegu dziennie."""
    from app.services.hr.m365 import reconcile

    result = await reconcile.run_once(db)
    if result.get("skipped") or result == {"mode": "off"}:
        return None
    return result


async def hr_m365_reconcile_loop() -> None:
    from app.services.hr.m365.executor import current_mode

    if not loops_enabled("hr_m365_reconcile"):
        return
    if current_mode() == "off":
        logger.info(
            "hr_m365_reconcile disabled (HR_M365_MODE=off) — pętla nie startuje"
        )
        return
    beat = loop_heartbeat.register(
        "hr_m365_reconcile",
        max_silence_seconds=HR_M365_RECONCILE_INTERVAL_SECONDS + 1800,
    )
    await run_periodic(
        "hr_m365_reconcile",
        beat,
        HR_M365_RECONCILE_INTERVAL_SECONDS,
        hr_m365_reconcile_job,
    )


# ── „Mój miesiąc”: przypomnienie o timesheecie 1.–5. dnia (E2) ─────────────
TIMESHEET_REMINDER_INTERVAL_SECONDS = 3 * 3600


async def timesheet_reminder_job(db: AsyncSession) -> dict[str, Any] | None:
    """Sam pilnuje modułu `time`, okna 1.–5. i wysyłki od 8:00 Warszawy."""
    from app.services.hr import time_reminders

    result = await time_reminders.run_once(db)
    return result if result.get("sent") else None


async def hr_timesheet_reminder_loop() -> None:
    if not loops_enabled("hr_timesheet_reminder"):
        return
    beat = loop_heartbeat.register(
        "hr_timesheet_reminder",
        max_silence_seconds=TIMESHEET_REMINDER_INTERVAL_SECONDS + 1800,
    )
    await run_periodic(
        "hr_timesheet_reminder",
        beat,
        TIMESHEET_REMINDER_INTERVAL_SECONDS,
        timesheet_reminder_job,
    )


# ── Opieka nad konsultantami: przypomnienia o kontaktach (E5) ──────────────
CARE_REMINDERS_INTERVAL_SECONDS = 3600


async def care_reminders_job(db: AsyncSession) -> dict[str, Any] | None:
    """Raz dziennie (rezerwacja w `hr_job_runs`), dzwonki dopiero od 7:00."""
    from app.core.scheduling import local_now
    from app.services.care.reminders import run_once

    if local_now().hour < 7:
        return None
    result = await run_once(db)
    return None if result.get("status") in {"disabled", "skipped"} else result


async def care_reminders_loop() -> None:
    if not loops_enabled("care_reminders"):
        return
    beat = loop_heartbeat.register(
        "care_reminders", max_silence_seconds=CARE_REMINDERS_INTERVAL_SECONDS + 1800
    )
    await run_periodic(
        "care_reminders", beat, CARE_REMINDERS_INTERVAL_SECONDS, care_reminders_job
    )


# ── Wejście i odejście: przekazanie pracy, wyłączenie kont, przypomnienia (E4) ─
LIFECYCLE_INTERVAL_SECONDS = 15 * 60


async def lifecycle_job(db: AsyncSession) -> dict[str, Any] | None:
    from app.services.hr.lifecycle_jobs import run_once

    return await run_once(db)


async def hr_lifecycle_loop() -> None:
    if not loops_enabled("hr_lifecycle"):
        return
    beat = loop_heartbeat.register(
        "hr_lifecycle", max_silence_seconds=LIFECYCLE_INTERVAL_SECONDS + 1800
    )
    await run_periodic("hr_lifecycle", beat, LIFECYCLE_INTERVAL_SECONDS, lifecycle_job)
