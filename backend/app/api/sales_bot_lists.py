"""Sprzedaż → Dzwonienie → Kampanie: Bot Listy (decyzje Artura 13.11.2026).

Prefiks ``/api/sales/bot-lists``. Odczyt briefu i „Co działa”: „Sprzedaż: podgląd”;
zapis briefu i „Zbuduj listę”: „Sprzedaż: edycja”. Budowa zapisuje rekordy od razu,
przez bramki importu listy (``calling_import``), bez przeglądania.

Bez ``from __future__ import annotations`` (slowapi #579). Logi: numery i liczby.
→ docs/claude/sprzedaz/bot-listy-kampanie.md
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.sales_gates import SalesEditUser, SalesViewUser
from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import limiter, user_or_ip_key
from app.models.sales import SalesCallCampaign
from app.models.user import User
from app.services.sales import bot_lists, calling_import

logger = logging.getLogger(__name__)

router = APIRouter()

NOT_FOUND_DETAIL = "Nie ma takiej kampanii albo jest w archiwum."
OFF_DETAIL = "Bot Listy jest wyłączony."
NO_BRIEF_DETAIL = "Najpierw zapisz brief kampanii."
CALLERS_DETAIL = "Wybierz osoby dzwoniące spośród aktywnych kont."


class RateOut(BaseModel):
    key: str
    label: str
    calls: int
    meetings: int
    rate: float
    not_interested: int


class BotListOut(BaseModel):
    enabled: bool
    campaign_id: int
    brief: Optional[bot_lists.Brief] = None
    built_at: Optional[datetime] = None
    by_role: list[RateOut] = []
    by_source: list[RateOut] = []


class BuildOut(BaseModel):
    campaign_id: int
    added: int
    per_caller: dict[int, int]
    skipped: dict[str, int]
    candidates: int


def _enabled() -> bool:
    return bool(settings.SALES_BOT_LISTS_ENABLED)


def _rates(rows: list[bot_lists.RoleRate], *, roles: bool) -> list[RateOut]:
    return [
        RateOut(
            key=row.role,
            label=bot_lists.ROLE_LABELS.get(row.role, row.role) if roles else row.role,
            calls=row.calls,
            meetings=row.meetings,
            rate=round(row.rate, 4),
            not_interested=row.not_interested,
        )
        for row in rows
    ]


async def _campaign(db: AsyncSession, campaign_id: int) -> SalesCallCampaign:
    campaign = await calling_import.campaign_or_none(db, campaign_id)
    if campaign is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
    return campaign


async def _state(db: AsyncSession, campaign_id: int) -> BotListOut:
    campaign = await _campaign(db, campaign_id)
    records = await bot_lists.rated_records(db, campaign.id)
    return BotListOut(
        enabled=_enabled(),
        campaign_id=campaign.id,
        brief=bot_lists.load_brief(campaign),
        built_at=campaign.bot_built_at,
        by_role=_rates(bot_lists.rates_by(records, "role"), roles=True),
        by_source=_rates(bot_lists.rates_by(records, "source"), roles=False),
    )


@router.get("/campaigns/{campaign_id}", response_model=BotListOut)
@limiter.limit("120/minute", key_func=user_or_ip_key)
async def bot_list_state(
    campaign_id: int,
    request: Request,
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
) -> BotListOut:
    return await _state(db, campaign_id)


@router.put("/campaigns/{campaign_id}/brief", response_model=BotListOut)
@limiter.limit("30/minute", key_func=user_or_ip_key)
async def save_brief(
    campaign_id: int,
    request: Request,
    payload: dict,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> BotListOut:
    if not _enabled():
        raise HTTPException(status.HTTP_409_CONFLICT, detail=OFF_DETAIL)
    try:
        brief = bot_lists.Brief.model_validate(payload)
    except ValidationError as exc:
        first = exc.errors()[0] if exc.errors() else {}
        message = str(first.get("msg") or "Nieprawidłowy brief.").removeprefix(
            "Value error, "
        )
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail=message
        ) from exc
    active = set(
        (
            await db.execute(
                select(User.id).where(
                    User.id.in_(brief.caller_ids), User.is_active.is_(True)
                )
            )
        ).scalars()
    )
    if active != set(brief.caller_ids):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=CALLERS_DETAIL)
    campaign = await _campaign(db, campaign_id)
    campaign.bot_brief = brief.model_dump()
    await db.commit()
    logger.info("bot_lists campaign=%s brief saved", campaign_id)
    return await _state(db, campaign_id)


@router.post("/campaigns/{campaign_id}/build", response_model=BuildOut)
@limiter.limit("10/minute", key_func=user_or_ip_key)
async def build_list(
    campaign_id: int,
    request: Request,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> BuildOut:
    if not _enabled():
        raise HTTPException(status.HTTP_409_CONFLICT, detail=OFF_DETAIL)
    campaign = await _campaign(db, campaign_id)
    if bot_lists.load_brief(campaign) is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=NO_BRIEF_DETAIL)
    try:
        result = await bot_lists.build(db, campaign, user_id=current_user.id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await db.commit()
    return BuildOut(
        campaign_id=result.campaign_id,
        added=result.added,
        per_caller=result.per_caller,
        skipped=result.skipped,
        candidates=result.candidates,
    )
