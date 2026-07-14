"""GET /api/admin/snapshot — single-call ops snapshot for cron + Claude Code.

Combines health + KPI counts + lifespan task status + alembic head + Sentry release
into one JSON response. Replaces 5+ round-trips that ops would otherwise make.

Auth: prefer X-Snapshot-Token header (machine-to-machine); fall back to admin JWT
(browser/manual debug). Cached 30s to absorb cron + manual reads without DB load.
"""

from __future__ import annotations

import asyncio
import hmac
import os
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.cache import cache_get, cache_set
from app.core.config import settings
from app.core.database import AsyncSessionLocal, get_db
from app.models.user import UserRole
from app.services.dashboard_metrics import compute_kpi_snapshot

router = APIRouter()

_CACHE_TTL_SECONDS = 30
_CACHE_KEY = "admin:snapshot"


async def _snapshot_auth(
    x_snapshot_token: Annotated[str | None, Header(alias="X-Snapshot-Token")] = None,
    bearer: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(HTTPBearer(auto_error=False)),
    ] = None,
    db: AsyncSession = Depends(get_db),
) -> str:
    """Token-first auth. Returns mode ("token" | "jwt") on success, raises 401 otherwise."""
    if x_snapshot_token and settings.SNAPSHOT_TOKEN:
        if hmac.compare_digest(x_snapshot_token, settings.SNAPSHOT_TOKEN):
            return "token"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid snapshot token",
        )
    if bearer is not None:
        try:
            user = await get_current_user(bearer, db)
        except HTTPException:
            raise
        if user.role == UserRole.admin:
            return "jwt"
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Snapshot requires admin role",
        )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Snapshot requires X-Snapshot-Token header or admin JWT",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def _check_database() -> str:
    try:
        async with AsyncSessionLocal() as session:
            await asyncio.wait_for(session.execute(text("SELECT 1")), timeout=2.0)
        return "healthy"
    except Exception:
        return "unhealthy"


async def _query_alembic_head() -> dict[str, str | None]:
    try:
        async with AsyncSessionLocal() as session:
            result = await asyncio.wait_for(
                session.execute(text("SELECT version_num FROM alembic_version")),
                timeout=2.0,
            )
            head = result.scalar_one_or_none()
        return {"head": head, "applied_at": None}
    except Exception:
        return {"head": None, "applied_at": None}


async def _background_worker_status() -> dict[str, object]:
    from app.background_worker import get_background_worker_health

    return (await get_background_worker_health()).as_dict()


def _background_tasks_status(request: Request) -> dict[str, Any]:
    """Inspect app.state.background_tasks dict (populated by lifespan)."""
    tasks = getattr(request.app.state, "background_tasks", None)
    if not isinstance(tasks, dict):
        return {"running": 0, "expected": 0, "tasks": []}
    running = [name for name, task in tasks.items() if not task.done()]
    return {
        "running": len(running),
        "expected": len(tasks),
        "tasks": sorted(running),
    }


def _resolve_deployed_at() -> str:
    explicit = os.environ.get("BUILT_AT", "").strip()
    if explicit and explicit != "unknown":
        try:
            datetime.fromisoformat(explicit.replace("Z", "+00:00"))
            return explicit
        except ValueError:
            pass
    return "unknown"


@router.get("/snapshot", summary="Single-call ops snapshot for cron + Claude Code")
async def admin_snapshot(
    request: Request,
    auth_mode: Annotated[str, Depends(_snapshot_auth)],
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    cached = await cache_get(_CACHE_KEY)
    if cached is not None:
        # Stamp authentication mode on every response for traceability without
        # caching the field itself across token vs jwt callers.
        return {**cached, "auth_mode": auth_mode, "cached": True}

    db_check = await _check_database()
    kpis = await compute_kpi_snapshot(db) if db_check == "healthy" else {}
    alembic = await _query_alembic_head()
    background_worker = await _background_worker_status()
    snapshot_ready = db_check == "healthy" and background_worker["status"] == "healthy"

    snapshot = {
        "health": {
            "status": "healthy" if snapshot_ready else "unhealthy",
            "version": os.environ.get("GIT_SHA", "unknown"),
            "deployedAt": _resolve_deployed_at(),
            "checks": {
                "database": db_check,
                "background_worker": background_worker["status"],
            },
        },
        "kpis": kpis,
        "background_tasks": _background_tasks_status(request),
        "background_worker": background_worker,
        "alembic": alembic,
        "sentry_release": os.environ.get("GIT_SHA", "unknown"),
        "generated_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    await cache_set(_CACHE_KEY, snapshot, ttl_seconds=_CACHE_TTL_SECONDS)
    return {**snapshot, "auth_mode": auth_mode, "cached": False}
