"""„Z czego powstało” — źródła dla AI przy CV etapu (D4, 13.10.2026).

`GET /api/candidates/stages/{stage_id}/cv/ai-sources` mówi karcie „CV do
klienta”, co model może przeczytać przy generacji i ile tego jest: oryginalne
CV, odpowiedzi ze screeningu (ile przeczy pytaniu), notatki tej rekrutacji,
Profil Championa, transkrypty rozmów (ile spoza okna tej rekrutacji),
podsumowania prepu i notatki ze stawką (zawsze wycinane). Same liczby — treść
widać w panelu osoby. Przełączniki idą potem w `POST /generate` (`sources`).
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import CandidateDocumentAccess
from app.api.recruitment_access import ensure_job_read_access
from app.core.database import get_db
from app.models.recruitment_pipeline import CandidateStage

router = APIRouter()


class AiSourceOriginal(BaseModel):
    document_id: int
    filename: Optional[str] = None
    uploaded_at: Optional[datetime] = None


class AiSourceFile(BaseModel):
    """Plik CV osoby do wyboru w kroku „Plik CV” (21.10.2026)."""

    document_id: int
    filename: Optional[str] = None
    uploaded_at: Optional[datetime] = None
    is_primary: bool = False
    # „Nieaktualne” albo z kwarantanny tożsamości — rekruter może je wybrać,
    # ale nie proponujemy ich domyślnie.
    outdated: bool = False
    # Ten sam plik co kopia „Oryginał CV” tej rekrutacji (po SHA).
    stage_original: bool = False


class AiSourceUsedFile(BaseModel):
    """Plik, z którego powstała bieżąca wersja CV etapu (21.10.2026)."""

    document_id: int
    filename: Optional[str] = None
    outdated: bool = False
    stage_original: bool = False
    # Pliku nie ma już wśród plików CV osoby (usunięty z profilu).
    removed: bool = False


class AiSourceCount(BaseModel):
    count: int = 0
    # Odpowiedzi: ile przeczy pytaniu (nie są dowodem). Transkrypty: ile
    # rozmów jest sprzed okna tej rekrutacji (nie wchodzą).
    excluded: int = 0


class AiSourcesResponse(BaseModel):
    # Plik zaznaczony domyślnie: kopia „Oryginał CV” etapu, a bez niej główne
    # (albo najnowsze) CV z pominięciem nieaktualnych i kwarantanny.
    original_cv: Optional[AiSourceOriginal] = None
    cv_files: list[AiSourceFile] = []
    champion: bool = False
    answers: AiSourceCount
    notes: AiSourceCount
    transcripts: AiSourceCount
    prep: AiSourceCount
    rate_notes: AiSourceCount
    defaults: dict[str, bool]
    # Wybór, z którego powstała bieżąca wersja CV etapu (None = sprzed zmiany).
    last_used: Optional[dict[str, bool]] = None
    # Plik CV bieżącej wersji („Powstało z”); None = CV sprzed 21.10.2026
    # albo spoza generatora.
    last_source_cv: Optional[AiSourceUsedFile] = None


@router.get(
    "/candidates/stages/{stage_id}/cv/ai-sources",
    response_model=AiSourcesResponse,
)
async def get_stage_cv_ai_sources(
    stage_id: int,
    current_user: CandidateDocumentAccess,
    db: AsyncSession = Depends(get_db),
) -> AiSourcesResponse:
    """Źródła dla AI przy CV tego etapu — tylko liczby, bez treści."""
    from app.models.call import Call
    from app.models.candidate_stage_cv import CandidateStageCV
    from app.models.cv_generated_document import CvGeneratedDocument
    from app.models.job import Job
    from app.models.note import Note
    from app.models.screening_note import ScreeningNote
    from app.schemas.champion import client_safe_screening
    from app.services import note_kinds
    from app.services.cv_generator_b2b.standalone_service import (
        _CALL_WINDOW_BEFORE_PIPELINE,
        AI_SOURCE_DEFAULTS,
        _not_followup_note,
        champion_present,
    )
    from app.services.money_text import is_rate_text
    from app.services.must_text_evidence import is_negative_answer

    stage = await db.get(CandidateStage, stage_id)
    if stage is None:
        raise HTTPException(status_code=404, detail="Nie ma takiego etapu kandydata.")
    await ensure_job_read_access(db, current_user, stage.job_id)
    job = await db.get(Job, stage.job_id)
    candidate_id = stage.candidate_id

    cv_files = await _cv_files(db, stage)
    default = next((f for f in cv_files if f.stage_original), None) or next(
        (f for f in cv_files if not f.outdated), None
    )
    if default is None and cv_files:
        default = cv_files[0]
    original = (
        AiSourceOriginal(
            document_id=default.document_id,
            filename=default.filename,
            uploaded_at=default.uploaded_at,
        )
        if default is not None
        else None
    )

    safe = client_safe_screening(stage.screening_answers) or {}
    responses = [
        str(a.get("response") or "").strip()
        for a in safe.get("answers") or []
        if isinstance(a, dict) and str(a.get("response") or "").strip()
    ]
    answers = AiSourceCount(
        count=len(responses),
        excluded=sum(1 for r in responses if is_negative_answer(r)),
    )

    # Te same 20 najnowszych notatek, które czyta kolektor dla modelu.
    note_rows = (
        await db.execute(
            select(Note.kind, Note.content)
            .where(
                Note.candidate_id == candidate_id,
                or_(Note.job_id == stage.job_id, Note.job_id.is_(None)),
                _not_followup_note(),
            )
            .order_by(Note.created_at.desc())
            .limit(20)
        )
    ).all()
    prep_count = sum(1 for kind, _ in note_rows if kind == note_kinds.PREP_SUMMARY)
    plain = [content for kind, content in note_rows if kind != note_kinds.PREP_SUMMARY]
    screening_count = await db.scalar(
        select(func.count(ScreeningNote.id)).where(
            ScreeningNote.candidate_id == candidate_id,
            ScreeningNote.job_id == stage.job_id,
        )
    )
    notes = AiSourceCount(
        count=len(plain)
        + int(screening_count or 0)
        + int(bool((stage.notes or "").strip()))
    )
    rate_notes = AiSourceCount(
        count=sum(1 for content in plain if content and is_rate_text(content))
    )

    first_moved = await db.scalar(
        select(func.min(CandidateStage.moved_at)).where(
            CandidateStage.candidate_id == candidate_id,
            CandidateStage.job_id == stage.job_id,
        )
    )
    call_dates = (
        await db.scalars(
            select(Call.created_at).where(
                Call.candidate_id == candidate_id, Call.transcript.isnot(None)
            )
        )
    ).all()
    window_start = (
        first_moved - _CALL_WINDOW_BEFORE_PIPELINE if first_moved is not None else None
    )
    transcripts = AiSourceCount(
        count=len(call_dates),
        excluded=sum(
            1
            for created in call_dates
            if window_start is not None
            and created is not None
            and created < window_start
        ),
    )

    last_used = None
    payload = await db.scalar(
        select(CvGeneratedDocument.render_payload)
        .join(
            CandidateStageCV,
            CandidateStageCV.generated_document_id == CvGeneratedDocument.id,
        )
        .where(CandidateStageCV.candidate_stage_id == stage.id)
    )
    if isinstance(payload, dict) and isinstance(payload.get("ai_sources"), dict):
        last_used = {
            key: bool(payload["ai_sources"].get(key, default))
            for key, default in AI_SOURCE_DEFAULTS.items()
        }
    last_source_cv = _used_file(payload, cv_files)

    return AiSourcesResponse(
        original_cv=original,
        cv_files=cv_files,
        champion=champion_present(job),
        answers=answers,
        notes=notes,
        transcripts=transcripts,
        prep=AiSourceCount(count=prep_count),
        rate_notes=rate_notes,
        defaults=dict(AI_SOURCE_DEFAULTS),
        last_used=last_used,
        last_source_cv=last_source_cv,
    )


async def _cv_files(db: AsyncSession, stage: CandidateStage) -> list[AiSourceFile]:
    """Pliki CV osoby, które generator umie przeczytać, w kolejności generatora.

    21.10.2026 (zgłoszenie zespołu „CV wygenerowało się z błędnego pliku”):
    karta pokazywała kopię „Oryginał CV” etapu, a generator brał główne albo
    najnowsze CV z profilu — także „nieaktualne” i z kwarantanny. Domyślnym
    plikiem jest teraz plik kopii etapu (po SHA, także sprzed ruchu karty).
    """
    from app.models.candidate_document import CandidateDocument
    from app.models.candidate_stage_cv import CandidateStageCV
    from app.services.candidate_identity_quarantine import source_is_eligible_clause
    from app.services.cv_generator_b2b.standalone_service import (
        _supported_cv_doc_filter,
    )

    eligible = source_is_eligible_clause(
        candidate_id_column=CandidateDocument.candidate_id,
        source_id_column=CandidateDocument.id,
        source_kind="document",
    )
    rows = (
        await db.execute(
            select(
                CandidateDocument.id,
                CandidateDocument.filename,
                CandidateDocument.uploaded_at,
                CandidateDocument.is_primary,
                CandidateDocument.content_sha256,
                CandidateDocument.outdated_at.isnot(None),
                eligible,
            )
            .where(
                CandidateDocument.candidate_id == stage.candidate_id,
                _supported_cv_doc_filter(),
            )
            .order_by(
                CandidateDocument.is_primary.desc(),
                CandidateDocument.uploaded_at.desc(),
                CandidateDocument.id.desc(),
            )
        )
    ).all()
    # Kopia bieżącego wiersza etapu, a bez niej najnowsza kopia pary (ruch
    # karty zakłada nowy wiersz etapu bez CV).
    original_sha = await db.scalar(
        select(CandidateStageCV.original_cv_sha256)
        .where(
            CandidateStageCV.candidate_id == stage.candidate_id,
            CandidateStageCV.job_id == stage.job_id,
            CandidateStageCV.original_cv_sha256.isnot(None),
        )
        .order_by(
            (CandidateStageCV.candidate_stage_id == stage.id).desc(),
            CandidateStageCV.original_snapshot_at.desc().nulls_last(),
            CandidateStageCV.id.desc(),
        )
        .limit(1)
    )
    files: list[AiSourceFile] = []
    marked = False
    for doc_id, filename, uploaded_at, primary, sha, outdated, ok in rows:
        is_original = bool(original_sha) and sha == original_sha and not marked
        marked = marked or is_original
        files.append(
            AiSourceFile(
                document_id=doc_id,
                filename=filename,
                uploaded_at=uploaded_at,
                is_primary=bool(primary),
                outdated=bool(outdated) or not bool(ok),
                stage_original=is_original,
            )
        )
    return files


def _used_file(
    payload: object, cv_files: list[AiSourceFile]
) -> Optional[AiSourceUsedFile]:
    """„Powstało z”: plik zapisany przy generacji (`render_payload["source_cv"]`)."""
    if not isinstance(payload, dict) or not isinstance(payload.get("source_cv"), dict):
        return None
    raw = payload["source_cv"]
    try:
        document_id = int(raw.get("document_id"))
    except (TypeError, ValueError):
        return None
    current = next((f for f in cv_files if f.document_id == document_id), None)
    return AiSourceUsedFile(
        document_id=document_id,
        filename=(current.filename if current else None) or raw.get("filename"),
        outdated=bool(current and current.outdated),
        stage_original=bool(current and current.stage_original),
        removed=current is None,
    )
