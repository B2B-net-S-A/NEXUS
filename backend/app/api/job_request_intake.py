# UWAGA: bez `from __future__ import annotations` — `@limiter.limit` na
# module z PEP 563 zamienia `Annotated` guardy w parametry query (slowapi #579).
"""Odczyt requestu klienta przed założeniem rekrutacji (strona /jobs/new).

Trasy tylko do odczytu — niczego nie zapisują w bazie poza
telemetrią AI (`ai_feature`). Rekrutację zakłada potem zwykłe `POST /api/jobs`,
a przekazanie do searchu zwykłe `POST /api/jobs/{id}/handoff`, więc ta
powierzchnia nie ma własnych reguł uprawnień do rekrutacji: odczyt requestu,
szkic ogłoszenia i opcje przekazania stoją za tym samym uprawnieniem co
założenie rekrutacji („Rekrutacje: zakładanie, zamykanie, wysyłka CV do
klienta” — `RecruitmentManageUser`).
"""

import logging
import os
import tempfile
from typing import Annotated, Any, Literal, Optional

import anthropic
from fastapi.concurrency import run_in_threadpool
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import OperationalUser, get_db
from app.api.permission_access import RecruitmentManageUser
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.config import settings
from app.core.rate_limit import limiter, user_or_ip_key
from app.models.ai_feature import AIFeatureKey
from app.models.client import Client
from app.models.user import User
from app.services import champion_document
from app.services import job_intake_champion_file as champion_file
from app.services import job_request_intake as intake
from app.services.ai_quota import AIQuotaExceeded, ai_feature
from app.services.auto_assign_owners import (
    pick_delivery_lead,
    resolve_default_owners,
)
from app.services.client_access import assert_client_assignable
from app.services.recruitment_allocation import effective_allocation_mode

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/job-intake", dependencies=PIPELINE_SECTION_DEPENDENCIES)

MAX_FILE_BYTES = 10 * 1024 * 1024
_ALLOWED_EXTENSIONS = (".docx", ".pdf", ".txt")
# Kto przeczytał wejście: model (`request`) albo tabele wzoru Profilu
# Championa (`champion_file.READER`). Formularz mówi to Delivery Leadowi.
READER_REQUEST = "request"


class ReadRequestBody(BaseModel):
    client_id: int = Field(..., gt=0)
    text: str = Field(
        ..., min_length=intake.MIN_REQUEST_CHARS, max_length=intake.MAX_REQUEST_CHARS
    )


async def _assert_client(db: AsyncSession, client_id: int) -> None:
    exists = await db.scalar(select(Client.id).where(Client.id == client_id))
    if exists is None:
        raise HTTPException(404, "Nie znaleziono klienta.")
    # Runda 7 (R7-X5-4): rekrutacji u usuniętego albo scalonego klienta i tak
    # nie da się założyć — mówimy to przed płatnym odczytem, nie po nim.
    await assert_client_assignable(db, client_id)


async def _read(
    db: AsyncSession, user_id: Optional[int], client_id: int, text: str
) -> dict:
    # `user_id=None` — konto serwisowe API v1 (`recruitments/read-request`):
    # zużycie AI liczy się jako „system”, odczyt jest ten sam.
    try:
        async with ai_feature(db, AIFeatureKey.champion_draft, user_id=user_id):
            await db.commit()
            result = await intake.read_request(
                db, client_id=client_id, request_text=text
            )
    except AIQuotaExceeded as exc:
        await db.rollback()
        raise HTTPException(503, {"message": exc.reason}) from exc
    except anthropic.APIError as exc:
        raise HTTPException(
            503, "Model AI chwilowo niedostępny — spróbuj za chwilę."
        ) from exc
    except (ValueError, RuntimeError) as exc:
        logger.warning("job_request_intake: read failed: %s", type(exc).__name__)
        raise HTTPException(
            502,
            "Nie udało się odczytać requestu — spróbuj ponownie albo uzupełnij pola ręcznie.",
        ) from exc
    return result.as_dict()


