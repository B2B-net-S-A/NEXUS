"""Zakładka „Wnioski” w Insights (decyzje Artura 04.11.2026).

Widzą ją i decydują admin oraz Head of Recruitment, lustro ``RHYTHM_ROLES`` z frontu.
Osoby za liczbą dodatkowo za ``CandidatePIIAccess``, jak w „Źródłach”. Sprawa z właścicielem
„Administrator” przyjmuje decyzję tylko od admina. Reguła:
``docs/claude/finanse-insights/zakladka-wnioski.md``.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import CandidatePIIAccess
from app.api.deps import require_roles
from app.api.section_access import INSIGHTS_SECTION_DEPENDENCIES
from app.core.cache import cache_get, cache_set, cache_single_flight
from app.core.database import get_db
from app.core.scheduling import business_today
from app.models.insight_decision import InsightDecision
from app.models.user import User, UserRole
from app.services import insights_wnioski as service

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=INSIGHTS_SECTION_DEPENDENCIES)

_CACHE_SECONDS = 300

Viewer = Annotated[User, Depends(require_roles(*service.VIEWER_ROLES))]


class DecisionIn(BaseModel):
    state: Literal["approved", "later", "rejected"]


async def _cached_cases(db: AsyncSession) -> dict[str, Any]:
    today = business_today()
    key = f"insights:wnioski:v1:cases:{today.isoformat()}"
    async with cache_single_flight(key, db=db):
        cached = await cache_get(key)
        if cached is not None:
            return cached
        payload = await service.compute_cases(db, today)
        await cache_set(key, payload, ttl_seconds=_CACHE_SECONDS)
    return payload


@router.get("/wnioski")
async def wnioski(_: Viewer, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Sprawy do decyzji i „Obserwujemy”. Liczby z cache, decyzje zawsze na świeżo."""
    today = business_today()
    computed = await _cached_cases(db)
    latest = await service.latest_decisions(db)
    cases = service.open_cases(computed["cases"], latest, today)
    return {
        "computed_at": computed["computed_at"],
        "counted_from": computed["counted_from"],
        "counted_from_label": computed["counted_from_label"],
        "open_count": len(cases),
        "cases": [service.with_copy(case) for case in cases],
        "watching": computed["watching"],
    }


@router.post("/wnioski/{key}/decision")
async def wnioski_decision(
    current_user: Viewer,
    body: DecisionIn,
    key: str = Path(..., max_length=64),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Zapisuje decyzję i termin. Nie zmienia działania systemu."""
    copy = service.CASE_COPY.get(key)
    if copy is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Nie ma takiej sprawy.")
    if copy.owner_role == UserRole.admin.value and not current_user.has_role(
        UserRole.admin
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="O tej sprawie decyduje Administrator.",
        )
    today = business_today()
    computed = await _cached_cases(db)
    case = next((item for item in computed["cases"] if item["key"] == key), None)
    await service.lock_case(db, key)
    latest = await service.latest_decisions(db)
    if (
        case is None
        or not case["enough"]
        or not service.is_case_open(case["count"], latest.get(key), today)
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Ta sprawa nie czeka już na decyzję. Odśwież widok.",
        )
    return_on, review_on = service.decision_dates(body.state, today)
    db.add(
        InsightDecision(
            insight_key=key,
            state=body.state,
            decided_by_id=current_user.id,
            count_at_decision=case["count"],
            number_at_decision=case["number"],
            return_on=return_on,
            review_on=review_on,
        )
    )
    await db.commit()
    logger.info(
        "insight decision key=%s state=%s user_id=%s", key, body.state, current_user.id
    )
    return {
        "key": key,
        "state": body.state,
        "return_on": return_on.isoformat() if return_on else None,
        "review_on": review_on.isoformat() if review_on else None,
    }


@router.get("/wnioski/history")
async def wnioski_history(
    _: Viewer, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Decyzje i ocena reguł z października, zawsze ze świeżym stanem decyzji."""
    return await service.compute_history(db, business_today())


@router.get("/wnioski/reasons")
async def wnioski_reasons(
    _: Viewer, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Powody odrzuceń przed i po odczytaniu opisów, ogółem i po klientach."""
    today = business_today()
    key = f"insights:wnioski:v1:reasons:{today.isoformat()}"
    async with cache_single_flight(key, db=db):
        cached = await cache_get(key)
        if cached is not None:
            return cached
        payload = await service.compute_reasons(db, today)
        await cache_set(key, payload, ttl_seconds=_CACHE_SECONDS)
    return payload


@router.get(
    "/wnioski/reasons/people",
    dependencies=[Depends(require_roles(*service.VIEWER_ROLES))],
)
async def wnioski_reason_people(
    _: CandidatePIIAccess,
    bucket: str = Query(..., pattern=service.BUCKET_PATTERN),
    basis: str = Query("after", pattern="^(today|after)$"),
    client_id: Optional[int] = Query(None),
    limit: int = Query(40, ge=1, le=500),
    skip: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Odrzucenia za liczbą. Ta sama klasyfikacja co liczba, bez treści opisu."""
    return await service.compute_reason_people(
        db,
        today=business_today(),
        bucket=bucket,
        basis=basis,
        client_id=client_id,
        limit=limit,
        offset=skip,
    )


@router.get("/wnioski/collected")
async def wnioski_collected(
    _: Viewer, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Spis zbieranych sygnałów. Tylko typy, bez miar per osoba."""
    today = business_today()
    key = f"insights:wnioski:v1:collected:{today.isoformat()}"
    async with cache_single_flight(key, db=db):
        cached = await cache_get(key)
        if cached is not None:
            return cached
        payload = await service.compute_collected(db, today)
        await cache_set(key, payload, ttl_seconds=_CACHE_SECONDS)
    return payload
