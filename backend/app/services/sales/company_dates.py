"""Daty zatrudnienia osób z firmy — uzupełniane per firma (decyzja D3, 26.10.2026).

Przy prawie 90% osób z dużych firm CV wymienia firmę bez dat (lista
pracodawców z Traffita), więc „kto tam pracuje teraz” jest niepewne. Pełny
bieg na całej bazie to ~50 tys. CV; tu uzupełniamy tylko osoby jednej firmy,
gdy handlowiec zakłada przy niej szansę albo kliknie „Uzupełnij daty”.

Bieg idzie w tle tym samym mechanizmem co dopisywanie dat dla CRM
(``experience_backfill.backfill_experience_dates``, kubełek kwoty
``experience_dates_on_demand``) i ma ten sam wyłącznik awaryjny
(``EXPERIENCE_DATES_ON_DEMAND_ENABLED``). Stan zapisujemy w
``sales_companies.dates_backfill``, żeby panel mógł powiedzieć „uzupełniamy
daty 120 osób” i żeby kolejna szansa w tej samej firmie nie płaciła drugi raz.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.core.config import settings
from app.core.tasks import spawn
from app.models.sales import SalesCompany

logger = logging.getLogger(__name__)

#: Sufit osób na jeden bieg — większa firma kończy w kolejnym (przycisk).
MAX_PEOPLE_PER_RUN = 1000
#: Po tylu dniach zakończony bieg można powtórzyć (nowe CV w bazie).
RERUN_AFTER = timedelta(days=30)

_IN_FLIGHT: set[int] = set()

Backfill = Callable[..., Awaitable[dict[str, Any]]]


def _now() -> datetime:
    return datetime.now(timezone.utc)


#: Bieg „running” starszy niż tyle jest porzucony — wieczorne wdrożenie
#: restartuje kontener, zadanie w tle ginie, a stan przy firmie zostaje.
#: 1000 osób to kilkanaście minut, więc 2 h to bezpieczny zapas.
ORPHANED_AFTER = timedelta(hours=2)


def _parse(value: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def is_running(state: Optional[dict[str, Any]], *, now: datetime) -> bool:
    """Bieg naprawdę trwa: status „running” i start nie dawniej niż ``ORPHANED_AFTER``."""

    if not state or state.get("status") != "running":
        return False
    started = _parse(state.get("started_at"))
    return started is not None and now - started < ORPHANED_AFTER


def visible_state(
    state: Optional[dict[str, Any]], *, now: datetime
) -> Optional[dict[str, Any]]:
    """Stan dla panelu: porzucony bieg pokazujemy jako nieudany (z przyciskiem)."""

    if state and state.get("status") == "running" and not is_running(state, now=now):
        return {**state, "status": "failed"}
    return state


def needs_run(state: Optional[dict[str, Any]], *, now: datetime) -> bool:
    """Czy firma potrzebuje biegu: nigdy nie było, padł, porzucony albo stary."""

    if not state:
        return True
    if state.get("status") == "running":
        return not is_running(state, now=now)
    finished = state.get("finished_at")
    if state.get("status") == "done" and finished:
        try:
            when = datetime.fromisoformat(finished)
        except ValueError:
            return True
        return now - when >= RERUN_AFTER
    return True


async def unknown_people(db, company: SalesCompany) -> list[int]:
    """Id osób, których CV wymienia firmę bez żadnej daty."""

    from app.api.integrations_companies import (
        CompanyPeopleRequest,
        lookup_company_people,
    )

    names = [n for n in dict.fromkeys((company.name, company.legal_name)) if n]
    result = await lookup_company_people(
        db,
        CompanyPeopleRequest(names=names[:10], nip=company.nip, limit=1),
        limit=MAX_PEOPLE_PER_RUN,
    )
    return [p.candidate_id for p in result.people if p.relationship == "unknown"]


async def run_company_dates(
    company_id: int,
    *,
    session_factory=None,
    backfill: Optional[Backfill] = None,
) -> dict[str, Any]:
    """Jeden bieg dla firmy: lista osób → uzupełnienie dat → stan przy firmie."""

    from app.models.ai_feature import AIFeatureKey

    if session_factory is None:
        from app.core.database import AsyncSessionLocal as session_factory
    if backfill is None:
        from app.services.experience_backfill import (
            backfill_experience_dates as backfill,
        )

    async with session_factory() as db:
        company = await db.get(SalesCompany, company_id)
        if company is None:
            return {"status": "missing"}
        ids = await unknown_people(db, company)
        company.dates_backfill = {
            "status": "running",
            "total": len(ids),
            "started_at": _now().isoformat(),
        }
        await db.commit()

    stats: dict[str, Any] = {}
    status = "done"
    try:
        if ids:
            async with session_factory() as db:
                stats = await backfill(
                    db,
                    candidate_ids=ids,
                    feature_key=AIFeatureKey.experience_dates_on_demand,
                )
    except Exception:  # noqa: BLE001 — bieg w tle nie może ubić procesu
        logger.exception("[sales-dates] firma %s: bieg padł", company_id)
        status = "failed"
    reason = stats.get("stopped_reason")
    if reason not in (None, "done"):
        status = "partial"
    state = {
        "status": status,
        "total": len(ids),
        "updated": int(stats.get("updated") or 0),
        "processed": int(stats.get("processed") or 0),
        "stopped_reason": reason,
        "finished_at": _now().isoformat(),
    }
    async with session_factory() as db:
        company = await db.get(SalesCompany, company_id)
        if company is not None:
            company.dates_backfill = state
            await db.commit()
    logger.info(
        "[sales-dates] firma %s: %s z %s osób, status %s",
        company_id,
        state["updated"],
        state["total"],
        status,
    )
    return state


def schedule_company_dates(company_id: int) -> bool:
    """Zakolejkuj bieg w tle. Nie rzuca — to dodatek, nie warunek zapisu szansy."""

    if not settings.EXPERIENCE_DATES_ON_DEMAND_ENABLED or company_id in _IN_FLIGHT:
        return False
    _IN_FLIGHT.add(company_id)

    async def _run() -> None:
        try:
            await run_company_dates(company_id)
        finally:
            _IN_FLIGHT.discard(company_id)

    try:
        spawn(_run(), f"sales company dates {company_id}")
    except RuntimeError:
        _IN_FLIGHT.discard(company_id)
        return False
    return True