@router.post("/read")
@limiter.limit("20/minute", key_func=user_or_ip_key)
async def read_request(
    request: Request,
    body: ReadRequestBody,
    current_user: RecruitmentManageUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _assert_client(db, body.client_id)
    return {
        "text": body.text,
        "intake": await _read(db, current_user.id, body.client_id, body.text),
        "reader": READER_REQUEST,
    }


async def _read_champion_form(data: bytes, name: str) -> Optional[dict]:
    """Odpowiedź dla wypełnionego wzoru Profilu Championa albo ``None``.

    Wzór czytamy z tabel (D4, 10.10.2026): bez modelu, bez `ai_feature`
    i bez limitu 20 000 znaków — limit dotyczy tylko tekstu pokazywanego obok
    formularza. Parsowanie Worda idzie w puli wątków, nie na pętli procesu.
    """
    try:
        profile = await run_in_threadpool(champion_file.read_champion_form, data, name)
    except champion_file.EmptyChampionForm as exc:
        raise HTTPException(422, champion_file.EMPTY_FORM_MESSAGE) from exc
    if profile is None:
        return None
    # Drugi odczyt tego samego pliku (tabele zagnieżdżone, których odczyt wzoru
    # nie dotyka). Jego awaria nie może dać 500 — plik idzie wtedy starą ścieżką.
    try:
        text = await run_in_threadpool(champion_document.document_text, data)
    except Exception as exc:  # noqa: BLE001 — w logu sama klasa, bez treści pliku
        logger.warning(
            "job_request_intake: champion form text failed: %s", type(exc).__name__
        )
        return None
    return {
        "text": text[: intake.MAX_REQUEST_CHARS],
        "intake": champion_file.intake_from_champion(profile).as_dict(),
        "reader": champion_file.READER,
        "champion_extras": champion_file.champion_extras(profile),
    }


@router.post("/read-file")
@limiter.limit("20/minute", key_func=user_or_ip_key)
async def read_request_file(
    request: Request,
    current_user: RecruitmentManageUser,
    client_id: Annotated[int, Form(gt=0)],
    file: Annotated[UploadFile, File()],
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _assert_client(db, client_id)
    name = (file.filename or "").lower()
    if not name.endswith(_ALLOWED_EXTENSIONS):
        raise HTTPException(422, "Obsługiwane pliki: .docx, .pdf, .txt.")
    data = await file.read(MAX_FILE_BYTES + 1)
    if not data:
        raise HTTPException(422, "Plik jest pusty.")
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(413, "Plik jest za duży (maks. 10 MB).")

    suffix = os.path.splitext(name)[1]
    if suffix == ".docx":
        champion = await _read_champion_form(data, name)
        if champion is not None:
            return champion

    from app.services.cv_text_extractor import extract_text

    with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
        tmp.write(data)
        tmp.flush()
        try:
            text = await run_in_threadpool(extract_text, tmp.name, name)
        except Exception as exc:  # noqa: BLE001 — każdy błąd odczytu = 422
            raise HTTPException(422, "Nie udało się odczytać tekstu z pliku.") from exc
    text = (text or "").strip()
    if len(text) < intake.MIN_REQUEST_CHARS:
        raise HTTPException(
            422, "W pliku nie ma tekstu do odczytania (skan bez tekstu?)."
        )
    # Sprawdzane na całym tekście: rubryka pytań stoi pod koniec wzoru.
    champion_pdf = suffix == ".pdf" and champion_file.looks_like_champion_text(text)
    text = text[: intake.MAX_REQUEST_CHARS]
    result = await _read(db, current_user.id, client_id, text)
    if champion_pdf:
        result["advisories"] = [*result["advisories"], champion_file.PDF_NOTE]
    return {"text": text, "intake": result, "reader": READER_REQUEST}


class PublicDraftRequest(BaseModel):
    """Pola rekrutacji z ekranu ``/jobs/new`` — przed zapisem rekrutacji."""

    title: str = Field(..., min_length=1, max_length=255)
    client_id: Optional[int] = Field(default=None, gt=0)
    description: Optional[str] = Field(
        default=None, max_length=intake.MAX_REQUEST_CHARS
    )
    must_skills: list[str] = Field(default_factory=list, max_length=40)
    nice_skills: list[str] = Field(default_factory=list, max_length=40)
    location: Optional[str] = Field(default=None, max_length=255)
    remote_policy: Optional[Literal["onsite", "hybrid", "remote"]] = None
    onsite_days_per_week: Optional[int] = Field(default=None, ge=0, le=5)
    champion_profile: Optional[dict[str, Any]] = None


@router.post("/public-draft")
@limiter.limit("20/minute", key_func=user_or_ip_key)
async def public_draft(
    request: Request,
    body: PublicDraftRequest,
    current_user: RecruitmentManageUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Szkic ogłoszenia na portale (0381) — tytuł bez klienta, opis, uwagi kontroli.

    Nic nie zapisuje. Publikacja idzie po utworzeniu rekrutacji zwykłą
    ścieżką strony kariery (zapis opisu → zatwierdzenie → link → portal).
    """
    from types import SimpleNamespace

    from app.models.job import RemotePolicy
    from app.services.job_public_profile import (
        PublicDraftUnavailable,
        draft_for_request,
    )

    from app.services.champion_requirement_rows import expand_patch

    if body.client_id is not None:
        await _assert_client(db, body.client_id)
    request_job = SimpleNamespace(
        id=None,
        title=body.title,
        client_id=body.client_id,
        description=body.description,
        requirements=None,
        must_skills=[s for s in body.must_skills if s.strip()],
        nice_skills=[s for s in body.nice_skills if s.strip()],
        location=body.location,
        remote_policy=RemotePolicy(body.remote_policy) if body.remote_policy else None,
        onsite_days_per_week=body.onsite_days_per_week,
        seniority=None,
        # Formularz wysyła wymagania jako wiersze — szkic czyta pola z nich wyprowadzone.
        champion_profile=expand_patch(body.champion_profile or {}),
    )
    try:
        return await draft_for_request(db, request_job, user_id=current_user.id)
    except PublicDraftUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc


class CriticalSuggestionRequest(BaseModel):
    must_skills: list[str] = Field(default_factory=list, max_length=60)
    title: Optional[str] = Field(default=None, max_length=300)
    # 02.10.2026: wiersze wymagań (słowa = warianty). Gdy podane, lista MUST
    # to ich etykiety — te same, które serwer zapisze w profilu.
    # Limity wewnętrzne (przegląd bezpieczeństwa 13.10.2026): surowe słowa szły
    # do odczytu frazy bez limitu długości — jedno żądanie zamrażało API.
    rows: Optional[
        list[
            Annotated[
                list[Annotated[str, Field(max_length=1000)]], Field(max_length=50)
            ]
        ]
    ] = Field(default=None, max_length=30)


@router.post("/critical-suggestion")
@limiter.limit("60/minute", key_func=user_or_ip_key)
async def critical_suggestion(
    request: Request,
    body: CriticalSuggestionRequest,
    current_user: OperationalUser,
) -> dict:
    """Podpowiedź umiejętności krytycznych dla listy MUST (30.09.2026).

    Dla listy, której jeszcze nie zapisano (/jobs/new, edytor Championa przed
    zapisem). Czyta wyłącznie statystyki z historii — bez bazy i bez modelu.
    Oznaczyć jako krytyczną wolno KAŻDĄ pozycję (09.10.2026 — decyduje
    Delivery Lead), więc ``selectable`` to cała lista, a ``blocked`` jest
    puste; ``eligible`` = technologie ze słownika (wymóg decyzji i tytuł dla
    rekrutera); ``suggested`` = podpowiedź
    (≤2, ≥90% wysłanych ją ma).
    """
    from app.services.critical_skills import stat_for, suggest_from_must
    from app.services.must_gate_terms import critical_eligible

    labels: list[str] = []
    row_words: list[list[str]] = []
    if body.rows is not None:
        from app.services.champion_requirement_rows import clean_rows, row_label

        # Słowa per wiersz po sicie zapisu (≤ 20 słów po ≤ 100 znaków), w kolejności
        # żądania; wiersz bez słów = pusta lista i pusta etykieta.
        row_words = [
            cleaned[0]["words"] if cleaned else []
            for cleaned in (
                clean_rows([{"words": row, "level": "must"}]) for row in body.rows
            )
        ]
        labels = [row_label(words) if words else "" for words in row_words]
        must = [label for label in labels if label]
    else:
        must = [s.strip()[:500] for s in body.must_skills if s and s.strip()]
    eligible = [label for label in must if critical_eligible(label)]
    stats = {}
    for label in eligible:
        stat = stat_for(label)
        if stat is not None:
            stats[label] = {"rate": stat.rate, "jobs": stat.jobs}
    # 13.10.2026 (wariant A): jak system przeczyta każde słowo wiersza — edytor
    # pokazuje pod zdaniem „zamień na słowa” albo „do rozmowy”.
    from app.services.requirement_phrase import read_row

    readings = [
        [reading.as_dict() for reading in read_row(words)] for words in row_words
    ]
    return {
        "readings": readings,
        "suggested": list(suggest_from_must(must, body.title or "")),
        "eligible": eligible,
        # Od 09.10.2026 krytyczną może być każda pozycja — decyduje Delivery
        # Lead. Oba pola zostają dla kart przeglądarki sprzed wdrożenia.
        "selectable": list(must),
        "blocked": {},
        "stats": stats,
        "labels": labels,
    }


class RequirementRowsRequest(BaseModel):
    must: list[str] = Field(default_factory=list, max_length=60)
    nice: list[str] = Field(default_factory=list, max_length=60)
    requirements: list[list[str]] = Field(default_factory=list, max_length=30)
    critical: Optional[list[str]] = Field(default=None, max_length=10)


@router.post("/requirement-rows")
@limiter.limit("60/minute", key_func=user_or_ip_key)
async def requirement_rows(
    request: Request,
    body: RequirementRowsRequest,
    current_user: OperationalUser,
) -> dict:
    """Stare pola wymagań → wiersze słów kluczowych (02.10.2026).

    Dla „Uprość do słów kluczowych” w Profilu Championa i dla kopii rekrutacji
    z szablonu. Niczego nie zapisuje i nie woła modelu: technologię rozpoznaje
    ta sama reguła co bramka must, zdania klienta wracają jako ``descriptive``.
    """
    from app.services.champion_requirement_rows import rows_from_legacy

    return rows_from_legacy(
        must=[s.strip()[:500] for s in body.must if s and s.strip()],
        nice=[s.strip()[:500] for s in body.nice if s and s.strip()],
        requirements=[
            [w.strip()[:100] for w in row if isinstance(w, str) and w.strip()]
            for row in body.requirements
        ],
        critical=body.critical,
    )


class CategorySuggestionRequest(BaseModel):
    role: Optional[str] = Field(default=None, max_length=300)
    client_title: Optional[str] = Field(default=None, max_length=300)
    description: Optional[str] = Field(
        default=None, max_length=intake.MAX_REQUEST_CHARS
    )
    must_skills: list[str] = Field(default_factory=list, max_length=60)
    nice_skills: list[str] = Field(default_factory=list, max_length=60)


@router.post("/category-suggestion")
@limiter.limit("60/minute", key_func=user_or_ip_key)
async def category_suggestion(
    request: Request,
    body: CategorySuggestionRequest,
    current_user: RecruitmentManageUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Podpowiedź kategorii kompetencji PRZED założeniem rekrutacji (02.10.2026).

    Ta sama reguła co przy zapisie (`job_cc.resolve_job_cc_id`): najpierw nazwa
    roli, potem klasyfikator po treści. Delivery Lead potwierdza kategorię na
    formularzu, bo od niej zależy, kto dostanie rekrutację. ``participants`` to
    liczba osób, które zostaną uczestnikami — bez nazwisk.
    """
    from types import SimpleNamespace

    from app.models.competence_category import CompetenceCategory
    from app.services.auto_cc_collaborators import participants_count
    from app.services.job_cc import resolve_job_cc_id

    categories = list(
        (
            await db.scalars(
                select(CompetenceCategory)
                .where(CompetenceCategory.is_active.is_(True))
                .order_by(CompetenceCategory.display_order, CompetenceCategory.id)
            )
        ).all()
    )
    title = " ".join(
        part.strip() for part in (body.role, body.client_title) if part and part.strip()
    )
    suggested_id: Optional[int] = None
    if title:
        try:
            suggested_id = await resolve_job_cc_id(
                SimpleNamespace(
                    id=None,
                    title=title,
                    description=body.description,
                    requirements=None,
                    subcategory=None,
                    industry=None,
                    must_skills=body.must_skills,
                    nice_skills=body.nice_skills,
                ),
                db,
            )
        except Exception:  # noqa: BLE001 — podpowiedź to dodatek, DL i tak wybiera
            logger.warning(
                "job_request_intake: category suggestion failed", exc_info=True
            )
    active_ids = {category.id for category in categories}
    counts = await participants_count(db, sorted(active_ids))
    return {
        "suggested_id": suggested_id if suggested_id in active_ids else None,
        "categories": [
            {
                "id": category.id,
                "slug": category.slug,
                "name": category.name_pl,
                "participants": int(counts.get(category.id, 0)),
            }
            for category in categories
        ],
    }


@router.get("/handoff-options")
@limiter.limit("60/minute", key_func=user_or_ip_key)
async def handoff_options(
    request: Request,
    current_user: RecruitmentManageUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Czy „Przydziel automatycznie” da się wybrać przed założeniem rekrutacji.

    Strona /jobs/new nie ma jeszcze rekrutacji, więc nie może zapytać
    `GET /api/jobs/{id}/readiness`. Ta sama flaga co w handoffie
    (`RECRUITMENT_ALLOCATION_ENABLED`) i tryb automatu przydziału (0371):
    `shadow` tylko proponuje osobę, `auto` ją przypisuje.
    """
    return {
        "automatic_enabled": bool(settings.RECRUITMENT_ALLOCATION_ENABLED),
        # Ta sama reguła co `readiness.allocation_mode` i odmowa 409 w handoffie.
        "mode": await effective_allocation_mode(db),
    }


@router.get("/delivery-lead")
@limiter.limit("60/minute", key_func=user_or_ip_key)
async def default_delivery_lead(
    request: Request,
    current_user: RecruitmentManageUser,
    client_id: Annotated[int, Query(ge=1)],
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Kto zostanie Delivery Leadem rekrutacji, jeśli formularz nikogo nie wskaże.

    Ta sama reguła co zapis (`pick_delivery_lead`): osoba z rolą Delivery Leada
    jest DL-em rekrutacji, którą zakłada; inaczej główny DL klienta. Do
    08.10.2026 formularz tego nie pokazywał i pomyłkę było widać dopiero po
    utworzeniu rekrutacji.
    """
    resolved = await resolve_default_owners(db, client_id)
    user_id, source = pick_delivery_lead(current_user, resolved.delivery_lead_id)
    if user_id is None:
        return {"default": None}
    name = (
        current_user.name
        if user_id == current_user.id
        else await db.scalar(select(User.name).where(User.id == user_id))
    )
    return {"default": {"user_id": user_id, "name": name, "source": source}}
