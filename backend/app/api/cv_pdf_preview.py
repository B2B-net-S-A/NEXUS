"""Podgląd CV jako strony PDF (Edytor CV 3, decyzja J2 Artura, 14.10.2026).

Trzy trasy obok tras pliku Word, z tymi samymi bramkami (zespół rekrutacji,
prawo do szkicu albo do odczytu, zgoda RODO) — PDF powstaje z TEGO SAMEGO
pliku Word (`services/cv_pdf_preview.py`):

- `POST …/stages/{id}/cv/branded/preview-pdf` — szkic z treści edytora
  (jak `preview-docx`),
- `GET …/stages/{id}/cv/branded/versions/{n}/pdf` — zatwierdzona wersja
  (jak `…/docx`),
- `POST …/cv-generator/generated/{id}/editor/preview-pdf` — edytor wyniku
  generatora.

Pobranie (`intent=download`) zapisuje wpis `cv_file_downloaded` z formatem
`pdf`; podgląd nie zapisuje nic. Awaria zamiany = 503 z polskim komunikatem,
a przeglądarka wraca do dotychczasowego podglądu pliku Word.

Osobny moduł, bo trasy mają limit żądań (zamiana kosztuje ok. 2 s procesora),
a `candidate_stage_cv.py` i `cv_generator_b2b.py` mają
``from __future__ import annotations``. Bez tego importu tutaj — slowapi #579.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import CandidateDocumentAccess, CandidateWriteAccess
from app.api.candidate_stage_cv import (
    NO_GENERATED_CV_MESSAGE,
    _generated_for_stage_cv,
    _load_csv_for_stage,
)
from app.api.cv_generator_b2b import _load_generated_editor, _log_generated_download
from app.core.database import get_db
from app.core.http_headers import content_disposition_attachment
from app.core.rate_limit import limiter, user_or_ip_key
from app.models.cv_document_version import CvDocumentVersion
from app.models.cv_generated_document import CvGeneratedDocument
from app.schemas.candidate_stage_cv import CVBrandedFinalize
from app.services import cv_consent_gate as consent_gate
from app.services import cv_generated_editor as generated_editor
from app.services.candidate_stage_cv_service import render_stage_editor_docx
from app.services.cv_document_versions import check_revision
from app.services.cv_download_log import log_cv_download
from app.services.cv_pdf_preview import (
    MSG_UNAVAILABLE,
    PdfPreviewUnavailable,
    pdf_from_docx,
)

router = APIRouter()

LIMIT = "20/minute"


async def _pdf(db: AsyncSession, docx: bytes) -> bytes:
    """PDF z pliku Word; przed zamianą kończy transakcję żądania.

    Zamiana może czekać na wolne miejsce do 30 s i trwać do 45 s. Do tego
    czasu nie trzymamy połączenia z bazą ani blokad wierszy (edytor wyniku
    generatora czyta szkic z `FOR UPDATE` — trzymana blokada wstrzymałaby
    autozapis). Obiekty zostają czytelne (`expire_on_commit=False`); wpis
    pobrania idzie potem w nowej transakcji.
    """
    await db.commit()
    try:
        return await pdf_from_docx(docx)
    except PdfPreviewUnavailable as error:
        raise HTTPException(status_code=503, detail=MSG_UNAVAILABLE) from error


def _pdf_name(docx_name: Optional[str], fallback: str) -> str:
    name = (docx_name or fallback).rsplit(".", 1)[0]
    return f"{name}.pdf"


def _response(pdf: bytes, filename: str, extra: Optional[dict] = None) -> Response:
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": content_disposition_attachment(filename),
            "Cache-Control": "private, no-store",
            **(extra or {}),
        },
    )


@router.post("/candidates/stages/{stage_id}/cv/branded/preview-pdf")
@limiter.limit(LIMIT, key_func=user_or_ip_key)
async def preview_stage_cv_pdf(
    request: Request,
    stage_id: int,
    payload: CVBrandedFinalize,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
    intent: Optional[str] = None,
    surface: Optional[str] = None,
) -> Response:
    """Strony PDF szkicu z bieżącej treści edytora — bez zatwierdzania."""
    # Bez blokady wiersza (inaczej niż `preview-docx`): zamiana trwa sekundy,
    # a niczego tu nie zapisujemy — blokada wstrzymałaby autozapis edytora
    # (transakcję i tak kończy `_pdf` przed zamianą).
    csv = await _load_csv_for_stage(db, stage_id, current_user)
    check_revision(csv, payload.expected_revision)
    if csv.branded_status == "none":
        raise HTTPException(409, NO_GENERATED_CV_MESSAGE)
    if csv.branded_status != "draft":
        raise HTTPException(
            409, "Podgląd dotyczy szkicu. Pobierz zatwierdzoną wersję CV."
        )
    consent_gate.ensure_copy_downloadable(await _generated_for_stage_cv(db, csv), csv)
    docx, _ = await render_stage_editor_docx(csv, payload.content_html)
    pdf = await _pdf(db, docx)
    await log_cv_download(
        db,
        intent=intent,
        surface=surface,
        entity_type="candidate_stage_cv",
        entity_id=csv.id,
        user=current_user,
        file_format="pdf",
        state="draft",
        version=csv.branded_version,
    )
    return _response(
        pdf,
        "SZKIC_" + _pdf_name(csv.branded_docx_filename, f"CV_v{csv.branded_version}"),
    )


@router.get("/candidates/stages/{stage_id}/cv/branded/versions/{version_number}/pdf")
@limiter.limit(LIMIT, key_func=user_or_ip_key)
async def approved_stage_cv_pdf(
    request: Request,
    stage_id: int,
    version_number: int,
    current_user: CandidateDocumentAccess,
    db: AsyncSession = Depends(get_db),
    intent: Optional[str] = None,
    surface: Optional[str] = None,
) -> Response:
    """Strony PDF zatwierdzonej wersji — z jej zamrożonego pliku Word."""
    csv = await _load_csv_for_stage(db, stage_id, current_user, read_access=True)
    version = await db.scalar(
        select(CvDocumentVersion).where(
            CvDocumentVersion.candidate_stage_cv_id == csv.id,
            CvDocumentVersion.version == version_number,
        )
    )
    if version is None:
        raise HTTPException(404, "Nie znaleziono zatwierdzonej wersji CV.")
    consent_gate.ensure_copy_downloadable(
        await db.get(CvGeneratedDocument, version.generated_document_id)
        if version.generated_document_id
        else None,
        csv,
        version,
    )
    if not version.docx_content:
        raise HTTPException(
            409,
            "Ta historyczna wersja nie ma zatwierdzonego DOCX. Utwórz i zatwierdź nową wersję.",
        )
    pdf = await _pdf(db, version.docx_content)
    await log_cv_download(
        db,
        intent=intent,
        surface=surface,
        entity_type="candidate_stage_cv",
        entity_id=csv.id,
        user=current_user,
        file_format="pdf",
        state="approved",
        version=version.version,
    )
    return _response(
        pdf,
        _pdf_name(version.docx_filename, "CV"),
        {"X-CV-Version": str(version.version)},
    )


@router.post("/cv-generator/generated/{generated_id}/editor/preview-pdf")
@limiter.limit(LIMIT, key_func=user_or_ip_key)
async def preview_generated_cv_pdf(
    request: Request,
    generated_id: int,
    payload: CVBrandedFinalize,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
    intent: Optional[str] = None,
    surface: Optional[str] = None,
) -> Response:
    """Strony PDF szkicu w edytorze wyniku generatora (bez rekrutacji)."""
    draft = await _load_generated_editor(db, generated_id, current_user, persist=False)
    consent_gate.ensure_copy_downloadable(
        await db.get(CvGeneratedDocument, generated_id), draft
    )
    check_revision(draft, payload.expected_revision)
    docx = await generated_editor.render(draft, payload.content_html)
    pdf = await _pdf(db, docx)
    await _log_generated_download(
        db,
        generated_id,
        current_user,
        intent,
        surface,
        "pdf",
        "draft",
        version=draft.branded_version,
    )
    await db.commit()
    return _response(pdf, "SZKIC_CV.pdf")
