"""
Admin-only endpoints for importing data from external sources.

Phase 7a.5 — POST /api/admin/import-talent-radar starts a background coroutine
that pulls 40k+ candidates from the Supabase talent-radar project and upserts
them into Nexus. A second step copies pgvector embeddings into Qdrant so we
don't burn Voyage credits re-embedding.

Progress is tracked in an in-process dict keyed by task_id. Not durable across
restarts — that's OK for a one-shot migration + manual re-run.

RBAC: AdminUser only.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel

from app.api.deps import AdminUser
from app.core.database import AsyncSessionLocal
from app.services.talent_radar_embedding_copier import (
    CopyProgress,
    TalentRadarEmbeddingCopier,
)
from app.services.talent_radar_importer import ImportProgress, TalentRadarImporter

logger = logging.getLogger(__name__)
router = APIRouter()


# ── In-process task registry ─────────────────────────────────────────────────

_TASKS: dict[str, dict] = {}


def _new_task(kind: str) -> str:
    tid = uuid.uuid4().hex[:12]
    _TASKS[tid] = {
        "task_id": tid,
        "kind": kind,
        "status": "queued",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "progress": {},
        "error": None,
    }
    return tid


def _set(tid: str, **kwargs) -> None:
    if tid in _TASKS:
        _TASKS[tid].update(kwargs)


# ── Schemas ──────────────────────────────────────────────────────────────────


class ImportTalentRadarRequest(BaseModel):
    dry_run: bool = False
    batch_size: int = 500
    # Optional override — by default we read from env
    source_dsn: Optional[str] = None
    # If True, after candidate import, run pgvector → Qdrant copy
    copy_embeddings: bool = True


class TaskStatus(BaseModel):
    task_id: str
    kind: str
    status: str  # queued | running | done | error
    started_at: str
    finished_at: Optional[str] = None
    progress: dict
    error: Optional[str] = None


# ── Background runner ───────────────────────────────────────────────────────


def _get_source_dsn(override: Optional[str]) -> str:
    """
    Resolve the talent-radar source DSN.
    Priority: explicit override > TALENT_RADAR_DSN env > build from Supabase envs.
    """
    if override:
        return override
    dsn = os.environ.get("TALENT_RADAR_DSN")
    if dsn:
        return dsn
    raise HTTPException(
        status_code=422,
        detail=(
            "TALENT_RADAR_DSN not set. Configure a Postgres DSN for the "
            "Supabase talent-radar project in Coolify env variables."
        ),
    )


async def _run_import(tid: str, req: ImportTalentRadarRequest) -> None:
    """Run candidate import + optional embedding copy, updating _TASKS inline."""
    _set(tid, status="running")
    try:
        dsn = _get_source_dsn(req.source_dsn)
    except HTTPException as e:
        _set(
            tid,
            status="error",
            error=e.detail,
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
        return

    # Phase A: candidates
    try:
        async with AsyncSessionLocal() as db:  # type: AsyncSession
            importer = TalentRadarImporter(
                source_dsn=dsn,
                target_db=db,
                batch_size=req.batch_size,
                dry_run=req.dry_run,
            )
            progress: ImportProgress = ImportProgress()
            async for progress in importer.run():
                _set(tid, progress={"candidates": progress.as_dict()})
    except Exception as e:  # noqa: BLE001
        logger.exception("talent-radar import failed")
        _set(
            tid,
            status="error",
            error=f"candidate import: {e!r}",
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
        return

    # Phase B: embeddings copy (optional, skipped in dry-run)
    if req.copy_embeddings and not req.dry_run:
        try:
            async with AsyncSessionLocal() as db:
                copier = TalentRadarEmbeddingCopier(
                    source_dsn=dsn, target_db=db, batch_size=200, dry_run=False
                )
                cp: CopyProgress = CopyProgress()
                async for cp in copier.run():
                    existing = _TASKS[tid]["progress"]
                    existing["embeddings"] = cp.as_dict()
                    _set(tid, progress=existing)
        except Exception as e:  # noqa: BLE001
            logger.exception("talent-radar embedding copy failed")
            _set(
                tid,
                status="error",
                error=f"embedding copy: {e!r}",
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            return

    _set(tid, status="done", finished_at=datetime.now(timezone.utc).isoformat())


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.post("/admin/import-talent-radar", response_model=TaskStatus)
async def start_import_talent_radar(
    _admin: AdminUser,
    req: ImportTalentRadarRequest = Body(default_factory=ImportTalentRadarRequest),
):
    """Kick off talent-radar candidate import + embedding copy in the background."""
    # Resolve DSN eagerly to fail fast on misconfig
    _get_source_dsn(req.source_dsn)
    tid = _new_task("import_talent_radar")
    asyncio.create_task(_run_import(tid, req))
    return TaskStatus(**_TASKS[tid])


@router.get("/admin/import-talent-radar/{task_id}", response_model=TaskStatus)
async def get_import_talent_radar_status(task_id: str, _admin: AdminUser):
    task = _TASKS.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskStatus(**task)


@router.get("/admin/import-tasks", response_model=list[TaskStatus])
async def list_import_tasks(_admin: AdminUser):
    """List all in-process import tasks (not persisted across restarts)."""
    return [
        TaskStatus(**t)
        for t in sorted(_TASKS.values(), key=lambda t: t["started_at"], reverse=True)
    ]
