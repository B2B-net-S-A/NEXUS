"""Endpointy CV per rekrutacja.

Faza 2 (PR1): tylko "original" snapshot.
  GET    /api/candidates/stages/{stage_id}/cv/original
  GET    /api/candidates/stages/{stage_id}/cv/original/download
  POST   /api/candidates/stages/{stage_id}/cv/original/refresh

Fazy 3-4 (PR2) dorzucą endpointy `branded` i `share-token`.
"""

from __future__ import annotations

import logging
import mimetypes
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, RecruiterPlus
from app.core.database import get_db
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.recruitment_pipeline import CandidateStage
from app.schemas.candidate_stage_cv import CVOriginalSnapshotResponse
from app.services.candidate_stage_cv_service import (
    refresh_original_cv_snapshot,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _build_original_response(csv: CandidateStageCV) -> CVOriginalSnapshotResponse:
    has_snapshot = csv.original_cv_content is not None
    return CVOriginalSnapshotResponse(
        candidate_stage_id=csv.candidate_stage_id,
        candidate_id=csv.candidate_id,
        job_id=csv.job_id,
        has_snapshot=has_snapshot,
        original_cv_filename=csv.original_cv_filename,
        original_cv_language=csv.original_cv_language,
        original_snapshot_at=csv.original_snapshot_at,
        original_snapshot_source=csv.original_snapshot_source,
        download_url=(
            f"/api/candidates/stages/{csv.candidate_stage_id}/cv/original/download"
            if has_snapshot
            else None
        ),
    )


async def _load_csv_for_stage(
    db: AsyncSession, stage_id: int
) -> CandidateStageCV:
    """Wczytaj CandidateStageCV dla stage_id, 404 gdy brak. Sprawdza tez czy
    sam stage istnieje — żeby rozróżnić "stage nie istnieje" od "stage bez CV"."""
    csv = await db.scalar(
        select(CandidateStageCV).where(
            CandidateStageCV.candidate_stage_id == stage_id
        )
    )
    if csv is not None:
        return csv

    stage_exists = await db.scalar(
        select(CandidateStage.id).where(CandidateStage.id == stage_id)
    )
    if stage_exists is None:
        raise HTTPException(status_code=404, detail="Stage nie znaleziony")
    raise HTTPException(
        status_code=404,
        detail=(
            "CV instance nie istnieje dla tego stage. "
            "Snapshot powinien być utworzony przy CREATE stage'a — "
            "jeśli stage jest historyczny, uruchom backfill 0070."
        ),
    )


@router.get(
    "/candidates/stages/{stage_id}/cv/original",
    response_model=CVOriginalSnapshotResponse,
)
async def get_original_cv(
    stage_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> CVOriginalSnapshotResponse:
    csv = await _load_csv_for_stage(db, stage_id)
    return _build_original_response(csv)


@router.get("/candidates/stages/{stage_id}/cv/original/download")
async def download_original_cv(
    stage_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> Response:
    csv = await _load_csv_for_stage(db, stage_id)
    if csv.original_cv_content is None:
        raise HTTPException(
            status_code=404,
            detail="Kandydat nie miał CV w momencie utworzenia rekrutacji.",
        )

    filename = csv.original_cv_filename or f"cv_stage_{stage_id}.pdf"
    media_type, _ = mimetypes.guess_type(filename)
    if not media_type:
        media_type = "application/octet-stream"

    return StreamingResponse(
        BytesIO(csv.original_cv_content),
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(csv.original_cv_content)),
        },
    )


@router.post(
    "/candidates/stages/{stage_id}/cv/original/refresh",
    response_model=CVOriginalSnapshotResponse,
)
async def refresh_original_cv(
    stage_id: int,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> CVOriginalSnapshotResponse:
    """Nadpisz snapshot aktualną zawartością CV kandydata (manual refresh).

    Idempotent w tym sensie, że można wołać wielokrotnie — każdorazowo nadpisuje.
    Jeśli kandydat aktualnie nie ma CV → 422 (nie ma czego skopiować).
    """
    try:
        csv = await refresh_original_cv_snapshot(
            db, stage_id, user_id=current_user.id
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    await db.commit()
    await db.refresh(csv)
    return _build_original_response(csv)
