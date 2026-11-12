"""Pętla kanału sygnałów z bota researchu (kontener worker).

Co 15 minut: wygasza biegi bez raportu (ostrzeżenie w logu), w poniedziałek od 7:00
startuje tygodniowy przegląd sygnałów firm pilota, a co godzinę zbiera firmy do
punktów do rozmowy (nowe leady i szanse, w poniedziałek od 7:30 także odświeżenie
przed krokiem). W poniedziałek od 8:00, przy włączonym ``SALES_BOT_TASKS_ENABLED``,
także mapy decydentów kont Fabryk IT z mapą poniżej 3 osób (rodzaj ``people``). Wyłącznik ``SALES_SIGNALS_ENABLED``, bez adresu bota pętla stoi.
Logi są publiczne: same liczby. → docs/claude/sprzedaz/sygnaly-grok-bot.md
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.scheduling import local_now
from app.models.sales import SalesSignalRun
from app.services import loop_heartbeat
from app.services.sales import bot_tasks
from app.services.sales import signal_targets as targets
from app.services.sales import signals
from app.services.sales.bot_tasks import people

logger = logging.getLogger(__name__)

TICK_SECONDS = 15 * 60
BRIEFING_EVERY = timedelta(hours=1)
RETRY_FAILED_AFTER = timedelta(hours=1)
SIGNALS_HOUR = 7
#: Mapy decydentów po sygnałach, żeby dwa duże biegi nie startowały w jednym ticku.
PEOPLE_HOUR = 8
REFRESH_HOUR, REFRESH_MINUTE = 7, 30


async def _last_start(db: AsyncSession, kind: str, *, now: datetime) -> datetime | None:
    """Ostatni start biegu; nieudany liczy się tylko przez godzinę, potem ponowienie."""

    return await db.scalar(
        select(func.max(SalesSignalRun.started_at)).where(
            SalesSignalRun.kind == kind,
            or_(
                SalesSignalRun.status != "failed",
                SalesSignalRun.started_at >= now - RETRY_FAILED_AFTER,
            ),
        )
    )


async def _last_weekly_people(db: AsyncSession, *, now: datetime) -> datetime | None:
    """Ostatni tygodniowy bieg map osób; bieg z przycisku ma zlecającego i się nie liczy."""

    return await db.scalar(
        select(func.max(SalesSignalRun.started_at)).where(
            SalesSignalRun.kind == "people",
            SalesSignalRun.requested_by_user_id.is_(None),
            or_(
                SalesSignalRun.status != "failed",
                SalesSignalRun.started_at >= now - RETRY_FAILED_AFTER,
            ),
        )
    )


def _started(run: object) -> bool:
    return getattr(run, "status", None) == "started"


def _monday_start(local: datetime) -> datetime:
    monday = (local - timedelta(days=local.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return monday.astimezone(timezone.utc)


async def tick(db: AsyncSession, *, now: datetime, local: datetime) -> dict[str, int]:
    done = {
        "expired": await signals.expire_runs(db, now=now),
        "signals": 0,
        "briefing": 0,
        "people": 0,
    }
    is_monday = local.weekday() == 0
    if is_monday and local.hour >= SIGNALS_HOUR:
        last = await _last_start(db, "signals", now=now)
        if last is None or last < _monday_start(local):
            ids = await targets.pilot_company_ids(db)
            if ids and _started(await signals.start_run(db, "signals", ids, now=now)):
                done["signals"] = len(ids)

    # Mapy decydentów: konta Fabryk IT z mapą poniżej 3 osób, tylko z flagą zadań.
    if is_monday and local.hour >= PEOPLE_HOUR and bot_tasks.enabled():
        last = await _last_weekly_people(db, now=now)
        if last is None or last < _monday_start(local):
            ids = await targets.people_company_ids(
                db, now=now, limit=people.MAX_WEEKLY_FIRMS
            )
            if ids and _started(await signals.start_run(db, "people", ids, now=now)):
                done["people"] = len(ids)

    last = await _last_start(db, "briefing", now=now)
    if last is None or last <= now - BRIEFING_EVERY:
        skip = await targets.recently_sent(db, now=now)
        candidates = await targets.new_company_ids(db, now=now, exclude=skip)
        if is_monday and (local.hour, local.minute) >= (REFRESH_HOUR, REFRESH_MINUTE):
            candidates += await targets.refresh_company_ids(db, now=now)
        ids = targets.pick(candidates, skip=skip, limit=targets.MAX_BRIEFING_FIRMS)
        if ids:
            modes = await targets.modes_for(db, ids, now=now)
            run = await signals.start_run(db, "briefing", ids, now=now, modes=modes)
            if _started(run):
                done["briefing"] = len(ids)
    return done


async def sales_signals_loop() -> None:
    if not signals.enabled():
        logger.info("sales_signals_loop disabled")
        return
    if not signals.configured():
        logger.warning("sales_signals_loop enabled without GROK_BOT_WEBHOOK_URL/KEY")
        return
    beat = loop_heartbeat.register(
        "sales_signals", max_silence_seconds=3 * TICK_SECONDS
    )
    while True:
        beat.tick()
        try:
            async with AsyncSessionLocal() as db:
                done = await tick(db, now=datetime.now(timezone.utc), local=local_now())
            if any(done.values()):
                logger.info(
                    "sales_signals tick expired=%d signals=%d briefing=%d people=%d",
                    done["expired"],
                    done["signals"],
                    done["briefing"],
                    done["people"],
                )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("sales_signals_loop iteration failed")
        await asyncio.sleep(TICK_SECONDS)
