"""CV Generator B2B — standalone module API.

Routes mounted under ``/api/cv-generator``:

  * ``GET  /candidates``                  — typeahead search (name, lastname, email)
  * ``GET  /candidates/{id}/recruitments`` — list candidate's processes + readiness
  * ``POST /generate``                    — New mode: generate DOCX from NEXUS DB
  * ``POST /generate-upload``             — Old mode: generate DOCX from manual uploads
                                            (1:1 with external CV-Generator)

All endpoints require an authenticated user (any role).
"""

from __future__ import annotations

import json
import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.database import get_db
from app.models.candidate import Candidate
from app.services.cv_generator_b2b.standalone_service import (
    StandaloneGenerationError,
    UploadGenerationInput,
    generate_cv_for_candidate,
    generate_cv_from_uploads,
    list_recruitments_with_readiness,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cv-generator", tags=["cv-generator-b2b"])


# ── Schemas ────────────────────────────────────────────────────────────────


class CandidateOption(BaseModel):
    """Typeahead row — just enough to render the picker."""

    id: int
    name: str
    lastname: str
    full_name: str
    position: Optional[str] = None
    email: Optional[str] = None


class RecruitmentOption(BaseModel):
    """A recruitment process the candidate participates in."""

    stage_id: int
    job_id: int
    job_title: str
    stage: str
    has_champion: bool
    has_notes: bool
    ready: bool


class GenerateRequest(BaseModel):
    candidate_id: int = Field(..., ge=1)
    stage_id: int = Field(..., ge=1)
    language: Literal["pl", "en"] = "pl"
    blind_cv: bool = False


# ── Helpers ────────────────────────────────────────────────────────────────


def _error_status(code: str) -> int:
    return {
        "candidate_not_found": 404,
        "stage_not_found": 404,
        "no_cv_file": 422,
        "no_champion": 422,
        "no_notes": 422,
        "invalid_input": 400,
        "extraction_failed": 502,
        "ai_failed": 502,
        "render_failed": 500,
    }.get(code, 500)


def _build_docx_response(
    docx_bytes: bytes,
    filename: str,
    candidate_name: str,
    warnings: list[str],
    processing_time_ms: int,
) -> Response:
    """Wrap a generated DOCX in the standard streaming Response with metadata
    headers used by both ``/generate`` and ``/generate-upload``."""
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Generator-Candidate-Name": candidate_name,
        "X-Generator-Warnings": json.dumps(warnings, ensure_ascii=False),
        "X-Generator-Processing-Ms": str(processing_time_ms),
        "Access-Control-Expose-Headers": (
            "Content-Disposition, X-Generator-Candidate-Name, "
            "X-Generator-Warnings, X-Generator-Processing-Ms"
        ),
    }
    return Response(
        content=docx_bytes,
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        headers=headers,
    )


# ── Endpoints ──────────────────────────────────────────────────────────────


@router.get("/candidates", response_model=list[CandidateOption])
async def search_candidates(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    q: str = Query(
        "",
        max_length=120,
        description="Free-text search across name, lastname and email.",
    ),
    limit: int = Query(20, ge=1, le=50),
) -> list[CandidateOption]:
    """Lightweight typeahead. Empty ``q`` returns the most recently updated rows."""

    del current_user  # auth only

    stmt = select(Candidate)
    needle = (q or "").strip()
    if needle:
        like = f"%{needle.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Candidate.name).like(like),
                func.lower(Candidate.lastname).like(like),
                func.lower(func.coalesce(Candidate.email, "")).like(like),
            )
        )
    stmt = stmt.order_by(Candidate.updated_at.desc()).limit(limit)

    rows = (await db.scalars(stmt)).all()

    return [
        CandidateOption(
            id=c.id,
            name=c.name,
            lastname=c.lastname,
            full_name=f"{c.name} {c.lastname}".strip(),
            position=getattr(c, "current_position", None),
            email=getattr(c, "email", None),
        )
        for c in rows
    ]


