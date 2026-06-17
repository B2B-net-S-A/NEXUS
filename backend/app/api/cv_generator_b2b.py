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
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.database import get_db
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.cv_generated_document import CvGeneratedDocument
from app.models.user import User, UserRole
from app.services.cv_generator_b2b.standalone_service import (
    StandaloneGenerationError,
    UploadGenerationInput,
    generate_cv_for_candidate,
    generate_cv_from_uploads,
    list_recruitments_with_readiness,
    rerender_docx_from_payload,
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
    has_cv: bool
    ready: bool


class GenerateRequest(BaseModel):
    candidate_id: int = Field(..., ge=1)
    stage_id: int = Field(..., ge=1)
    language: Literal["pl", "en"] = "pl"
    blind_cv: bool = False


class GeneratedCvItem(BaseModel):
    """A row in the „Wygenerowane CV" panel list."""

    id: int
    candidate_id: Optional[int] = None
    job_id: Optional[int] = None
    candidate_name: str
    position: Optional[str] = None
    language: str
    blind: bool
    mode: str
    filename: str
    created_at: Optional[str] = None
    created_by_name: Optional[str] = None
    can_download: bool
    can_delete: bool


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
    generated_id: int | None = None,
) -> Response:
    """Wrap a generated DOCX in the standard streaming Response with metadata
    headers used by both ``/generate`` and ``/generate-upload``.

    HTTP header values must be latin-1 (ISO-8859-1) encodable. Candidate names
    and Claude warnings routinely carry Polish characters (ł, ą, ę…) that fall
    outside latin-1; emitting them raw makes the ASGI server raise
    ``UnicodeEncodeError`` while serializing headers, surfacing as a bare 500.
    Percent-encode the human-readable name and force ASCII-only ``\\uXXXX``
    escapes in the warnings JSON — ``decodeURIComponent`` / ``JSON.parse`` on
    the client decode both transparently.
    """
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Generator-Candidate-Name": quote(candidate_name),
        "X-Generator-Warnings": json.dumps(warnings, ensure_ascii=True),
        "X-Generator-Processing-Ms": str(processing_time_ms),
        "Access-Control-Expose-Headers": (
            "Content-Disposition, X-Generator-Candidate-Name, "
            "X-Generator-Warnings, X-Generator-Processing-Ms, X-Generated-Id"
        ),
    }
    if generated_id is not None:
        headers["X-Generated-Id"] = str(generated_id)
    return Response(
        content=docx_bytes,
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        headers=headers,
    )


async def _persist_generated(
    db: AsyncSession,
    *,
    result,
    mode: str,
    candidate_id: int | None,
    language: str,
    blind_cv: bool,
    user_id: int,
) -> int:
    """Log a generated CV so it appears in the panel list and can be
    re-downloaded/previewed later without another Claude call. Returns the row id.

    Stored alongside the Activity audit entry — the caller commits both together.
    """
    payload = result.render_payload or {}
    # For blind CVs ``result.candidate_name`` is the anonymized "Kandydat" — use
    # the real name captured in the payload so the INTERNAL list stays
    # identifiable (the DOCX itself remains anonymized on re-render).
    display_name = str(payload.get("name") or result.candidate_name)
    row = CvGeneratedDocument(
        candidate_id=candidate_id,
        job_id=result.job_id,
        candidate_name=display_name,
        position=payload.get("position"),
        language=language,
        blind=blind_cv,
        mode=mode,
        filename=result.filename,
        render_payload=result.render_payload,
        created_by=user_id,
    )
    db.add(row)
    await db.flush()  # assign row.id before commit so the caller can return it
    return row.id


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
    """Lightweight typeahead. Empty ``q`` returns the most recently updated rows.

    Matches "Imię Nazwisko" / "Nazwisko Imię" as a whole (concatenated
    columns) and ranks exact / prefix lastname+name matches above substring
    hits — "Bogdan" must surface Michał *Bogdan* before *Bogdan*owicz.
    """

    del current_user  # auth only

    stmt = select(Candidate)
    needle = (q or "").strip().lower()
    if needle:
        like = f"%{needle}%"
        name_l = func.lower(func.coalesce(Candidate.name, ""))
        lastname_l = func.lower(func.coalesce(Candidate.lastname, ""))
        full = name_l + " " + lastname_l
        full_rev = lastname_l + " " + name_l
        stmt = stmt.where(
            or_(
                name_l.like(like),
                lastname_l.like(like),
                full.like(like),
                full_rev.like(like),
                func.lower(func.coalesce(Candidate.email, "")).like(like),
            )
        )
        rank = case(
            (
                or_(
                    lastname_l == needle,
                    name_l == needle,
                    full == needle,
                    full_rev == needle,
                ),
                0,
            ),
            (
                or_(
                    lastname_l.like(f"{needle}%"),
                    name_l.like(f"{needle}%"),
                    full.like(f"{needle}%"),
                    full_rev.like(f"{needle}%"),
                ),
                1,
            ),
            else_=2,
        )
        stmt = stmt.order_by(rank, Candidate.updated_at.desc()).limit(limit)
    else:
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
            has_cv=r.has_cv,
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

    # Audit trail — CV generation is a Claude-billed operation on personal
    # data; without this there is zero trace of who generated what.
    db.add(
        Activity(
            entity_type="candidate",
            entity_id=payload.candidate_id,
            action="b2b_cv_generated",
            details={
                "stage_id": payload.stage_id,
                "language": payload.language,
                "blind_cv": payload.blind_cv,
                "filename": result.filename,
                "warnings_count": len(result.warnings),
                "processing_time_ms": result.processing_time_ms,
            },
            user_id=current_user.id,
        )
    )
    generated_id = await _persist_generated(
        db,
        result=result,
        mode="new",
        candidate_id=payload.candidate_id,
        language=payload.language,
        blind_cv=payload.blind_cv,
        user_id=current_user.id,
    )
    await db.commit()

    return _build_docx_response(
        docx_bytes=result.docx_bytes,
        filename=result.filename,
        candidate_name=result.candidate_name,
        warnings=result.warnings,
        processing_time_ms=result.processing_time_ms,
        generated_id=generated_id,
    )


