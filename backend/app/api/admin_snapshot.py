"""GET /api/admin/snapshot — single-call ops snapshot for cron + Claude Code.

Combines health + KPI counts + lifespan task status + alembic head + Sentry release
into one JSON response. Replaces 5+ round-trips that ops would otherwise make.

Auth, w kolejności sprawdzania:

1. ``X-API-Key`` — konto serwisowe ze scope'em ``ops:snapshot`` (**preferowane**;
   ma termin ważności, rotację, rewokację i mówi KTO wywołał),
2. ``X-Snapshot-Token`` — legacy: JEDEN globalny sekret z env-a, bez terminu,
   bez rotacji, bez rewokacji i bez atrybucji. Zostaje, bo używa go dziś cron
   i ops-skille; do wycofania, gdy konsumenci przejdą na klucze API,
3. ``Authorization: Bearer`` z JWT admina — przeglądarka / ręczny debug.

Cached 30s to absorb cron + manual reads without DB load.
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

from app.api.deps import get_current_user, require_service_scope
from app.core.cache import cache_get, cache_set
from app.core.config import settings
from app.core.database import AsyncSessionLocal, get_db
from app.models.service_account import ServiceScope
from app.models.user import UserRole
from app.services.dashboard_metrics import compute_kpi_snapshot
from app.services.service_account_auth import API_KEY_HEADER

router = APIRouter()

_CACHE_TTL_SECONDS = 30
_CACHE_KEY = "admin:snapshot"

# Zbudowane raz przy imporcie. ``require_service_scope`` waliduje listę scope'ów
# w momencie wywołania fabryki, więc pusta lista pęka przy starcie aplikacji,
# a nie przy pierwszym requeście na produkcji.
_require_snapshot_scope = require_service_scope(
    ServiceScope.ops_snapshot, allow_admin_jwt=False
)


async def _snapshot_auth(
    request: Request,
    x_snapshot_token: Annotated[str | None, Header(alias="X-Snapshot-Token")] = None,
    bearer: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(HTTPBearer(auto_error=False)),
    ] = None,
    db: AsyncSession = Depends(get_db),
) -> str:
    """Zwraca tryb ("service_account" | "token" | "jwt") albo rzuca 401/403.

    Klucz API jest sprawdzany PIERWSZY, żeby konsument, który już przeszedł na
    konta serwisowe, nie wpadał przypadkiem na legacy token, gdyby oba nagłówki
    poleciały w jednym requeście (tak wygląda migracja w praktyce).
    """
    raw_api_key = request.headers.get(API_KEY_HEADER)
    if raw_api_key:
        # Ta sama zależność co przy Traffit — jedno miejsce, w którym zapada
        # decyzja o kluczu, wliczając blokadę impersonacji i stempel użycia.
        await _require_snapshot_scope(request=request, credentials=None, db=db)
        return "service_account"

    if x_snapshot_token and settings.SNAPSHOT_TOKEN:
        if hmac.compare_digest(x_snapshot_token, settings.SNAPSHOT_TOKEN):
            return "token"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid snapshot token",
        )
    if bearer is not None:
        try:
            # R0 fix (plan 2026-07-16): get_current_user(request, credentials, db)
            # — wcześniejsze wywołanie (bearer, db) mijało się z sygnaturą
            # i ścieżka JWT wywalała się 500 zamiast działać.
            user = await get_current_user(request, bearer, db)
        except HTTPException:
            raise
        if user.has_role(UserRole.admin):
            return "jwt"
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Snapshot requires admin role",
        )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Snapshot requires X-API-Key, X-Snapshot-Token header or admin JWT",
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

    snapshot = {
        "health": {
            "status": "healthy" if db_check == "healthy" else "unhealthy",
            "version": os.environ.get("GIT_SHA", "unknown"),
            "deployedAt": _resolve_deployed_at(),
            "checks": {"database": db_check},
        },
        "kpis": kpis,
        "background_tasks": _background_tasks_status(request),
        "alembic": alembic,
        "sentry_release": os.environ.get("GIT_SHA", "unknown"),
        "generated_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    await cache_set(_CACHE_KEY, snapshot, ttl_seconds=_CACHE_TTL_SECONDS)
    return {**snapshot, "auth_mode": auth_mode, "cached": False}
