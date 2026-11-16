"""Pętla radaru przepisów (kontener worker), co 15 minut.

* wygasza biegi bez raportu (ostrzeżenie w logu),
* codziennie od 5:30 (kalendarz firmy) startuje Grok Zbieracza, raz dziennie;
  nieudany start liczy się tylko przez godzinę, potem ponowienie,
* dokańcza bramkę dla pozycji ``pending`` starszych niż 20 minut (np. po
  restarcie w trakcie sprawdzania w API Sejmu),
* ponawia Analityka, gdy pozycje po bramce czekają, a żaden bieg nie trwa
  (ostatni start starszy niż godzina),
* od 6:30 raz dziennie przelicza sondy otwartych zmian.

Wyłącznik ``LAW_RADAR_ENABLED`` sprawdzany przed pętlą. Na stagingu pętla stoi
(``STAGING_BLOCKED_TASKS``). Logi: same liczby.
→ docs/claude/przepisy/radar-przepisow-dwa-boty.md
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time, timedelta, timezone
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_date, local_day_start_utc, local_now
from app.models.law_radar import LawRadarItem, LawRadarRun
from app.services import loop_heartbeat
from app.services.law_radar import analyze, collect, flow, gate, probes, runs

logger = logging.getLogger(__name__)

TICK_SECONDS = 15 * 60
COLLECT_AT = time(5, 30)
PROBES_AT = time(6, 30)
RETRY_FAILED_AFTER = timedelta(hours=1)
ANALYZE_RETRY_AFTER = timedelta(hours=1)
PENDING_STALE_AFTER = timedelta(minutes=20)


async def last_start(
    db: AsyncSession, kind: str, *, now: datetime
) -> Optional[datetime]:
    """Ostatni start biegu; nieudany liczy się tylko przez godzinę, potem ponowienie."""

    return await db.scalar(
        select(func.max(LawRadarRun.started_at)).where(
            LawRadarRun.kind == kind,
            or_(
                LawRadarRun.status != "failed",
                LawRadarRun.started_at >= now - RETRY_FAILED_AFTER,
            ),
        )
    )


def _at(local: datetime, moment: time) -> datetime:
    """Godzina ``moment`` dnia ``local`` w kalendarzu firmy, jako UTC."""

    return local.replace(
        hour=moment.hour, minute=moment.minute, second=0, microsecond=0
    ).astimezone(timezone.utc)


def collect_due(local: datetime, last: Optional[datetime]) -> bool:
    """Od 5:30 czasu firmy, jeśli dziś (od północy) nie startował żaden bieg."""

    if local.time() < COLLECT_AT:
        return False
    return last is None or last < local_day_start_utc(local.date())


def probes_due(local: datetime, oldest: Optional[datetime]) -> bool:
    """Od 6:30, gdy któryś wynik otwartej zmiany jest sprzed dzisiejszej 6:30."""

    if local.time() < PROBES_AT or oldest is None:
        return False
    return oldest < _at(local, PROBES_AT)


async def _stale_pending(db: AsyncSession, *, now: datetime) -> bool:
    found = await db.scalar(
        select(LawRadarItem.id)
        .where(
            LawRadarItem.gate == "pending",
            LawRadarItem.created_at < now - PENDING_STALE_AFTER,
        )
        .limit(1)
    )
    return found is not None


async def tick(db: AsyncSession, *, now: datetime, local: datetime) -> dict[str, int]:
    done = {
        "expired": await runs.expire_runs(db, now=now),
        "collect": 0,
        "gated": 0,
        "analyze": 0,
        "probes": 0,
    }
    if collect_due(local, await last_start(db, collect.KIND, now=now)):
        run = await flow.start_collect(db, now=now)
        done["collect"] = int(run is not None and run.status in ("started", "received"))
    if await _stale_pending(db, now=now):
        checked = await gate.verify_pending(db)
        done["gated"] = sum(
            checked[key] for key in ("verified", "unverified", "rejected")
        )
    last_analyze = await last_start(db, analyze.KIND, now=now)
    if last_analyze is None or last_analyze <= now - ANALYZE_RETRY_AFTER:
        run = await flow.start_analyze(db, now=now)
        done["analyze"] = int(run is not None and run.status in ("started", "received"))
    if probes_due(local, await probes.oldest_open_computed_at(db)):
        done["probes"] = await probes.recompute(
            db, await probes.open_change_ids(db), now=now, today=business_date(now)
        )
    return done


async def law_radar_loop() -> None:
    if not runs.enabled():
        logger.info("law_radar_loop disabled")
        return
    for kind in ("collect", "analyze"):
        if not runs.configured(kind):
            logger.warning(
                "law_radar_loop enabled without %s webhook configuration", kind
            )
    beat = loop_heartbeat.register("law_radar", max_silence_seconds=3 * TICK_SECONDS)
    while True:
        beat.tick()
        try:
            async with AsyncSessionLocal() as db:
                done = await tick(db, now=datetime.now(timezone.utc), local=local_now())
            if any(done.values()):
                logger.info(
                    "law_radar tick expired=%d collect=%d gated=%d analyze=%d probes=%d",
                    done["expired"],
                    done["collect"],
                    done["gated"],
                    done["analyze"],
                    done["probes"],
                )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("law_radar_loop iteration failed")
        await asyncio.sleep(TICK_SECONDS)
