# UWAGA: bez `from __future__ import annotations` — `@limiter.limit` na
# module z PEP 563 zamienia `Annotated` guardy w parametry query (slowapi #579).
"""Karta rekomendacji z notatki rekrutera i „Ułóż w zdanie” (0421, 06.10.2026).

Trasy (sekcja Pipeline; bramki jak zapis karty — zapis kandydata, odczyt
rekrutacji i 12-godzinna blokada osoby):

* ``POST /recommendation-cards/note/read`` i ``…/note/read-file`` — odczyt
  wklejonej albo wgranej notatki; propozycja pól i odpowiedzi, BEZ zapisu.
  Pliku nie zapisujemy nigdzie (D1) — wraca tylko jego tekst.
* ``POST /recommendation-cards/note/apply`` — zapis tego, co rekruter
  zaznaczył: tekst notatki trafia do historii jako zwykła notatka z rozmowy, pola do
  karty (ta sama droga co zapis ręczny: zmiana stawki, „Stawka od”),
  odpowiedzi do arkusza screeningu pary (D2 — bo zatwierdza człowiek).
* ``POST /recommendation-cards/phrase`` — zdania z haseł (D3, D4), bez zapisu.

Wyłącznik ``RECOMMENDATION_CARD_ASSIST_ENABLED``: wyłączony = 404 na każdej
trasie. Reguły odczytu: ``app/services/recommendation_card_assist.py``.
"""

import logging
import os
import tempfile
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import CandidateWriteAccess
from app.api.recommendation_cards import (
    CardResponse,
    after_card_save,
    card_response,
)
from app.api.recruitment_access import ensure_job_membership, ensure_job_read_access
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import limiter, user_or_ip_key
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.note import Note, NoteType
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User
from app.schemas.champion import (
    SCREENING_ANSWERS_MAX,
    SCREENING_TEXT_MAX_CHARS,
    ScreeningAnswerItem,
    ScreeningAnswers,
)
from app.services import candidate_claim, note_kinds, screening_sheets
from app.services import recommendation_card_assist as assist
from app.services import recommendation_cards as cards
from app.services.screening_note_sync import humanize_origins

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)

MAX_FILE_BYTES = 5 * 1024 * 1024
_ALLOWED_EXTENSIONS = (".docx", ".pdf", ".txt")
SOURCE_NAME_MAX = 200


def _assert_enabled() -> None:
    if not settings.RECOMMENDATION_CARD_ASSIST_ENABLED:
        raise HTTPException(status_code=404, detail="Funkcja jest wyłączona.")


async def _authorized_pair(
    db: AsyncSession, user: User, candidate_id: int, job_id: int
) -> tuple[Candidate, Job]:
    """Bramki zapisu karty: kandydat i rekrutacja istnieją, odczyt rekrutacji,
    blokada 12 h osoby (inny rekruter nie wypełnia cudzej karty z notatki)."""
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Rekrutacja nie istnieje.")
    candidate = await db.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Kandydat nie istnieje.")
    await ensure_job_read_access(db, user, job_id)
    process = await candidate_claim.load_process(
        db, candidate_id=candidate_id, job_id=job_id
    )
    await candidate_claim.assert_can_act(db, process=process, user=user)
    return candidate, job


async def _read(
    db: AsyncSession, user: User, candidate: Candidate, job: Job, text: str
) -> dict[str, Any]:
    try:
        return await assist.read_note(
            db, user_id=user.id, candidate=candidate, job=job, content=text
        )
    except assist.NoteTooShort as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


# ── Odczyt notatki ─────────────────────────────────────────────────────────


class NoteReadBody(BaseModel):
    candidate_id: int = Field(gt=0)
    job_id: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=assist.NOTE_MAX_CHARS * 2)


