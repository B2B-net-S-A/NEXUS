"""Insights → „Przegrane” (decyzje Artura 25.11.2026).

Moduł na comiesięczne spotkanie z Delivery Leadami: fakty o przegranych
rekrutacjach okresu, „Co zdecydowało?”, wnioski ze spotkania (zasady klienta),
pytanie do hiring managera i wnioski AI (F56). Widzą i zapisują admin, Head of
Recruitment i Delivery Lead — lustro ``LOST_REVIEW_ROLES`` na froncie.
Reguła: ``docs/claude/finanse-insights/przegrane-przeglad-z-dl.md``.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.periods import Period, PeriodError, PeriodKind, resolve_period
from app.api.deps import require_roles
from app.api.section_access import (
    INSIGHTS_SECTION_DEPENDENCIES,
    PIPELINE_SECTION_DEPENDENCIES,
)
from app.core.cache import cache_get, cache_set
from app.core.database import get_db
from app.models.job import Job
from app.models.user import User
from app.services import lost_review as service

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=INSIGHTS_SECTION_DEPENDENCIES)
# Zapisy ze spotkania („Co zdecydowało?”, wnioski) to praca na rekrutacjach, jak
# okno zamknięcia: bramka sekcji Rekrutacja, w której Delivery Lead ma zapis.
# W Insights DL ma tylko odczyt, więc bramka Insights odmówiłaby mu każdego zapisu.
write_router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)

Viewer = Annotated[User, Depends(require_roles(*service.VIEWER_ROLES))]

_AI_CACHE_SECONDS = 24 * 3600
_MONTHS = (
    "styczeń", "luty", "marzec", "kwiecień", "maj", "czerwiec",
    "lipiec", "sierpień", "wrzesień", "październik", "listopad", "grudzień",
)  # fmt: skip


class WhyIn(BaseModel):
    why: list[str] = Field(default_factory=list, max_length=6)
    source: Optional[Literal["client", "ours", "unknown"]] = None


class LessonIn(BaseModel):
    scope: Literal["job", "client", "all"]
    text: str = Field(min_length=1, max_length=service.LESSON_MAX)
    job_id: Optional[int] = None
    client_id: Optional[int] = None


def _unprocessable(exc: service.LostReviewError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"code": exc.code, "message": exc.message},
    )


def _period(
    period: str,
    offset: int,
    anchor: Optional[date],
    date_from: Optional[date],
    date_to: Optional[date],
) -> Period:
    try:
        return resolve_period(
            period, offset=offset, anchor=anchor, date_from=date_from, date_to=date_to
        )
    except PeriodError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def period_label(p: Period) -> str:
    """Okres słowami, jak w nagłówku ekranu: „listopad 2026”, „IV kwartał 2026”."""
    first = p.start.date()
    last = (p.end - timedelta(seconds=1)).date()
    if p.kind is PeriodKind.month:
        return f"{_MONTHS[first.month - 1]} {first.year}"
    if p.kind is PeriodKind.quarter:
        return (
            f"{('I', 'II', 'III', 'IV')[(first.month - 1) // 3]} kwartał {first.year}"
        )
    if p.kind is PeriodKind.year:
        return f"rok {first.year}"
    return f"{first:%d.%m.%Y}–{last:%d.%m.%Y}"


async def _payload(
    db: AsyncSession, p: Period, dl_id: Optional[int] = None
) -> dict[str, Any]:
    payload = await service.compute(db, start=p.start, end=p.end, dl_id=dl_id)
    payload["period"] = p.as_payload()
    payload["period_label"] = period_label(p)
    return payload


PeriodQuery = Annotated[str, Query(pattern="^(day|week|month|quarter|year|custom)$")]
# Filtr na górze ekranu: cała strona dla jednego DL; 0 = rekrutacje bez DL.
DlQuery = Annotated[Optional[int], Query(ge=0)]


@router.get("/lost-review")
async def lost_review(
    _: Viewer,
    db: AsyncSession = Depends(get_db),
    period: PeriodQuery = "month",
    offset: int = Query(0),
    anchor: Optional[date] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    dl_id: DlQuery = None,
) -> dict[str, Any]:
    """Przegrane i wygrane okresu z faktami, wykresami i wnioskami z reguł.

    Bez cache: wybory „Co zdecydowało?” i wnioski widać od razu po zapisie.
    """
    return await _payload(
        db, _period(period, offset, anchor, date_from, date_to), dl_id
    )


@router.post("/lost-review/ai-summary")
async def lost_review_ai_summary(
    current_user: Viewer,
    db: AsyncSession = Depends(get_db),
    period: PeriodQuery = "month",
    offset: int = Query(0),
    anchor: Optional[date] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    refresh: bool = Query(False),
    dl_id: DlQuery = None,
) -> dict[str, Any]:
    """Wnioski, rady i pytania na spotkanie od modelu (F56).

    Ten sam okres i te same dane = ta sama odpowiedź z cache przez dobę; nowy
    wybór „Co zdecydowało?” albo wniosek zmienia dane, więc liczy się od nowa.
    """
    p = _period(period, offset, anchor, date_from, date_to)
    payload = await _payload(db, p, dl_id)
    key = f"insights:lost-review:ai:v1:{p.cache_suffix}:dl{dl_id}:{service.input_hash(service.model_input(payload))}"
    if not refresh:
        cached = await cache_get(key)
        if cached is not None:
            return {**cached, "cached": True}
    try:
        result = await service.ai_summary(db, payload, user_id=current_user.id)
    except service.LostReviewError as exc:
        raise _unprocessable(exc) from exc
    await cache_set(key, result, ttl_seconds=_AI_CACHE_SECONDS)
    return {**result, "cached": False}


async def _job(db: AsyncSession, job_id: int) -> Job:
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Nie ma takiej rekrutacji.")
    return job


@write_router.put("/lost-review/jobs/{job_id}/why")
async def put_why(
    body: WhyIn,
    current_user: Viewer,
    job_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """„Co zdecydowało?” i „Skąd wiesz?” na spotkaniu — to samo co w oknie zamknięcia."""
    job = await _job(db, job_id)
    try:
        row = await service.save_why(
            db, job, why=body.why, source=body.source, user_id=current_user.id
        )
    except service.LostReviewError as exc:
        raise _unprocessable(exc) from exc
    await db.commit()
    return {
        "job_id": job_id,
        "why": list(row.why) if row else [],
        "source": row.source if row else None,
    }


@router.get("/lost-review/jobs/{job_id}/client-question")
async def client_question(
    current_user: Viewer,
    job_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Szkic pytania do hiring managera — DL wysyła je ze swojej skrzynki."""
    job = await _job(db, job_id)
    facts = (await service.job_facts(db, [job.id]))[job.id]
    return service.client_question(
        title=job.working_title or job.title,
        cvs=facts.cvs,
        interviews=facts.interviews,
        sender=current_user.name,
    )


