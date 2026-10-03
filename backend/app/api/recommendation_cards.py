"""Router karty rekomendacji — `/api/recommendation-cards` (0413).

Karta pary (kandydat, rekrutacja): pola odczytane z notatek rekrutera plus
pola wpisane w NEXUSIE. Reguły: ``app/services/recommendation_cards.py``.

Dostęp: sekcja Pipeline; odczyt jak rekrutacja (``ensure_job_read_access``),
zapis jak notatka kandydata (``CandidateWriteAccess``) z poszanowaniem
12-godzinnej blokady osoby. Karta nie niesie stawki do klienta — stawka na
karcie to oczekiwania kandydata, które widzi każda rola wewnętrzna.
"""

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import CandidateWriteAccess
from app.api.deps import OperationalUser
from app.api.recruitment_access import ensure_job_read_access
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.recommendation_card import RecommendationCard
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User
from app.services import candidate_claim, screening_sheets
from app.services import recommendation_cards as cards

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)


class CardCompleteness(BaseModel):
    status: str
    filled: int
    total: int
    missing: list[str]


class CardResponse(BaseModel):
    candidate_id: int
    job_id: int
    exists: bool
    fields: dict[str, dict[str, Any]]
    previous: dict[str, dict[str, Any]]
    suggestions: dict[str, str]
    note_answers: Optional[dict[str, Any]] = None
    # Pytania z Profilu Championa z odpowiedzią: z arkusza screeningu, a gdy
    # go nie ma — z notatki (tylko do odczytu).
    questions: list[dict[str, Any]]
    completeness: CardCompleteness
    labels: dict[str, str]
    editable_fields: list[str]
    legacy_text: str
    updated_at: Optional[datetime] = None


class CardUpdate(BaseModel):
    candidate_id: int = Field(gt=0)
    job_id: int = Field(gt=0)
    # Klucz = pole karty, wartość = tekst; ``null`` albo pusty tekst zdejmuje
    # pole wpisane ręcznie (wraca wartość z notatki, jeśli jest).
    fields: dict[str, Optional[str]] = Field(min_length=1)

    @field_validator("fields")
    @classmethod
    def _known_fields(cls, value: dict[str, Optional[str]]) -> dict[str, Optional[str]]:
        for key, raw in value.items():
            if key not in cards.EDITABLE_FIELDS:
                raise ValueError(f"Nieznane pole karty: {key}")
            if raw is not None and len(raw) > cards.max_length(key):
                raise ValueError(
                    f"Pole „{cards.DISPLAY_LABELS[key]}” może mieć najwyżej "
                    f"{cards.max_length(key)} znaków."
                )
        return value


async def _pair(
    db: AsyncSession, candidate_id: int, job_id: int
) -> tuple[Candidate, Job]:
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Rekrutacja nie istnieje.")
    candidate = await db.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Kandydat nie istnieje.")
    return candidate, job


async def _nationality_suggestion(
    db: AsyncSession, candidate: Candidate, job_id: int
) -> Optional[str]:
    """Narodowość z poprzedniej karty tej osoby albo z importu Traffita."""
    rows = await db.execute(
        select(RecommendationCard.fields_manual, RecommendationCard.fields_notes)
        .where(
            RecommendationCard.candidate_id == candidate.id,
            RecommendationCard.job_id != job_id,
        )
        .order_by(RecommendationCard.updated_at.desc())
        .limit(10)
    )
    for manual, notes in rows.all():
        for fields in (manual, notes):
            value = str(
                ((fields or {}).get("nationality") or {}).get("raw") or ""
            ).strip()
            if value:
                return value
    extracted = candidate.cv_extracted_data
    value = (
        extracted.get("traffit_nationality") if isinstance(extracted, dict) else None
    )
    return value.strip() if isinstance(value, str) and value.strip() else None


