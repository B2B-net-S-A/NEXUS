"""Sprzedaż: odczyt kanału sygnałów (raport ostatniego biegu, punkty do rozmowy).

Prefiks ``/api/sales/signals``, „Sprzedaż: podgląd”. Z wyłączoną flagą
``SALES_SIGNALS_ENABLED`` odpowiedzi mówią ``enabled: false`` i ekran nic nie pokazuje;
raport „Warto wrócić” i „Nowe centra IT” zależy od ``SALES_BOT_TASKS_ENABLED``.
Haczyk przed telefonem (``call_hook``) dochodzi do punktów firmy tylko przy włączonym
``SALES_BOT_TASKS_ENABLED``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.sales_gates import SalesViewUser
from app.core.database import get_db
from app.models.sales import SalesCompanyBriefing, SalesSignalRun
from app.services.sales import bot_tasks, signals
from app.services.sales.bot_tasks import call_hook

router = APIRouter()


class RunOut(BaseModel):
    id: int
    kind: str
    status: str
    started_at: datetime
    received_at: Optional[datetime]
    company_count: int
    report: dict[str, Any]
    error: Optional[str]


class LatestRunOut(BaseModel):
    enabled: bool
    reject_reasons: list[str]
    run: Optional[RunOut]


class BriefingOut(BaseModel):
    mode: str
    points: list[dict[str, Any]]
    generated_at: datetime


class CallHookOut(BaseModel):
    sentence: str
    facts: list[dict[str, Any]]
    generated_at: datetime


class CompanyBriefingOut(BaseModel):
    enabled: bool
    briefing: Optional[BriefingOut]
    #: Haczyk do telefonu z kolejki dzwonienia; ``None`` bez haczyka albo bez flagi.
    call_hook: Optional[CallHookOut] = None


@router.get("/latest-run", response_model=LatestRunOut)
async def latest_run(
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
    kind: Literal["signals", "briefing", "winback", "discovery"] = Query(
        default="signals"
    ),
) -> LatestRunOut:
    # „Warto wrócić” i „Nowe centra IT” to zadania bota: ich własna flaga.
    on = signals.enabled() if kind in bot_tasks.LEGACY_KINDS else bot_tasks.enabled()
    if not on:
        return LatestRunOut(enabled=False, reject_reasons=[], run=None)
    run = (
        await db.execute(
            select(SalesSignalRun)
            .where(SalesSignalRun.kind == kind)
            .order_by(SalesSignalRun.started_at.desc(), SalesSignalRun.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return LatestRunOut(
        enabled=True,
        reject_reasons=list(signals.REJECT_REASONS),
        run=None
        if run is None
        else RunOut(
            id=run.id,
            kind=run.kind,
            status=run.status,
            started_at=run.started_at,
            received_at=run.received_at,
            company_count=len(run.company_ids or []),
            report=run.report or {},
            error=run.error,
        ),
    )


@router.get("/briefings/{company_id}", response_model=CompanyBriefingOut)
async def company_briefing(
    company_id: int,
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
) -> CompanyBriefingOut:
    if not signals.enabled():
        return CompanyBriefingOut(enabled=False, briefing=None)
    row = await db.get(SalesCompanyBriefing, company_id)
    hook = await call_hook.latest(db, company_id) if bot_tasks.enabled() else None
    return CompanyBriefingOut(
        enabled=True,
        briefing=None
        if row is None
        else BriefingOut(
            mode=row.mode, points=list(row.points or []), generated_at=row.generated_at
        ),
        call_hook=None
        if hook is None
        else CallHookOut(
            sentence=str(hook.payload.get("sentence") or ""),
            facts=list(hook.payload.get("facts") or []),
            generated_at=hook.updated_at,
        ),
    )
