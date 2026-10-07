# UWAGA: bez `from __future__ import annotations` — `@limiter.limit` na
# module z PEP 563 zamienia `Annotated` guardy w parametry query (slowapi #579).
"""Karta rekomendacji z notatki rekrutera i „Ułóż w zdanie” (0421, 06.10.2026).

Trasy (sekcja Pipeline; bramki jak zapis karty — zapis kandydata, odczyt
rekrutacji i 12-godzinna blokada osoby):

* ``POST /recommendation-cards/note/read`` i ``…/note/read-file`` — odczyt
  wklejonej albo wgranej notatki; propozycja pól i odpowiedzi, BEZ zapisu.
  Pliku nie zapisujemy nigdzie (D1) — wraca tylko jego tekst.
* ``POST /recommendation-cards/phrase`` — zdania z haseł (D3, D4), bez zapisu.

Od 0424 (07.10.2026) zapis tego, co rekruter przyjął z notatki, idzie przez
jeden formularz screeningu (``PUT /api/screening-form`` z ``note_import``) —
dawna trasa ``…/note/apply`` zniknęła.

Wyłącznik ``RECOMMENDATION_CARD_ASSIST_ENABLED``: wyłączony = 404 na każdej
trasie. Reguły odczytu: ``app/services/recommendation_card_assist.py``.
"""

import logging
import os
import tempfile
from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import CandidateWriteAccess
from app.api.recruitment_access import ensure_job_read_access
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import limiter, user_or_ip_key
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.user import User
from app.services import candidate_claim
from app.services import recommendation_card_assist as assist

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)

MAX_FILE_BYTES = 5 * 1024 * 1024
_ALLOWED_EXTENSIONS = (".docx", ".pdf", ".txt")


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
