"""Insights → Rekrutacja: „Lejek po etapach” (Pipeline v4, 23.09.2026).

Tablica ma 6 kolumn, ale statystyki dalej liczą każdy etap i każdą odznakę
— logika w `app.services.insights_stage_breakdown`. Ta sama bramka, okres
i cache co lejek (`insights_recruitment.py`); endpoint niczego nie zapisuje.
Powody zakończenia niosą etykiety po polsku, a jednorazowe wpisy ręczne
jadą zbiorczo jako „Inne” z listą treści (decyzja właściciela 23.09.2026) —
przycięte do 80 znaków.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.periods import PeriodError, resolve_period
from app.api.deps import CurrentUser
from app.api.section_access import INSIGHTS_SECTION_DEPENDENCIES
from app.core.cache import cache_get, cache_set, cache_single_flight
from app.core.database import get_db
from app.services.insights_stage_breakdown import compute_stage_breakdown

router = APIRouter(dependencies=INSIGHTS_SECTION_DEPENDENCIES)

CACHE_TTL_SECONDS = 300


@router.get("/stage-breakdown")
async def insights_stage_breakdown(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    period: str = Query("month", pattern="^(day|week|month|quarter|year|custom)$"),
    offset: int = Query(0, description="0 = bieżący okres, -1 = poprzedni zamknięty"),
    anchor: date | None = Query(None, description="dowolny dzień wewnątrz okresu"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
):
    """Każdy etap i odznaka Tablicy: ile osób doszło w oknie i ile stoi teraz."""

    try:
        resolved = resolve_period(
            period,
            offset=offset,
            anchor=anchor,
            date_from=date_from,
            date_to=date_to,
        )
    except PeriodError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    # Klucz niesie okno — inaczej liczby jednego okresu wyszłyby pod etykietą
    # drugiego. „Teraz” jest stanem na dziś, więc żyje tyle co TTL.
    cache_key = f"insights:recruitment:stage-breakdown:v2:{resolved.cache_suffix}"
    async with cache_single_flight(cache_key, db=db):
        cached = await cache_get(cache_key)
        if cached is not None:
            return cached
        result = {
            "period": resolved.as_payload(),
            **await compute_stage_breakdown(db, start=resolved.start, end=resolved.end),
        }
        await cache_set(cache_key, result, ttl_seconds=CACHE_TTL_SECONDS)
        return result
