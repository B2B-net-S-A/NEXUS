"""Admin API kanonicznego RecruitmentProcess — shadow mode (M4 plan PR-06).

Endpoints (AdminUser):

- ``POST /api/admin/recruitment-processes/backfill`` — start backfillu w tle
  (wzorzec backfill-names: single-flight, resumable — insert-only, więc
  restart kontenera po prostu dokańcza brakujące pary). Parametry:
  ``limit_pairs`` (batch weryfikacyjny), ``resync_stale`` (aktualizacja
  procesów, których latest legacy się zmienił — legacy jest authority do
  PR-08).
- ``GET  /api/admin/recruitment-processes/backfill/status`` — postęp.
- ``GET  /api/admin/recruitment-processes/shadow-compare`` — komparator:
  pary bez procesu, stale pointers, kwarantanna semantyczna.
- ``GET  /api/admin/recruitment-processes/by-pair/{candidate_id}/{job_id}``
  — read-only detal procesu pary + faktyczny latest legacy + zgodność.

Runtime pipeline NIC z tego nie czyta — authority przejmie PR-07/08.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser
from app.core.database import AsyncSessionLocal, get_db
from app.models.recruitment_pipeline import CandidateStage
from app.models.recruitment_process import RecruitmentProcess
from app.services.process_backfill import (
    backfill_recruitment_processes,
    compare_shadow_state,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_JOB: dict[str, Any] = {
    "running": False,
    "total_pairs": 0,
    "pairs_seen": 0,
    "created": 0,
    "skipped_existing": 0,
    "resynced": 0,
    "unmapped_semantic": 0,
    "started_at": None,
    "finished_at": None,
    "limit_pairs": None,
    "resync_stale": False,
    "last_error": None,
}


async def _run_backfill(limit_pairs: Optional[int], resync_stale: bool) -> None:
    _JOB.update(
        running=True,
        total_pairs=0,
        pairs_seen=0,
        created=0,
        skipped_existing=0,
        resynced=0,
        unmapped_semantic=0,
        started_at=datetime.now(timezone.utc).isoformat(),
        finished_at=None,
        limit_pairs=limit_pairs,
        resync_stale=resync_stale,
        last_error=None,
    )
    try:
        async with AsyncSessionLocal() as db:
            await backfill_recruitment_processes(
                db,
                limit_pairs=limit_pairs,
                resync_stale=resync_stale,
                progress=_JOB,
            )
    except Exception as e:  # noqa: BLE001 — background task nie może umrzeć głośno
        _JOB["last_error"] = repr(e)
        logger.exception("[process-backfill] job crashed")
    finally:
        _JOB["running"] = False
        _JOB["finished_at"] = datetime.now(timezone.utc).isoformat()


@router.post("/recruitment-processes/backfill")
async def trigger_process_backfill(
    _admin: AdminUser,
    limit_pairs: Optional[int] = Query(
        default=None,
        ge=1,
        description="Ogranicz liczbę par w tym przebiegu (batch weryfikacyjny).",
    ),
    resync_stale: bool = Query(
        default=False,
        description=(
            "Zaktualizuj procesy backfillowe, których latest legacy się "
            "zmienił (pointer/status/semantic + state_version+1)."
        ),
    ),
) -> dict[str, Any]:
    if _JOB["running"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Backfill już trwa",
        )
    asyncio.create_task(_run_backfill(limit_pairs, resync_stale))
    return {
        "status": "started",
        "limit_pairs": limit_pairs,
        "resync_stale": resync_stale,
    }


@router.get("/recruitment-processes/backfill/status")
async def process_backfill_status(_admin: AdminUser) -> dict[str, Any]:
    return dict(_JOB)


@router.get("/recruitment-processes/shadow-compare")
async def shadow_compare(
    _admin: AdminUser,
    sample_limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await compare_shadow_state(db, sample_limit=sample_limit)


@router.get("/recruitment-processes/by-pair/{candidate_id}/{job_id}")
async def process_detail_by_pair(
    candidate_id: int,
    job_id: int,
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    processes = (
        (
            await db.execute(
                select(RecruitmentProcess)
                .where(
                    RecruitmentProcess.candidate_id == candidate_id,
                    RecruitmentProcess.job_id == job_id,
                )
                .order_by(RecruitmentProcess.attempt_no)
            )
        )
        .scalars()
        .all()
    )
    if not processes:
        raise HTTPException(status_code=404, detail="Brak procesu dla pary")

    actual_latest = await db.scalar(
        select(CandidateStage.id)
        .where(
            CandidateStage.candidate_id == candidate_id,
            CandidateStage.job_id == job_id,
        )
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
        .limit(1)
    )
    newest = processes[-1]
    return {
        "candidate_id": candidate_id,
        "job_id": job_id,
        "actual_latest_candidate_stage_id": actual_latest,
        "pointer_in_sync": (newest.legacy_current_candidate_stage_id == actual_latest),
        "processes": [
            {
                "id": p.id,
                "attempt_no": p.attempt_no,
                "status": p.status.value,
                "state_version": p.state_version,
                "current_semantic_state": p.current_semantic_state,
                "current_stage_revision_id": p.current_stage_revision_id,
                "workflow_revision_id": p.workflow_revision_id,
                "legacy_current_candidate_stage_id": (
                    p.legacy_current_candidate_stage_id
                ),
                "owner_user_id": p.owner_user_id,
                "source_authority": p.source_authority,
                "opened_at": p.opened_at.isoformat() if p.opened_at else None,
                "closed_at": p.closed_at.isoformat() if p.closed_at else None,
            }
            for p in processes
        ],
    }
