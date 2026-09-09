"""Endpointy CV per rekrutacja.

Faza 2 (PR1) — `original` snapshot:
  GET    /api/candidates/stages/{stage_id}/cv/original
  GET    /api/candidates/stages/{stage_id}/cv/original/download
  POST   /api/candidates/stages/{stage_id}/cv/original/refresh

Faza 3 (PR2) — `branded` draft + finalize (mirror Contract Draft):
  GET    /api/candidates/stages/{stage_id}/cv/branded
  PATCH  /api/candidates/stages/{stage_id}/cv/branded
  GET    /api/candidates/stages/{stage_id}/cv/branded/render-pdf
  POST   /api/candidates/stages/{stage_id}/cv/branded/finalize

Faza 4 (PR2) — public share:
  POST   /api/candidates/stages/{stage_id}/cv/share-token
  DELETE /api/candidates/stages/cv/share-token/{token}
  GET    /api/public/cv/{token}                          (osobny router public_share)
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import secrets
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import HTMLResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool
from app.models.cv_document_version import CvDocumentVersion
from app.services.cv_document_assets import (
    generated_assets,
    default_template,
    CvAssetsError,
)
from app.services.cv_approved_docx import (
    render_approved_docx,
    ApprovedDocxError,
    RENDERER_VERSION,
)

from app.core.http_headers import content_disposition_attachment
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.services.cv_html_renderer import _generate_cv_html
from app.services.html_sanitizer import sanitize_cv_html
from app.services.cv_document_versions import check_revision, freeze_approved_version

# M2 audit follow-up (PR1b): the stage-CV snapshot router serves the SAME
# candidate CV bytes that PR1 closed on /api/candidates/*, but only its
# write routes were gated - the reads stayed open to any logged-in role.
# A read-only viewer/client could enumerate sequential stage_id values and
# download every candidate's original + branded CV. Reads now require the
# same CandidateDocumentAccess capability as the canonical document routes.
from app.api.candidate_access import CandidateDocumentAccess, CandidateWriteAccess
from app.api.recruitment_access import ensure_job_membership, ensure_job_read_access
from app.core.database import get_db
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.cv_share_token import CVShareToken
from app.models.cv_generated_document import CvGeneratedDocument
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User, UserRole
from app.schemas.candidate_stage_cv import (
    CVBrandedFinalize,
    CVBrandedNewDraft,
    CVBrandedFinalizeResponse,
    CVBrandedResponse,
    CVBrandedUpdate,
    CVBrandedSelectGenerated,
    CVOriginalSnapshotResponse,
    CVShareTokenListItem,
    CVShareTokenResponse,
)
from app.services import storage_service
from app.services.candidate_stage_cv_service import (
    refresh_original_cv_snapshot,
)
from app.services.hiring_manager_verdicts import veto_for_candidate_stage

logger = logging.getLogger(__name__)
router = APIRouter()


# Default config dla pierwszego renderu brandowanego CV (mirror Contract Draft
# `is_default=True` template). Reuse `_generate_cv_html()` z cv_generator.py.
_DEFAULT_TEMPLATE = "standard"
_DEFAULT_LANGUAGE = "pl"


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


async def _ensure_stage_membership(db: AsyncSession, stage_id: int, user: User) -> None:
    """Resource scope dla tras adresujących etap, które NIE ładują CV przez
    ``_load_csv_for_stage``.

    Dziś jedna taka trasa: ``refresh_original_cv`` buduje snapshot od zera
    (``refresh_original_cv_snapshot``), więc nigdy nie przechodziła przez
    choke point — i jako jedyna w tym routerze nadpisywała CV cudzej
    rekrutacji bez żadnego sprawdzenia. Wyłapane przez
    ``tests/test_job_scope_contract.py``, nie przez czytanie kodu.
    """
    job_id = await db.scalar(
        select(CandidateStage.job_id).where(CandidateStage.id == stage_id)
    )
    if job_id is None:
        raise HTTPException(status_code=404, detail="Stage nie znaleziony")
    await ensure_job_membership(db, user, job_id)


async def _load_csv_for_stage(
    db: AsyncSession,
    stage_id: int,
    user: User,
    *,
    read_access: bool = False,
    lock: bool = False,
) -> CandidateStageCV:
    """Wczytaj CandidateStageCV dla stage_id, 404 gdy brak. Sprawdza tez czy
    sam stage istnieje — żeby rozróżnić "stage nie istnieje" od "stage bez CV".

    Egzekwuje też **resource scope**: `stage_id` niesie `job_id`, więc dostęp do
    CV tej rekrutacji wymaga przynależności do jej zespołu. Rola
    (`CandidateDocumentAccess` / `CandidateWriteAccess`) odpowiada tylko na pytanie
    „czy wolno ci oglądać CV", nie „czy wolno ci oglądać CV **tej**
    rekrutacji" — i to jest dokładnie ta różnica, przez którą łatanie kolejnych
    routerów nigdy nie trzymało (#791 → #815 → #819).

    Guard siedzi TUTAJ, bo to jedyne wejście do CV dla 9 z 11 tras tego
    routera. Gdyby stał w każdej trasie z osobna, następna dopisana trasa
    musiałaby o nim pamiętać — a „trzeba pamiętać" jest właśnie tym trybem
    awarii, który zamykamy.

    Jedno zapytanie (LEFT JOIN), żeby zachować rozróżnienie 404 bez dokładania
    round-tripa do bazy na każdy odczyt CV.
    """
    row = (
        await db.execute(
            select(CandidateStage.job_id, CandidateStageCV)
            .select_from(CandidateStage)
            .outerjoin(
                CandidateStageCV,
                CandidateStageCV.candidate_stage_id == CandidateStage.id,
            )
            .where(CandidateStage.id == stage_id)
        )
    ).first()

    if row is None:
        raise HTTPException(status_code=404, detail="Stage nie znaleziony")

    job_id, csv = row
    if read_access:
        await ensure_job_read_access(db, user, job_id)
    else:
        await ensure_job_membership(db, user, job_id)

    if csv is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "CV instance nie istnieje dla tego stage. "
                "Snapshot powinien być utworzony przy CREATE stage'a — "
                "jeśli stage jest historyczny, uruchom backfill 0070."
            ),
        )
    if lock:
        csv = await db.scalar(
            select(CandidateStageCV)
            .where(CandidateStageCV.id == csv.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    return csv


@router.get(
    "/candidates/stages/{stage_id}/cv/original",
    response_model=CVOriginalSnapshotResponse,
)
async def get_original_cv(
    stage_id: int,
    current_user: CandidateDocumentAccess,
    db: AsyncSession = Depends(get_db),
) -> CVOriginalSnapshotResponse:
    csv = await _load_csv_for_stage(db, stage_id, current_user, read_access=True)
    return _build_original_response(csv)


@router.get("/candidates/stages/{stage_id}/cv/original/download")
async def download_original_cv(
    stage_id: int,
    current_user: CandidateDocumentAccess,
    db: AsyncSession = Depends(get_db),
) -> Response:
    csv = await _load_csv_for_stage(db, stage_id, current_user, read_access=True)
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
            "Content-Disposition": content_disposition_attachment(filename),
            "Content-Length": str(len(csv.original_cv_content)),
        },
    )


@router.post(
    "/candidates/stages/{stage_id}/cv/original/refresh",
    response_model=CVOriginalSnapshotResponse,
)
async def refresh_original_cv(
    stage_id: int,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> CVOriginalSnapshotResponse:
    """Nadpisz snapshot aktualną zawartością CV kandydata (manual refresh).

    Idempotent w tym sensie, że można wołać wielokrotnie — każdorazowo nadpisuje.
    Jeśli kandydat aktualnie nie ma CV → 422 (nie ma czego skopiować).
    """
    await _ensure_stage_membership(db, stage_id, current_user)
    try:
        csv = await refresh_original_cv_snapshot(db, stage_id, user_id=current_user.id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    await db.commit()
    await db.refresh(csv)
    return _build_original_response(csv)


# ── Branded CV — draft + finalize (Faza 3) ─────────────────────────────────


def _wrap_printable_cv(body_html: str, stage_id: int, candidate_label: str) -> str:
    """Wrap HTML w printable wrapper z auto-print (mirror contracts._wrap_printable).

    Body HTML z `_generate_cv_html()` jest już kompletnym dokumentem — przy
    finalize i render-pdf chcemy upewnić się, że ma `window.print()` script.
    Dla CV body zawiera już `<style>` więc dorzucamy tylko script + tytuł.
    """
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        f"<title>CV — {candidate_label} (rekrutacja #{stage_id})</title>"
        "<script>window.addEventListener('load',()=>setTimeout("
        "()=>window.print(),300));</script>"
        "</head><body>"
        f"{body_html}"
        "</body></html>"
    )


async def _load_candidate_and_job(
    db: AsyncSession, csv: CandidateStageCV
) -> tuple[Candidate, Optional[Job]]:
    candidate = await db.scalar(
        select(Candidate).where(Candidate.id == csv.candidate_id)
    )
    if candidate is None:
        raise HTTPException(status_code=404, detail="Kandydat nie znaleziony")
    job = await db.scalar(select(Job).where(Job.id == csv.job_id))
    return candidate, job


def _build_branded_response(
    csv: CandidateStageCV,
    *,
    updated_by_name: Optional[str] = None,
    finalized_by_name: Optional[str] = None,
    rendered_from_default: bool = False,
) -> CVBrandedResponse:
    return CVBrandedResponse(
        candidate_stage_id=csv.candidate_stage_id,
        generated_document_id=csv.generated_document_id,
        from_generator=bool(csv.branded_from_generator),
        docx_available=csv.branded_status == "finalized"
        and bool((csv.branded_render_metadata or {}).get("renderer_version")),
        docx_filename=csv.branded_docx_filename
        if csv.branded_status == "finalized"
        else None,
        edit_revision=csv.edit_revision or 0,
        version=csv.branded_version or 1,
        status=csv.branded_status,  # type: ignore[arg-type]
        content_html=csv.branded_draft_html,
        template=csv.branded_template,
        language=csv.branded_language,
        updated_at=csv.branded_updated_at,
        updated_by=csv.branded_updated_by,
        updated_by_name=updated_by_name,
        finalized_at=csv.branded_finalized_at,
        finalized_by=csv.branded_finalized_by,
        finalized_by_name=finalized_by_name,
        snapshot_filename=csv.branded_snapshot_filename,
        rendered_from_default=rendered_from_default,
    )


def _build_transient_branded_response(
    csv: CandidateStageCV, html: str
) -> CVBrandedResponse:
    """Finance preview for an uninitialized draft without mutating the ORM row."""

    return CVBrandedResponse(
        candidate_stage_id=csv.candidate_stage_id,
        status="draft",
        content_html=html,
        template=_DEFAULT_TEMPLATE,
        language=_DEFAULT_LANGUAGE,
        updated_at=None,
        updated_by=None,
        updated_by_name=None,
        finalized_at=None,
        finalized_by=None,
        finalized_by_name=None,
        snapshot_filename=None,
        rendered_from_default=True,
    )


@router.get(
    "/candidates/stages/{stage_id}/cv/branded",
    response_model=CVBrandedResponse,
)
async def get_branded_cv(
    stage_id: int,
    current_user: CandidateDocumentAccess,
    db: AsyncSession = Depends(get_db),
) -> CVBrandedResponse:
    """Lazy render brandowanego CV — pierwszy GET generuje HTML z `_generate_cv_html()`,
    następne zwracają zachowany content."""
    csv = await _load_csv_for_stage(db, stage_id, current_user, read_access=True)

    rendered = False
    if csv.branded_status == "none":
        candidate, job = await _load_candidate_and_job(db, csv)
        html = _generate_cv_html(candidate, _DEFAULT_TEMPLATE, _DEFAULT_LANGUAGE, job)
        if current_user.has_role(UserRole.finance):
            return _build_transient_branded_response(csv, html)
        csv = await _load_csv_for_stage(db, stage_id, current_user, lock=True)
        if csv.branded_status != "none":
            return _build_branded_response(csv)
        csv.branded_draft_html = html
        csv.branded_template = _DEFAULT_TEMPLATE
        csv.branded_language = _DEFAULT_LANGUAGE
        csv.branded_status = "draft"
        csv.edit_revision += 1
        csv.branded_updated_at = datetime.now(timezone.utc)
        csv.branded_updated_by = current_user.id
        rendered = True
        db.add(
            Activity(
                entity_type="candidate_stage_cv",
                entity_id=csv.id,
                action="branded_cv_initialized",
                user_id=current_user.id,
                details={
                    "candidate_stage_id": stage_id,
                    "template": _DEFAULT_TEMPLATE,
                    "language": _DEFAULT_LANGUAGE,
                },
            )
        )
        await db.commit()
        await db.refresh(csv)

    updated_by_name: Optional[str] = None
    if csv.branded_updated_by:
        updated_by_name = await db.scalar(
            select(User.email).where(User.id == csv.branded_updated_by)
        )
    finalized_by_name: Optional[str] = None
    if csv.branded_finalized_by:
        finalized_by_name = await db.scalar(
            select(User.email).where(User.id == csv.branded_finalized_by)
        )

    return _build_branded_response(
        csv,
        updated_by_name=updated_by_name,
        finalized_by_name=finalized_by_name,
        rendered_from_default=rendered,
    )


@router.post(
    "/candidates/stages/{stage_id}/cv/branded/select-generated",
    response_model=CVBrandedResponse,
)
async def select_generated_cv(
    stage_id: int,
    payload: CVBrandedSelectGenerated,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> CVBrandedResponse:
    """Explicitly replace the current draft with this process's generated CV.

    Row lock + revision prevent overwriting edits made since selection. Previous
    approvals and their public links remain pinned before a new draft is opened.
    No model call and no regeneration from Candidate fields occurs here.
    """
    csv = await _load_csv_for_stage(db, stage_id, current_user, lock=True)
    check_revision(csv, payload.expected_revision)
    generated = await db.get(CvGeneratedDocument, payload.generated_document_id)
    if (
        generated is None
        or generated.candidate_id != csv.candidate_id
        or generated.job_id != csv.job_id
    ):
        raise HTTPException(404, "Nie znaleziono CV tego kandydata w tej rekrutacji.")
    if generated.status != "ready" or not generated.render_payload:
        raise HTTPException(422, "Wybierz zakończoną generację CV.")
    from app.services.cv_generator_b2b.html_export import render_interactive_html
    from app.services.cv_generator_b2b.public_view import build_public_payload

    try:
        template, consent, metadata = await run_in_threadpool(
            generated_assets, generated
        )
    except CvAssetsError as error:
        raise HTTPException(422, str(error)) from error
    public = build_public_payload(generated.render_payload)
    html = sanitize_cv_html(render_interactive_html(public, [], document_only=True))
    from app.services.cv_approval_provenance import capture_editor_origin

    metadata.update(
        capture_editor_origin(
            html, generated.render_payload.get("factual_verification")
        )
    )
    if csv.branded_status == "finalized":
        await freeze_approved_version(db, csv)
        csv.branded_version += 1
    csv.generated_document_id = generated.id
    csv.branded_from_generator = True
    csv.branded_template_content = template
    csv.branded_consent_content = consent
    csv.branded_docx_filename = generated.filename
    csv.branded_render_metadata = metadata
    csv.branded_draft_html = html
    csv.branded_template = "blind" if public["blind"] else "standard"
    csv.branded_language = public["language"]
    csv.branded_status = "draft"
    csv.edit_revision += 1
    csv.branded_updated_at = datetime.now(timezone.utc)
    csv.branded_updated_by = current_user.id
    csv.branded_finalized_at = None
    csv.branded_finalized_by = None
    csv.branded_snapshot_path = None
    csv.branded_snapshot_filename = None
    csv.branded_snapshot_size_bytes = None
    db.add(
        Activity(
            entity_type="candidate_stage_cv",
            entity_id=csv.id,
            action="branded_cv_selected_from_generator",
            user_id=current_user.id,
            details={
                "candidate_stage_id": stage_id,
                "generated_document_id": generated.id,
                "version": csv.branded_version,
                "edit_revision": csv.edit_revision,
            },
        )
    )
    await db.commit()
    await db.refresh(csv)
    return _build_branded_response(csv)


@router.patch(
    "/candidates/stages/{stage_id}/cv/branded",
    response_model=CVBrandedResponse,
)
async def update_branded_cv(
    stage_id: int,
    payload: CVBrandedUpdate,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> CVBrandedResponse:
    """Update brandowanego CV — XOR `content_html` (save) / `template+language` (re-render).

    Walidacja XOR jest w `CVBrandedUpdate.model_validator`. Po finalize 409.
    """
    csv = await _load_csv_for_stage(db, stage_id, current_user, lock=True)
    check_revision(csv, payload.expected_revision)
    if csv.branded_status == "finalized":
        raise HTTPException(
            status_code=409,
            detail=(
                "CV jest zatwierdzone. Utwórz nową wersję, aby wprowadzić poprawki; "
                "dotychczasowe linki zachowają wcześniejszą treść."
            ),
        )

    action: str
    details: dict
    if payload.content_html is not None:
        csv.branded_draft_html = sanitize_cv_html(payload.content_html)
        action = "branded_cv_edited"
        details = {"length": len(csv.branded_draft_html)}
    else:
        if csv.branded_from_generator:
            raise HTTPException(
                409,
                "To CV pochodzi z generatora. Zmień treść w edytorze lub wybierz "
                "nowy wynik generatora we właściwym języku i szablonie.",
            )
        # Re-render branch — wymaga template+language (jeden lub oba mogą być
        # podane; brakujące biorą wartość obecną).
        new_template = payload.template or csv.branded_template or _DEFAULT_TEMPLATE
        new_language = payload.language or csv.branded_language or _DEFAULT_LANGUAGE
        candidate, job = await _load_candidate_and_job(db, csv)
        csv.branded_draft_html = _generate_cv_html(
            candidate, new_template, new_language, job
        )
        csv.branded_template = new_template
        csv.branded_language = new_language
        action = "branded_cv_template_changed"
        details = {"template": new_template, "language": new_language}

    if csv.branded_status == "none":
        csv.branded_status = "draft"
    csv.edit_revision += 1
    csv.branded_updated_at = datetime.now(timezone.utc)
    csv.branded_updated_by = current_user.id
    db.add(
        Activity(
            entity_type="candidate_stage_cv",
            entity_id=csv.id,
            action=action,
            user_id=current_user.id,
            details={"candidate_stage_id": stage_id, **details},
        )
    )
    await db.commit()
    await db.refresh(csv)

    updated_by_name = await db.scalar(
        select(User.email).where(User.id == current_user.id)
    )
    return _build_branded_response(csv, updated_by_name=updated_by_name)


@router.get(
    "/candidates/stages/{stage_id}/cv/branded/render-pdf",
    response_class=HTMLResponse,
)
async def render_branded_cv_for_print(
    stage_id: int,
    current_user: CandidateDocumentAccess,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Wrap brandowane CV w printable HTML z auto window.print() — FE otwiera w
    nowej karcie i drukuje (Save as PDF)."""
    csv = await _load_csv_for_stage(db, stage_id, current_user, read_access=True)
    draft_html = csv.branded_draft_html
    candidate: Optional[Candidate] = None
    if not draft_html and current_user.has_role(UserRole.finance):
        candidate, job = await _load_candidate_and_job(db, csv)
        draft_html = _generate_cv_html(
            candidate, _DEFAULT_TEMPLATE, _DEFAULT_LANGUAGE, job
        )
    if not draft_html:
        raise HTTPException(
            status_code=404,
            detail="Brandowane CV jest puste — otwórz edytor pierwszy raz, by je wygenerować.",
        )
    if candidate is None:
        candidate = await db.scalar(
            select(Candidate).where(Candidate.id == csv.candidate_id)
        )
    label = (
        f"{candidate.name} {candidate.lastname}" if candidate else f"stage_{stage_id}"
    )
    # M4 PR-04 (audyt P1.9): printable HTML przechodzi allowlist sanitizer —
    # authenticated flow otwiera blob text/html w nowej karcie.
    return HTMLResponse(
        content=_wrap_printable_cv(sanitize_cv_html(draft_html), stage_id, label)
    )


async def _render_editor_docx(csv, content_html: str) -> tuple[bytes, bytes]:
    template = csv.branded_template_content or await run_in_threadpool(default_template)
    try:
        docx = await run_in_threadpool(
            render_approved_docx,
            sanitize_cv_html(content_html),
            template,
            consent=csv.branded_consent_content,
            language=csv.branded_language or "pl",
        )
    except ApprovedDocxError as error:
        raise HTTPException(422, str(error)) from error
    return docx, template


@router.post("/candidates/stages/{stage_id}/cv/branded/preview-docx")
async def preview_branded_docx(
    stage_id: int,
    payload: CVBrandedFinalize,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Render the current editor contents and frozen assets without approval."""
    csv = await _load_csv_for_stage(db, stage_id, current_user, lock=True)
    check_revision(csv, payload.expected_revision)
    if csv.branded_status != "draft":
        raise HTTPException(
            409, "Podgląd dotyczy szkicu. Pobierz zatwierdzoną wersję CV."
        )
    docx, _ = await _render_editor_docx(csv, payload.content_html)
    return Response(
        content=docx,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": content_disposition_attachment(
                "SZKIC_"
                + (csv.branded_docx_filename or f"CV_v{csv.branded_version}.docx")
            ),
            "Cache-Control": "private, no-store",
        },
    )


@router.post(
    "/candidates/stages/{stage_id}/cv/branded/finalize",
    response_model=CVBrandedFinalizeResponse,
)
async def finalize_branded_cv(
    stage_id: int,
    payload: CVBrandedFinalize,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> CVBrandedFinalizeResponse:
    """Snapshot brandowanego draftu → storage_service + status `draft → finalized`.

    Po finalize:
    * `branded_draft_html` zostaje w DB (ostatnia edytowalna wersja, do podglądu),
    * `branded_snapshot_path/filename/size` wskazuje na plik HTML w storage,
    * 409 przy próbie kolejnego PATCH — immutable.
    """
    csv = await _load_csv_for_stage(db, stage_id, current_user, lock=True)
    check_revision(csv, payload.expected_revision)
    if csv.branded_status != "draft":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Branded CV is in status '{csv.branded_status}', "
                "expected 'draft' to finalize."
            ),
        )
    csv.branded_draft_html = sanitize_cv_html(payload.content_html)
    if not csv.branded_draft_html.strip():
        raise HTTPException(
            status_code=422,
            detail="Brandowane CV jest puste — wygeneruj treść przed finalize.",
        )

    candidate = await db.scalar(
        select(Candidate).where(Candidate.id == csv.candidate_id)
    )
    candidate_label = (
        f"{candidate.name}_{candidate.lastname}".replace(" ", "_")
        if candidate
        else f"stage_{stage_id}"
    )
    today = datetime.now(timezone.utc).date().isoformat()
    filename = f"cv_brandowane_{candidate_label}_v{csv.branded_version}_{today}.html"

    # Render the exact submitted/sanitized content once, before approval. The
    # stored bytes are subsequently downloaded without accessing live sources.
    docx, template = await _render_editor_docx(csv, csv.branded_draft_html)
    docx_filename = (
        csv.branded_docx_filename or filename.removesuffix(".html") + ".docx"
    )
    from app.services.cv_approval_provenance import approval_provenance

    metadata = {
        **(csv.branded_render_metadata or {}),
        **approval_provenance(csv.branded_draft_html, csv.branded_render_metadata),
        "renderer_version": RENDERER_VERSION,
        "template_sha256": hashlib.sha256(template).hexdigest(),
        "consent_sha256": hashlib.sha256(csv.branded_consent_content).hexdigest()
        if csv.branded_consent_content
        else None,
    }
    snapshot_html = _wrap_printable_cv(
        csv.branded_draft_html, stage_id, candidate_label
    )
    blob = snapshot_html.encode("utf-8")
    relative_path, size = storage_service.save_branded_cv(
        candidate_stage_id=stage_id,
        upload_filename=filename,
        source=BytesIO(blob),
    )

    csv.edit_revision += 1
    csv.branded_updated_at = datetime.now(timezone.utc)
    csv.branded_updated_by = current_user.id
    csv.branded_status = "finalized"
    csv.branded_finalized_at = datetime.now(timezone.utc)
    csv.branded_finalized_by = current_user.id
    csv.branded_snapshot_path = relative_path
    csv.branded_snapshot_filename = filename
    csv.branded_snapshot_size_bytes = size

    csv.branded_docx_filename = docx_filename
    csv.branded_render_metadata = metadata
    version = await freeze_approved_version(
        db,
        csv,
        docx_content=docx,
        docx_filename=docx_filename,
        render_metadata=metadata,
    )
    db.add(
        Activity(
            entity_type="candidate_stage_cv",
            entity_id=csv.id,
            action="branded_cv_finalized",
            user_id=current_user.id,
            details={
                "candidate_stage_id": stage_id,
                "snapshot_filename": filename,
                "size_bytes": size,
                "document_version_id": version.id,
                "version": version.version,
                "content_sha256": version.content_sha256,
            },
        )
    )
    await db.commit()
    await db.refresh(csv)

    return CVBrandedFinalizeResponse(
        candidate_stage_id=csv.candidate_stage_id,
        edit_revision=csv.edit_revision or 0,
        version=csv.branded_version or 1,
        status=csv.branded_status,  # type: ignore[arg-type]
        snapshot_filename=filename,
        snapshot_size_bytes=size,
        document_version_id=version.id,
    )


@router.get("/candidates/stages/{stage_id}/cv/branded/versions/{version_number}/docx")
async def download_approved_docx(
    stage_id: int,
    version_number: int,
    current_user: CandidateDocumentAccess,
    db: AsyncSession = Depends(get_db),
) -> Response:
    csv = await _load_csv_for_stage(db, stage_id, current_user, read_access=True)
    version = await db.scalar(
        select(CvDocumentVersion).where(
            CvDocumentVersion.candidate_stage_cv_id == csv.id,
            CvDocumentVersion.version == version_number,
        )
    )
    if version is None:
        raise HTTPException(404, "Nie znaleziono zatwierdzonej wersji CV.")
    if not version.docx_content:
        raise HTTPException(
            409,
            "Ta historyczna wersja nie ma zatwierdzonego DOCX. Utwórz i zatwierdź nową wersję.",
        )
    return Response(
        content=version.docx_content,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": content_disposition_attachment(
                version.docx_filename or "CV.docx"
            ),
            "ETag": f'"{version.docx_sha256}"',
            "X-CV-Version": str(version.version),
            "X-CV-Content-SHA256": version.content_sha256,
            "Cache-Control": "private, no-store",
        },
    )


@router.post(
    "/candidates/stages/{stage_id}/cv/branded/new-draft",
    response_model=CVBrandedResponse,
)
async def new_branded_cv_draft(
    stage_id: int,
    payload: CVBrandedNewDraft,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> CVBrandedResponse:
    csv = await _load_csv_for_stage(db, stage_id, current_user, lock=True)
    check_revision(csv, payload.expected_revision)
    previous = await freeze_approved_version(db, csv)
    csv.branded_version += 1
    csv.edit_revision += 1
    csv.branded_status = "draft"
    csv.branded_updated_at = datetime.now(timezone.utc)
    csv.branded_updated_by = current_user.id
    csv.branded_finalized_at = None
    csv.branded_finalized_by = None
    csv.branded_snapshot_path = None
    csv.branded_snapshot_filename = None
    csv.branded_snapshot_size_bytes = None
    db.add(
        Activity(
            entity_type="candidate_stage_cv",
            entity_id=csv.id,
            action="branded_cv_new_version",
            user_id=current_user.id,
            details={
                "candidate_stage_id": stage_id,
                "previous_version_id": previous.id,
                "version": csv.branded_version,
            },
        )
    )
    await db.commit()
    return _build_branded_response(csv)


# ── Public share token (Faza 4 — auth side) ────────────────────────────────


_SHARE_PATH_PREFIX = "/cv/"


@router.post(
    "/candidates/stages/{stage_id}/cv/share-token",
    response_model=CVShareTokenResponse,
    status_code=201,
)
async def create_cv_share_token(
    stage_id: int,
    current_user: CandidateWriteAccess,
    expires_in_days: int = Query(14, ge=1, le=90),
    max_views: Optional[int] = Query(None, ge=1, le=1000),
    purpose: Optional[str] = Query(None, max_length=120),
    db: AsyncSession = Depends(get_db),
) -> CVShareTokenResponse:
    """Generuje token-link do brandowanego CV. Wymaga statusu `finalized`.

    M4 PR-04 (audyt P1.9, token v2): sekret NIE jest zapisywany — w DB ląduje
    wyłącznie SHA-256 (`token_sha256`), a PK dostaje nie-sekretny identyfikator
    `v2$<hex>` (revoke-key). Raw token zwracamy jeden raz. Domyślny TTL
    skrócony 30 → 14 dni (max 90); opcjonalny limit wyświetleń i purpose.
    """
    csv = await _load_csv_for_stage(db, stage_id, current_user, lock=True)
    if csv.branded_status != "finalized":
        raise HTTPException(
            status_code=409,
            detail=("Nie można udostępnić draftu — najpierw zfinalizuj brandowane CV."),
        )

    # Last line before the CV reaches the client. The assignment gate does not
    # cover pipelines created before this feature, nor a reason flagged
    # disqualifying after the fact.
    verdict = await veto_for_candidate_stage(db, candidate_stage_id=stage_id)
    if verdict is not None:
        raise HTTPException(
            status_code=409,
            detail=f"{verdict.as_polish_detail()} Nie wysyłaj mu ponownie tego CV.",
        )

    version = await freeze_approved_version(db, csv)
    raw_token = secrets.token_urlsafe(36)
    revoke_key = f"v2${secrets.token_hex(16)}"
    token_digest = hashlib.sha256(raw_token.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)
    db.add(
        CVShareToken(
            token=revoke_key,
            token_sha256=token_digest,
            candidate_stage_cv_id=csv.id,
            document_version_id=version.id,
            created_by=current_user.id,
            expires_at=expires_at,
            max_views=max_views,
            purpose=purpose,
        )
    )
    db.add(
        Activity(
            entity_type="candidate_stage_cv",
            entity_id=csv.id,
            action="cv_share_created",
            user_id=current_user.id,
            details={
                "candidate_stage_id": stage_id,
                "expires_at": expires_at.isoformat(),
                "revoke_key": revoke_key,
                "max_views": max_views,
                "purpose": purpose,
            },
        )
    )
    await db.commit()

    return CVShareTokenResponse(
        token=raw_token,
        expires_at=expires_at,
        share_url_suffix=f"{_SHARE_PATH_PREFIX}{raw_token}",
        candidate_stage_cv_id=csv.id,
        revoke_key=revoke_key,
        max_views=max_views,
    )


def _token_list_item(row: CVShareToken) -> CVShareTokenListItem:
    is_v2 = row.token_sha256 is not None
    return CVShareTokenListItem(
        revoke_key=row.token,
        token_preview=(
            f"v2 · {row.token_sha256[:6]}…" if is_v2 else f"{row.token[:8]}…"
        ),
        is_v2=is_v2,
        created_at=row.created_at,
        created_by_name=(row.creator.name if row.creator else None),
        expires_at=row.expires_at,
        revoked=row.revoked,
        revoked_at=row.revoked_at,
        revoke_reason=row.revoke_reason,
        view_count=row.view_count or 0,
        max_views=row.max_views,
        last_viewed_at=row.last_viewed_at,
        purpose=row.purpose,
        # Legacy: raw w DB — URL odtwarzalny (i tak jest w obiegu).
        # v2: sekret nieodtwarzalny — None.
        share_url_suffix=(None if is_v2 else f"{_SHARE_PATH_PREFIX}{row.token}"),
    )


@router.get(
    "/candidates/stages/{stage_id}/cv/share-tokens",
    response_model=list[CVShareTokenListItem],
)
async def list_cv_share_tokens(
    stage_id: int,
    current_user: CandidateDocumentAccess,
    db: AsyncSession = Depends(get_db),
) -> list[CVShareTokenListItem]:
    """Lista linków (aktywnych i odwołanych) dla CV tego stage'a — bez
    sekretów. M4 PR-04: dotąd modal gubił token po zamknięciu i nie dało się
    odwołać wcześniejszych linków (audyt P1.9 dead-end)."""
    csv = await _load_csv_for_stage(db, stage_id, current_user, read_access=True)
    rows = (
        (
            await db.execute(
                select(CVShareToken)
                .options(selectinload(CVShareToken.creator))
                .where(CVShareToken.candidate_stage_cv_id == csv.id)
                .order_by(CVShareToken.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [_token_list_item(r) for r in rows]


@router.delete("/candidates/stages/cv/share-token/{token}")
async def revoke_cv_share_token(
    token: str,
    current_user: CandidateWriteAccess,
    reason: Optional[str] = Query(None, max_length=255),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Odwołaj share token. Idempotent.

    Przyjmuje revoke-key (`v2$...`), legacy raw token (BC) albo raw token v2
    (lookup po hashu — okładka na wypadek, gdy caller ma tylko link).
    """
    digest = hashlib.sha256(token.encode()).hexdigest()
    row = await db.scalar(
        select(CVShareToken).where(
            (CVShareToken.token == token) | (CVShareToken.token_sha256 == digest)
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Token nie znaleziony")

    # Resource scope — ta trasa jako jedyna w routerze adresuje zasób tokenem,
    # nie `stage_id`, więc nie przechodzi przez `_load_csv_for_stage`.
    # Rekrutację wyprowadzamy z łańcucha token → CandidateStageCV → CandidateStage.
    # Sprawdzenie idzie PRZED wyjściem po `already_revoked`, żeby ta gałąź nie
    # potwierdzała obcemu użytkownikowi istnienia i stanu cudzego tokenu.
    job_id = await db.scalar(
        select(CandidateStage.job_id)
        .select_from(CandidateStageCV)
        .join(CandidateStage, CandidateStage.id == CandidateStageCV.candidate_stage_id)
        .where(CandidateStageCV.id == row.candidate_stage_cv_id)
    )
    if job_id is None:
        raise HTTPException(status_code=404, detail="Token nie znaleziony")
    await ensure_job_membership(db, current_user, job_id)

    if row.revoked:
        return {"status": "already_revoked", "token": row.token}

    await db.execute(
        update(CVShareToken)
        .where(CVShareToken.token == row.token)
        .values(
            revoked=True,
            revoked_at=datetime.now(timezone.utc),
            revoked_by=current_user.id,
            revoke_reason=reason,
        )
    )
    db.add(
        Activity(
            entity_type="candidate_stage_cv",
            entity_id=row.candidate_stage_cv_id,
            action="cv_share_revoked",
            user_id=current_user.id,
            details={"revoke_key": row.token, "reason": reason},
        )
    )
    await db.commit()
    return {"status": "revoked", "token": row.token}


@router.delete("/candidates/stages/{stage_id}/cv/share-tokens")
async def revoke_all_cv_share_tokens(
    stage_id: int,
    current_user: CandidateWriteAccess,
    reason: Optional[str] = Query(None, max_length=255),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Odwołaj WSZYSTKIE aktywne linki CV tego stage'a (M4 PR-04)."""
    csv = await _load_csv_for_stage(db, stage_id, current_user)
    result = await db.execute(
        update(CVShareToken)
        .where(
            CVShareToken.candidate_stage_cv_id == csv.id,
            CVShareToken.revoked.is_(False),
        )
        .values(
            revoked=True,
            revoked_at=datetime.now(timezone.utc),
            revoked_by=current_user.id,
            revoke_reason=reason,
        )
    )
    db.add(
        Activity(
            entity_type="candidate_stage_cv",
            entity_id=csv.id,
            action="cv_share_revoked_all",
            user_id=current_user.id,
            details={"count": result.rowcount or 0, "reason": reason},
        )
    )
    await db.commit()
    return {"status": "revoked_all", "count": result.rowcount or 0}
