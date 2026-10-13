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


class AiSourceCount(BaseModel):
    count: int = 0
    # Odpowiedzi: ile przeczy pytaniu (nie są dowodem). Transkrypty: ile
    # rozmów jest sprzed okna tej rekrutacji (nie wchodzą).
    excluded: int = 0


class AiSourcesResponse(BaseModel):
    original_cv: Optional[AiSourceOriginal] = None
    champion: bool = False
    answers: AiSourceCount
    notes: AiSourceCount
    transcripts: AiSourceCount
    prep: AiSourceCount
    rate_notes: AiSourceCount
    defaults: dict[str, bool]
    # Wybór, z którego powstała bieżąca wersja CV etapu (None = sprzed zmiany).
    last_used: Optional[dict[str, bool]] = None


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
        list_candidate_cv_sources,
    )
    from app.services.money_text import is_rate_text
    from app.services.must_text_evidence import is_negative_answer

    stage = await db.get(CandidateStage, stage_id)
    if stage is None:
        raise HTTPException(status_code=404, detail="Nie ma takiego etapu kandydata.")
    await ensure_job_read_access(db, current_user, stage.job_id)
    job = await db.get(Job, stage.job_id)
    candidate_id = stage.candidate_id

    documents = await list_candidate_cv_sources(db, candidate_id)
    original = (
        AiSourceOriginal(
            document_id=documents[0]["id"],
            filename=documents[0]["filename"],
            uploaded_at=documents[0]["uploaded_at"],
        )
        if documents
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

    note_rows = (
        await db.execute(
            select(Note.kind, Note.content).where(
                Note.candidate_id == candidate_id,
                or_(Note.job_id == stage.job_id, Note.job_id.is_(None)),
                _not_followup_note(),
            )
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

    return AiSourcesResponse(
        original_cv=original,
        champion=champion_present(job),
        answers=answers,
        notes=notes,
        transcripts=transcripts,
        prep=AiSourceCount(count=prep_count),
        rate_notes=rate_notes,
        defaults=dict(AI_SOURCE_DEFAULTS),
        last_used=last_used,
    )