async def _author_names(db: AsyncSession, fields: dict[str, dict[str, Any]]) -> None:
    ids = sorted({v["by"] for v in fields.values() if isinstance(v.get("by"), int)})
    if not ids:
        return
    names = {
        row.id: row.name
        for row in (
            await db.execute(select(User.id, User.name).where(User.id.in_(ids)))
        ).all()
    }
    for value in fields.values():
        if isinstance(value.get("by"), int):
            value["by_name"] = names.get(value["by"])


async def _response(
    db: AsyncSession,
    candidate: Candidate,
    job: Job,
    card: Optional[RecommendationCard],
) -> CardResponse:
    process = await candidate_claim.load_process(
        db, candidate_id=candidate.id, job_id=job.id
    )
    attempt_started = cards.attempt_started(process)
    current, previous = cards.split_fields(
        card.fields_notes if card else {},
        card.fields_manual if card else {},
        attempt_started=attempt_started,
    )
    await _author_names(db, current)
    answers = cards.current_answers(
        card.note_answers if card else None, attempt_started=attempt_started
    )
    conversations = await screening_sheets.candidate_conversations(
        db, candidate_id=candidate.id, job_scope=CandidateStage.job_id == job.id
    )
    questions = cards.merge_questions(
        screening_sheets.question_texts(job.champion_profile),
        conversations[0]["answers"] if conversations else [],
        answers["items"] if answers else [],
    )
    suggestions: dict[str, str] = {}
    if "nationality" not in current:
        nationality = await _nationality_suggestion(db, candidate, job.id)
        if nationality:
            suggestions["nationality"] = nationality
    name = " ".join(
        part for part in (candidate.name, candidate.lastname) if part
    ).strip()
    return CardResponse(
        candidate_id=candidate.id,
        job_id=job.id,
        exists=card is not None,
        fields=current,
        previous=previous,
        suggestions=suggestions,
        note_answers=answers,
        questions=questions,
        completeness=CardCompleteness(**cards.completeness(current)),
        labels=cards.LABELS,
        editable_fields=list(cards.EDITABLE_FIELDS),
        legacy_text=cards.legacy_text(
            current,
            questions,
            candidate_name=name,
            project=(job.client_reference or job.title or "").strip(),
        ),
        updated_at=card.updated_at if card else None,
    )


@router.get("/recommendation-cards", response_model=CardResponse)
async def get_recommendation_card(
    user: OperationalUser,
    candidate_id: int = Query(gt=0),
    job_id: int = Query(gt=0),
    db: AsyncSession = Depends(get_db),
) -> CardResponse:
    candidate, job = await _pair(db, candidate_id, job_id)
    await ensure_job_read_access(db, user, job_id)
    card = await cards.load_card(db, candidate_id=candidate_id, job_id=job_id)
    return await _response(db, candidate, job, card)


@router.put("/recommendation-cards", response_model=CardResponse)
async def update_recommendation_card(
    data: CardUpdate,
    user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> CardResponse:
    candidate, job = await _pair(db, data.candidate_id, data.job_id)
    await ensure_job_read_access(db, user, data.job_id)
    process = await candidate_claim.load_process(
        db, candidate_id=data.candidate_id, job_id=data.job_id
    )
    await candidate_claim.assert_can_act(db, process=process, user=user)
    card, changed = await cards.save_manual(
        db,
        candidate_id=data.candidate_id,
        job_id=data.job_id,
        changes=data.fields,
        user_id=user.id,
        attempt_started=cards.attempt_started(process),
    )
    if changed:
        # Same nazwy pól — treść karty (narodowość, red flags) nie trafia
        # do dziennika zdarzeń.
        db.add(
            Activity(
                entity_type="candidate",
                entity_id=data.candidate_id,
                action="recommendation_card_updated",
                details={"job_id": data.job_id, "fields": sorted(changed)},
                user_id=user.id,
            )
        )
        await db.flush()
        await db.refresh(card)
    return await _response(db, candidate, job, card)
