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
    request: Request,
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


async def _query_analytics_shadow_status() -> dict[str, Any]:
    """Return persisted parity evidence used by the seven-day rollout gate."""

    if settings.ANALYTICS_V1_MODE != "shadow":
        return {
            "mode": settings.ANALYTICS_V1_MODE,
            "quality": "disabled",
            "observed_days": 0,
            "identical": 0,
            "mismatch": 0,
            "unavailable": 0,
            "latest_observed_on": None,
        }
    try:
        async with AsyncSessionLocal() as session:
            result = await asyncio.wait_for(
                session.execute(
                    text(
                        """
                        SELECT
                          count(DISTINCT observed_on) AS observed_days,
                          count(*) FILTER (WHERE status = 'identical') AS identical,
                          count(*) FILTER (WHERE status = 'mismatch') AS mismatch,
                          count(*) FILTER (WHERE status = 'unavailable') AS unavailable,
                          max(observed_on) AS latest_observed_on
                        FROM analytics_shadow_comparisons
                        WHERE observed_on >= (current_date - interval '7 days')
                        """
                    )
                ),
                timeout=2.0,
            )
            row = result.mappings().one()
        mismatches = int(row["mismatch"] or 0)
        unavailable = int(row["unavailable"] or 0)
        observed_days = int(row["observed_days"] or 0)
        return {
            "mode": "shadow",
            "quality": (
                "complete"
                if observed_days >= 7 and mismatches == 0 and unavailable == 0
                else "partial"
            ),
            "observed_days": observed_days,
            "identical": int(row["identical"] or 0),
            "mismatch": mismatches,
            "unavailable": unavailable,
            "latest_observed_on": (
                row["latest_observed_on"].isoformat()
                if row["latest_observed_on"] is not None
                else None
            ),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "mode": "shadow",
            "quality": "unavailable",
            "observed_days": 0,
            "identical": 0,
            "mismatch": 0,
            "unavailable": 0,
            "latest_observed_on": None,
            "warning": f"{type(exc).__name__}: {exc}"[:300],
        }


async def _ai_control_plane_snapshot() -> dict[str, Any]:
    from app.ai.circuit_breaker import circuit_breaker

    try:
        async with AsyncSessionLocal() as session:
            routing = (
                (
                    await session.execute(
                        text(
                            "SELECT registry_version, lock_version, activated_at "
                            "FROM ai_routing_state WHERE id = 1"
                        )
                    )
                )
                .mappings()
                .first()
            )
            usage = (
                (
                    await session.execute(
                        text(
                            "SELECT feature, count(*) AS attempts, "
                            "coalesce(sum(cost_usd), 0) AS cost_usd, "
                            "sum(CASE WHEN status='error' THEN 1 ELSE 0 END) AS errors, "
                            "max(created_at) AS last_call_at "
                            "FROM ai_call_ledger "
                            "WHERE created_at >= now() - interval '30 days' GROUP BY feature"
                        )
                    )
                )
                .mappings()
                .all()
            )
            queue = (
                (
                    await session.execute(
                        text(
                            "SELECT status, count(*) AS count FROM embedding_index_queue "
                            "GROUP BY status"
                        )
                    )
                )
                .mappings()
                .all()
            )
            rollouts = (
                (
                    await session.execute(
                        text(
                            "SELECT feature, baseline_registry, target_registry, stage, "
                            "percentage, status, lock_version, stage_started_at, "
                            "rollback_reason, rollback_available_until, monitoring_until, "
                            "next_regression_at FROM ai_rollout_state ORDER BY feature"
                        )
                    )
                )
                .mappings()
                .all()
            )
        return {
            "routing": dict(routing) if routing else {"registry_version": "v1_current"},
            "usage_30d": [dict(row) for row in usage],
            "embedding_queue": {row["status"]: row["count"] for row in queue},
            "rollouts": [dict(row) for row in rollouts],
            "circuit_breakers": circuit_breaker.snapshot(),
        }
    except Exception as exc:  # noqa: BLE001
        return {"status": "unavailable", "error_type": type(exc).__name__}


def _background_tasks_status(request: Request) -> dict[str, Any]:
    """Inspect lifespan jobs without treating a clean exit as a missing task."""
    tasks = getattr(request.app.state, "background_tasks", None)
    if not isinstance(tasks, dict):
        return {
            "running": 0,
            "disabled": 0,
            "completed": 0,
            "crashed": 0,
            "expected": 0,
            "tasks": [],
        }

    enabled_by_config = {
        "kpi_coach_nudger": (
            settings.KPI_COACH_V2_NUDGE_MODE != "off"
            or settings.KPI_COACH_V2_NUDGES_ENABLED
        ),
        "linkedin_sync": bool(
            settings.PROXYCURL_ENABLED and settings.PROXYCURL_API_KEY
        ),
        "microsoft365_sync": bool(
            settings.M365_INTEGRATION_ENABLED and settings.M365_SYNC_LOOP_ENABLED
        ),
        "m365_rematch": bool(
            settings.M365_INTEGRATION_ENABLED and settings.M365_REMATCH_ENABLED
        ),
        "m365_webhook_renewal": bool(
            settings.M365_INTEGRATION_ENABLED and settings.M365_WEBHOOKS_ENABLED
        ),
        "m365_recording_discovery": bool(
            settings.M365_INTEGRATION_ENABLED
            and settings.M365_RECORDING_DISCOVERY_ENABLED
        ),
        "marketplace_sweeper": settings.MARKETPLACE_ENABLED,
        "autenti_sweeper": settings.AUTENTI_ENABLED,
        "signing_sweeper": settings.SIGNING_ENABLED,
        "cloudtalk_sync": settings.CLOUDTALK_ENABLED,
        "traffit_sync": settings.TRAFFIT_SYNC_ENABLED,
        "analytics_shadow": settings.ANALYTICS_V1_MODE == "shadow",
        "embedding_index_sync": settings.EMBEDDING_INDEX_SYNC_ENABLED,
    }

    rows: list[dict[str, str | None]] = []
    counts = {"running": 0, "disabled": 0, "completed": 0, "crashed": 0}
    for name, task in sorted(tasks.items()):
        error: str | None = None
        if enabled_by_config.get(name) is False:
            task_status = "disabled"
        elif not task.done():
            task_status = "running"
        elif task.cancelled():
            task_status = "completed"
        else:
            exception = task.exception()
            if exception is None:
                task_status = "completed"
            else:
                task_status = "crashed"
                error = f"{type(exception).__name__}: {exception}"[:300]
        counts[task_status] += 1
        rows.append({"name": name, "status": task_status, "error": error})

    return {
        **counts,
        "expected": len(tasks),
        "tasks": rows,
        "running_tasks": [r["name"] for r in rows if r["status"] == "running"],
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
    analytics_shadow = await _query_analytics_shadow_status()
    ai_control_plane = (
        await _ai_control_plane_snapshot() if db_check == "healthy" else {}
    )

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
        "analytics_shadow": analytics_shadow,
        "ai": ai_control_plane,
        "sentry_release": os.environ.get("GIT_SHA", "unknown"),
        "generated_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    await cache_set(_CACHE_KEY, snapshot, ttl_seconds=_CACHE_TTL_SECONDS)
    return {**snapshot, "auth_mode": auth_mode, "cached": False}
