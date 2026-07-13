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

import logging
import mimetypes
import secrets
from datetime import datetime, timedelta, timezone
from html import escape
from io import BytesIO
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import HTMLResponse, StreamingResponse

from app.core.http_headers import content_disposition_attachment
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.cv_html_renderer import _generate_cv_html
from app.api.deps import (
    CurrentUser,
    DocumentReader,
    RecruiterPlus,
    is_read_only_viewer,
)
from app.core.database import get_db
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.cv_share_token import CVShareToken
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User
from app.schemas.candidate_stage_cv import (
    CVBrandedFinalizeResponse,
    CVBrandedResponse,
    CVBrandedUpdate,
    CVOriginalSnapshotResponse,
    CVShareTokenResponse,
)
from app.services import storage_service
from app.services.security_audit import record_sensitive_read
from app.services.cv_html_security import sanitize_branded_cv_html
from app.services.m365.html_sanitize import sanitize_html
from app.services.candidate_stage_cv_service import (
    refresh_original_cv_snapshot,
)

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


async def _load_csv_for_stage(db: AsyncSession, stage_id: int) -> CandidateStageCV:
    """Wczytaj CandidateStageCV dla stage_id, 404 gdy brak. Sprawdza tez czy
    sam stage istnieje — żeby rozróżnić "stage nie istnieje" od "stage bez CV"."""
    csv = await db.scalar(
        select(CandidateStageCV).where(CandidateStageCV.candidate_stage_id == stage_id)
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
    current_user: DocumentReader,
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

    await record_sensitive_read(
        db,
        user=current_user,
        entity_type="candidate_stage_cv",
        entity_id=csv.id,
        action="document_downloaded",
        details={"candidate_stage_id": stage_id, "document_type": "original_cv"},
    )

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
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> CVOriginalSnapshotResponse:
    """Nadpisz snapshot aktualną zawartością CV kandydata (manual refresh).

    Idempotent w tym sensie, że można wołać wielokrotnie — każdorazowo nadpisuje.
    Jeśli kandydat aktualnie nie ma CV → 422 (nie ma czego skopiować).
    """
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
    safe_label = escape(candidate_label)
    safe_body = sanitize_branded_cv_html(body_html)
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        f"<title>CV — {safe_label} (rekrutacja #{stage_id})</title>"
        "<script>window.addEventListener('load',()=>setTimeout("
        "()=>window.print(),300));</script>"
        "</head><body>"
        f"{safe_body}"
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
    content_html_override: Optional[str] = None,
    status_override: Optional[str] = None,
    template_override: Optional[str] = None,
    language_override: Optional[str] = None,
) -> CVBrandedResponse:
    content_html = (
        content_html_override
        if content_html_override is not None
        else csv.branded_draft_html
    )
    return CVBrandedResponse(
        candidate_stage_id=csv.candidate_stage_id,
        status=status_override or csv.branded_status,  # type: ignore[arg-type]
        content_html=(
            sanitize_branded_cv_html(content_html) if content_html is not None else None
        ),
        template=template_override or csv.branded_template,
        language=language_override or csv.branded_language,
        updated_at=csv.branded_updated_at,
        updated_by=csv.branded_updated_by,
        updated_by_name=updated_by_name,
        finalized_at=csv.branded_finalized_at,
        finalized_by=csv.branded_finalized_by,
        finalized_by_name=finalized_by_name,
        snapshot_filename=csv.branded_snapshot_filename,
        rendered_from_default=rendered_from_default,
    )