@router.get(
    "/candidates/{candidate_id}/recruitments",
    response_model=list[RecruitmentOption],
)
async def list_candidate_recruitments(
    candidate_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> list[RecruitmentOption]:
    """Return all recruitment processes the candidate participates in, with
    readiness flags (champion present, screening notes present)."""

    del current_user

    try:
        readiness = await list_recruitments_with_readiness(db, candidate_id)
    except StandaloneGenerationError as err:
        raise HTTPException(
            status_code=_error_status(err.code), detail=err.message
        ) from err

    return [
        RecruitmentOption(
            stage_id=r.stage_id,
            job_id=r.job_id,
            job_title=r.job_title,
            stage=r.stage,
            has_champion=r.has_champion,
            has_notes=r.has_notes,
            ready=r.ready,
        )
        for r in readiness
    ]


@router.post("/generate")
async def generate(
    payload: GenerateRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Generate the B2B-formatted CV and return it as a streamed DOCX.

    Streams ``application/vnd.openxmlformats-officedocument.wordprocessingml.document``
    with the rendered filename in ``Content-Disposition``. Warnings (e.g.
    missing MUST-HAVE / NICE-TO-HAVE technologies) are surfaced via the
    ``X-Generator-Warnings`` header as a JSON-encoded array.
    """

    del current_user

    try:
        result = await generate_cv_for_candidate(
            db,
            candidate_id=payload.candidate_id,
            stage_id=payload.stage_id,
            language=payload.language,
            blind_cv=payload.blind_cv,
        )
    except StandaloneGenerationError as err:
        raise HTTPException(
            status_code=_error_status(err.code), detail=err.message
        ) from err

    return _build_docx_response(
        docx_bytes=result.docx_bytes,
        filename=result.filename,
        candidate_name=result.candidate_name,
        warnings=result.warnings,
        processing_time_ms=result.processing_time_ms,
    )


@router.post("/generate-upload")
async def generate_from_upload(
    current_user: CurrentUser,
    cv_file: UploadFile = File(..., description="Plik CV (PDF / DOCX / DOC)"),
    language: Literal["pl", "en"] = Form("pl"),
    blind_cv: bool = Form(False),
    screening_notes: str = Form(""),
    champion_file: Optional[UploadFile] = File(
        None, description="Opcjonalny plik DOCX z Profilem Championa"
    ),
) -> Response:
    """1:1 odpowiednik external ``POST /api/v1/generate`` (multipart wariant).

    Old-mode: user wgrywa CV ręcznie, opcjonalnie DOCX championa i notatki
    ze screeningu. Nic nie trafia do NEXUS DB — pełen flow przebiega na
    danych z requestu i Claude API.
    """
    del current_user  # auth only

    cv_bytes = await cv_file.read()
    champion_bytes: bytes | None = None
    champion_filename: str | None = None
    if champion_file is not None and champion_file.filename:
        champion_bytes = await champion_file.read()
        champion_filename = champion_file.filename

    payload = UploadGenerationInput(
        cv_bytes=cv_bytes,
        cv_filename=cv_file.filename or "cv.pdf",
        language=language,
        blind_cv=blind_cv,
        screening_notes=screening_notes or "",
        champion_bytes=champion_bytes,
        champion_filename=champion_filename,
    )

    try:
        result = await run_in_threadpool(generate_cv_from_uploads, payload)
    except StandaloneGenerationError as err:
        raise HTTPException(
            status_code=_error_status(err.code), detail=err.message
        ) from err

    return _build_docx_response(
        docx_bytes=result.docx_bytes,
        filename=result.filename,
        candidate_name=result.candidate_name,
        warnings=result.warnings,
        processing_time_ms=result.processing_time_ms,
    )


# Silence the unused-import warning for `and_` if linter complains.
_ = and_
