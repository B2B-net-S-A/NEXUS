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

from app.core.http_headers import content_disposition_attachment
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.services.cv_html_renderer import _generate_cv_html
from app.services.html_sanitizer import sanitize_cv_html

# M2 audit follow-up (PR1b): the stage-CV snapshot router serves the SAME
# candidate CV bytes that PR1 closed on /api/candidates/*, but only its
# write routes were gated - the reads stayed open to any logged-in role.
# A read-only viewer/client could enumerate sequential stage_id values and
# download every candidate's original + branded CV. Reads now require the
# same CandidateDocumentAccess capability as the canonical document routes.
from app.api.candidate_access import CandidateDocumentAccess
from app.api.deps import RecruiterPlus
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
    current_user: CandidateDocumentAccess,
    db: AsyncSession = Depends(get_db),
) -> CVOriginalSnapshotResponse:
    csv = await _load_csv_for_stage(db, stage_id)
    return _build_original_response(csv)


@router.get("/candidates/stages/{stage_id}/cv/original/download")
async def download_original_cv(
    stage_id: int,
    current_user: CandidateDocumentAccess,
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
    csv = await _load_csv_for_stage(db, stage_id)

    rendered = False
    if csv.branded_status == "none":
        candidate, job = await _load_candidate_and_job(db, csv)
        html = _generate_cv_html(candidate, _DEFAULT_TEMPLATE, _DEFAULT_LANGUAGE, job)
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
        csv.branded_draft_html = payload.content_html
        action = "branded_cv_edited"
        details = {"length": len(payload.content_html)}
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
    current_user: CandidateDocumentAccess,
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
    # M4 PR-04 (audyt P1.9): printable HTML przechodzi allowlist sanitizer —
    # authenticated flow otwiera blob text/html w nowej karcie.
    return HTMLResponse(
        content=_wrap_printable_cv(
            sanitize_cv_html(csv.branded_draft_html), stage_id, label
        )
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
    csv = await _load_csv_for_stage(db, stage_id)
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

    raw_token = secrets.token_urlsafe(36)
    revoke_key = f"v2${secrets.token_hex(16)}"
    token_digest = hashlib.sha256(raw_token.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)
    db.add(
        CVShareToken(
            token=revoke_key,
            token_sha256=token_digest,
            candidate_stage_cv_id=csv.id,
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
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> list[CVShareTokenListItem]:
    """Lista linków (aktywnych i odwołanych) dla CV tego stage'a — bez
    sekretów. M4 PR-04: dotąd modal gubił token po zamknięciu i nie dało się
    odwołać wcześniejszych linków (audyt P1.9 dead-end)."""
    csv = await _load_csv_for_stage(db, stage_id)
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
    current_user: RecruiterPlus,
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
    current_user: RecruiterPlus,
    reason: Optional[str] = Query(None, max_length=255),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Odwołaj WSZYSTKIE aktywne linki CV tego stage'a (M4 PR-04)."""
    csv = await _load_csv_for_stage(db, stage_id)
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