@router.post("/recommendation-cards/note/read")
@limiter.limit("20/minute", key_func=user_or_ip_key)
async def read_note_text(
    request: Request,
    body: NoteReadBody,
    user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> dict:
    _assert_enabled()
    candidate, job = await _authorized_pair(db, user, body.candidate_id, body.job_id)
    return await _read(db, user, candidate, job, body.text)


@router.post("/recommendation-cards/note/read-file")
@limiter.limit("20/minute", key_func=user_or_ip_key)
async def read_note_file(
    request: Request,
    user: CandidateWriteAccess,
    candidate_id: Annotated[int, Form(gt=0)],
    job_id: Annotated[int, Form(gt=0)],
    file: Annotated[UploadFile, File()],
    db: AsyncSession = Depends(get_db),
) -> dict:
    _assert_enabled()
    candidate, job = await _authorized_pair(db, user, candidate_id, job_id)
    name = (file.filename or "").lower()
    if not name.endswith(_ALLOWED_EXTENSIONS):
        raise HTTPException(422, "Obsługiwane pliki: .docx, .pdf, .txt.")
    data = await file.read(MAX_FILE_BYTES + 1)
    if not data:
        raise HTTPException(422, "Plik jest pusty.")
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(413, "Plik jest za duży (maks. 5 MB).")

    from app.services.cv_text_extractor import extract_text  # noqa: PLC0415

    # Plik żyje wyłącznie w katalogu tymczasowym na czas odczytu (D1).
    suffix = os.path.splitext(name)[1]
    with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
        tmp.write(data)
        tmp.flush()
        try:
            text = await run_in_threadpool(extract_text, tmp.name, name)
        except Exception as exc:  # noqa: BLE001 — każdy błąd odczytu = 422
            raise HTTPException(422, "Nie udało się odczytać tekstu z pliku.") from exc
    text = (text or "").strip()
    if len(text) < assist.NOTE_MIN_CHARS:
        raise HTTPException(
            422, "W pliku nie ma tekstu do odczytania (skan bez tekstu?)."
        )
    return await _read(db, user, candidate, job, text)


# ── „Ułóż w zdanie” ────────────────────────────────────────────────────────


class PhraseItemBody(BaseModel):
    key: str = Field(min_length=1, max_length=100)
    keywords: str = Field(min_length=1, max_length=assist.KEYWORDS_MAX_CHARS)
    question: Optional[str] = Field(default=None, max_length=2000)


class PhraseBody(BaseModel):
    candidate_id: int = Field(gt=0)
    job_id: int = Field(gt=0)
    items: list[PhraseItemBody] = Field(
        min_length=1, max_length=assist.PHRASE_MAX_ITEMS
    )
    language: Optional[Literal["pl", "en"]] = None


@router.post("/recommendation-cards/phrase")
@limiter.limit("30/minute", key_func=user_or_ip_key)
async def phrase_keywords(
    request: Request,
    body: PhraseBody,
    user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> dict:
    _assert_enabled()
    _, job = await _authorized_pair(db, user, body.candidate_id, body.job_id)
    language = body.language or await assist.phrase_language(db, job)
    return await assist.phrase(
        db,
        user_id=user.id,
        items=[item.model_dump() for item in body.items],
        language=language,
    )


# ── Zapis zaznaczonych pozycji ─────────────────────────────────────────────


class NoteApplyAnswer(BaseModel):
    question_id: str = Field(min_length=1, max_length=100)
    response: str = Field(min_length=1, max_length=SCREENING_TEXT_MAX_CHARS)
    keywords: Optional[str] = Field(default=None, max_length=SCREENING_TEXT_MAX_CHARS)
    # „note_import” = odpowiedź przyjęta z notatki; „phrased” = rekruter
    # wstawił zdanie ułożone z haseł notatki.
    origin: Literal["note_import", "phrased"] = "note_import"


class NoteApplyBody(BaseModel):
    candidate_id: int = Field(gt=0)
    job_id: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=assist.NOTE_MAX_CHARS * 2)
    source_name: Optional[str] = Field(default=None, max_length=SOURCE_NAME_MAX)
    fields: dict[str, str] = Field(default_factory=dict)
    # Pochodzenie pól: „note_ai” (odczyt Luny) albo „note_rule” (reguła wzoru).
    field_origins: dict[str, Literal["note_ai", "note_rule"]] = Field(
        default_factory=dict
    )
    answers: list[NoteApplyAnswer] = Field(
        default_factory=list, max_length=SCREENING_ANSWERS_MAX
    )


def _validated_fields(body: NoteApplyBody) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, raw in body.fields.items():
        if key not in cards.EDITABLE_FIELDS:
            raise HTTPException(422, f"Nieznane pole karty: {key}")
        value = (raw or "").strip()
        if not value:
            continue
        if len(value) > cards.max_length(key):
            raise HTTPException(
                422,
                f"Pole „{cards.DISPLAY_LABELS[key]}” może mieć najwyżej "
                f"{cards.max_length(key)} znaków.",
            )
        out[key] = value
    return out


def _note_content(body: NoteApplyBody, note_text: str) -> str:
    source = (body.source_name or "").strip()
    header = f"Notatka z rozmowy (plik: {source})" if source else "Notatka z rozmowy"
    return f"{header}\n\n{note_text}"


async def _write_answers(
    db: AsyncSession,
    *,
    user: User,
    job: Job,
    candidate_id: int,
    answers: list[NoteApplyAnswer],
) -> bool:
    """Odpowiedzi do arkusza screeningu pary (D2) — najnowszy wiersz etapu."""
    from app.api.pipeline import _latest_filled_screening  # noqa: PLC0415

    questions = screening_sheets.question_texts(job.champion_profile)
    unknown = [a.question_id for a in answers if a.question_id not in questions]
    if unknown:
        raise HTTPException(
            422, "Nie ma takiego pytania w Profilu Championa tej rekrutacji."
        )
    latest = await db.scalar(
        select(CandidateStage)
        .where(
            CandidateStage.candidate_id == candidate_id,
            CandidateStage.job_id == job.id,
        )
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
        .limit(1)
        .with_for_update()
    )
    if latest is None:
        raise HTTPException(
            409,
            "Tej osoby nie ma w rekrutacji — nie ma gdzie zapisać odpowiedzi.",
        )
    previous, _ = await _latest_filled_screening(db, latest, for_write=True)
    try:
        sheet = (
            ScreeningAnswers.model_validate(previous)
            if isinstance(previous, dict) and previous
            else ScreeningAnswers()
        )
    except ValidationError:
        raise HTTPException(
            409,
            "Arkusz screeningu tej osoby ma nieprawidłowe dane — popraw go w arkuszu.",
        ) from None
    # Zapis człowieka przejmuje arkusz z notatki (07.10.2026) — automat
    # (`screening_note_sync`) poprawia tylko arkusz z samych `note_sync`.
    humanize_origins(sheet)
    by_id = {item.question_id: item for item in sheet.answers}
    for answer in answers:
        keywords = (answer.keywords or "").strip() or None
        existing = by_id.get(answer.question_id)
        if existing is None:
            if len(sheet.answers) >= SCREENING_ANSWERS_MAX:
                raise HTTPException(422, "Arkusz screeningu ma już komplet odpowiedzi.")
            item = ScreeningAnswerItem(
                question_id=answer.question_id,
                response=answer.response.strip(),
                origin=answer.origin,
                keywords=keywords,
            )
            sheet.answers.append(item)
            by_id[answer.question_id] = item
            continue
        existing.response = answer.response.strip()
        existing.origin = answer.origin
        existing.keywords = keywords
        existing.skipped = False
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
            action="screening_answered",
            user_id=user.id,
            details={
                "candidate_id": candidate_id,
                "job_id": job.id,
                "overall_fit": sheet.overall_fit,
                "match_percent": sheet.match_percent(),
                "source": "note_import",
                "question_ids": sorted({a.question_id for a in answers}),
            },
        )
    )
    await db.flush()
    return True


