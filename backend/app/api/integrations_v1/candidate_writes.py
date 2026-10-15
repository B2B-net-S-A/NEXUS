"""Zapis kandydatów w API v1: nowy kandydat, wgranie CV, notatka.

Scope'y ``candidates:write`` i ``notes:write``. Te same ciała co ekran —
``candidates.apply_candidate_create``, ``candidates._ingest_candidate_cv_file``
(i ``_attach_candidate_document``), ``notes.apply_note_create`` — z autorem
``WriteAuthor.service_account`` (``services/write_author.py``): kolumny autora
``None``, ``details.via`` na ``Activity`` ze stempla sesji klucza, bez wpisu
``UserActivity`` (ranking ludzi).

Reguły ekranu zostają:

* „ta sama osoba = ten sam e-mail” (``dedup_service.find_candidate_by_email``,
  bez rozróżniania wielkości liter) — duplikat to 409 ``duplicate_candidate``
  z samym ``details.candidate_id`` istniejącego profilu;
* imię i nazwisko bez dopisków („[ACTIVE]”, „(czarna lista)”) — 422 przy
  polu, jak ręczny wpis na ekranie (``candidate_name_rules``);
* CV tylko PDF/DOC/DOCX, limit rozmiaru jak na ekranie, odczyt AI i bramka
  tożsamości w tle PO commicie;
* notatka z klucza to notatka systemowa (``candidate_claim`` — reguła 0412).

Świadomie węziej niż ekran: e-mail kandydata jest wymagany (bez niego automat
zakładałby duplikaty), LinkedIn tylko jako adres profilu ``linkedin.com/in/…``,
notatka bez odpowiedzi na wątek i bez wzmianek „@” (klucz nikogo nie oznacza),
CV bez ``dry_run`` (plik trafia na dysk przed commitem).

Moduł NIE MOŻE mieć ``from __future__ import annotations`` (slowapi #579).
"""

import hashlib
import os
from typing import Annotated, Any, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import Response
from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    ValidationError,
    field_validator,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import candidates as candidate_routes
from app.api import notes as note_routes
from app.api.integrations_v1.common import (
    INT4_MAX,
    CandidatesWrite,
    IdPath,
    IntegrationRoute,
    NotesWrite,
    dry_run_response,
    idempotent_write,
    integration_actor,
    principal_of,
    principal_rate_key,
    write_rate_limit,
)
from app.api.jobs import jobs_register_base_clause
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocumentKind
from app.models.job import Job
from app.models.note import NoteType
from app.models.purged_candidate import PurgedCandidate
from app.schemas.candidate import CandidateCreate
from app.schemas.note import NoteCreate
from app.services.candidate_audit import (
    EMAIL_TOMBSTONE_SOURCE,
    candidate_email_tombstone,
)
from app.services.candidate_name_rules import (
    NAME_MARKER_ERROR_TYPE,
    find_name_markers,
    name_marker_message,
)
from app.services.dedup_service import find_candidate_by_email
from app.services.integration_actor import VIA_PREFIX
from app.services.proxycurl.client import normalize_linkedin_url
from app.services.write_author import WriteAuthor

router = APIRouter(route_class=IntegrationRoute)

# Jak w rekrutacji (``candidate_stage_cv``): podgląd, QC i generator czytają
# wyłącznie te formaty, więc ODT/RTF/TXT z automatu dałyby CV „bez treści”.
CV_EXTENSIONS = (".pdf", ".doc", ".docx")
# Ekran nie ma limitu treści notatki poza limitem ciała żądania (30 MB);
# automat dostaje rozsądny sufit — dłuższy tekst to plik, nie notatka.
NOTE_MAX_CHARS = 100_000


def _author(caller: Any) -> WriteAuthor:
    return WriteAuthor.service_account(integration_actor(caller))


def _validation_error(errors: list[dict[str, Any]]) -> HTTPException:
    """422 w kształcie walidacji v1 (jak ``RequestValidationError``)."""
    return HTTPException(
        422,
        detail={
            "error": "validation_error",
            "message": "Nieprawidłowe dane żądania.",
            "errors": errors,
        },
    )


# ── Wejście i wyjście ────────────────────────────────────────────────────────

SkillName = Annotated[str, Field(min_length=1, max_length=100)]


