"""Ustawienia → Historia zdarzeń — odczyt dziennika krytycznych operacji.

Widoczne wyłącznie dla ról Admin i Finanse (``FinanceModuleUser``). Tylko
odczyt: wpisów nie da się edytować ani kasować przez API — dziennik, który
można wyczyścić, przestaje być dowodem.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Literal, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import FinanceModuleUser
from app.core.database import get_db
from app.core.scheduling import DEFAULT_TZ
from app.models.critical_event import CriticalEvent
from app.services.critical_events import (
    ENTITY_TYPE_LABELS,
    EVENT_TYPE_LABELS,
    OUTCOME_LABELS,
)

router = APIRouter()


class CriticalEventOut(BaseModel):
    id: int
    occurred_at: datetime
    event_type: str
    event_label: str
    entity_type: str
    entity_type_label: str
    entity_id: Optional[int] = None
    entity_label: Optional[str] = None
    outcome: Literal["executed", "blocked"]
    outcome_label: str
    reason_code: Optional[str] = None
    reason: Optional[str] = None
    actor_user_id: Optional[int] = None
    actor_name: Optional[str] = None
    actor_email: Optional[str] = None
    client_id: Optional[int] = None
    client_name: Optional[str] = None
    details: dict[str, Any]


class CriticalEventList(BaseModel):
    items: list[CriticalEventOut]
    total: int
    limit: int
    offset: int
    entity_types: dict[str, str]
    event_types: dict[str, str]
    outcomes: dict[str, str]


def _day_start(day: date) -> datetime:
    """Początek dnia w strefie firmy — filtr dat mówi o dniach w Polsce."""

    return datetime.combine(day, time.min, tzinfo=ZoneInfo(DEFAULT_TZ)).astimezone(
        timezone.utc
    )


def _serialize(row: CriticalEvent) -> CriticalEventOut:
    return CriticalEventOut(
        id=row.id,
        occurred_at=row.occurred_at,
        event_type=row.event_type,
        event_label=EVENT_TYPE_LABELS.get(row.event_type, row.event_type),
        entity_type=row.entity_type,
        entity_type_label=ENTITY_TYPE_LABELS.get(row.entity_type, row.entity_type),
        entity_id=row.entity_id,
        entity_label=row.entity_label,
        outcome=row.outcome,  # type: ignore[arg-type]
        outcome_label=OUTCOME_LABELS.get(row.outcome, row.outcome),
        reason_code=row.reason_code,
        reason=row.reason,
        actor_user_id=row.actor_user_id,
        actor_name=row.actor_name,
        actor_email=row.actor_email,
        client_id=row.client_id,
        client_name=row.client_name,
        details=dict(row.details or {}),
    )


@router.get("/event-history", response_model=CriticalEventList)
async def list_event_history(
    _reader: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
    entity_type: Optional[str] = Query(None, max_length=32),
    outcome: Optional[Literal["executed", "blocked"]] = Query(None),
    q: Optional[str] = Query(None, max_length=200),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    filters = []
    if entity_type:
        filters.append(CriticalEvent.entity_type == entity_type)
    if outcome:
        filters.append(CriticalEvent.outcome == outcome)
    if date_from:
        filters.append(CriticalEvent.occurred_at >= _day_start(date_from))
    if date_to:
        filters.append(
            CriticalEvent.occurred_at < _day_start(date_to + timedelta(days=1))
        )
    needle = (q or "").strip()
    if needle:
        escaped = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        filters.append(
            or_(
                CriticalEvent.entity_label.ilike(pattern, escape="\\"),
                CriticalEvent.client_name.ilike(pattern, escape="\\"),
                CriticalEvent.actor_name.ilike(pattern, escape="\\"),
                CriticalEvent.actor_email.ilike(pattern, escape="\\"),
                CriticalEvent.reason.ilike(pattern, escape="\\"),
            )
        )

    total = await db.scalar(select(func.count(CriticalEvent.id)).where(*filters))
    rows = (
        (
            await db.execute(
                select(CriticalEvent)
                .where(*filters)
                .order_by(CriticalEvent.occurred_at.desc(), CriticalEvent.id.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return CriticalEventList(
        items=[_serialize(row) for row in rows],
        total=int(total or 0),
        limit=limit,
        offset=offset,
        entity_types=ENTITY_TYPE_LABELS,
        event_types=EVENT_TYPE_LABELS,
        outcomes=OUTCOME_LABELS,
    )
