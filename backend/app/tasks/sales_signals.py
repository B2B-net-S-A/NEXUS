"""Pętla kanału sygnałów z bota researchu (kontener worker).

Co 15 minut: wygasza biegi bez raportu (ostrzeżenie w logu), w poniedziałek od 7:00
startuje tygodniowy przegląd sygnałów firm pilota, a co godzinę zbiera firmy do
punktów do rozmowy (nowe leady i szanse, w poniedziałek od 7:30 także odświeżenie
przed krokiem i przy ofertach „Do decyzji”). Osobny kanał Cognism bierze firmy
z odebranego researchu po dacie uruchomienia. W nocy od 1:00 do 6:00
osobna flaga zadań uruchamia uzupełnianie kart firm bez domeny, a w pierwszy
poniedziałek miesiąca od 7:00 (albo przy pierwszym obrocie po nim) „Warto wrócić”
i „Nowe centra IT” (``SALES_BOT_TASKS_ENABLED``). Z obiema flagami
(``SALES_SIGNALS_ENABLED`` i ``SALES_BOT_TASKS_ENABLED``) w dzień roboczy od 16:00
jeszcze haczyk przed telefonem i teczka przed spotkaniem na następny dzień roboczy
(``services/sales/hook_prep_targets.py``).
Logi są publiczne: same liczby. → docs/claude/sprzedaz/sygnaly-grok-bot.md
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.scheduling import is_business_day, local_now
from app.models.sales import SalesSignalRun
from app.services import loop_heartbeat
from app.services.sales import bot_tasks
from app.services.sales import hook_prep_targets as hook_prep
from app.services.sales import signal_targets as targets
from app.services.sales import signals
from app.services.sales import registry_cards
from app.services.sales.bot_tasks import enrich
from app.services.sales.bot_tasks.call_hook import CALL_HOOK
from app.services.sales.bot_tasks.signals_briefing import MEETING_PREP

logger = logging.getLogger(__name__)

TICK_SECONDS = 15 * 60
BRIEFING_EVERY = timedelta(hours=1)
RETRY_FAILED_AFTER = timedelta(hours=1)
SIGNALS_HOUR = 7
REFRESH_HOUR, REFRESH_MINUTE = 7, 30
#: Rodzaje miesięczne (decyzja Artura 12.11.2026): pierwszy poniedziałek od 7:00.
MONTHLY_KINDS: tuple[str, ...] = ("winback", "discovery")


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


def _started(run: object) -> bool:
    return getattr(run, "status", None) == "started"


def _monday_start(local: datetime) -> datetime:
    monday = (local - timedelta(days=local.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return monday.astimezone(timezone.utc)


async def _start_cognism_people(db: AsyncSession, *, now: datetime) -> int:
    if (
        not signals.people_enabled()
        or not signals.people_configured()
        or settings.SALES_COGNISM_PEOPLE_RESEARCH_SINCE is None
    ):
        return 0
    await targets.lock_people_starts(db)
    if await targets.cognism_run_active(db, now=now):
        return 0
    ids = await targets.cognism_company_ids(db, now=now)
    if not ids:
        return 0
    run = await signals.start_run(
        db, "people", ids, now=now, request=targets.COGNISM_REQUEST
    )
    return len(ids) if run is not None and run.status in ("started", "received") else 0


async def _night_enrich(db: AsyncSession, *, now: datetime, local: datetime) -> int:
    """Nocny bieg uzupełnienia kart; zwraca liczbę wysłanych firm."""

    start, end = enrich.NIGHT_HOURS
    if not bot_tasks.enabled() or not start <= local.hour < end:
        return 0
    night = local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(
        timezone.utc
    )
    # Tylko biegi pętli: przycisk na karcie ma własny limit i nie zjada nocy.
    started, last = (
        await db.execute(
            select(func.count(), func.max(SalesSignalRun.started_at)).where(
                SalesSignalRun.kind == enrich.KIND,
                SalesSignalRun.requested_by_user_id.is_(None),
                SalesSignalRun.started_at >= night,
            )
        )
    ).one()
    if started >= enrich.NIGHT_MAX_RUNS or (
        last is not None and last > now - enrich.NIGHT_EVERY
    ):
        return 0
    ids = await enrich.night_company_ids(db, now=now)
    if ids and _started(await signals.start_run(db, enrich.KIND, ids, now=now)):
        return len(ids)
    return 0


def first_monday_start(local: datetime) -> datetime:
    """Pierwszy poniedziałek miesiąca chwili ``local``, godz. 7:00 czasu firmy."""

    first = local.replace(day=1, hour=SIGNALS_HOUR, minute=0, second=0, microsecond=0)
    return first + timedelta(days=(7 - first.weekday()) % 7)


async def _monthly_ids(db: AsyncSession, kind: str, *, now: datetime) -> list[int]:
    if kind == "winback":
        return await targets.winback_company_ids(db, now=now)
    return []


async def _monthly_runs(
    db: AsyncSession, *, now: datetime, local: datetime, done: dict[str, int]
) -> None:
    """„Warto wrócić” i „Nowe centra IT”: raz w miesiącu, tylko przy flagze zadań."""

    due = first_monday_start(local)
    if not bot_tasks.enabled() or local < due:
        return
    for kind in MONTHLY_KINDS:
        last = await _last_start(db, kind, now=now)
        if last is not None and last >= due.astimezone(timezone.utc):
            continue
        ids = await _monthly_ids(db, kind, now=now)
        if bot_tasks.REGISTRY[kind].needs_firms and not ids:
            continue
        if _started(await signals.start_run(db, kind, ids, now=now)):
            # Bieg bez listy firm liczy się jako jeden.
            done[kind] = len(ids) or 1


async def _legacy_tick(
    db: AsyncSession, *, now: datetime, local: datetime, done: dict[str, int]
) -> None:
    is_monday = local.weekday() == 0
    if is_monday and local.hour >= SIGNALS_HOUR:
        last = await _last_start(db, "signals", now=now)
        if last is None or last < _monday_start(local):
            ids = await targets.pilot_company_ids(db)
            if ids and _started(await signals.start_run(db, "signals", ids, now=now)):
                done["signals"] = len(ids)

    last = await _last_start(db, "briefing", now=now)
    if last is None or last <= now - BRIEFING_EVERY:
        skip = await targets.recently_sent(db, now=now)
        candidates = await targets.new_company_ids(db, now=now, exclude=skip)
        to_decide: list[int] = []
        if is_monday and (local.hour, local.minute) >= (REFRESH_HOUR, REFRESH_MINUTE):
            candidates += await targets.refresh_company_ids(db, now=now)
            to_decide = await targets.to_decide_company_ids(db, now=now)
            candidates += to_decide
        ids = targets.pick(candidates, skip=skip, limit=targets.MAX_BRIEFING_FIRMS)
        if ids:
            modes = await targets.modes_for(db, ids, now=now, ongoing=to_decide)
            run = await signals.start_run(db, "briefing", ids, now=now, modes=modes)
            if _started(run):
                done["briefing"] = len(ids)


async def hooks_and_prep(
    db: AsyncSession, *, now: datetime, local: datetime
) -> dict[str, int]:
    """Dzień roboczy od 16:00: haczyki i teczki na następny dzień roboczy, raz dziennie."""

    done = {CALL_HOOK: 0, MEETING_PREP: 0}
    if (
        not bot_tasks.enabled()
        or not is_business_day(local)
        or local.hour < hook_prep.START_HOUR
    ):
        return done
    since = local.replace(
        hour=hook_prep.START_HOUR, minute=0, second=0, microsecond=0
    ).astimezone(timezone.utc)
    runs = await hook_prep.runs_since(db, since)
    today = local.date()

    if not hook_prep.opened_today(runs, CALL_HOOK, now=now):
        ids = await hook_prep.hook_company_ids(db, now=now, today=today)
        if ids:
            run = await signals.start_run(
                db, "briefing", ids, now=now, modes={cid: CALL_HOOK for cid in ids}
            )
            if _started(run):
                done[CALL_HOOK] = len(ids)

    if not hook_prep.opened_today(runs, MEETING_PREP, now=now):
        ids = await hook_prep.prep_company_ids(db, now=now, today=today)
        if ids:
            talked = await targets.modes_for(db, ids, now=now)
            run = await signals.start_run(
                db,
                "briefing",
                ids,
                now=now,
                modes={cid: MEETING_PREP for cid in ids},
                request={
                    "first_meeting": sorted(
                        cid for cid, mode in talked.items() if mode == "first_call"
                    )
                },
            )
            if _started(run):
                done[MEETING_PREP] = len(ids)
    return done


async def tick(
    db: AsyncSession,
    *,
    now: datetime,
    local: datetime,
    legacy_ready: bool | None = None,
    bot_tasks_ready: bool = True,
) -> dict[str, int]:
    done = {
        "expired": await signals.expire_runs(db, now=now),
        "signals": 0,
        "briefing": 0,
        "people": 0,
        "enrich": 0,
        **{kind: 0 for kind in MONTHLY_KINDS},
        CALL_HOOK: 0,
        MEETING_PREP: 0,
    }
    if bot_tasks_ready:
        done["enrich"] = await _night_enrich(db, now=now, local=local)
        await _monthly_runs(db, now=now, local=local, done=done)
    if legacy_ready is None:
        legacy_ready = signals.enabled()
    if legacy_ready:
        await _legacy_tick(db, now=now, local=local, done=done)
        # Haczyk i teczka to biegi ``briefing``: kanał punktów i flaga zadań naraz.
        if bot_tasks_ready:
            done.update(await hooks_and_prep(db, now=now, local=local))
    done["people"] = await _start_cognism_people(db, now=now)
    return done


async def sales_signals_loop() -> None:
    shared_configured = signals.configured()
    legacy_ready = signals.enabled() and shared_configured
    bot_tasks_ready = bot_tasks.enabled() and shared_configured
    cognism_ready = signals.people_enabled() and signals.people_configured()
    if (signals.enabled() or bot_tasks.enabled()) and not shared_configured:
        logger.warning("sales_signals_loop enabled without GROK_BOT_WEBHOOK_URL/KEY")
    if signals.people_enabled() and not cognism_ready:
        logger.warning(
            "sales_signals_loop enabled without Cognism webhook configuration"
        )
    # Rejestry państwowe (biała lista VAT, KRS) nie potrzebują bota ani webhooka.
    registry_ready = registry_cards.enabled()
    if not (legacy_ready or bot_tasks_ready or cognism_ready or registry_ready):
        logger.info("sales_signals_loop disabled")
        return
    beat = loop_heartbeat.register(
        "sales_signals", max_silence_seconds=3 * TICK_SECONDS
    )
    while True:
        beat.tick()
        try:
            async with AsyncSessionLocal() as db:
                done = await tick(
                    db,
                    now=datetime.now(timezone.utc),
                    local=local_now(),
                    legacy_ready=legacy_ready,
                    bot_tasks_ready=bot_tasks_ready,
                )
            if registry_ready:
                # Noc 1–6: paczka kart do rejestrów (``services/sales/registry_cards.py``),
                # we własnej sesji, bo sprawdzenie zamyka transakcję przed siecią.
                # Liczby loguje samo sprawdzenie.
                async with AsyncSessionLocal() as db:
                    await registry_cards.night_step(
                        db, now=datetime.now(timezone.utc), local=local_now()
                    )
            if any(done.values()):
                logger.info(
                    "sales_signals tick expired=%d signals=%d briefing=%d "
                    "enrich=%d people=%d winback=%d discovery=%d "
                    "call_hook=%d meeting_prep=%d",
                    done["expired"],
                    done["signals"],
                    done["briefing"],
                    done["enrich"],
                    done["people"],
                    done["winback"],
                    done["discovery"],
                    done[CALL_HOOK],
                    done[MEETING_PREP],
                )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("sales_signals_loop iteration failed")
        await asyncio.sleep(TICK_SECONDS)