class CandidateCreateIn(BaseModel):
    """Nowy kandydat. E-mail jest wymagany — to reguła tożsamości („ta sama
    osoba = ten sam e-mail”); inny e-mail to inna osoba."""

    # Literówka w nazwie pola nie może przejść po cichu jako „brak wartości”.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    phone: Optional[str] = Field(None, max_length=30)
    linkedin_url: Optional[str] = Field(
        None,
        max_length=500,
        description="Adres profilu LinkedIn (linkedin.com/in/…); zapisywany "
        "w postaci kanonicznej.",
    )
    city: Optional[str] = Field(None, max_length=120)
    country: Optional[str] = Field(
        None, pattern=r"^[A-Za-z]{2}$", description="Kod kraju ISO 3166-1 (PL)."
    )
    skills: Optional[list[SkillName]] = Field(None, max_length=200)
    source: Optional[str] = Field(
        None,
        max_length=100,
        description="Skąd jest osoba (np. portal albo nazwa automatyzacji).",
    )

    @field_validator("linkedin_url")
    @classmethod
    def _linkedin_profile(cls, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        normalized = normalize_linkedin_url(value)
        if normalized is None:
            raise ValueError("Podaj adres profilu LinkedIn (linkedin.com/in/…).")
        return normalized


class CandidateCreatedOut(BaseModel):
    id: int
    created: bool = Field(
        True, description="Zawsze true — istniejący e-mail to 409, nie nadpisanie."
    )


class CandidateCvOut(BaseModel):
    document_id: int
    is_primary: bool = Field(
        ..., description="Czy plik jest głównym CV (odczyt AI odświeży profil w tle)."
    )


class NoteCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(..., min_length=1, max_length=NOTE_MAX_CHARS)
    job_id: Optional[int] = Field(
        None, ge=1, le=INT4_MAX, description="Rekrutacja, której dotyczy notatka."
    )
    note_type: NoteType = NoteType.general

    @field_validator("content")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Notatka nie może być pusta.")
        return value


class NoteCreatedOut(BaseModel):
    note_id: int


# ── Reguły ───────────────────────────────────────────────────────────────────


def _reject_name_markers(body: CandidateCreateIn) -> None:
    """Dopisek w imieniu → 422 przy polu v1 (reguła ``candidate_name_rules``,
    jak ręczny wpis na ekranie — automat dostaje odmowę zamiast cichej zmiany)."""
    errors = [
        {
            "loc": ["body", field],
            "msg": name_marker_message(),
            "type": NAME_MARKER_ERROR_TYPE,
        }
        for field, value in (
            ("first_name", body.first_name),
            ("last_name", body.last_name),
        )
        if find_name_markers(value)
    ]
    if errors:
        raise _validation_error(errors)


def _screen_candidate(body: CandidateCreateIn) -> CandidateCreate:
    """Model ekranu z danych v1 — jego walidatory jako 422 v1, nie 500."""
    try:
        return CandidateCreate.model_validate(
            {
                "name": body.first_name,
                "lastname": body.last_name,
                "email": body.email,
                "phone": body.phone,
                "linkedin": body.linkedin_url,
                "city": body.city,
                "country": body.country,
                "skills": body.skills,
                "source": body.source,
            }
        )
    except ValidationError as exc:
        raise _validation_error(
            [
                {
                    "loc": list(err.get("loc", ())),
                    "msg": err.get("msg"),
                    "type": err.get("type"),
                }
                for err in exc.errors()
            ]
        ) from None


async def _assert_new_email(db: AsyncSession, email: Optional[str]) -> None:
    """Ta sama osoba = ten sam e-mail → 409 z identyfikatorem profilu (bez jego
    danych — do profilu jest odczyt ``candidates:read``)."""
    rows = await find_candidate_by_email(db, email)
    if rows:
        raise HTTPException(
            409,
            detail={
                "error": "duplicate_candidate",
                "message": "Kandydat z tym adresem e-mail już istnieje "
                "(ta sama osoba = ten sam e-mail).",
                "candidate_id": rows[0]["candidate_id"],
            },
        )


async def _assert_not_erased(db: AsyncSession, email: Optional[str]) -> None:
    """Osoba, której dane usunięto na jej żądanie (RODO), nie wraca z automatu.

    Ekran tego nie sprawdza — tam decyduje człowiek, który rozmawiał z osobą.
    Automatyzacja zakłada kandydatów hurtem (np. z maili), więc nagrobek
    adresu (``candidate_email_tombstone``, ten sam co przy imporcie) daje
    409 ``candidate_erased`` bez żadnych danych osoby. Decyzja 15.10.2026.
    """
    email_hash = candidate_email_tombstone(email)
    if email_hash is None:
        return
    erased = await db.scalar(
        select(PurgedCandidate.id).where(
            PurgedCandidate.external_source == EMAIL_TOMBSTONE_SOURCE,
            PurgedCandidate.external_id_hash == email_hash,
        )
    )
    if erased is not None:
        raise HTTPException(
            409,
            detail={
                "error": "candidate_erased",
                "message": "Dane osoby z tym adresem e-mail usunięto na jej "
                "żądanie (RODO) — API nie zakłada jej ponownie. Jeśli osoba sama "
                "wróciła do kontaktu, dodaje ją człowiek na ekranie.",
            },
        )


# ── Kandydat ────────────────────────────────────────────────────────────────


@router.post(
    "/candidates",
    response_model=CandidateCreatedOut,
    status_code=201,
    summary="Dodaj kandydata",
)
@limiter.limit(write_rate_limit, key_func=principal_rate_key)
async def create_candidate(
    request: Request,
    body: CandidateCreateIn,
    caller: CandidatesWrite,
    db: AsyncSession = Depends(get_db),
    dry_run: bool = Query(
        False, description="Tylko walidacja i sprawdzenie duplikatu, bez zapisu."
    ),
) -> Response:
    """Jak „Dodaj kandydata” na ekranie: profil, wpis w historii, dzwonek dla
    adminów i Head of Recruitment, indeks wyszukiwania. Autor = konto
    serwisowe. Kandydat z tym samym e-mailem (bez rozróżniania wielkości
    liter) już jest → 409 ``duplicate_candidate`` z ``candidate_id``. Adres
    osoby usuniętej na jej żądanie (RODO) → 409 ``candidate_erased``.
    Dopisek w imieniu („[ACTIVE]”, „(czarna lista)”) → 422 przy polu."""
    _reject_name_markers(body)
    data = _screen_candidate(body)
    author = _author(caller)

    async def run():
        await _assert_new_email(db, data.email)
        await _assert_not_erased(db, data.email)
        if dry_run:
            return 200, {"valid": True}
        try:
            candidate = await candidate_routes.apply_candidate_create(
                db, data, author=author
            )
        except HTTPException as exc:
            if exc.status_code == 409:
                # Wyścig: równoległy zapis tego adresu wygrał między
                # sprawdzeniem a INSERT-em — odpowiedź jak przy duplikacie.
                await _assert_new_email(db, data.email)
            raise
        return 201, {"id": candidate.id, "created": True}

    if dry_run:
        return await dry_run_response(db, run)
    return await idempotent_write(
        request, db, caller, payload=body.model_dump(mode="json"), run=run
    )


# ── CV ──────────────────────────────────────────────────────────────────────


@router.post(
    "/candidates/{candidate_id}/cv",
    response_model=CandidateCvOut,
    status_code=201,
    summary="Wgraj CV kandydata",
)
@limiter.limit(write_rate_limit, key_func=principal_rate_key)
async def upload_candidate_cv(
    request: Request,
    candidate_id: IdPath,
    caller: CandidatesWrite,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(..., description="CV: PDF, DOC albo DOCX."),
    make_primary: bool = Form(
        True,
        description="Główne CV (AI odświeży profil w tle). false = plik obok "
        "obecnego głównego CV; gdy osoba nie ma głównego CV, ten plik nim zostaje.",
    ),
) -> Response:
    """Jak wgranie CV na ekranie: plik w teczce kandydata (ten sam plik drugi
    raz nie tworzy kopii), główne CV odczytuje AI w tle i odświeża profil po
    bramce tożsamości — CV innej osoby nie nadpisze profilu. Tylko PDF, DOC,
    DOCX (415); pusty plik 400, za duży 413."""
    content = await candidate_routes._read_upload_bounded(file, label="Plik CV")
    safe_filename = candidate_routes._sanitize_upload_filename(
        file.filename, fallback="CV"
    )
    ext = os.path.splitext(safe_filename.lower())[1]
    if ext not in CV_EXTENSIONS:
        raise HTTPException(
            415,
            detail={
                "error": "unsupported_media_type",
                "message": "CV wgraj jako PDF, DOC albo DOCX.",
            },
        )
    digest = hashlib.sha256(content).hexdigest()
    author = _author(caller)
    # Odczyt AI startuje dopiero po commicie paragonu; powtórka z paragonu
    # (ten sam Idempotency-Key) nie uruchamia go drugi raz.
    to_enrich: list = []

    async def run():
        candidate = await db.scalar(
            select(Candidate).where(Candidate.id == candidate_id)
        )
        if candidate is None:
            raise HTTPException(404, detail="Kandydat nie istnieje.")
        replaced_primary = await candidate_routes._primary_cv_before_change(
            db, candidate_id
        )
        # Jak `POST /api/candidates/{id}/documents` z rodzajem CV: plik bez
        # `make_primary` zostaje głównym CV, gdy osoba żadnego nie ma.
        if make_primary or replaced_primary.document_id is None:
            document = await candidate_routes._ingest_candidate_cv_file(
                db,
                candidate=candidate,
                content=content,
                safe_filename=safe_filename,
                content_type=candidate_routes._DOCUMENT_CONTENT_TYPES[ext],
                user_id=author.user_id,
            )
            to_enrich.append((candidate, document, replaced_primary))
        else:
            document = await candidate_routes._attach_candidate_document(
                db,
                candidate_id=candidate_id,
                safe_filename=safe_filename,
                content=content,
                content_type=candidate_routes._DOCUMENT_CONTENT_TYPES[ext],
                kind=CandidateDocumentKind.cv,
                user_id=author.user_id,
            )
        return 201, {
            "document_id": document.id,
            "is_primary": bool(document.is_primary),
        }

    response = await idempotent_write(
        request,
        db,
        caller,
        payload={
            "candidate_id": candidate_id,
            "file_sha256": digest,
            "filename": file.filename,
            "make_primary": make_primary,
        },
        run=run,
    )
    for candidate, document, replaced_primary in to_enrich:
        await candidate_routes._after_cv_commit(
            db,
            background_tasks,
            candidate=candidate,
            document=document,
            actor_user_id=author.user_id,
            replaced_primary=replaced_primary,
        )
    return response


# ── Notatka ─────────────────────────────────────────────────────────────────


@router.post(
    "/candidates/{candidate_id}/notes",
    response_model=NoteCreatedOut,
    status_code=201,
    summary="Dodaj notatkę o kandydacie",
)
@limiter.limit(write_rate_limit, key_func=principal_rate_key)
async def create_candidate_note(
    request: Request,
    candidate_id: IdPath,
    body: NoteCreateIn,
    caller: NotesWrite,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Notatka systemowa (wpis automatu): w Historii kandydata za „Pokaż
    systemowe”, bez autora-osoby, nie czyta jej AI ani bramka wymagań.
    ``@`` w treści nikogo nie oznacza — klucz API nie wysyła ludziom dzwonków
    ani maili. ``job_id`` przypina notatkę do rekrutacji (404, gdy jej nie
    ma)."""
    author = _author(caller)
    created_box: list = []

    async def run():
        if body.job_id is not None and (
            await db.scalar(
                select(Job.id).where(Job.id == body.job_id, jobs_register_base_clause())
            )
            is None
        ):
            # Rekrutacja ukrytego albo usuniętego klienta nie istnieje dla klucza.
            raise HTTPException(404, detail="Rekrutacja nie istnieje.")
        created = await note_routes.apply_note_create(
            db,
            NoteCreate(
                content=body.content,
                note_type=body.note_type,
                candidate_id=candidate_id,
                job_id=body.job_id,
            ),
            author=author,
        )
        # Autor w odczycie notatek (``GET …/notes``): „Integracja: <konto>”
        # ze stempla, bo ``author_id`` konta serwisowego jest pusty.
        created.note.source_ref = f"{VIA_PREFIX}{principal_of(caller).slug}"
        created_box.append(created)
        return 201, {"note_id": created.note.id}

    response = await idempotent_write(
        request,
        db,
        caller,
        payload={"candidate_id": candidate_id, **body.model_dump(mode="json")},
        run=run,
    )
    # Po commicie — jak na ekranie. Klucz nikogo nie oznacza, więc dziś to
    # pusty krok; zostaje, żeby ciało i jego skutki nie rozjechały się.
    for created in created_box:
        await note_routes.send_note_create_side_effects(created)
    return response
