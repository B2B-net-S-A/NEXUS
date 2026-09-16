"""Admin: ręczne uruchomienie importu JJIT i jego stan.

``POST /api/admin/integrations/jjit/run`` startuje run w tle (zwraca od razu);
``GET /api/admin/integrations/jjit/status`` mówi, czy coś trwa i jak jest
skonfigurowany job (enabled / dry_run / pora). Tylko admin — to ten sam
poziom, co ``POST /api/admin/traffit/sync``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, select

from app.api.deps import AdminUser
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.integration_run import IntegrationRun
from app.services.integration_runs import run_to_dict
from app.services.integrations.jjit import runner

logger = logging.getLogger(__name__)
router = APIRouter()

_manual_task: Optional[asyncio.Task] = None


class JjitRunRequest(BaseModel):
    dry_run: Optional[bool] = Field(
        None, description="Domyślnie JJIT_DRY_RUN z configu."
    )
    since: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    states: Optional[list[str]] = Field(None, description="np. ['published','expired']")
    limit: int = Field(0, ge=0, le=5000, description="0 = bez limitu")


@router.post("/jjit/run", status_code=status.HTTP_202_ACCEPTED)
async def trigger_jjit_run(payload: JjitRunRequest, admin: AdminUser) -> dict:
    global _manual_task
    if _manual_task is not None and not _manual_task.done():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Run JJIT już trwa"
        )
    if runner._RUN_LOCK.locked():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Run JJIT już trwa (harmonogram)",
        )
    logger.info(
        "jjit manual run by user_id=%s dry_run=%s since=%s",
        admin.id,
        payload.dry_run,
        payload.since,
    )
    _manual_task = asyncio.create_task(
        runner.run_once(
            dry_run=payload.dry_run,
            since=payload.since,
            states=payload.states,
            limit=payload.limit,
        )
    )
    return {
        "started": True,
        "dry_run": bool(settings.JJIT_DRY_RUN)
        if payload.dry_run is None
        else payload.dry_run,
    }


@router.get("/jjit/status")
async def jjit_status(_: AdminUser) -> dict:
    async with AsyncSessionLocal() as db:
        last = await db.scalar(
            select(IntegrationRun)
            .where(IntegrationRun.source == "jjit")
            .order_by(desc(IntegrationRun.started_at))
            .limit(1)
        )
    return {
        "enabled": bool(settings.JJIT_ENABLED),
        "dry_run": bool(settings.JJIT_DRY_RUN),
        "run_at_local": f"{settings.JJIT_RUN_HOUR_LOCAL:02d}:{settings.JJIT_RUN_MINUTE_LOCAL:02d}",
        "running": runner._RUN_LOCK.locked()
        or (_manual_task is not None and not _manual_task.done()),
        "match_min_score": float(settings.JJIT_MATCH_MIN_SCORE),
        "require_must_match": bool(settings.JJIT_REQUIRE_MUST_MATCH),
        "last_run": run_to_dict(last) if last else None,
    }
