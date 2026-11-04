"""Zakładka „Źródła” w Insights: tabela, ogłoszenia, linki po osobach, osoby za liczbą.

Bramka jak ``GET /api/reports/sources`` (``CandidatePIIAccess``), bo to te same dane
kandydatów. Wyniki linków po osobach jak „Kto co przyniósł” (``LinkResultsManager``).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.periods import Period, PeriodError, resolve_period
from app.api.candidate_access import CandidatePIIAccess
from app.api.deps import LinkResultsManager
from app.api.section_access import INSIGHTS_SECTION_DEPENDENCIES
from app.core.cache import cache_get, cache_set, cache_single_flight
from app.core.database import get_db
from app.models.user import User, UserRole
from app.services import competition_history, insights_sources

router = APIRouter(dependencies=INSIGHTS_SECTION_DEPENDENCIES)

_PERIOD_PATTERN = "^(day|week|month|quarter|year|custom)$"
_LINK_MANAGERS = (UserRole.admin, UserRole.head_of_recruitment, UserRole.delivery_lead)
_CACHE_SECONDS = 300


def _window(
    period: str,
    offset: int,
    anchor: Optional[date],
    date_from: Optional[date],
    date_to: Optional[date],
) -> tuple[Period, datetime, datetime]:
    """Okno z paska, przycięte do 12.10.2026 (źródeł wcześniej nie liczymy)."""
    try:
        resolved = resolve_period(
            period, offset=offset, anchor=anchor, date_from=date_from, date_to=date_to
        )
    except PeriodError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return resolved, competition_history.board_start(resolved.start), resolved.end


def _is_link_manager(user: User) -> bool:
    return bool(user.has_any_role(*_LINK_MANAGERS))


@router.get("/sources")
async def insights_sources_table(
    _: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
    period: str = Query("custom", pattern=_PERIOD_PATTERN),
    offset: int = Query(0),
    anchor: Optional[date] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
) -> dict[str, Any]:
    """Portale i strona kariery z tym samym lejkiem."""
    resolved, since, until = _window(period, offset, anchor, date_from, date_to)
    cache_key = f"insights:sources:v2:{resolved.cache_suffix}"
    async with cache_single_flight(cache_key, db=db):
        cached = await cache_get(cache_key)
        if cached is not None:
            return cached
        payload = {
            "period": resolved.as_payload(),
            "counted_from": since.isoformat(),
            **await insights_sources.compute_sources(db, since=since, until=until),
        }
        await cache_set(cache_key, payload, ttl_seconds=_CACHE_SECONDS)
    return payload


@router.get("/sources/offers")
async def insights_sources_offers(
    _: CandidatePIIAccess,
    source: str = Query(..., pattern="^(pracuj|jjit)$"),
    db: AsyncSession = Depends(get_db),
    period: str = Query("custom", pattern=_PERIOD_PATTERN),
    offset: int = Query(0),
    anchor: Optional[date] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    limit: int = Query(6, ge=1, le=500),
    skip: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Ogłoszenia portalu, od najwięcej zgłoszeń."""
    _, since, until = _window(period, offset, anchor, date_from, date_to)
    return await insights_sources.compute_portal_offers(
        db, source=source, since=since, until=until, limit=limit, offset=skip
    )


@router.get("/sources/links")
async def insights_sources_links(
    _: LinkResultsManager,
    source: str = Query(..., pattern="^(link_general|link_job)$"),
    db: AsyncSession = Depends(get_db),
    period: str = Query("custom", pattern=_PERIOD_PATTERN),
    offset: int = Query(0),
    anchor: Optional[date] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
) -> dict[str, Any]:
    """Link ogólny po rekruterach, linki do rekrutacji po rekrutacjach."""
    _, since, until = _window(period, offset, anchor, date_from, date_to)
    return await insights_sources.compute_link_breakdown(
        db, source=source, since=since, until=until
    )


@router.get("/sources/people")
async def insights_sources_people(
    current_user: CandidatePIIAccess,
    source: str = Query(..., pattern=insights_sources.SOURCE_PATTERN),
    metric: str = Query(..., pattern=insights_sources.METRIC_PATTERN),
    db: AsyncSession = Depends(get_db),
    period: str = Query("custom", pattern=_PERIOD_PATTERN),
    offset: int = Query(0),
    anchor: Optional[date] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    offer: Optional[str] = Query(None, max_length=500),
    owner_id: Optional[int] = Query(None),
    job_id: Optional[int] = Query(None),
    limit: int = Query(40, ge=1, le=5000),
    skip: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Osoby za liczbą z tabeli.

    Filtr po właścicielu linku to cudze wyniki, więc tylko dla ról z
    ``LinkResultsManager``. Pozostali dostają listę bez właściciela linku.
    """
    manager = _is_link_manager(current_user)
    if owner_id is not None and not manager:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Wyniki linków po osobach są niedostępne dla tej roli.",
        )
    _, since, until = _window(period, offset, anchor, date_from, date_to)
    result = await insights_sources.compute_people(
        db,
        source=source,
        metric=metric,
        since=since,
        until=until,
        offer=offer,
        owner_id=owner_id,
        job_id=job_id,
        limit=limit,
        offset=skip,
    )
    if not manager:
        for row in result["rows"]:
            row["link_owner"] = None
    return result
