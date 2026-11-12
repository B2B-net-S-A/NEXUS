"""Haczyk przed telefonem i teczka przed spotkaniem: które firmy idą do bota.

Raz w dzień roboczy od 16:00 (kalendarz firmy), na następny dzień roboczy:

* **Haczyk** (tryb ``call_hook``): firmy z kolejki dzwonienia, które staną w niej
  w tym dniu (``calling.companies_due_by``: powroty z datą i nowe rekordy aktywnych
  kampanii w kolejności kolejki), najwyżej 40, bez firm z haczykiem młodszym niż
  14 dni.
* **Teczka** (tryb ``meeting_prep``): firmy ze spotkaniami od jutra do końca
  następnego dnia roboczego (w piątek także sobota i niedziela) — spotkania
  z kalendarza osób ze Sprzedaży i terminy z „Umów spotkanie”, bo termin
  przekazania jest aktywnością prowadzącego (``my_day.meeting_company_ids``);
  bez firm z punktami młodszymi niż 3 dni.

Bieg danego trybu startuje raz dziennie; nieudany liczy się tylko przez godzinę,
potem ponowienie (jak przegląd sygnałów). → docs/claude/sprzedaz/sygnaly-grok-bot.md
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import local_day_start_utc
from app.models.sales import SalesCompanyBriefing, SalesSignalRun
from app.services.sales import calling, my_day
from app.services.sales.bot_tasks import call_hook

START_HOUR = 16
PREP_FRESH = timedelta(days=3)
MAX_PREP_FIRMS = 40
RETRY_FAILED_AFTER = timedelta(hours=1)


def due_day(today: date) -> date:
    """Następny dzień roboczy (piątek → poniedziałek, przed świętem dzień po nim)."""

    return calling.next_business_day(today)


def prep_window(today: date) -> tuple[datetime, datetime]:
    """Od jutrzejszej północy do końca następnego dnia roboczego, w UTC (domknięty)."""

    start = local_day_start_utc(today + timedelta(days=1))
    end = local_day_start_utc(due_day(today) + timedelta(days=1))
    return start, end - timedelta(microseconds=1)


def opened_today(
    runs: Iterable[tuple[str, datetime, dict[str, Any]]],
    mode: str,
    *,
    now: datetime,
) -> bool:
    """Czy dzisiejszy bieg tego trybu już ruszył (nieudany tylko przez godzinę)."""

    return any(
        mode in (modes or {}).values()
        and (status != "failed" or started_at >= now - RETRY_FAILED_AFTER)
        for status, started_at, modes in runs
    )


async def runs_since(
    db: AsyncSession, since: datetime
) -> list[tuple[str, datetime, dict[str, Any]]]:
    rows = await db.execute(
        select(
            SalesSignalRun.status, SalesSignalRun.started_at, SalesSignalRun.modes
        ).where(SalesSignalRun.kind == "briefing", SalesSignalRun.started_at >= since)
    )
    return [(status, started_at, modes) for status, started_at, modes in rows.all()]


async def hook_company_ids(
    db: AsyncSession, *, now: datetime, today: date
) -> list[int]:
    fresh = await call_hook.fresh_company_ids(db, now=now)
    return await calling.companies_due_by(
        db, due_day(today), today, exclude=fresh, limit=call_hook.MAX_HOOK_FIRMS
    )


async def prep_company_ids(
    db: AsyncSession, *, now: datetime, today: date
) -> list[int]:
    start, end = prep_window(today)
    ids = await my_day.meeting_company_ids(db, start, end)
    if not ids:
        return []
    fresh = set(
        (
            await db.execute(
                select(SalesCompanyBriefing.company_id).where(
                    SalesCompanyBriefing.company_id.in_(ids),
                    SalesCompanyBriefing.generated_at >= now - PREP_FRESH,
                )
            )
        ).scalars()
    )
    return [cid for cid in ids if cid not in fresh][:MAX_PREP_FIRMS]