@router.post("/generate-upload")
async def generate_from_upload(
    current_user: CurrentUser,
    cv_file: UploadFile = File(..., description="Plik CV (PDF / DOCX)"),
    language: Literal["pl", "en"] = Form("pl"),
    blind_cv: bool = Form(False),
    screening_notes: str = Form(""),
    champion_file: Optional[UploadFile] = File(
        None, description="Opcjonalny plik DOCX z Profilem Championa"
    ),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """1:1 odpowiednik external ``POST /api/v1/generate`` (multipart wariant).

    Old-mode: user wgrywa CV ręcznie, opcjonalnie DOCX championa i notatki
    ze screeningu. Poza wpisem audytowym nic nie trafia do NEXUS DB — pełen
    flow przebiega na danych z requestu i Claude API.
    """
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

    # Upload mode has no candidate context — anchor the audit entry on the user.
    db.add(
        Activity(
            entity_type="user",
            entity_id=current_user.id,
            action="b2b_cv_generated_upload",
            details={
                "cv_filename": cv_file.filename,
                "language": language,
                "blind_cv": blind_cv,
                "filename": result.filename,
                "warnings_count": len(result.warnings),
                "processing_time_ms": result.processing_time_ms,
            },
            user_id=current_user.id,
        )
    )
    generated_id = await _persist_generated(
        db,
        result=result,
        mode="upload",
        candidate_id=None,
        language=language,
        blind_cv=blind_cv,
        user_id=current_user.id,
    )
    await db.commit()

    return _build_docx_response(
        docx_bytes=result.docx_bytes,
        filename=result.filename,
        candidate_name=result.candidate_name,
        warnings=result.warnings,
        processing_time_ms=result.processing_time_ms,
        generated_id=generated_id,
    )


# ── Saved-CV list („Wygenerowane CV") ──────────────────────────────────────


@router.get("/generated", response_model=list[GeneratedCvItem])
async def list_generated_cvs(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(60, ge=1, le=200),
):
    """Recently generated CVs for the panel list (newest first).

    ``can_download`` tells the UI whether the DOCX can be re-rendered (rows from
    before this feature have no ``render_payload``); ``can_delete`` whether the
    current user may remove the row (its author or an admin).
    """
    is_admin = current_user.has_role(UserRole.admin)
    rows = (
        await db.execute(
            select(CvGeneratedDocument, User.name)
            .outerjoin(User, User.id == CvGeneratedDocument.created_by)
            .order_by(CvGeneratedDocument.created_at.desc())
            .limit(limit)
        )
    ).all()
    return [
        GeneratedCvItem(
            id=r.id,
            candidate_id=r.candidate_id,
            job_id=r.job_id,
            candidate_name=r.candidate_name,
            position=r.position,
            language=r.language,
            blind=r.blind,
            mode=r.mode,
            filename=r.filename,
            created_at=r.created_at.isoformat() if r.created_at else None,
            created_by_name=creator_name,
            can_download=r.render_payload is not None,
            can_delete=is_admin or r.created_by == current_user.id,
        )
        for r, creator_name in rows
    ]


@router.get("/generated/{generated_id}/docx")
async def download_generated_cv(
    generated_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Re-render a previously generated CV from its saved payload and return it.

    Deterministic render — no Claude call. Rows generated before this feature
    have no payload → 422 asking to generate again. Used for both inline preview
    and explicit download in the panel.
    """
    row = await db.get(CvGeneratedDocument, generated_id)
    if not row:
        raise HTTPException(status_code=404, detail="Wpis nie został znaleziony")
    if not row.render_payload:
        raise HTTPException(
            status_code=422,
            detail=(
                "To CV wygenerowano zanim dodaliśmy zapis danych — nie można go "
                "odtworzyć. Wygeneruj je ponownie."
            ),
        )
    try:
        docx_bytes = await run_in_threadpool(
            rerender_docx_from_payload, row.render_payload
        )
    except Exception as err:  # noqa: BLE001 — python-docx raises various types
        logger.exception("[cv_b2b] Re-render of saved CV %s failed: %s", row.id, err)
        raise HTTPException(
            status_code=500, detail=f"Nie udało się odtworzyć DOCX: {err}"
        ) from err
    return _build_docx_response(
        docx_bytes=docx_bytes,
        filename=row.filename,
        candidate_name=row.candidate_name,
        warnings=[],
        processing_time_ms=0,
        generated_id=row.id,
    )


@router.delete("/generated/{generated_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_generated_cv(
    generated_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Remove a row from the „Wygenerowane CV" list (author or admin only).

    Only the list entry is deleted; nothing irreplaceable is lost — the CV can be
    regenerated from the candidate's recruitment at any time.
    """
    row = await db.get(CvGeneratedDocument, generated_id)
    if not row:
        raise HTTPException(status_code=404, detail="Wpis nie został znaleziony")
    if not current_user.has_role(UserRole.admin) and row.created_by != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="Możesz usunąć tylko CV, które samodzielnie wygenerowałeś.",
        )
    await db.delete(row)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