@router.get(
    "/candidates/stages/{stage_id}/cv/branded",
    response_model=CVBrandedResponse,
)
async def get_branded_cv(
    stage_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> CVBrandedResponse:
    """Lazy render brandowanego CV — pierwszy GET generuje HTML z `_generate_cv_html()`,
    następne zwracają zachowany content."""
    csv = await _load_csv_for_stage(db, stage_id)

    rendered = False
    if csv.branded_status == "none":
        candidate, job = await _load_candidate_and_job(db, csv)
        html = _generate_cv_html(candidate, _DEFAULT_TEMPLATE, _DEFAULT_LANGUAGE, job)
        if is_read_only_viewer(current_user):
            # A viewer may inspect the generated preview, but a GET from a
            # read-only principal must never initialize or update DB state.
            return _build_branded_response(
                csv,
                rendered_from_default=True,
                content_html_override=html,
                status_override="draft",
                template_override=_DEFAULT_TEMPLATE,
                language_override=_DEFAULT_LANGUAGE,
            )
        csv.branded_draft_html = html
        csv.branded_template = _DEFAULT_TEMPLATE
        csv.branded_language = _DEFAULT_LANGUAGE
        csv.branded_status = "draft"
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


@router.patch(
    "/candidates/stages/{stage_id}/cv/branded",
    response_model=CVBrandedResponse,
)
async def update_branded_cv(
    stage_id: int,
    payload: CVBrandedUpdate,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> CVBrandedResponse:
    """Update brandowanego CV — XOR `content_html` (save) / `template+language` (re-render).

    Walidacja XOR jest w `CVBrandedUpdate.model_validator`. Po finalize 409.
    """
    csv = await _load_csv_for_stage(db, stage_id)
    if csv.branded_status == "finalized":
        raise HTTPException(
            status_code=409,
            detail=(
                "Brandowane CV jest sfinalizowane (immutable). Aby zaktualizować — "
                "odwołaj wszystkie share-tokens i zresetuj draft (TODO)."
            ),
        )

    action: str
    details: dict
    if payload.content_html is not None:
        csv.branded_draft_html = sanitize_html(payload.content_html)
        action = "branded_cv_edited"
        details = {"length": len(csv.branded_draft_html)}
    else:
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
    current_user: DocumentReader,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Wrap brandowane CV w printable HTML z auto window.print() — FE otwiera w
    nowej karcie i drukuje (Save as PDF)."""
    csv = await _load_csv_for_stage(db, stage_id)
    if not csv.branded_draft_html:
        raise HTTPException(
            status_code=404,
            detail="Brandowane CV jest puste — otwórz edytor pierwszy raz, by je wygenerować.",
        )
    candidate = await db.scalar(
        select(Candidate).where(Candidate.id == csv.candidate_id)
    )
    label = (
        f"{candidate.name} {candidate.lastname}" if candidate else f"stage_{stage_id}"
    )
    await record_sensitive_read(
        db,
        user=current_user,
        entity_type="candidate_stage_cv",
        entity_id=csv.id,
        action="document_downloaded",
        details={"candidate_stage_id": stage_id, "document_type": "branded_cv"},
    )
    return HTMLResponse(
        content=_wrap_printable_cv(csv.branded_draft_html, stage_id, label)
    )


@router.post(
    "/candidates/stages/{stage_id}/cv/branded/finalize",
    response_model=CVBrandedFinalizeResponse,
)
async def finalize_branded_cv(
    stage_id: int,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> CVBrandedFinalizeResponse:
    """Snapshot brandowanego draftu → storage_service + status `draft → finalized`.

    Po finalize:
    * `branded_draft_html` zostaje w DB (ostatnia edytowalna wersja, do podglądu),
    * `branded_snapshot_path/filename/size` wskazuje na plik HTML w storage,
    * 409 przy próbie kolejnego PATCH — immutable.
    """
    csv = await _load_csv_for_stage(db, stage_id)
    if csv.branded_status != "draft":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Branded CV is in status '{csv.branded_status}', "
                "expected 'draft' to finalize."
            ),
        )
    if not csv.branded_draft_html:
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
    filename = f"cv_brandowane_{candidate_label}_{today}.html"

    snapshot_html = _wrap_printable_cv(
        csv.branded_draft_html, stage_id, candidate_label
    )
    blob = snapshot_html.encode("utf-8")
    relative_path, size = storage_service.save_branded_cv(
        candidate_stage_id=stage_id,
        upload_filename=filename,
        source=BytesIO(blob),
    )

    csv.branded_status = "finalized"
    csv.branded_finalized_at = datetime.now(timezone.utc)
    csv.branded_finalized_by = current_user.id
    csv.branded_snapshot_path = relative_path
    csv.branded_snapshot_filename = filename
    csv.branded_snapshot_size_bytes = size

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
            },
        )
    )
    await db.commit()
    await db.refresh(csv)

    return CVBrandedFinalizeResponse(
        candidate_stage_id=csv.candidate_stage_id,
        status=csv.branded_status,  # type: ignore[arg-type]
        snapshot_filename=filename,
        snapshot_size_bytes=size,
    )


# ── Public share token (Faza 4 — auth side) ────────────────────────────────


_SHARE_PATH_PREFIX = "/cv/"


@router.post(
    "/candidates/stages/{stage_id}/cv/share-token",
    response_model=CVShareTokenResponse,
    status_code=201,
)
async def create_cv_share_token(
    stage_id: int,
    current_user: RecruiterPlus,
    expires_in_days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> CVShareTokenResponse:
    """Generuje token-link do brandowanego CV. Wymaga statusu `finalized`."""
    csv = await _load_csv_for_stage(db, stage_id)
    if csv.branded_status != "finalized":
        raise HTTPException(
            status_code=409,
            detail=("Nie można udostępnić draftu — najpierw zfinalizuj brandowane CV."),
        )

    token = secrets.token_urlsafe(36)
    expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)
    db.add(
        CVShareToken(
            token=token,
            candidate_stage_cv_id=csv.id,
            created_by=current_user.id,
            expires_at=expires_at,
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
                "token_prefix": token[:8],
            },
        )
    )
    await db.commit()

    return CVShareTokenResponse(
        token=token,
        expires_at=expires_at,
        share_url_suffix=f"{_SHARE_PATH_PREFIX}{token}",
        candidate_stage_cv_id=csv.id,
    )


@router.delete("/candidates/stages/cv/share-token/{token}")
async def revoke_cv_share_token(
    token: str,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Odwołaj share token (`revoked=true`). Idempotent."""
    row = await db.scalar(select(CVShareToken).where(CVShareToken.token == token))
    if row is None:
        raise HTTPException(status_code=404, detail="Token nie znaleziony")
    if row.revoked:
        return {"status": "already_revoked", "token": token}

    await db.execute(
        update(CVShareToken).where(CVShareToken.token == token).values(revoked=True)
    )
    db.add(
        Activity(
            entity_type="candidate_stage_cv",
            entity_id=row.candidate_stage_cv_id,
            action="cv_share_revoked",
            user_id=current_user.id,
            details={"token_prefix": token[:8]},
        )
    )
    await db.commit()
    return {"status": "revoked", "token": token}
