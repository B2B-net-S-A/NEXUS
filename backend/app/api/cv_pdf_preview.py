"""Podgląd CV jako strony PDF (Edytor CV 3, decyzja J2 Artura, 14.10.2026).

Trzy trasy obok tras pliku Word, z tymi samymi bramkami (zespół rekrutacji,
prawo do szkicu albo do odczytu, zgoda RODO) — PDF powstaje z TEGO SAMEGO
pliku Word (`services/cv_pdf_preview.py`):

- `POST …/stages/{id}/cv/branded/preview-pdf` — szkic z treści edytora
  (jak `preview-docx`),
- `GET …/stages/{id}/cv/branded/versions/{n}/pdf` — zatwierdzona wersja
  (jak `…/docx`),
- `POST …/cv-generator/generated/{id}/editor/preview-pdf` — edytor wyniku
  generatora,
- `GET …/cv-generator/generated/{id}/pdf` — PDF pliku, który daje „Pobierz
  DOCX” wyniku generatora (25.11.2026: klient z formatem PDF w regule CV).

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
from app.api.cv_generator_b2b import (
    _load_generated_document,
    _load_generated_editor,
    _log_generated_download,
    _with_client_panel_frame,
    generated_docx_bytes,
)
from app.core.database import get_db
from app.core.http_headers import content_disposition_attachment
from app.core.rate_limit import limiter, user_or_ip_key
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.cv_document_version import CvDocumentVersion
from app.models.cv_generated_document import CvGeneratedDocument
from app.schemas.candidate_stage_cv import CVBrandedFinalize
from app.services import cv_consent_gate as consent_gate
from app.services import cv_generated_editor as generated_editor
from app.services.candidate_stage_cv_service import render_stage_editor_docx
from app.services.cv_document_versions import check_revision
from app.services.client_panel import stamp_for_download, stamp_pdf_for_download
from app.services.cv_download_log import DOWNLOAD_INTENT, log_cv_download
from app.services.cv_pdf_preview import (
    MSG_UNAVAILABLE,
    PdfPreviewUnavailable,
    pdf_from_docx,
)
from app.services import cv_layout as layout_service
from app.services.cv_new_pdf import NewCvPdf, NewCvPdfError, cv_facts, render_new_cv_pdf
from app.services.cv_rodo_clause import keep_rodo_clause
from app.services.html_sanitizer import sanitize_cv_html

router = APIRouter()

LIMIT = "20/minute"
MSG_GENERATED_NEW_LAYOUT = (
    "To CV jest w układzie „Nowe CV”. PDF pobierzesz z karty „CV do klienta” "
    "w rekrutacji."
)


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


async def _download_copy(
    db: AsyncSession, csv, docx: bytes, intent: Optional[str]
) -> bytes:
    """Plik dla klienta niesie ramkę panelu rekrutacji; podgląd w NEXUSIE nie."""
    if intent != DOWNLOAD_INTENT:
        return docx
    return await stamp_for_download(
        db,
        job_id=csv.job_id,
        candidate_id=csv.candidate_id,
        docx=docx,
        language=csv.branded_language,
    )


async def _download_new_pdf(
    db: AsyncSession, csv, pdf: bytes, intent: Optional[str]
) -> bytes:
    """PDF „Nowego CV” do klienta: ostatnia strona z linkiem panelu (te same
    dane co ramka w pliku Word). Podgląd w NEXUSIE — bez niej."""
    if intent != DOWNLOAD_INTENT:
        return pdf
    return await stamp_pdf_for_download(
        db,
        job_id=csv.job_id,
        candidate_id=csv.candidate_id,
        pdf=pdf,
        language=csv.branded_language,
    )


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


def _wanted_layout(requested: Optional[str], stored: Optional[str]) -> str:
    """Układ PDF: jawny ``?layout=`` (miniatura drugiego układu) albo zapisany.

    Przy wyłączonej fladze zawsze klasyczny — PDF z pliku Word jak dotąd.
    """
    return layout_service.wanted(requested, stored)


async def _new_cv_pdf(
    db: AsyncSession,
    content_html: str,
    *,
    language: Optional[str],
    template: Optional[str],
    generated: Optional[CvGeneratedDocument],
    extras: Optional[dict],
    consent: Optional[bytes],
    csv: Optional[CandidateStageCV] = None,
) -> NewCvPdf:
    """PDF „Nowego CV”; przed renderem kończy transakcję żądania (jak `_pdf`)."""
    fallback = generated.render_payload if generated is not None else None
    facts = (
        await cv_facts(db, csv.candidate_id, csv.job_id) if csv is not None else None
    )
    await db.commit()
    try:
        return await render_new_cv_pdf(
            content_html,
            language=language,
            template=template,
            fallback=fallback if isinstance(fallback, dict) else None,
            extras=extras,
            consent=consent,
            facts=facts,
        )
    except NewCvPdfError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


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
    layout: Optional[str] = None,
) -> Response:
    """Strony PDF szkicu z bieżącej treści edytora — bez zatwierdzania.

    Układ „Nowe CV” renderuje się z tej samej treści (WeasyPrint), klasyczny
    — z pliku Word przez LibreOffice, jak dotąd.
    """
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
    generated = await _generated_for_stage_cv(db, csv)
    consent_gate.ensure_copy_downloadable(generated, csv)
    filename = "SZKIC_" + _pdf_name(
        csv.branded_docx_filename, f"CV_v{csv.branded_version}"
    )
    if _wanted_layout(layout, csv.cv_layout) == layout_service.LAYOUT_NEW:
        result = await _new_cv_pdf(
            db,
            keep_rodo_clause(
                csv.branded_draft_html, sanitize_cv_html(payload.content_html)
            ),
            language=csv.branded_language,
            template=csv.branded_template,
            generated=generated,
            extras=csv.page1_extras,
            consent=csv.branded_consent_content,
            csv=csv,
        )
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
            await _download_new_pdf(db, csv, result.pdf, intent),
            filename,
            result.headers(),
        )
    docx, _ = await render_stage_editor_docx(csv, payload.content_html)
    pdf = await _pdf(db, await _download_copy(db, csv, docx, intent))
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
    return _response(pdf, filename)


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
    layout: Optional[str] = None,
) -> Response:
    """Strony PDF zatwierdzonej wersji — z jej zamrożonego pliku Word albo,
    w układzie „Nowe CV”, z jej zamrożonej treści i dodatków strony 1."""
    csv = await _load_csv_for_stage(db, stage_id, current_user, read_access=True)
    version = await db.scalar(
        select(CvDocumentVersion).where(
            CvDocumentVersion.candidate_stage_cv_id == csv.id,
            CvDocumentVersion.version == version_number,
        )
    )
    if version is None:
        raise HTTPException(404, "Nie znaleziono zatwierdzonej wersji CV.")
    generated = (
        await db.get(CvGeneratedDocument, version.generated_document_id)
        if version.generated_document_id
        else None
    )
    consent_gate.ensure_copy_downloadable(generated, csv, version)
    if _wanted_layout(layout, version.cv_layout) == layout_service.LAYOUT_NEW:
        result = await _new_cv_pdf(
            db,
            version.content_html,
            language=version.language,
            template=version.template,
            generated=generated,
            extras=version.page1_extras,
            consent=version.consent_content,
            csv=csv,
        )
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
            await _download_new_pdf(db, csv, result.pdf, intent),
            _pdf_name(version.docx_filename, "CV"),
            {"X-CV-Version": str(version.version), **result.headers()},
        )
    if not version.docx_content:
        raise HTTPException(
            409,
            "Ta historyczna wersja nie ma zatwierdzonego DOCX. Utwórz i zatwierdź nową wersję.",
        )
    pdf = await _pdf(db, await _download_copy(db, csv, version.docx_content, intent))
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


@router.get("/cv-generator/generated/{generated_id}/pdf")
@limiter.limit(LIMIT, key_func=user_or_ip_key)
async def generated_cv_pdf(
    request: Request,
    generated_id: int,
    current_user: CandidateDocumentAccess,
    db: AsyncSession = Depends(get_db),
    version_id: Optional[int] = None,
    intent: Optional[str] = None,
    surface: Optional[str] = None,
) -> Response:
    """PDF wyniku generatora z tego samego pliku Word co „Pobierz DOCX”.

    Bramki jak plik Word (`_load_generated_document`, zgoda RODO); z
    ``version_id`` — zatwierdzona wersja pakietu (jak `…/approved/{id}/docx`).
    Plik do klienta niesie ramkę panelu rekrutacji, podgląd nie.
    """
    from app.services.cv_generated_approval import approved_version_for_generation

    row = await _load_generated_document(db, generated_id, current_user)
    if layout_service.is_new(row.cv_layout):
        # Plik Word wyniku jest klasyczny — PDF z niego nie byłby tym „Nowym
        # CV”, które rekruter wybrał. Ten jest w karcie CV etapu.
        raise HTTPException(409, MSG_GENERATED_NEW_LAYOUT)
    if version_id is not None:
        version = await approved_version_for_generation(db, row, version_id)
        consent_gate.ensure_downloadable(row, version)
        if not version.docx_content:
            raise HTTPException(409, "Ta wersja nie ma zatwierdzonego pliku Word.")
        docx, filename = version.docx_content, version.docx_filename
        state, number = "approved", version.version
    else:
        consent_gate.ensure_downloadable(row)
        docx, filename = await generated_docx_bytes(row), row.filename
        state, number = "generated", None
    pdf = await _pdf(db, await _with_client_panel_frame(db, row, docx, intent))
    await _log_generated_download(
        db, generated_id, current_user, intent, surface, "pdf", state, version=number
    )
    await db.commit()
    return _response(pdf, _pdf_name(filename, "CV"))
