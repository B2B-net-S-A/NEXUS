"""CV Generator B2B — standalone module API.

Routes mounted under ``/api/cv-generator``:

  * ``GET  /candidates``                  — typeahead search (name, lastname, email)
  * ``GET  /candidates/{id}/recruitments`` — list candidate's processes + readiness
  * ``POST /generate``                    — generate DOCX (streamed as octet-stream)

All endpoints require an authenticated user (any role).
"""

from __future__ import annotations

import logging
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func

from fastapi import Depends

from app.api.deps import CurrentUser
from app.core.database import get_db
from app.models.candidate import Candidate
from app.services.cv_generator_b2b.standalone_service import (
    StandaloneGenerationError,
    generate_cv_for_candidate,
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
        "extraction_failed": 502,
        "ai_failed": 502,
        "render_failed": 500,
    }.get(code, 500)


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
        raise HTTPException(status_code=_error_status(err.code), detail=err.message) from err

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
        raise HTTPException(status_code=_error_status(err.code), detail=err.message) from err

    import json as _json

    headers = {
        "Content-Disposition": f'attachment; filename="{result.filename}"',
        "X-Generator-Candidate-Name": result.candidate_name,
        "X-Generator-Warnings": _json.dumps(result.warnings, ensure_ascii=False),
        "X-Generator-Processing-Ms": str(result.processing_time_ms),
        "Access-Control-Expose-Headers": (
            "Content-Disposition, X-Generator-Candidate-Name, "
            "X-Generator-Warnings, X-Generator-Processing-Ms"
        ),
    }

    return Response(
        content=result.docx_bytes,
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        headers=headers,
    )


# Silence the unused-import warning for `and_` if linter complains.
_ = and_