@router.post("/recommendation-cards/note/apply", response_model=CardResponse)
@limiter.limit("30/minute", key_func=user_or_ip_key)
async def apply_note(
    request: Request,
    body: NoteApplyBody,
    user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> CardResponse:
    """Zapisuje to, co rekruter zaznaczył w przeglądzie propozycji.

    W jednej transakcji: zwykła notatka w historii (tekst notatki, bez pliku),
    pola karty z pochodzeniem, odpowiedzi w arkuszu screeningu pary.
    """
    _assert_enabled()
    candidate, job = await _authorized_pair(db, user, body.candidate_id, body.job_id)
    fields = _validated_fields(body)
    if body.answers:
        # Zapis arkusza to mutacja pipeline'u — ta sama bramka co zapis
        # arkusza w warsztacie screeningu.
        await ensure_job_membership(db, user, job.id)
    note_text = assist.note_text(body.text)
    if not note_text:
        raise HTTPException(422, "Notatka jest pusta.")

    # Zwykła notatka z rozmowy, NIE notatka-karta: projekcja kart (0413)
    # wpisałaby wtedy do karty także pola, które rekruter odznaczył
    # w przeglądzie. Do karty trafia wyłącznie to, co zaznaczył.
    note = Note(
        content=_note_content(body, note_text),
        note_type=NoteType.general,
        candidate_id=candidate.id,
        job_id=job.id,
        author_id=user.id,
        kind=note_kinds.HUMAN,
        # Pochodzenie trzyma rodzaj także po edycji treści (Q3).
        external_source=note_kinds.CARD_ASSIST_SOURCE,
    )
    db.add(note)
    await db.flush()

    # Najpierw odpowiedzi: ich walidacja (pytanie z profilu, wiersz etapu,
    # arkusz) może odmówić — zanim cokolwiek zostanie zatwierdzone. Zapis pól
    # niżej bywa z commitem (zmiana stawki z mailem do DL, 0418).
    answers_written = False
    if body.answers:
        answers_written = await _write_answers(
            db, user=user, job=job, candidate_id=candidate.id, answers=body.answers
        )

    process = await candidate_claim.load_process(
        db, candidate_id=candidate.id, job_id=job.id
    )
    card, changed = await cards.save_manual(
        db,
        candidate_id=candidate.id,
        job_id=job.id,
        changes=fields,
        user_id=user.id,
        attempt_started=cards.attempt_started(process),
        provenance={
            key: {"origin": body.field_origins.get(key, "note_ai"), "note_id": note.id}
            for key in fields
        },
    )
    await after_card_save(db, card=card, changed=changed, user=user, source="note")
    await db.commit()

    if answers_written:
        # Odpowiedzi zmieniają `champion_fit` pary — wynik dopasowania musi
        # się przeliczyć (lustro zapisu arkusza w `api/pipeline`).
        try:
            from app.services.match_score_cache import (  # noqa: PLC0415
                mark_stale_for_candidate,
            )

            await mark_stale_for_candidate(db, candidate.id)
            await db.commit()
        except Exception:  # noqa: BLE001
            logger.warning(
                "recommendation_card_assist: nie oznaczono wyników kandydata=%s",
                candidate.id,
            )
            await db.rollback()
            # Rollback wygasza obiekty sesji — odpowiedź czyta ich pola.
            await db.refresh(candidate)
            await db.refresh(job)

    card = await cards.load_card(db, candidate_id=candidate.id, job_id=job.id)
    return await card_response(db, candidate, job, card)
