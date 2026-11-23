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

Klient NEXUSA (``client_gate``) nie idzie ani po haczyk, ani po teczkę: jego popyt
prowadzi Delivery Lead (decyzja Artura 22.10.2026).

Haczyki idą w małych paczkach, z ograniczonym ponowieniem pojedynczych firm.
Teczki zachowują osobny rozkład. → docs/claude/sprzedaz/sygnaly-grok-bot.md
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import local_day_start_utc
from app.models.sales import SalesCompanyBriefing, SalesSignalRun
from app.services.sales import calling, client_gate, my_day
from app.services.sales.bot_tasks import call_hook

START_HOUR = 16
PREP_FRESH = timedelta(days=3)
MAX_PREP_FIRMS = 40
HOOK_BATCH_SIZE = 5
HOOK_ATTEMPTS_PER_COMPANY = 2
RETRY_FAILED_AFTER = timedelta(hours=1)
# status, czas startu, tryby firm, raport zapisany przez import
RunState = tuple[str, datetime, dict[str, Any], dict[str, Any]]


def due_day(today: date) -> date:
    """Następny dzień roboczy (piątek → poniedziałek, przed świętem dzień po nim)."""

    return calling.next_business_day(today)


def prep_window(today: date) -> tuple[datetime, datetime]:
    """Od jutrzejszej północy do końca następnego dnia roboczego, w UTC (domknięty)."""

    start = local_day_start_utc(today + timedelta(days=1))
    end = local_day_start_utc(due_day(today) + timedelta(days=1))
    return start, end - timedelta(microseconds=1)


def opened_today(
    runs: Iterable[RunState],
    mode: str,
    *,
    now: datetime,
) -> bool:
    """Czy dzisiejszy bieg tego trybu już ruszył (nieudany tylko przez godzinę)."""

    return any(
        mode in (modes or {}).values()
        and (status != "failed" or started_at >= now - RETRY_FAILED_AFTER)
        for status, started_at, modes, _report in runs
    )


async def lock_hook_starts(db: AsyncSession) -> None:
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": "sales_research_call_hook_start"},
    )


async def runs_since(db: AsyncSession, since: datetime) -> list[RunState]:
    rows = await db.execute(
        select(
            SalesSignalRun.status,
            SalesSignalRun.started_at,
            SalesSignalRun.modes,
            SalesSignalRun.report,
        ).where(SalesSignalRun.kind == "briefing", SalesSignalRun.started_at >= since)
    )
    return [
        (status, started_at, modes, report)
        for status, started_at, modes, report in rows
    ]


def next_hook_batch(
    candidates: Iterable[int], runs: Iterable[RunState], *, now: datetime
) -> list[int]:
    """Zachowaj dzienny limit firm i najpierw wyślij te bez żadnej próby."""
    attempts: Counter[int] = Counter()
    covered: set[int] = set()
    cooling_down: set[int] = set()
    for status, started_at, modes, report in runs:
        refs = {
            int(ref)
            for ref, mode in (modes or {}).items()
            if mode == call_hook.CALL_HOOK
        }
        if not refs:
            continue
        if status == "started":
            return []
        attempts.update(refs)
        if status == "received":
            covered.update(
                refs.intersection((report or {}).get("hook_covered_company_ids") or ())
            )
        elif status == "failed" and started_at > now - RETRY_FAILED_AFTER:
            cooling_down.update(refs)

    retry = []
    new = []
    remaining = max(0, call_hook.MAX_HOOK_FIRMS - len(attempts))
    for company_id in candidates:
        if company_id in covered or company_id in cooling_down:
            continue
        if not attempts[company_id] and len(new) < remaining:
            new.append(company_id)
        elif 0 < attempts[company_id] < HOOK_ATTEMPTS_PER_COMPANY:
            retry.append(company_id)
    return (new + retry)[:HOOK_BATCH_SIZE]


async def hook_company_ids(
    db: AsyncSession, *, now: datetime, today: date
) -> list[int]:
    fresh = await call_hook.fresh_company_ids(db, now=now)
    due = await calling.companies_due_by(
        db, due_day(today), today, exclude=fresh, limit=call_hook.MAX_HOOK_FIRMS
    )
    return await client_gate.without_clients(db, due)


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
    return (
        await client_gate.without_clients(db, [cid for cid in ids if cid not in fresh])
    )[:MAX_PREP_FIRMS]
