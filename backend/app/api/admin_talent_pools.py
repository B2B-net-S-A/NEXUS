"""Admin endpoints for the Talent-Pool membership backfill.

- ``POST /api/admin/talent-pools/backfill`` — replay all (or recent) ``cv_sent``
  stages into pool memberships in the background (returns immediately). This is
  the autonomous way to populate the curated role pools from the
  "CV wysłane do klienta" history; idempotent, so safe to re-run.
- ``GET  /api/admin/talent-pools/backfill/status`` — running flag + last-run
  stats (counts + top pools filled).

RBAC: admin only (``AdminUser`` dependency).
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import AdminUser
from app.services.talent_pool_backfill import (
    backfill_is_running,
    last_backfill_stats,
    run_membership_backfill,
)

router = APIRouter()


@router.post("/backfill")
async def trigger_talent_pool_backfill(
    _admin: AdminUser,
    since: Optional[str] = Query(
        None,
        description="ISO-8601 datetime — replay only cv_sent stages on/after this moment.",
    ),
    limit: Optional[int] = Query(
        None, ge=1, description="Cap rows processed (smoke runs)."
    ),
) -> dict[str, Any]:
    """Kick the membership backfill in the background. Admin only."""
    if backfill_is_running():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A talent-pool backfill is already running",
        )
    since_dt: Optional[datetime] = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"since must be ISO-8601 datetime, got {since!r}",
            ) from exc

    # Fire-and-forget: replaying ~19k rows takes minutes. Progress is observable
    # via GET /backfill/status.
    asyncio.create_task(
        run_membership_backfill(since=since_dt, commit=True, limit=limit)
    )
    return {"status": "started", "since": since, "limit": limit}


@router.get("/backfill/status")
async def talent_pool_backfill_status(_admin: AdminUser) -> dict[str, Any]:
    """Running flag + stats from the last completed backfill run (in-memory)."""
    return {
        "running": backfill_is_running(),
        "last_run": last_backfill_stats(),
    }
