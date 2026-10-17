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
    if result.get("skipped") or result.get("status") == "disabled":
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


# ── Microsoft 365: termin sekretu i kartoteka z katalogu (krok 7) ──────────
HR_M365_DAILY_INTERVAL_SECONDS = 3600


async def hr_m365_daily_job(db: AsyncSession) -> dict[str, Any] | None:
    """Alarm o terminie sekretu (od 7:00, raz na próg) i odczyt profili (od 6:00, raz
    dziennie). Pętla startuje także przy ``HR_M365_MODE=off`` — rejestracji
    „NEXUS Kadry” używają też Intune i czytnik administracja@."""
    from app.services.hr.m365 import profile_sync, secret_expiry

    result: dict[str, Any] = {}
    try:
        alert = await secret_expiry.run_once(db)
        if alert.get("status") in {"notified", "failed"}:
            result["secret"] = alert
    except Exception:  # noqa: BLE001 — alarm nie blokuje odczytu profili
        logger.exception("hr_m365_daily secret check failed")
        await db.rollback()
    sync = await profile_sync.run_once(db)
    if sync.get("status") != "disabled" and not sync.get("skipped"):
        result["profiles"] = sync
    return result or None


async def hr_m365_daily_loop() -> None:
    if not loops_enabled("hr_m365_daily"):
        return
    beat = loop_heartbeat.register(
        "hr_m365_daily", max_silence_seconds=HR_M365_DAILY_INTERVAL_SECONDS + 1800
    )
    await run_periodic(
        "hr_m365_daily", beat, HR_M365_DAILY_INTERVAL_SECONDS, hr_m365_daily_job
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


# ── Opieka: komunikaty do konsultantów, kolejka 30 maili na minutę (O12) ────
CARE_ANNOUNCEMENTS_INTERVAL_SECONDS = 60


async def care_announcements_job(db: AsyncSession) -> dict[str, Any] | None:
    """Wysyła kolejkę zatwierdzonych komunikatów; wyłączony przełącznik = nic."""
    from app.services.care.announcement_queue import run_once

    result = await run_once(db)
    keys = ("sent", "failed", "uncertain", "deferred", "interrupted")
    return result if any(result.get(key) for key in keys) else None


async def care_announcements_send_loop() -> None:
    if not loops_enabled("care_announcements_send"):
        return
    beat = loop_heartbeat.register(
        "care_announcements_send",
        max_silence_seconds=CARE_ANNOUNCEMENTS_INTERVAL_SECONDS + 600,
    )
    await run_periodic(
        "care_announcements_send",
        beat,
        CARE_ANNOUNCEMENTS_INTERVAL_SECONDS,
        care_announcements_job,
    )


# ── Wejście i odejście: przekazanie pracy, wyłączenie kont, przypomnienia (E4) ─
LIFECYCLE_INTERVAL_SECONDS = 15 * 60


async def lifecycle_job(db: AsyncSession) -> dict[str, Any] | None:
    from app.api.hr_import import purge_expired_uploads
    from app.services.hr.lifecycle_jobs import run_once
    from app.services.hr.student_reminders import student_contribution_reminders

    result = await run_once(db)
    # Paczka importu z Compassa niesie dane osobowe — po 24 h bez zapisu
    # traci surowe dane także wtedy, gdy nikt nie robi kolejnego importu.
    if purged := await purge_expired_uploads(db):
        await db.commit()
        result = {**(result or {}), "import_uploads_expired": purged}
    # Uczeń/student na zleceniu (etap 2, D8): 30 dni przed końcem zwolnienia ze
    # składek Płace i Kadry dostają przypomnienie — raz na osobę i datę
    # (rezerwacja w `hr_job_runs`), więc przebieg co 15 minut jest tani.
    students = await student_contribution_reminders(db)
    if students.get("sent"):
        result = {**(result or {}), "student_contribution_reminders": students["sent"]}
    return result


async def hr_lifecycle_loop() -> None:
    if not loops_enabled("hr_lifecycle"):
        return
    beat = loop_heartbeat.register(
        "hr_lifecycle", max_silence_seconds=LIFECYCLE_INTERVAL_SECONDS + 1800
    )
    await run_periodic("hr_lifecycle", beat, LIFECYCLE_INTERVAL_SECONDS, lifecycle_job)


# ── Kontrakty → Płace, Sprzęt, Sprawy (przegląd startów i końców) ─────────
CONTRACT_HOOKS_INTERVAL_SECONDS = 3600


async def contract_hooks_job(db: AsyncSession) -> dict[str, Any] | None:
    from app.services.hr.contract_hooks import reconcile_upcoming

    result = await reconcile_upcoming(db)
    await db.commit()
    return result if any(result.values()) else None


async def hr_contract_hooks_loop() -> None:
    if not loops_enabled("hr_contract_hooks"):
        return
    beat = loop_heartbeat.register(
        "hr_contract_hooks", max_silence_seconds=CONTRACT_HOOKS_INTERVAL_SECONDS + 1800
    )
    await run_periodic(
        "hr_contract_hooks", beat, CONTRACT_HOOKS_INTERVAL_SECONDS, contract_hooks_job
    )


# ── Płace: propozycje premii z kontraktów i Ligi (E3) ──────────────────────
HR_BONUS_PROPOSALS_INTERVAL_SECONDS = 6 * 3600


async def hr_bonus_proposals_job(db: AsyncSession) -> dict[str, Any] | None:
    from app.services.hr.payroll_jobs import run_once

    result = await run_once(db)
    return None if result.get("status") == "disabled" else result


async def hr_bonus_proposals_loop() -> None:
    if not loops_enabled("hr_bonus_proposals"):
        return
    beat = loop_heartbeat.register(
        "hr_bonus_proposals",
        max_silence_seconds=HR_BONUS_PROPOSALS_INTERVAL_SECONDS + 1800,
    )
    await run_periodic(
        "hr_bonus_proposals",
        beat,
        HR_BONUS_PROPOSALS_INTERVAL_SECONDS,
        hr_bonus_proposals_job,
    )


# ── Sprzęt: przypomnienia „Do zrobienia” (S1–S3) ───────────────────────────
EQUIPMENT_REMINDERS_INTERVAL_SECONDS = 30 * 60


async def equipment_reminders_job(db: AsyncSession) -> dict[str, Any] | None:
    """Wyłączony moduł / przed 7:00 / już dziś = brak efektu."""
    from app.services.equipment.tasks import run_once

    result = await run_once(db)
    return None if result.get("skipped") or result.get("status") else result


async def equipment_reminders_loop() -> None:
    if not loops_enabled("equipment_reminders"):
        return
    beat = loop_heartbeat.register(
        "equipment_reminders",
        max_silence_seconds=EQUIPMENT_REMINDERS_INTERVAL_SECONDS + 1800,
    )
    await run_periodic(
        "equipment_reminders",
        beat,
        EQUIPMENT_REMINDERS_INTERVAL_SECONDS,
        equipment_reminders_job,
    )


# ── Sprzęt ↔ Intune: nocny odczyt urządzeń (etap 4, D9) ────────────────────
EQUIPMENT_INTUNE_INTERVAL_SECONDS = 30 * 60


async def equipment_intune_sync_job(db: AsyncSession) -> dict[str, Any] | None:
    """Sam pilnuje modułu, 05:30 Warszawy i jednego przebiegu dziennie."""
    from app.services.equipment.intune import run_once

    result = await run_once(db)
    return (
        None if result.get("status") in {"disabled", "too_early", "skipped"} else result
    )


async def equipment_intune_sync_loop() -> None:
    from app.services.equipment.intune_graph import current_mode

    if not loops_enabled("equipment_intune_sync"):
        return
    if current_mode() == "off":
        logger.info(
            "equipment_intune_sync disabled (EQUIPMENT_INTUNE_MODE=off) — pętla nie startuje"
        )
        return
    beat = loop_heartbeat.register(
        "equipment_intune_sync",
        max_silence_seconds=EQUIPMENT_INTUNE_INTERVAL_SECONDS + 1800,
    )
    await run_periodic(
        "equipment_intune_sync",
        beat,
        EQUIPMENT_INTUNE_INTERVAL_SECONDS,
        equipment_intune_sync_job,
    )
