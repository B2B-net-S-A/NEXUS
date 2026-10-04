"""Router karty rekomendacji — `/api/recommendation-cards` (0413).

Od 04.10.2026 `POST /recommendation-cards/deal-breaker` zaznacza (albo
zdejmuje) trafienie „Odpada, gdy…” przy pytaniu — w arkuszu screeningu pary,
bo to arkusz czyta okno „Przesuń dalej” (`move_requirements`).

Karta pary (kandydat, rekrutacja): pola odczytane z notatek rekrutera plus
pola wpisane w NEXUSIE. Reguły: ``app/services/recommendation_cards.py``.

Dostęp: sekcja Pipeline; odczyt jak rekrutacja (``ensure_job_read_access``),
zapis jak notatka kandydata (``CandidateWriteAccess``) z poszanowaniem
12-godzinnej blokady osoby. Karta nie niesie stawki do klienta — stawka na
karcie to oczekiwania kandydata, które widzi każda rola wewnętrzna.
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal
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
from app.services import candidate_claim, champion_view, screening_sheets
from app.services import recommendation_cards as cards

logger = logging.getLogger(__name__)

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
    # go nie ma — z notatki (tylko do odczytu). Od 04.10.2026 każde niesie
    # `question_id` (identyfikator z profilu albo `null` dla pytań z samej
    # notatki), `deal_breaker` („Odpada, gdy…” albo `null`) i
    # `deal_breaker_hit` (z arkusza screeningu pary).
    questions: list[dict[str, Any]]
    completeness: CardCompleteness
    labels: dict[str, str]
    editable_fields: list[str]
    legacy_text: str
    updated_at: Optional[datetime] = None


class DealBreakerUpdate(BaseModel):
    candidate_id: int = Field(gt=0)
    job_id: int = Field(gt=0)
    # Identyfikator pytania z Profilu Championa (`questions[].question_id`).
    question_id: str = Field(min_length=1, max_length=100)
    hit: bool


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
    sheet_answers = conversations[0]["answers"] if conversations else []
    questions = cards.attach_deal_breakers(
        cards.merge_questions(
            screening_sheets.question_texts(job.champion_profile),
            sheet_answers,
            answers["items"] if answers else [],
        ),
        champion_view.screening_questions(job.champion_profile),
        sheet_answers,
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


async def _card_rate_change(db: AsyncSession, *, card, user) -> None:  # noqa: ANN001
    """Stawka wpisana ręcznie na karcie od „Zweryfikowany” to zmiana stawki
    w procesie (0418): ślad, dzwonek DL i Head of Recruitment, zadanie DL po
    wysłaniu CV. Tylko PLN/h odczytane bez zgadywania; import z notatek tu
    nie przechodzi (to zapis ręczny)."""

    from app.services import candidate_rate_change as rate_change  # noqa: PLC0415

    hourly = cards.card_rate_hourly((card.fields_manual or {}).get("rate"))
    if hourly is None:
        return
    column = await rate_change.pair_column(
        db, candidate_id=card.candidate_id, job_id=card.job_id
    )
    if column not in rate_change.NOTIFY_COLUMNS:
        return
    result = await rate_change.change_rate(
        db,
        candidate_id=card.candidate_id,
        job_id=card.job_id,
        amount=Decimal(str(hourly)),
        unit="hourly",
        currency="PLN",
        source="card",
        reason="other",
        actor=user,
    )
    if result.emails:
        await db.commit()
        await rate_change.send_pending_emails(result.emails)


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
        if "rate" in changed:
            await _card_rate_change(db, card=card, user=user)
            # „Stawka od” (0414) — od razu, nie czekając na pętlę kolejki.
            from app.services.candidate_rate_from import recompute_safely

            await recompute_safely(db, [data.candidate_id])
        await db.refresh(card)
    return await _response(db, candidate, job, card)


@router.post("/recommendation-cards/deal-breaker", response_model=CardResponse)
async def mark_recommendation_card_deal_breaker(
    data: DealBreakerUpdate,
    user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> CardResponse:
    """Odpowiedź narusza (albo nie) „Odpada, gdy…” — zapis w arkuszu pary.

    Flaga ląduje w NAJNOWSZYM wierszu etapu pary. Wiersz bez własnego arkusza
    dostaje kopię najnowszego wypełnionego arkusza pary (arkusz należy do
    pary, nie do etapu); bez arkusza powstaje nowy z jedną odpowiedzią. Ta
    sama bramka co zapis karty: zapis kandydata, odczyt rekrutacji i blokada
    12 h. Dziennik niesie identyfikator pytania i flagę — bez treści.
    """

    from pydantic import ValidationError  # noqa: PLC0415

    from app.schemas.champion import (  # noqa: PLC0415
        SCREENING_ANSWERS_MAX,
        ScreeningAnswerItem,
        ScreeningAnswers,
    )
    from app.services.move_requirements import sheet_filled  # noqa: PLC0415

    candidate, job = await _pair(db, data.candidate_id, data.job_id)
    await ensure_job_read_access(db, user, data.job_id)
    process = await candidate_claim.load_process(
        db, candidate_id=data.candidate_id, job_id=data.job_id
    )
    await candidate_claim.assert_can_act(db, process=process, user=user)
    questions = screening_sheets.question_texts(job.champion_profile)
    question_id = data.question_id.strip()
    if question_id not in questions:
        raise HTTPException(
            status_code=422,
            detail="Nie ma takiego pytania w Profilu Championa tej rekrutacji.",
        )
    rows = (
        await db.scalars(
            select(CandidateStage)
            .where(
                CandidateStage.candidate_id == data.candidate_id,
                CandidateStage.job_id == data.job_id,
            )
            .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
            .with_for_update()
        )
    ).all()
    if not rows:
        raise HTTPException(
            status_code=409,
            detail="Tej osoby nie ma w rekrutacji — nie ma gdzie zapisać odpowiedzi.",
        )
    latest = rows[0]
    previous = next(
        (r.screening_answers for r in rows if sheet_filled(r.screening_answers)),
        None,
    )
    try:
        sheet = (
            ScreeningAnswers.model_validate(previous)
            if isinstance(previous, dict)
            else ScreeningAnswers()
        )
    except ValidationError:
        raise HTTPException(
            status_code=409,
            detail="Arkusz screeningu tej osoby ma nieprawidłowe dane — popraw go w arkuszu.",
        ) from None
    answer = next((a for a in sheet.answers if a.question_id == question_id), None)
    if answer is None:
        if not data.hit:
            card = await cards.load_card(
                db, candidate_id=data.candidate_id, job_id=data.job_id
            )
            return await _response(db, candidate, job, card)
        if len(sheet.answers) >= SCREENING_ANSWERS_MAX:
            raise HTTPException(
                status_code=422, detail="Arkusz screeningu ma już komplet odpowiedzi."
            )
        # Odpowiedzi z notatek NIE trafiają do arkusza (reguła 0413: arkusz
        # zmienia punktację i wymagania ruchu). Bez arkusza pary nie ma gdzie
        # zapisać trafienia — pusta pozycja zaliczałaby wymóg „Arkusz
        # screeningu” przy ruchu na „Zweryfikowany”.
        if previous is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Najpierw wypełnij arkusz screeningu tej osoby — tam "
                    "zaznaczysz, że odpowiedź narusza „Odpada, gdy…”."
                ),
            )
        sheet.answers.append(
            ScreeningAnswerItem(question_id=question_id, deal_breaker_hit=True)
        )
        changed = True
    else:
        changed = answer.deal_breaker_hit != data.hit
        answer.deal_breaker_hit = data.hit
    if changed:
        screening_sheets.stamp_sheet(
            sheet,
            questions=questions,
            previous=previous,
            user_id=user.id,
            now=datetime.now(timezone.utc),
        )
        latest.screening_answers = sheet.model_dump(mode="json")
        db.add(
            Activity(
                entity_type="candidate_stage",
                entity_id=latest.id,
                action="screening_deal_breaker_marked",
                details={
                    "candidate_id": data.candidate_id,
                    "job_id": data.job_id,
                    "question_id": question_id,
                    "hit": data.hit,
                },
                user_id=user.id,
            )
        )
        await db.flush()
        # Trafienie zeruje `match_percent` arkusza — wynik dopasowania pary
        # musi się przeliczyć (lustro zapisu arkusza w `api/pipeline`).
        try:
            from app.services.match_score_cache import (  # noqa: PLC0415
                mark_stale_for_candidate,
            )

            async with db.begin_nested():
                await mark_stale_for_candidate(db, data.candidate_id)
        except Exception:  # noqa: BLE001
            logger.warning(
                "recommendation_cards: nie oznaczono wyników kandydata=%s jako starych",
                data.candidate_id,
            )
    card = await cards.load_card(db, candidate_id=data.candidate_id, job_id=data.job_id)
    return await _response(db, candidate, job, card)
