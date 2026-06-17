"""Admin endpoints for the scheduled Traffit → Nexus sync.

- ``POST /api/admin/traffit/sync?mode=delta|full`` — kick a run now (returns
  immediately; the import runs in the background). Used to activate / verify
  without waiting for the 02:00 UTC window.
- ``GET  /api/admin/traffit/sync/status`` — watermark + last-run stats per phase.

RBAC: admin only (``AdminUser`` dependency).
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser
from app.core.config import settings
from app.core.database import get_db
from app.tasks.traffit_sync import run_traffit_sync, sync_is_running

router = APIRouter()


@router.post("/sync")
async def trigger_traffit_sync(
    _admin: AdminUser,
    mode: str = Query("delta", pattern="^(delta|full)$"),
) -> dict[str, Any]:
    """Trigger a Traffit sync run in the background. Admin only."""
    if not settings.TRAFFIT_SYNC_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Traffit sync disabled (TRAFFIT_SYNC_ENABLED=false)",
        )
    if sync_is_running():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A Traffit sync is already running",
        )
    # Fire-and-forget: a full reconcile can take minutes/hours; don't block the
    # request. Progress is observable via GET /sync/status.
    asyncio.create_task(run_traffit_sync(mode))
    return {"status": "started", "mode": mode}


@router.get("/sync/status")
async def traffit_sync_status(
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Current watermark + last-run stats for every phase + scheduler markers."""
    rows = await db.execute(
        text(
            "SELECT phase, last_synced_at, last_run_started_at, "
            "last_run_finished_at, last_status, stats "
            "FROM traffit_sync_state ORDER BY phase"
        )
    )
    states = [
        {
            "phase": r.phase,
            "last_synced_at": r.last_synced_at.isoformat()
            if r.last_synced_at
            else None,
            "last_run_started_at": r.last_run_started_at.isoformat()
            if r.last_run_started_at
            else None,
            "last_run_finished_at": r.last_run_finished_at.isoformat()
            if r.last_run_finished_at
            else None,
            "last_status": r.last_status,
            "stats": r.stats,
        }
        for r in rows
    ]
    return {
        "enabled": settings.TRAFFIT_SYNC_ENABLED,
        "running": sync_is_running(),
        "states": states,
    }
