"""Admin endpoints for one-off candidate data-quality jobs.

- ``POST /api/admin/candidates/backfill-names`` — recover name/email/phone for
  Traffit candidates imported as ``"? ?"`` by parsing their stored CV. Returns
  immediately; the job runs in the background (parsing N CVs through the LLM
  takes minutes). Idempotent + resumable.
- ``GET  /api/admin/candidates/backfill-names/status`` — live progress.

RBAC: admin only (``AdminUser`` dependency).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import AdminUser
from app.core.database import AsyncSessionLocal
from app.services.cv_backfill import backfill_missing_names

logger = logging.getLogger(__name__)

router = APIRouter()

# Single-flight in-memory job state. A backfill is a one-off operation; if the
# container restarts mid-run the job is resumable (it only targets rows still
# marked "?"), so we don't need durable state.
_JOB: dict[str, Any] = {
    "running": False,
    "total": 0,
    "processed": 0,
    "resolved": 0,
    "unresolved": 0,
    "errors": 0,
    "started_at": None,
    "finished_at": None,
    "limit": None,
    "last_error": None,
}


async def _run_backfill(limit: Optional[int], prefer_llm: bool) -> None:
    _JOB.update(
        running=True,
        total=0,
        processed=0,
        resolved=0,
        unresolved=0,
        errors=0,
        started_at=datetime.now(timezone.utc).isoformat(),
        finished_at=None,
        limit=limit,
        last_error=None,
    )
    try:
        async with AsyncSessionLocal() as db:
            await backfill_missing_names(
                db, limit=limit, prefer_llm=prefer_llm, progress=_JOB
            )
    except Exception as e:  # noqa: BLE001 — never crash the background task
        _JOB["last_error"] = repr(e)
        logger.exception("[backfill-names] job crashed")
    finally:
        _JOB["running"] = False
        _JOB["finished_at"] = datetime.now(timezone.utc).isoformat()


@router.post("/backfill-names")
async def trigger_backfill_names(
    _admin: AdminUser,
    limit: Optional[int] = Query(
        default=None,
        ge=1,
        description="Cap the number of candidates processed this run (e.g. for "
        "a small verification batch). Omit to process all remaining '?' rows.",
    ),
    prefer_llm: bool = Query(
        default=True,
        description="Use the LLM CV parser (name+email+phone+skills). When "
        "false, falls back to regex + filename-derived name only.",
    ),
) -> dict[str, Any]:
    """Kick a name-backfill run in the background. Admin only."""
    if _JOB["running"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A backfill run is already in progress",
        )
    asyncio.create_task(_run_backfill(limit, prefer_llm))
    return {"status": "started", "limit": limit, "prefer_llm": prefer_llm}


@router.get("/backfill-names/status")
async def backfill_names_status(_admin: AdminUser) -> dict[str, Any]:
    """Current backfill progress (in-memory; resets on container restart)."""
    return dict(_JOB)