@write_router.post("/lost-review/lessons", status_code=status.HTTP_201_CREATED)
async def add_lesson(
    body: LessonIn,
    current_user: Viewer,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Wniosek ze spotkania. „ten klient” zostaje zasadą klienta."""
    try:
        lesson = await service.add_lesson(
            db,
            scope=body.scope,
            text_value=body.text,
            job_id=body.job_id,
            client_id=body.client_id,
            user_id=current_user.id,
        )
    except service.LostReviewError as exc:
        raise _unprocessable(exc) from exc
    await db.commit()
    await db.refresh(lesson)
    return {
        "id": lesson.id,
        "scope": lesson.scope,
        "client_id": lesson.client_id,
        "job_id": lesson.job_id,
        "text": lesson.text,
        "created_at": lesson.created_at.isoformat(),
    }


@write_router.delete(
    "/lost-review/lessons/{lesson_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def archive_lesson(
    _: Viewer,
    lesson_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Zasada przestaje obowiązywać — wiersz zostaje w bazie z datą."""
    if not await service.archive_lesson(db, lesson_id):
        raise HTTPException(status_code=404, detail="Nie ma takiego wniosku.")
    await db.commit()


@router.get("/lost-review/client-rules/{client_id}")
async def client_rules(
    _: Viewer,
    client_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Zasady klienta ze spotkań — pasek na stronie jego rekrutacji."""
    return {"rules": await service.client_rules(db, client_id)}
