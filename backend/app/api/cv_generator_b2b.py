"""CV Generator B2B — standalone module API.

Routes mounted under ``/api/cv-generator``:

  * ``GET  /candidates``                  — typeahead search (name, lastname, email)
  * ``GET  /candidates/{id}/recruitments`` — list candidate's processes + readiness
  * ``POST /generate``                    — New mode: generate DOCX from NEXUS DB
  * ``POST /generate-upload``             — Old mode: generate DOCX from manual uploads
                                            (1:1 with external CV-Generator)

All endpoints require an authenticated user (any role).

NOTE: this module must NOT use ``from __future__ import annotations``. The two
``@limiter.limit`` (slowapi) POST endpoints below take params whose FastAPI
markers live only inside ``Annotated[...]`` (``cv_file`` → ``File()``,
``current_user`` → ``Depends()``) with no default value. Under PEP 563 the
slowapi wrapper makes FastAPI evaluate those stringized annotations against
slowapi's module globals (where ``UploadFile``/``File``/``Depends`` are
undefined), so the markers are lost and the params get misclassified as required
*query* params → ``422 {"loc":["query","cv_file"],"msg":"Field required"}`` at
request time. Real (non-stringized) annotations sidestep it. Same reason as
``cv_match_preview``.
"""

import json
import logging
from pathlib import Path
from typing import Annotated, Literal, Optional
from urllib.parse import quote

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.database import AsyncSessionLocal, get_db
from app.core.rate_limit import limiter
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.cv_generated_document import CvGeneratedDocument
from app.models.user import User, UserRole
from app.services.cv_generator_b2b.standalone_service import (
    StandaloneGenerationError,
    UploadGenerationInput,
    ascii_filename_fallback,
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
    # Async generation lifecycle — the UI polls this list and renders a spinner
    # for "processing", the CV for "ready" and the reason for "failed".
    status: str = "ready"
    error_message: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
    created_at: Optional[str] = None
    created_by_name: Optional[str] = None
    can_download: bool
    can_delete: bool


class GenerateEnqueuedResponse(BaseModel):
    """202 payload — generation was enqueued and runs in the background.

    The recruiter can leave the tab; the result appears on ``GET /generated``
    (poll it) with ``status`` flipping to „ready" or „failed"."""

    id: int
    status: str = "processing"
    candidate_name: str


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
        "ai_overloaded": 503,
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

    The filename follows the same rule via RFC 6266/5987: an ASCII ``filename=``
    fallback (latin-1 safe) plus a ``filename*=UTF-8''…`` parameter carrying the
    real, Polish-character spelling so modern clients save it intact.
    """
    ascii_name = ascii_filename_fallback(filename)
    disposition = f'attachment; filename="{ascii_name}"'
    if filename != ascii_name:
        disposition += f"; filename*=UTF-8''{quote(filename, safe='')}"
    headers = {
        "Content-Disposition": disposition,
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


async def _create_pending_row(
    db: AsyncSession,
    *,
    mode: str,
    candidate_id: int | None,
    candidate_name: str,
    position: str | None,
    language: str,
    blind_cv: bool,
    user_id: int,
) -> int:
    """Insert a „processing" placeholder so the CV shows on the list the moment
    generation is enqueued — the recruiter can then close the tab while the
    background job fills in ``render_payload`` / ``status``. Returns the row id.
    """
    row = CvGeneratedDocument(
        candidate_id=candidate_id,
        job_id=None,
        candidate_name=candidate_name or "Generowanie…",
        position=position,
        language=language,
        blind=blind_cv,
        mode=mode,
        filename="",  # filled from the rendered filename on completion
        status="processing",
        render_payload=None,
        created_by=user_id,
    )
    db.add(row)
    await db.flush()  # assign row.id before commit so the caller can return it
    return row.id


async def _finalize_success(db: AsyncSession, generated_id: int, *, result) -> bool:
    """Flip a „processing" row to „ready" with its render payload + warnings, so
    it can be re-downloaded/previewed later without another Claude call. Returns
    ``False`` when the row vanished (recruiter deleted it mid-generation).
    """
    row = await db.get(CvGeneratedDocument, generated_id)
    if row is None:
        return False
    payload = result.render_payload or {}
    # For blind CVs ``result.candidate_name`` is the anonymized "Kandydat" — use
    # the real name captured in the payload so the INTERNAL list stays
    # identifiable (the DOCX itself remains anonymized on re-render).
    row.candidate_name = str(payload.get("name") or result.candidate_name)
    row.position = payload.get("position")
    row.job_id = result.job_id
    row.filename = result.filename
    row.render_payload = result.render_payload
    row.warnings = list(result.warnings or [])
    row.error_message = None
    row.status = "ready"
    return True


async def _finalize_failure(db: AsyncSession, generated_id: int, message: str) -> None:
    """Mark a „processing" row „failed" with the reason. No-op if it's gone."""
    row = await db.get(CvGeneratedDocument, generated_id)
    if row is None:
        return
    row.status = "failed"
    row.error_message = message[:1000]


# ── Background generation jobs ─────────────────────────────────────────────
#
# Scheduled via FastAPI ``BackgroundTasks`` AFTER the 202 response is fully sent,
# so a client disconnect (recruiter closing the tab) no longer cancels the work —
# that is the whole point of this feature. Each job owns a fresh DB session
# (the request session is long gone) and never raises: any failure is written
# onto the row as ``status="failed"``. Orphaned „processing" rows left by a
# server restart mid-job are reaped to „failed" on startup (see main.lifespan).


async def _run_generate_new_job(
    generated_id: int,
    *,
    candidate_id: int,
    stage_id: int,
    language: Literal["pl", "en"],
    blind_cv: bool,
    user_id: int,
) -> None:
    """Background worker for New-mode (DB-backed) generation."""
    async with AsyncSessionLocal() as db:
        try:
            result = await generate_cv_for_candidate(
                db,
                candidate_id=candidate_id,
                stage_id=stage_id,
                language=language,
                blind_cv=blind_cv,
            )
        except StandaloneGenerationError as err:
            await _finalize_failure(db, generated_id, err.message)
            await db.commit()
            return
        except Exception as err:  # noqa: BLE001 — a job must never crash silently
            logger.exception("[cv_b2b] New-mode job %s crashed: %s", generated_id, err)
            await _finalize_failure(
                db, generated_id, "Nieoczekiwany błąd generacji CV."
            )
            await db.commit()
            return

        if await _finalize_success(db, generated_id, result=result):
            db.add(
                Activity(
                    entity_type="candidate",
                    entity_id=candidate_id,
                    action="b2b_cv_generated",
                    details={
                        "stage_id": stage_id,
                        "language": language,
                        "blind_cv": blind_cv,
                        "filename": result.filename,
                        "warnings_count": len(result.warnings),
                        "processing_time_ms": result.processing_time_ms,
                        "generated_id": generated_id,
                    },
                    user_id=user_id,
                )
            )
        await db.commit()


async def _run_generate_upload_job(
    generated_id: int,
    *,
    payload: UploadGenerationInput,
    user_id: int,
) -> None:
    """Background worker for Old-mode (manual upload) generation."""
    async with AsyncSessionLocal() as db:
        try:
            result = await run_in_threadpool(generate_cv_from_uploads, payload)
        except StandaloneGenerationError as err:
            await _finalize_failure(db, generated_id, err.message)
            await db.commit()
            return
        except Exception as err:  # noqa: BLE001 — a job must never crash silently
            logger.exception("[cv_b2b] Upload job %s crashed: %s", generated_id, err)
            await _finalize_failure(
                db, generated_id, "Nieoczekiwany błąd generacji CV."
            )
            await db.commit()
            return

        if await _finalize_success(db, generated_id, result=result):
            # Upload mode has no candidate context — anchor the audit on the user.
            db.add(
                Activity(
                    entity_type="user",
                    entity_id=user_id,
                    action="b2b_cv_generated_upload",
                    details={
                        "cv_filename": payload.cv_filename,
                        "language": payload.language,
                        "blind_cv": payload.blind_cv,
                        "filename": result.filename,
                        "warnings_count": len(result.warnings),
                        "processing_time_ms": result.processing_time_ms,
                        "generated_id": generated_id,
                    },
                    user_id=user_id,
                )
            )
        await db.commit()


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


@router.post(
    "/generate",
    response_model=GenerateEnqueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
@limiter.limit("10/minute")
async def generate(
    request: Request,
    payload: GenerateRequest,
    current_user: CurrentUser,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> GenerateEnqueuedResponse:
    """Enqueue New-mode CV generation and return immediately (202 Accepted).

    Generation (60-90 s: Claude + DOCX render) runs in the background, so the
    recruiter can close/leave the tab without losing the result — it lands on
    the „Wygenerowane CV" list (``GET /generated``) with ``status`` „ready" or
    „failed". A „processing" placeholder row is created here so the CV shows up
    on the list right away; the deep readiness contract (CV file / champion /
    notes present) is validated inside the background job and any failure is
    written onto that row.
    """
    candidate = await db.get(Candidate, payload.candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Kandydat nie został znaleziony.")

    candidate_name = f"{candidate.name} {candidate.lastname}".strip() or "Kandydat"
    generated_id = await _create_pending_row(
        db,
        mode="new",
        candidate_id=payload.candidate_id,
        candidate_name=candidate_name,
        position=getattr(candidate, "current_position", None),
        language=payload.language,
        blind_cv=payload.blind_cv,
        user_id=current_user.id,
    )
    # Commit before scheduling/returning so the row is visible to both the poll
    # and the background job (which opens its own session).
    await db.commit()

    background_tasks.add_task(
        _run_generate_new_job,
        generated_id,
        candidate_id=payload.candidate_id,
        stage_id=payload.stage_id,
        language=payload.language,
        blind_cv=payload.blind_cv,
        user_id=current_user.id,
    )
    return GenerateEnqueuedResponse(
        id=generated_id, status="processing", candidate_name=candidate_name
    )


@router.post(
    "/generate-upload",
    response_model=GenerateEnqueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
@limiter.limit("10/minute")
async def generate_from_upload(
    request: Request,
    current_user: CurrentUser,
    background_tasks: BackgroundTasks,
    # No `from __future__ import annotations` in this module (see module docstring),
    # so this multipart marker resolves correctly even under the slowapi
    # `@limiter.limit` wrapper. Annotated form is the FastAPI-recommended style.
    cv_file: Annotated[UploadFile, File(description="Plik CV (PDF / DOCX)")],
    language: Literal["pl", "en"] = Form("pl"),
    blind_cv: bool = Form(False),
    screening_notes: str = Form(""),
    champion_file: Annotated[
        Optional[UploadFile],
        File(description="Opcjonalny plik DOCX z Profilem Championa"),
    ] = None,
    db: AsyncSession = Depends(get_db),
) -> GenerateEnqueuedResponse:
    """1:1 odpowiednik external ``POST /api/v1/generate`` (multipart wariant),
    ale enqueue + 202 (generacja w tle).

    Old-mode: user wgrywa CV ręcznie, opcjonalnie DOCX championa i notatki ze
    screeningu. Bajty plików czytamy tu (``UploadFile`` nie przeżyje requestu)
    i przekazujemy do zadania w tle, dzięki czemu rekruter może zamknąć kartę —
    wynik ląduje na liście „Wygenerowane CV". Poza wpisem audytowym nic nie
    trafia do NEXUS DB.
    """
    cv_bytes = await cv_file.read()
    champion_bytes: bytes | None = None
    champion_filename: str | None = None
    if champion_file is not None and champion_file.filename:
        champion_bytes = await champion_file.read()
        champion_filename = champion_file.filename

    gen_payload = UploadGenerationInput(
        cv_bytes=cv_bytes,
        cv_filename=cv_file.filename or "cv.pdf",
        language=language,
        blind_cv=blind_cv,
        screening_notes=screening_notes or "",
        champion_bytes=champion_bytes,
        champion_filename=champion_filename,
    )

    # Provisional label until Claude parses the real name out of the CV.
    provisional = Path(cv_file.filename or "").stem or "Nowe CV"
    generated_id = await _create_pending_row(
        db,
        mode="upload",
        candidate_id=None,
        candidate_name=provisional,
        position=None,
        language=language,
        blind_cv=blind_cv,
        user_id=current_user.id,
    )
    await db.commit()

    background_tasks.add_task(
        _run_generate_upload_job,
        generated_id,
        payload=gen_payload,
        user_id=current_user.id,
    )
    return GenerateEnqueuedResponse(
        id=generated_id, status="processing", candidate_name=provisional
    )


# ── Saved-CV list („Wygenerowane CV") ──────────────────────────────────────


@router.get("/generated", response_model=list[GeneratedCvItem])
async def list_generated_cvs(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(60, ge=1, le=200),
):
    """Recently generated CVs for the panel list (newest first).

    ``status`` drives the row's look (spinner while „processing", the CV once
    „ready", the reason on „failed"); the UI polls this endpoint while any row
    is still „processing". ``can_download`` is true only for „ready" rows with a
    saved ``render_payload`` (rows from before this feature have none);
    ``can_delete`` whether the current user may remove the row (author or admin).
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
            status=r.status,
            error_message=r.error_message,
            warnings=list(r.warnings or []),
            created_at=r.created_at.isoformat() if r.created_at else None,
            created_by_name=creator_name,
            can_download=r.status == "ready" and r.render_payload is not None,
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
