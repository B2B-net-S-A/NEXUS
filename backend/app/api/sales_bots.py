"""Sprzedaż → Leady → Boty: cztery boty, ich stan, biegi i wstrzymanie.

Prefiks ``/api/sales/bots``. Odczyt „Sprzedaż: podgląd”, wstrzymanie
i wznowienie tylko administrator (bot pracuje dla całej Sprzedaży).
Pauza leży w ``app_settings`` (``services/sales/bots.py``) i zatrzymuje nowe
biegi w ``signals.start_run``; flagi środowiskowe zostają głównym włącznikiem.

Bez ``from __future__ import annotations`` (slowapi #579). Logi: numery i liczby.
→ docs/claude/sprzedaz/cztery-boty-sprzedazy.md
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.sales_gates import SalesEditUser, SalesViewUser, is_admin
from app.core.database import get_db
from app.core.rate_limit import limiter, user_or_ip_key
from app.models.sales import SalesSignalRun
from app.models.user import User
from app.services.sales import bot_tasks, bots, signals

logger = logging.getLogger(__name__)

router = APIRouter()

WINDOW = timedelta(days=7)
ADMIN_DETAIL = "Boty wstrzymuje i wznawia administrator."
UNKNOWN_DETAIL = "Nie ma takiego bota."


class BotOut(BaseModel):
    key: str
    name: str
    kinds: list[str]
    #: ``own`` — własna rutyna, ``shared`` — wspólny webhook, ``none`` — brak.
    webhook: str
    #: Flaga środowiskowa rodzajów bota (główny włącznik).
    enabled: bool
    paused: bool
    runs_7d: int
    received_7d: int
    failed_7d: int
    last_received_at: Optional[datetime] = None


class BotsOut(BaseModel):
    items: list[BotOut]
    can_pause: bool


def _kinds(bot: str) -> list[str]:
    if bot == bots.COGNISM:
        return ["people"]
    return [kind for kind, owner in bots.KIND_BOT.items() if owner == bot]


def _enabled(bot: str) -> bool:
    """Główny włącznik bota z flag środowiskowych (pauza to osobny stan)."""

    if bot == bots.COGNISM:
        return signals.people_enabled()
    if bot in (bots.LEADS, bots.RESEARCH):
        # Sygnały i punkty chodzą na starej fladze, reszta na fladze zadań.
        return signals.enabled() or bot_tasks.enabled()
    return bot_tasks.enabled()


def _webhook(bot: str) -> str:
    if all(bots.own_webhook(bot)):
        return "own"
    return "shared" if all(bots.webhook(bot)) else "none"


async def _state(db: AsyncSession, *, can_pause: bool) -> BotsOut:
    since = datetime.now(timezone.utc) - WINDOW
    rows = await db.execute(
        select(
            SalesSignalRun.kind,
            SalesSignalRun.request,
            SalesSignalRun.status,
            func.count(),
            func.max(SalesSignalRun.received_at),
        )
        .where(SalesSignalRun.started_at >= since)
        .group_by(SalesSignalRun.kind, SalesSignalRun.request, SalesSignalRun.status)
    )
    stats: dict[str, dict] = {
        bot: {"runs": 0, "received": 0, "failed": 0, "last": None} for bot in bots.BOTS
    }
    for kind, request, run_status, count, last in rows.all():
        bot = bots.bot_for(kind, request)
        if bot is None:
            continue
        item = stats[bot]
        item["runs"] += count
        if run_status == "received":
            item["received"] += count
            if last and (item["last"] is None or last > item["last"]):
                item["last"] = last
        elif run_status in ("failed", "expired"):
            item["failed"] += count
    paused = await bots.paused_bots(db)
    return BotsOut(
        can_pause=can_pause,
        items=[
            BotOut(
                key=bot,
                name=bots.NAMES[bot],
                kinds=_kinds(bot),
                webhook=_webhook(bot),
                enabled=_enabled(bot),
                paused=bot in paused,
                runs_7d=stats[bot]["runs"],
                received_7d=stats[bot]["received"],
                failed_7d=stats[bot]["failed"],
                last_received_at=stats[bot]["last"],
            )
            for bot in bots.BOTS
        ],
    )


@router.get("", response_model=BotsOut)
@limiter.limit("120/minute", key_func=user_or_ip_key)
async def list_bots(
    request: Request,
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
) -> BotsOut:
    return await _state(db, can_pause=is_admin(current_user))


async def _set(db: AsyncSession, bot: str, paused: bool, user: User) -> BotsOut:
    if not is_admin(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=ADMIN_DETAIL)
    if bot not in bots.BOTS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=UNKNOWN_DETAIL)
    await bots.set_paused(db, bot, paused, user_id=user.id)
    await db.commit()
    logger.info("sales_bots bot=%s paused=%s", bot, paused)
    return await _state(db, can_pause=True)


@router.post("/{bot}/pause", response_model=BotsOut)
@limiter.limit("30/minute", key_func=user_or_ip_key)
async def pause_bot(
    bot: str,
    request: Request,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> BotsOut:
    return await _set(db, bot, True, current_user)


@router.post("/{bot}/resume", response_model=BotsOut)
@limiter.limit("30/minute", key_func=user_or_ip_key)
async def resume_bot(
    bot: str,
    request: Request,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> BotsOut:
    return await _set(db, bot, False, current_user)
