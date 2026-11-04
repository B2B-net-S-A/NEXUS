"""Podgląd importu pliku Word w edytorze CV (Edytor CV 2, PR 5).

`POST /api/candidates/stages/{stage_id}/cv/branded/import-preview` zamienia
plik Word z dysku na HTML edytora i NICZEGO nie zapisuje: szkic, numer
rewizji, wersje i historia zdarzeń zostają bez zmian. Treść przyjmuje edytor
jedną cofalną zmianą, a utrwala ją zwykły autozapis (`PATCH …/cv/branded`).
Zapis pliku od razu jako szkicu to inna funkcja: `…/cv/branded/upload`
(„Użyj innego CV”), która odłącza CV od generatora. Okno „Użyj innego CV”
woła tę trasę PRZED zapisem i patrzy na `b2b_template` — plik bez układu
szablonu B2B to zwykle CV kandydata, o które trzeba zapytać (29.10.2026).

Plik przechodzi dokładnie tę drogę co przy `…/upload`: odczyt z limitem,
konwersja z kontrolą archiwum i sanitizerem (`cv_docx_import`), te same
komunikaty odmowy.

Osobny moduł, bo trasa ma limit żądań, a `candidate_stage_cv.py` ma
``from __future__ import annotations`` i trasy bez limitu — nie może stać na
liście modułów z limitem (`tests/test_public_surface_hardening.py`).

Bez ``from __future__ import annotations`` — slowapi #579 (PEP 563 zamienia
guardy `Annotated` w parametry QUERY).
"""

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import CandidateWriteAccess
from app.api.candidate_stage_cv import read_word_upload, word_to_editor_html
from app.api.recruitment_access import ensure_job_membership
from app.core.database import get_db
from app.core.rate_limit import limiter, user_or_ip_key
from app.models.recruitment_pipeline import CandidateStage
from app.schemas.candidate_stage_cv import CV_CONTENT_HTML_MAX, CVImportPreview

router = APIRouter()

MSG_CONTENT_TOO_LONG = (
    "Treść tego pliku jest za długa, żeby zapisać ją w edytorze CV. "
    "Skróć dokument w Wordzie i wgraj go ponownie."
)


@router.post(
    "/candidates/stages/{stage_id}/cv/branded/import-preview",
    response_model=CVImportPreview,
)
@limiter.limit("10/minute", key_func=user_or_ip_key)
async def preview_stage_cv_import(
    request: Request,
    stage_id: int,
    current_user: CandidateWriteAccess,
    file: UploadFile = File(..., description="CV poprawione w Wordzie (.docx)"),
    db: AsyncSession = Depends(get_db),
) -> CVImportPreview:
    """Plik Word jako HTML edytora CV — sam podgląd, bez żadnego zapisu."""
    # Bramki jak przy `…/upload`: zapis w kandydatach + zespół TEJ rekrutacji,
    # bo wynik ma sens tylko dla osoby, która może go potem zapisać. Bez
    # `_load_csv_for_stage(create_missing=True)` — ten zakładałby wiersz CV.
    job_id = await db.scalar(
        select(CandidateStage.job_id).where(CandidateStage.id == stage_id)
    )
    if job_id is None:
        raise HTTPException(status_code=404, detail="Stage nie znaleziony")
    await ensure_job_membership(db, current_user, job_id)

    content, filename = await read_word_upload(file)
    imported = await word_to_editor_html(content)
    if len(imported.html) > CV_CONTENT_HTML_MAX:
        raise HTTPException(status_code=422, detail=MSG_CONTENT_TOO_LONG)
    return CVImportPreview(
        content_html=imported.html,
        filename=filename,
        b2b_template=imported.b2b_template,
    )
