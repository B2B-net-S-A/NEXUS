"""CV Generator B2B — standalone module API.

Routes mounted under ``/api/cv-generator``:

  * ``GET  /candidates``                  — typeahead search (name, lastname, email)
  * ``GET  /candidates/{id}/recruitments`` — list candidate's processes + readiness
  * ``POST /generate``                    — New mode: generate DOCX from NEXUS DB
  * ``POST /generate-upload``             — Old mode: generate DOCX from manual uploads
                                            (1:1 with external CV-Generator)

All endpoints require an authenticated user (any role).

NOTE: this module must NOT use ``from __future__ import annotations``. The two
``@limiter.limit`` (slowapi) POST endpoints below take params whose FastAPI
markers live only inside ``Annotated[...]`` (``cv_file`` → ``File()``,
``current_user`` → ``Depends()``) with no default value. Under PEP 563 the
slowapi wrapper makes FastAPI evaluate those stringized annotations against
slowapi's module globals (where ``UploadFile``/``File``/``Depends`` are
undefined), so the markers are lost and the params get misclassified as required
*query* params → ``422 {"loc":["query","cv_file"],"msg":"Field required"}`` at
request time. Real (non-stringized) annotations sidestep it. Same reason as
``cv_match_preview``.
"""

import hashlib
import json
import logging
from contextlib import nullcontext
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Literal, Optional
from urllib.parse import quote

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
    status,
)
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

# Re-audyt M2 (PR1c): kolejna rownolegla powierzchnia danych kandydata.
# Panel generatora B2B jest w sidebarze dostepny dla WSZYSTKICH rol, a jego
# trasy stały na golym CurrentUser: typeahead przeszukiwal cala baze po
# imieniu/nazwisku/emailu (puste q = ostatnio modyfikowani), lista pokazywala
# candidate_name cudzych CV, a /generated/{id}/docx NIE MIAL zadnej kontroli
# wlasnosci (403 przy 755 dotyczy DELETE) -> viewer pobieral dowolne
# wygenerowane CV kandydata chodzac po sekwencyjnym ID.
from app.api.candidate_access import (
    CandidateDocumentAccess,
    CandidatePIIAccess,
    CandidateSearchAccess,
    CandidateWriteAccess,
)
from app.api.recruitment_access import (
    ensure_job_membership,
    ensure_job_read_access,
    job_read_scope_clause,
)
from app.core.database import AsyncSessionLocal, get_db
from app.core.rate_limit import limiter
from app.models.activity import Activity
from app.models.ai_feature import AIFeatureKey
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.cv_generated_document import CvGeneratedDocument
from app.models.cv_generated_share import CvGeneratedShareToken
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User, UserRole
from app.services import object_storage
from app.services.ai_quota import (
    AIQuotaExceeded,
    QuotaState,
    check_and_increment,
    declared_call,
)
from app.services.cv_generator_b2b import consent_binding
from app.services.cv_generator_b2b.upload_preflight import (
    MAX_UPLOAD_BYTES,
    validate_upload_inputs,
)
from app.services.cv_generator_b2b.client_rules import (
    required_input_problems,
    resolve_client_rule,
    resolve_content_mode,
    snapshot_rule,
)
from app.services.cv_generator_b2b.standalone_service import (
    ContentMode,
    DEFAULT_CONTENT_MODE,
    StandaloneGenerationError,
    UploadGenerationInput,
    apply_content_mode_cap,
    ascii_filename_fallback,
    champion_present,
    generate_cv_for_candidate,
    generate_cv_from_uploads,
    list_recruitments_with_readiness,
    rerender_docx_from_payload,
    screening_notes_char_count,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cv-generator", tags=["cv-generator-b2b"])


# ── Schemas ────────────────────────────────────────────────────────────────


class CandidateOption(BaseModel):
    """Typeahead row — just enough to render the picker."""

    id: int
    name: str
    lastname: str
    full_name: str
    position: Optional[str] = None
    email: Optional[str] = None


class RecruitmentOption(BaseModel):
    """A recruitment process the candidate participates in."""

    stage_id: int
    job_id: int
    job_title: str
    stage: str
    has_champion: bool
    has_notes: bool
    has_cv: bool
    # Długość notatek, które poszłyby do modelu — reguła klienta może wymagać
    # minimum, a front ma to pokazać PRZED kliknięciem (0267).
    notes_chars: int = 0
    ready: bool
    content_mode: ContentMode = DEFAULT_CONTENT_MODE
    required_champion: bool = False
    required_notes_min_chars: int = 0
    missing_inputs: list[str] = Field(default_factory=list)
    # Klient wyprowadzony z oferty — w tym trybie NIE jest wybierany ręcznie.
    client_id: Optional[int] = None
    client_name: Optional[str] = None


class GenerateRequest(BaseModel):
    candidate_id: int = Field(..., ge=1)
    stage_id: int = Field(..., ge=1)
    # Klient jest wyprowadzany z rekrutacji; jawna wartość służy wyłącznie do
    # sprawdzenia, że front i serwer mówią o tym samym. Rozjazd = 422, bo
    # cicha wygrana którejkolwiek strony oznaczałaby zastosowanie reguł
    # (nazwa pliku, język) innego klienta niż widzi rekruter.
    client_id: Optional[int] = Field(default=None, ge=1)
    # Numer/nazwa projektu do tokenu {PROJEKT} we wzorze nazwy pliku
    # (ENERGA, ORLEN, PKO BP). Nie da się go wyprowadzić z oferty.
    project_ref: str = Field(default="", max_length=120)
    language: Literal["pl", "en"] = "pl"
    blind_cv: bool = False
    # Defaults to "polished", never "tailored": the most-positioned variant has
    # to be an explicit choice. May be lowered by the client's cap.
    content_mode: ContentMode = DEFAULT_CONTENT_MODE
    # Legacy storage keys require a matching signed receipt; they cannot
    # authorize attachment reuse on their own. New clients send only the token.
    consent_screenshot_key: str = Field(default="", max_length=500)
    consent_screenshot_token: str = Field(default="", max_length=4096)


class GeneratedCvItem(BaseModel):
    """A row in the „Wygenerowane CV" panel list."""

    id: int
    candidate_id: Optional[int] = None
    job_id: Optional[int] = None
    client_id: Optional[int] = None
    client_name: Optional[str] = None
    candidate_name: str
    position: Optional[str] = None
    language: str
    blind: bool
    mode: str
    # Ile obróbki prezentacyjnej faktycznie zastosowano przy tej generacji.
    # Celowo BEZ wartości domyślnej: każda domyślna zgadywałaby tryb dokumentu,
    # który już poszedł do klienta. Historia to "tailored", nowe wiersze bywają
    # dowolne — brak wartości ma być głośnym błędem serializacji, nie cichym
    # przekłamaniem w panelu.
    content_mode: str
    filename: str
    # Async generation lifecycle — the UI polls this list and renders a spinner
    # for "processing", the CV for "ready" and the reason for "failed".
    status: str = "ready"
    error_message: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
    created_at: Optional[str] = None
    created_by_name: Optional[str] = None
    can_download: bool
    can_delete: bool


class GenerateEnqueuedResponse(BaseModel):
    """202 payload — generation was enqueued and runs in the background.

    The recruiter can leave the tab; the result appears on ``GET /generated``
    (poll it) with ``status`` flipping to „ready" or „failed"."""

    id: int
    status: str = "processing"
    candidate_name: str


# ── Helpers ────────────────────────────────────────────────────────────────


def _error_status(code: str) -> int:
    return {
        "candidate_not_found": 404,
        "stage_not_found": 404,
        "no_cv_file": 422,
        "no_champion": 422,
        "no_notes": 422,
        "notes_too_short": 422,
        "missing_required_input": 422,
        "invalid_input": 400,
        "extraction_failed": 502,
        "ai_failed": 502,
        "ai_overloaded": 503,
        "render_failed": 500,
    }.get(code, 500)


def _build_docx_response(
    docx_bytes: bytes,
    filename: str,
    candidate_name: str,
    warnings: list[str],
    processing_time_ms: int,
    generated_id: int | None = None,
) -> Response:
    """Wrap a generated DOCX in the standard streaming Response with metadata
    headers used by both ``/generate`` and ``/generate-upload``.

    HTTP header values must be latin-1 (ISO-8859-1) encodable. Candidate names
    and Claude warnings routinely carry Polish characters (ł, ą, ę…) that fall
    outside latin-1; emitting them raw makes the ASGI server raise
    ``UnicodeEncodeError`` while serializing headers, surfacing as a bare 500.
    Percent-encode the human-readable name and force ASCII-only ``\\uXXXX``
    escapes in the warnings JSON — ``decodeURIComponent`` / ``JSON.parse`` on
    the client decode both transparently.

    The filename follows the same rule via RFC 6266/5987: an ASCII ``filename=``
    fallback (latin-1 safe) plus a ``filename*=UTF-8''…`` parameter carrying the
    real, Polish-character spelling so modern clients save it intact.
    """
    ascii_name = ascii_filename_fallback(filename)
    disposition = f'attachment; filename="{ascii_name}"'
    if filename != ascii_name:
        disposition += f"; filename*=UTF-8''{quote(filename, safe='')}"
    headers = {
        "Content-Disposition": disposition,
        "X-Generator-Candidate-Name": quote(candidate_name),
        "X-Generator-Warnings": json.dumps(warnings, ensure_ascii=True),
        "X-Generator-Processing-Ms": str(processing_time_ms),
        "Access-Control-Expose-Headers": (
            "Content-Disposition, X-Generator-Candidate-Name, "
            "X-Generator-Warnings, X-Generator-Processing-Ms, X-Generated-Id"
        ),
    }
    if generated_id is not None:
        headers["X-Generated-Id"] = str(generated_id)
    return Response(
        content=docx_bytes,
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        headers=headers,
    )


def _enforce_client_language(rule, requested_language: str) -> None:
    """422, gdy klient wymaga innego języka CV niż wybrany w formularzu.

    Odmowa jest jawna, a nie ciche przestawienie języka: rekruter, który
    świadomie wybrał polski, ma zobaczyć powód, a nie dostać angielski
    dokument bez wyjaśnienia. Reguła bez `cv_language` (m.in. czterej klienci
    wymagający OBU wersji) nie ogranicza niczego.
    """
    if rule is None or not rule.cv_language:
        return
    if rule.cv_language == requested_language:
        return
    wanted = "polskim" if rule.cv_language == "pl" else "angielskim"
    raise HTTPException(
        status_code=422,
        detail=(
            f"Ten klient wymaga CV w języku {wanted} "
            f"({rule.cv_language.upper()}). Zmień język generacji albo zdejmij "
            f"wymóg w regułach CV klienta."
        ),
    )


async def _create_pending_row(
    db: AsyncSession,
    *,
    mode: str,
    candidate_id: int | None,
    candidate_name: str,
    position: str | None,
    language: str,
    blind_cv: bool,
    user_id: int,
    content_mode: str,
    client_id: int | None = None,
    job_id: int | None = None,
) -> int:
    """Insert a „processing" placeholder so the CV shows on the list the moment
    generation is enqueued — the recruiter can then close the tab while the
    background job fills in ``render_payload`` / ``status``. Returns the row id.

    ``content_mode`` is the REQUESTED mode; a per-client cap may lower it, and
    :func:`_finalize_success` overwrites this with what the pipeline actually
    used, so the stored value always describes the delivered document.
    """
    row = CvGeneratedDocument(
        candidate_id=candidate_id,
        job_id=job_id,
        client_id=client_id,
        candidate_name=candidate_name or "Generowanie…",
        position=position,
        language=language,
        blind=blind_cv,
        mode=mode,
        content_mode=content_mode,
        filename="",  # filled from the rendered filename on completion
        status="processing",
        render_payload=None,
        created_by=user_id,
    )
    db.add(row)
    await db.flush()  # assign row.id before commit so the caller can return it
    return row.id


async def _finalize_success(
    db: AsyncSession,
    generated_id: int,
    *,
    result,
    consent_screenshot: Optional[dict] = None,
    rule_version: Optional[int] = None,
) -> bool:
    """Flip a „processing" row to „ready" with its render payload + warnings, so
    it can be re-downloaded/previewed later without another Claude call. Returns
    ``False`` when the row vanished (recruiter deleted it mid-generation).
    """
    row = await db.get(CvGeneratedDocument, generated_id)
    if row is None:
        return False
    payload = result.render_payload or {}
    # For blind CVs ``result.candidate_name`` is the anonymized "Kandydat" — use
    # the real name captured in the payload so the INTERNAL list stays
    # identifiable (the DOCX itself remains anonymized on re-render).
    row.candidate_name = str(payload.get("name") or result.candidate_name)
    row.position = payload.get("position")
    # Upload parsing has no recruitment context; retain the authorized enqueue binding.
    if result.job_id is not None:
        row.job_id = result.job_id
    row.filename = result.filename
    # Zrzut zgody kandydata (wymóg PKO BP) doklejamy do payloadu, a nie do
    # osobnej kolumny: DOCX jest re-renderowany z payloadu przy KAŻDYM pobraniu,
    # więc wszystko, co ma być w pliku, musi tam być. Zapisujemy sam klucz
    # w magazynie — obraz waży setki kilobajtów i w JSONB puchłby przy każdym
    # odczycie wiersza.
    if consent_screenshot and isinstance(result.render_payload, dict):
        result.render_payload["consent_screenshot"] = consent_screenshot
    row.render_payload = result.render_payload
    row.warnings = list(result.warnings or [])
    # Stempel wersji reguły klienta (0267) — odpowiedź na „którą regułą
    # powstało CV, na które klient się skarży".
    if rule_version is not None:
        row.client_rule_version = rule_version
    # The mode the pipeline ACTUALLY ran with — a per-client cap may have
    # lowered what the recruiter requested, and the row has to describe the
    # document that reached the client, not the intent behind it. Only written
    # when the payload carries one, so re-finalising an older payload leaves
    # the value the row was created with rather than blanking it.
    payload_mode = payload.get("content_mode")
    if payload_mode:
        row.content_mode = str(payload_mode)
    row.error_message = None
    row.status = "ready"
    return True


async def _charge_cv_generation_quota(db: AsyncSession, user_id: int) -> QuotaState:
    """Obciąż kwotę AI za generację CV B2B — i odmów, gdy jest wyczerpana.

    To NAJDROŻSZE wywołanie Claude'a w produkcie (16 384 tokeny outputu, łańcuch
    Sonnet → Opus, do 3 prób na model), a stało całkowicie poza systemem kwot:
    `AIMasterToggle.enabled = False` jest sprawdzany wyłącznie wewnątrz
    `check_and_increment`, którego ta ścieżka nigdy nie wołała. Admin gasił AI
    w Ustawieniach → AI (UI twierdzi „Wszystkie funkcje AI są wyłączone
    globalnie"), a `POST /generate` i `/generate-upload` dalej wydawały
    pieniądze — przy czym w tym samym background-jobie tani precompute mapy
    wymagań był posłusznie odmawiany, bo TEN akurat miał swój klucz.

    `check_and_increment`, nie `async with ai_feature(...)`: kontekst deklaracji
    z `ai_feature` nie przeżyłby do miejsca wydatku. Claude jest tu wołany w
    `BackgroundTasks`, czyli PO zamknięciu bloku handlera, a `ai_client` tego
    generatora buduje klienta SDK bezpośrednio (nie przez `claude_client`), więc
    `_assert_declared` i tak go nie ogląda. Deklaracja byłaby obietnicą pokrycia,
    którego nie ma; liczenie i sufit działają niezależnie od niej.

    Naliczamy DECYZJĘ O DOPUSZCZENIU, nie sukces round-tripu do dostawcy —
    tak samo jak generator ogłoszeń. Nieudana generacja też kosztowała tokeny,
    więc darmowe ponowienie po awarii byłoby dziurą w suficie.

    Bramka stoi w handlerze, PRZED założeniem wiersza „processing": odrzucenie
    w tle zostawiłoby na liście wiersz „failed" zamiast czytelnego 503, a
    rekruter nie dowiedziałby się, że to decyzja administratora, nie awaria.
    Licznik commituje wywołujący razem z wierszem „processing" — 404 na
    kandydacie nie commituje niczego, więc nie obciąża kwoty.
    """
    from app.models.ai_feature import AIFeatureKey
    from app.services.ai_quota import (
        AIQuotaExceeded,
        check_and_increment,
    )

    try:
        return await check_and_increment(db, AIFeatureKey.cv_generator, user_id=user_id)
    except AIQuotaExceeded as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "feature": exc.feature.value,
                "reason": exc.reason,
                "used": exc.used,
                "limit": exc.limit,
            },
        ) from exc


async def _run_declared(fn, *args, quota_state=None, quota_user_id=None, **kwargs):
    """Odpal zadanie w tle z DEKLARACJĄ kwoty naliczonej już w handlerze.

    `BackgroundTasks` biegnie po odesłaniu odpowiedzi, więc contextvar
    ustawiony przez handler jest już zresetowany, a generacja CV — najdroższe
    wywołanie w produkcie — dolatuje do granicy dostawcy jako niezadeklarowana.
    Pod `AI_QUOTA_STRICT` skończyłaby się wyjątkiem mimo poprawnie naliczonej
    kwoty.

    Owijamy TUTAJ, na poziomie zakolejkowania, a nie w ciele zadania: ciała obu
    generacji mają po kilkaset linii i wcięcie ich w `with` dałoby diff, w
    którym nie widać zmiany logiki. Bramka odmowy zostaje w handlerze — odmowa
    w tle zostawiłaby wiersz „failed" zamiast czytelnego 503.
    """
    declaration = (
        declared_call(
            AIFeatureKey.cv_generator, user_id=quota_user_id, state=quota_state
        )
        if quota_state is not None
        else nullcontext()
    )
    with declaration:
        await fn(*args, **kwargs)


async def _finalize_failure(db: AsyncSession, generated_id: int, message: str) -> None:
    """Mark a „processing" row „failed" with the reason. No-op if it's gone."""
    row = await db.get(CvGeneratedDocument, generated_id)
    if row is None:
        return
    row.status = "failed"
    row.error_message = message[:1000]


def _reject_missing_inputs(problems: list[str]) -> None:
    """422 z listą braków — PRZED naliczeniem kwoty, jak zrzut zgody u PKO BP."""
    if problems:
        raise HTTPException(status_code=422, detail="\n".join(problems))


def _second_language(rule, language: str) -> Optional[str]:
    """Język drugiej wersji, gdy reguła każe ją generować automatycznie.

    Tylko gdy klient oczekuje OBU wersji i nie wymusza jednego języka —
    przy wymuszonym języku druga wersja byłaby dokumentem, którego klient
    nie chce. ``None`` = nic nie generuj.
    """
    if rule is None or not rule.auto_second_language or not rule.requires_en_copy:
        return None
    if rule.cv_language:
        return None
    return "en" if language == "pl" else "pl"


async def _charge_second_language_or_note(
    db: AsyncSession, *, first_generated_id: int, user_id: int
) -> bool:
    """Obciąż kwotę za drugą wersję; przy odmowie dopisz uwagę do pierwszego
    wiersza zamiast padać — druga wersja jest wygodą, pierwsza już powstała."""
    try:
        await check_and_increment(db, AIFeatureKey.cv_generator, user_id=user_id)
        return True
    except AIQuotaExceeded as exc:
        row = await db.get(CvGeneratedDocument, first_generated_id)
        if row is not None:
            row.warnings = [
                *list(row.warnings or []),
                "Druga wersja językowa nie powstała: "
                + (exc.reason or "limit AI wyczerpany")
                + " — wygeneruj ją ręcznie.",
            ]
        await db.commit()
        return False


# ── Background generation jobs ─────────────────────────────────────────────
#
# Scheduled via FastAPI ``BackgroundTasks`` AFTER the 202 response is fully sent,
# so a client disconnect (recruiter closing the tab) no longer cancels the work —
# that is the whole point of this feature. Each job owns a fresh DB session
# (the request session is long gone) and never raises: any failure is written
# onto the row as ``status="failed"``. Orphaned „processing" rows left by a
# server restart mid-job are reaped to „failed" on startup (see main.lifespan).


async def _run_generate_new_job(
    generated_id: int,
    *,
    candidate_id: int,
    stage_id: int,
    language: Literal["pl", "en"],
    blind_cv: bool,
    user_id: int,
    content_mode: ContentMode = DEFAULT_CONTENT_MODE,
    client_id: int | None = None,
    project_ref: str = "",
    consent_screenshot: Optional[dict] = None,
) -> None:
    """Background worker for New-mode (DB-backed) generation."""
    async with AsyncSessionLocal() as db:
        try:
            # Regułę czytamy w SESJI TEGO ZADANIA i od razu zamrażamy do
            # snapshotu — pipeline jest synchroniczny i leci w threadpoolu,
            # gdzie dostęp do atrybutu wiersza ORM kończy się MissingGreenlet.
            rule = await resolve_client_rule(db, client_id)
            rule_snapshot = snapshot_rule(rule)
            result = await generate_cv_for_candidate(
                db,
                candidate_id=candidate_id,
                stage_id=stage_id,
                language=language,
                blind_cv=blind_cv,
                content_mode=content_mode,
                client_rule=rule_snapshot,
                project_ref=project_ref or None,
            )
        except StandaloneGenerationError as err:
            await _finalize_failure(db, generated_id, err.message)
            await db.commit()
            return
        except Exception as err:  # noqa: BLE001 — a job must never crash silently
            logger.exception("[cv_b2b] New-mode job %s crashed: %s", generated_id, err)
            await _finalize_failure(
                db, generated_id, "Nieoczekiwany błąd generacji CV."
            )
            await db.commit()
            return

        finalized = await _finalize_success(
            db,
            generated_id,
            result=result,
            consent_screenshot=consent_screenshot,
            rule_version=rule_snapshot.version if rule_snapshot else None,
        )
        if finalized:
            db.add(
                Activity(
                    entity_type="candidate",
                    entity_id=candidate_id,
                    action="b2b_cv_generated",
                    details={
                        "stage_id": stage_id,
                        "language": language,
                        "blind_cv": blind_cv,
                        "content_mode_requested": content_mode,
                        "content_mode_used": (result.render_payload or {}).get(
                            "content_mode"
                        ),
                        "filename": result.filename,
                        "warnings_count": len(result.warnings),
                        "processing_time_ms": result.processing_time_ms,
                        "generated_id": generated_id,
                    },
                    user_id=user_id,
                )
            )
        await db.commit()

        # Interaktywne CV: precompute mapy „wymaganie → dowody" (kafelki na
        # publicznym linku). Fail-open — porażka/kwota nie psuje generacji,
        # link działa wtedy w samym widoku classic.
        if finalized:
            from app.services.cv_generator_b2b.requirement_map import (
                ensure_requirement_map,
            )

            await ensure_requirement_map(db, generated_id, user_id=user_id)

        # Druga wersja językowa (0267): klient oczekuje PL i EN, a Delivery
        # Lead włączył automat. Osobny wiersz na liście, osobna kwota, osobna
        # awaria — porażka drugiej nie dotyka pierwszej.
        second = _second_language(rule_snapshot, language) if finalized else None
        if second is not None:
            if not await _charge_second_language_or_note(
                db, first_generated_id=generated_id, user_id=user_id
            ):
                return
            first_row = await db.get(CvGeneratedDocument, generated_id)
            second_id = await _create_pending_row(
                db,
                mode="new",
                candidate_id=candidate_id,
                candidate_name=first_row.candidate_name if first_row else "Kandydat",
                position=first_row.position if first_row else None,
                language=second,
                blind_cv=blind_cv,
                user_id=user_id,
                content_mode=content_mode,
                client_id=client_id,
                job_id=result.job_id,
            )
            await db.commit()
            try:
                second_result = await generate_cv_for_candidate(
                    db,
                    candidate_id=candidate_id,
                    stage_id=stage_id,
                    language=second,  # type: ignore[arg-type]
                    blind_cv=blind_cv,
                    content_mode=content_mode,
                    client_rule=rule_snapshot,
                    project_ref=project_ref or None,
                )
            except StandaloneGenerationError as err:
                await _finalize_failure(db, second_id, err.message)
                await db.commit()
                return
            except Exception as err:  # noqa: BLE001
                logger.exception(
                    "[cv_b2b] second-language job %s crashed: %s", second_id, err
                )
                await _finalize_failure(
                    db, second_id, "Nieoczekiwany błąd generacji CV."
                )
                await db.commit()
                return
            second_finalized = await _finalize_success(
                db,
                second_id,
                result=second_result,
                consent_screenshot=consent_screenshot,
                rule_version=rule_snapshot.version if rule_snapshot else None,
            )
            if second_finalized:
                db.add(
                    Activity(
                        entity_type="candidate",
                        entity_id=candidate_id,
                        action="b2b_cv_generated",
                        details={
                            "stage_id": stage_id,
                            "language": second,
                            "blind_cv": blind_cv,
                            "content_mode_requested": content_mode,
                            "content_mode_used": (
                                second_result.render_payload or {}
                            ).get("content_mode"),
                            "filename": second_result.filename,
                            "warnings_count": len(second_result.warnings),
                            "processing_time_ms": second_result.processing_time_ms,
                            "generated_id": second_id,
                            "auto_second_language": True,
                        },
                        user_id=user_id,
                    )
                )
            await db.commit()
            if second_finalized:
                from app.services.cv_generator_b2b.requirement_map import (
                    ensure_requirement_map,
                )

                await ensure_requirement_map(db, second_id, user_id=user_id)


def _upload_requirements(payload: UploadGenerationInput) -> list[dict[str, str]]:
    """Wymagania na kafelki dla trybu upload (brak joba).

    Pierwszeństwo mają RĘCZNE pola rekrutera; gdy puste, a wgrano plik
    championa — sekcje MUST-HAVE/NICE-TO-HAVE z niego. Champion jest tu
    parsowany DRUGI raz (pierwszy — w pipeline generacji): świadomie, to tani
    regex na DOCX, a przewlekanie list przez ``GenerationResult`` wiązałoby
    kontrakt wyniku generacji z feature'em kafelków. Zwraca [] gdy brak źródeł.
    """
    from app.services.cv_generator_b2b.requirement_map import (
        parse_manual_requirements,
    )

    requirements = parse_manual_requirements(
        payload.must_requirements, payload.nice_requirements
    )
    if not requirements and payload.champion_bytes:
        try:
            from app.services.cv_generator_b2b.champion_builder import (
                parse_champion_from_docx_bytes,
            )

            champ = parse_champion_from_docx_bytes(
                payload.champion_bytes,
                payload.champion_filename or "champion.docx",
            )
            requirements = parse_manual_requirements(
                ", ".join(champ.must_have), ", ".join(champ.nice_to_have)
            )
        except Exception as err:  # noqa: BLE001 — fallback nie psuje mapy
            logger.warning("[cv_b2b] champion parse for requirements failed: %s", err)
    return requirements


async def _run_generate_upload_job(
    generated_id: int,
    *,
    payload: UploadGenerationInput,
    user_id: int,
    consent_screenshot: Optional[dict] = None,
) -> None:
    """Background worker for Old-mode (manual upload) generation."""
    async with AsyncSessionLocal() as db:
        try:
            result = await run_in_threadpool(generate_cv_from_uploads, payload)
        except StandaloneGenerationError as err:
            await _finalize_failure(db, generated_id, err.message)
            await db.commit()
            return
        except Exception as err:  # noqa: BLE001 — a job must never crash silently
            logger.exception("[cv_b2b] Upload job %s crashed: %s", generated_id, err)
            await _finalize_failure(
                db, generated_id, "Nieoczekiwany błąd generacji CV."
            )
            await db.commit()
            return

        finalized = await _finalize_success(
            db,
            generated_id,
            result=result,
            consent_screenshot=consent_screenshot,
            rule_version=payload.client_rule.version if payload.client_rule else None,
        )
        if finalized:
            # Upload mode has no candidate context — anchor the audit on the user.
            db.add(
                Activity(
                    entity_type="user",
                    entity_id=user_id,
                    action="b2b_cv_generated_upload",
                    details={
                        "cv_filename": payload.cv_filename,
                        "language": payload.language,
                        "blind_cv": payload.blind_cv,
                        "content_mode": payload.content_mode,
                        "filename": result.filename,
                        "warnings_count": len(result.warnings),
                        "processing_time_ms": result.processing_time_ms,
                        "generated_id": generated_id,
                    },
                    user_id=user_id,
                )
            )
        await db.commit()

        # Interaktywne CV w trybie upload: kafelki powstają z RĘCZNYCH wymagań
        # rekrutera, a gdy ich brak — z wgranego pliku championa (ma sekcje
        # MUST-HAVE / NICE-TO-HAVE). Bez żadnego źródła = link classic-only.
        # Fail-open jak w trybie "new" — mapa nigdy nie psuje generacji.
        if finalized:
            from app.services.cv_generator_b2b.requirement_map import (
                ensure_requirement_map,
            )

            requirements = _upload_requirements(payload)
            if requirements:
                await ensure_requirement_map(
                    db, generated_id, user_id=user_id, requirements=requirements
                )

        # Druga wersja językowa (0267) — patrz worker trybu „new".
        second = (
            _second_language(payload.client_rule, payload.language)
            if finalized
            else None
        )
        if second is not None:
            import dataclasses

            if not await _charge_second_language_or_note(
                db, first_generated_id=generated_id, user_id=user_id
            ):
                return
            first_row = await db.get(CvGeneratedDocument, generated_id)
            second_payload = dataclasses.replace(payload, language=second)  # type: ignore[arg-type]
            second_id = await _create_pending_row(
                db,
                mode="upload",
                candidate_id=first_row.candidate_id if first_row else None,
                job_id=first_row.job_id if first_row else None,
                candidate_name=first_row.candidate_name if first_row else "Kandydat",
                position=payload.position or None,
                language=second,
                blind_cv=payload.blind_cv,
                user_id=user_id,
                content_mode=payload.content_mode,
                client_id=first_row.client_id if first_row else None,
            )
            await db.commit()
            try:
                second_result = await run_in_threadpool(
                    generate_cv_from_uploads, second_payload
                )
            except StandaloneGenerationError as err:
                await _finalize_failure(db, second_id, err.message)
                await db.commit()
                return
            except Exception as err:  # noqa: BLE001
                logger.exception(
                    "[cv_b2b] second-language upload %s crashed: %s", second_id, err
                )
                await _finalize_failure(
                    db, second_id, "Nieoczekiwany błąd generacji CV."
                )
                await db.commit()
                return
            second_finalized = await _finalize_success(
                db,
                second_id,
                result=second_result,
                consent_screenshot=consent_screenshot,
                rule_version=(
                    payload.client_rule.version if payload.client_rule else None
                ),
            )
            if second_finalized:
                db.add(
                    Activity(
                        entity_type="user",
                        entity_id=user_id,
                        action="b2b_cv_generated_upload",
                        details={
                            "cv_filename": payload.cv_filename,
                            "language": second,
                            "blind_cv": payload.blind_cv,
                            "content_mode": payload.content_mode,
                            "filename": second_result.filename,
                            "warnings_count": len(second_result.warnings),
                            "processing_time_ms": second_result.processing_time_ms,
                            "generated_id": second_id,
                            "auto_second_language": True,
                        },
                        user_id=user_id,
                    )
                )
            await db.commit()
            if second_finalized:
                from app.services.cv_generator_b2b.requirement_map import (
                    ensure_requirement_map,
                )

                requirements = _upload_requirements(second_payload)
                if requirements:
                    await ensure_requirement_map(
                        db, second_id, user_id=user_id, requirements=requirements
                    )


# ── Endpoints ──────────────────────────────────────────────────────────────


class ClassifyTechRequest(BaseModel):
    names: list[str] = Field(default_factory=list, max_length=200)


class ClassifyTechResponse(BaseModel):
    # name -> True iff the chip would produce a bold in the generated CV
    technologies: dict[str, bool]


@router.post("/classify-technologies", response_model=ClassifyTechResponse)
async def classify_technologies(
    payload: ClassifyTechRequest,
    current_user: CandidateSearchAccess,
) -> ClassifyTechResponse:
    """Tell the UI which criteria chips will be bolded as technologies in the
    generated CV — using the SAME classifier as the renderer (taxonomy + the
    heuristic fallback), so the preview never diverges from the actual output."""
    del current_user  # auth only
    from app.services.cv_generator_b2b.docx_renderer import compile_keyword_patterns

    result = {
        name: bool(compile_keyword_patterns([name]))
        for name in payload.names
        if isinstance(name, str) and name.strip()
    }
    return ClassifyTechResponse(technologies=result)


@router.get("/candidates", response_model=list[CandidateOption])
async def search_candidates(
    current_user: CandidateSearchAccess,
    db: AsyncSession = Depends(get_db),
    q: str = Query(
        "",
        max_length=120,
        description="Free-text search across name, lastname and email.",
    ),
    limit: int = Query(20, ge=1, le=50),
) -> list[CandidateOption]:
    """Lightweight typeahead. Empty ``q`` returns the most recently updated rows.

    Matches "Imię Nazwisko" / "Nazwisko Imię" as a whole (concatenated
    columns) and ranks exact / prefix lastname+name matches above substring
    hits — "Bogdan" must surface Michał *Bogdan* before *Bogdan*owicz.
    """

    del current_user  # auth only

    stmt = select(Candidate)
    needle = (q or "").strip().lower()
    if needle:
        like = f"%{needle}%"
        name_l = func.lower(func.coalesce(Candidate.name, ""))
        lastname_l = func.lower(func.coalesce(Candidate.lastname, ""))
        full = name_l + " " + lastname_l
        full_rev = lastname_l + " " + name_l
        stmt = stmt.where(
            or_(
                name_l.like(like),
                lastname_l.like(like),
                full.like(like),
                full_rev.like(like),
                func.lower(func.coalesce(Candidate.email, "")).like(like),
            )
        )
        rank = case(
            (
                or_(
                    lastname_l == needle,
                    name_l == needle,
                    full == needle,
                    full_rev == needle,
                ),
                0,
            ),
            (
                or_(
                    lastname_l.like(f"{needle}%"),
                    name_l.like(f"{needle}%"),
                    full.like(f"{needle}%"),
                    full_rev.like(f"{needle}%"),
                ),
                1,
            ),
            else_=2,
        )
        stmt = stmt.order_by(rank, Candidate.updated_at.desc()).limit(limit)
    else:
        stmt = stmt.order_by(Candidate.updated_at.desc()).limit(limit)

    rows = (await db.scalars(stmt)).all()

    return [
        CandidateOption(
            id=c.id,
            name=c.name,
            lastname=c.lastname,
            full_name=f"{c.name} {c.lastname}".strip(),
            position=getattr(c, "current_position", None),
            email=getattr(c, "email", None),
        )
        for c in rows
    ]


@router.get(
    "/candidates/{candidate_id}/recruitments",
    response_model=list[RecruitmentOption],
)
async def list_candidate_recruitments(
    candidate_id: int,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
    content_mode: ContentMode = DEFAULT_CONTENT_MODE,
) -> list[RecruitmentOption]:
    """Return all recruitment processes the candidate participates in, with
    readiness flags (champion present, screening notes present)."""

    try:
        readiness = await list_recruitments_with_readiness(
            db,
            candidate_id,
            job_scope=job_read_scope_clause(current_user, CandidateStage.job_id),
            content_mode=content_mode,
        )
    except StandaloneGenerationError as err:
        raise HTTPException(
            status_code=_error_status(err.code), detail=err.message
        ) from err

    return [
        RecruitmentOption(
            stage_id=r.stage_id,
            job_id=r.job_id,
            job_title=r.job_title,
            stage=r.stage,
            has_champion=r.has_champion,
            has_notes=r.has_notes,
            has_cv=r.has_cv,
            notes_chars=r.notes_chars,
            ready=r.ready,
            content_mode=r.content_mode,
            required_champion=r.required_champion,
            required_notes_min_chars=r.required_notes_min_chars,
            missing_inputs=r.missing_inputs,
            client_id=r.client_id,
            client_name=r.client_name,
        )
        for r in readiness
    ]


# ── Zrzut zgody kandydata (wymóg PKO BP) ───────────────────────────────────
#
# Bank wymaga, żeby pod treścią CV był widoczny zrzut maila, w którym kandydat
# zgadza się na przetwarzanie danych. Do 09.2026 generator tylko OSTRZEGAŁ
# rekrutera, żeby wkleił go ręcznie przed wysyłką (patrz `client_rules`), bo nie
# miał skąd wziąć obrazu.
#
# Obraz idzie do magazynu obiektów, a w `render_payload` ląduje sam klucz: DOCX
# jest re-renderowany przy KAŻDYM pobraniu, więc zrzut musi być trwały, a nie
# doklejony raz. Setki kilobajtów w JSONB puchłyby przy każdym odczycie wiersza.

CONSENT_SCREENSHOT_MAX_BYTES = 8 * 1024 * 1024
CONSENT_SCREENSHOT_TYPES = ("image/png", "image/jpeg", "image/webp")


def _sniff_image_type(content: bytes) -> Optional[str]:
    """Rozpoznaj format po SYGNATURZE BAJTÓW, nie po nagłówku żądania.

    `UploadFile.content_type` przychodzi od klienta i można w nim napisać
    cokolwiek — `image/png` na SVG z JavaScriptem albo na HTML-u. Renderowanie
    DOCX jest wprawdzie fail-soft (nieczytelny plik daje CV bez zrzutu), ale bez
    tej kontroli dowolny plik ląduje najpierw w magazynie obiektów, a magazyn
    trzyma dokumenty kandydatów.

    Zwraca `None`, gdy sygnatura nie pasuje do żadnego dozwolonego formatu.
    """
    if content[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if content[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return None


class ConsentScreenshotResponse(BaseModel):
    storage_key: str
    filename: str
    consent_token: str


@router.post("/consent-screenshot", response_model=ConsentScreenshotResponse)
@limiter.limit("20/minute")
async def upload_consent_screenshot(
    request: Request,
    current_user: CandidateWriteAccess,
    file: Annotated[UploadFile, File(description="Zrzut ekranu ze zgodą kandydata")],
    candidate_id: Optional[int] = Form(None, ge=1),
    stage_id: Optional[int] = Form(None, ge=1),
    client_id: Optional[int] = Form(None, ge=1),
    cv_sha256: Optional[str] = Form(None, pattern=r"^[a-f0-9]{64}$"),
    db: AsyncSession = Depends(get_db),
) -> ConsentScreenshotResponse:
    """Wgraj zrzut zgody i podpisz przypisanie do źródła i klienta.

    Osobny endpoint, a nie pole w `/generate`, bo ta ścieżka przyjmuje JSON —
    obraz w base64 puchnie o jedną trzecią i ląduje w logach requestów. Przy
    okazji ten sam format przypisania obsługuje obie ścieżki generacji (`/generate`
    i `/generate-upload`) jednym mechanizmem.
    """
    if cv_sha256:
        if candidate_id is not None or stage_id is not None:
            raise HTTPException(
                status_code=422, detail="Wybierz jeden rodzaj źródła CV."
            )
        if client_id is not None and await db.get(Client, client_id) is None:
            raise HTTPException(status_code=404, detail="Klient nie został znaleziony.")
        context = consent_binding.subject(cv_sha256=cv_sha256, client_id=client_id)
    else:
        if candidate_id is None or stage_id is None:
            raise HTTPException(
                status_code=422,
                detail="Najpierw wybierz kandydata i rekrutację albo wgraj plik CV.",
            )
        stage = await db.get(CandidateStage, stage_id)
        if stage is None or stage.candidate_id != candidate_id:
            raise HTTPException(
                status_code=404, detail="Rekrutacja nie należy do tego kandydata."
            )
        await ensure_job_membership(db, current_user, stage.job_id)
        job = await db.get(Job, stage.job_id)
        if job is None or (client_id is not None and job.client_id != client_id):
            raise HTTPException(
                status_code=422,
                detail="Kontekst klienta uległ zmianie. Odśwież formularz.",
            )
        context = consent_binding.subject(
            candidate_id=candidate_id, stage_id=stage_id, client_id=job.client_id
        )
    content = await file.read(CONSENT_SCREENSHOT_MAX_BYTES + 1)
    if not content:
        raise HTTPException(status_code=422, detail="Plik jest pusty.")
    if len(content) > CONSENT_SCREENSHOT_MAX_BYTES:
        raise HTTPException(
            status_code=422,
            detail=(
                "Zrzut jest za duży (limit "
                f"{CONSENT_SCREENSHOT_MAX_BYTES // (1024 * 1024)} MB)."
            ),
        )
    sniffed = _sniff_image_type(content)
    if sniffed is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "To nie wygląda na obraz PNG, JPEG ani WEBP — sprawdź, czy "
                "wgrywasz zrzut ekranu."
            ),
        )
    if not object_storage.is_available():
        raise HTTPException(
            status_code=503,
            detail=(
                "Magazyn plików jest niedostępny — nie mogę zapisać zrzutu zgody. "
                "Spróbuj ponownie za chwilę."
            ),
        )

    filename = file.filename or "zgoda.png"
    key = await run_in_threadpool(
        # Typ ROZPOZNANY, nie deklarowany przez klienta — inaczej magazyn
        # serwowałby plik z `Content-Type`, którego nikt nie zweryfikował.
        object_storage.upload_cv,
        content,
        filename,
        sniffed,
    )
    return ConsentScreenshotResponse(
        storage_key=key,
        filename=filename,
        consent_token=consent_binding.issue(key, current_user.id, context),
    )


def _verified_consent(
    rule, token: str, legacy_key: str, user_id: int, context: dict
) -> dict | None:
    if not token and not legacy_key:
        _require_consent_screenshot(rule, "")
        return None
    try:
        receipt = consent_binding.verify(token, user_id, context)
        if legacy_key and receipt["storage_key"] != legacy_key:
            raise ValueError
        return receipt
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=(
                "Zrzut zgody nie jest przypisany do bieżącego CV, osoby lub klienta albo wygasł. "
                "Odśwież formularz i wgraj zgodę ponownie."
            ),
        ) from None


def _require_consent_screenshot(rule, storage_key: str) -> None:
    """Odmów generacji, gdy klient wymaga zrzutu, a rekruter go nie wgrał.

    Twarda odmowa, nie ostrzeżenie: dla PKO BP CV bez zrzutu jest dokumentem
    niekompletnym, którego i tak nie da się wysłać. Ostrzeżenie w tej sytuacji
    znaczyłoby „wygenerowaliśmy Ci plik do wyrzucenia" — a generacja to
    najdroższe wywołanie modelu w produkcie.
    """
    if rule is None or not getattr(rule, "requires_rodo_consent_block", False):
        return
    if storage_key.strip():
        return
    raise HTTPException(
        status_code=422,
        detail=(
            "Ten klient wymaga zrzutu ekranu ze zgodą kandydata na przetwarzanie "
            "danych — wgraj go przed wygenerowaniem CV."
        ),
    )


@router.post(
    "/generate",
    response_model=GenerateEnqueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
@limiter.limit("10/minute")
async def generate(
    request: Request,
    payload: GenerateRequest,
    current_user: CandidateWriteAccess,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> GenerateEnqueuedResponse:
    """Enqueue New-mode CV generation and return immediately (202 Accepted).

    Generation (60-90 s: Claude + DOCX render) runs in the background, so the
    recruiter can close/leave the tab without losing the result — it lands on
    the „Wygenerowane CV" list (``GET /generated``) with ``status`` „ready" or
    „failed". A „processing" placeholder row is created here so the CV shows up
    on the list right away; the deep readiness contract (CV file / champion /
    notes present) is validated inside the background job and any failure is
    written onto that row.
    """
    candidate = await db.get(Candidate, payload.candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Kandydat nie został znaleziony.")

    # Etap musi należeć do TEGO kandydata — inaczej wymagane wejścia zgłaszałyby
    # „brak notatek" dla cudzego etapu zamiast 404.
    stage = await db.get(CandidateStage, payload.stage_id)
    if stage is None or stage.candidate_id != payload.candidate_id:
        raise HTTPException(
            status_code=404, detail="Rekrutacja nie należy do tego kandydata."
        )

    await ensure_job_membership(db, current_user, stage.job_id)

    # Klienta wyprowadza SERWER z rekrutacji — front go nie wybiera. Jawna
    # wartość w żądaniu jest tylko asercją; rozjazd oznacza, że rekruter widzi
    # inne reguły (nazwa pliku, język), niż zostałyby zastosowane.
    client_id = (
        await db.execute(
            select(Job.client_id)
            .join(CandidateStage, CandidateStage.job_id == Job.id)
            .where(CandidateStage.id == payload.stage_id)
        )
    ).scalar_one_or_none()
    if payload.client_id is not None and payload.client_id != client_id:
        raise HTTPException(
            status_code=422,
            detail=(
                "Klient wskazany w żądaniu nie zgadza się z klientem tej "
                "rekrutacji. Odśwież stronę i spróbuj ponownie."
            ),
        )

    rule = await resolve_client_rule(db, client_id)
    rule_snapshot = snapshot_rule(rule)
    _enforce_client_language(rule_snapshot, payload.language)

    # Blokada trybu (0267): zablokowany tryb nadpisuje żądanie — kafelki w UI
    # są wyłączone, ale kontrakt trzyma serwer. Sufit z karty klienta nakłada
    # `generate_cv_for_candidate` już na tę wartość.
    effective_mode, _forced = resolve_content_mode(rule_snapshot, payload.content_mode)
    client = await db.get(Client, client_id) if client_id else None
    effective_mode, _capped = apply_content_mode_cap(
        effective_mode, getattr(client, "cv_content_mode_cap", None)
    )

    consent = _verified_consent(
        rule,
        payload.consent_screenshot_token,
        payload.consent_screenshot_key,
        current_user.id,
        consent_binding.subject(
            candidate_id=candidate.id, stage_id=stage.id, client_id=client_id
        ),
    )

    # Wymagane wejścia (0267) — 422 z listą braków PRZED naliczeniem kwoty.
    if effective_mode == "tailored" or (
        rule_snapshot is not None
        and (
            rule_snapshot.require_screening_notes_min_chars
            or rule_snapshot.require_project_ref
            or rule_snapshot.require_champion
        )
    ):
        job = await db.get(Job, stage.job_id)
        notes_chars = await screening_notes_char_count(
            db, candidate_id=payload.candidate_id, stage_id=payload.stage_id
        )
        if effective_mode == "tailored" and not champion_present(job):
            _reject_missing_inputs(
                [
                    "Tryb dopasowany wymaga Profilu Championa. Uzupełnij go lub wybierz Przepisanie/Redakcję, jeśli reguła klienta na to pozwala."
                ]
            )
        _reject_missing_inputs(
            required_input_problems(
                rule_snapshot,
                mode="new",
                screening_chars=notes_chars or 0,
                has_project_ref=bool(payload.project_ref.strip()),
                has_position=True,
                has_champion=champion_present(job),
            )
        )

    # Kwota naliczana PO walidacjach — odrzucone żądanie nie może kosztować
    # rekrutera limitu, którego nie zużyło.
    quota_state = await _charge_cv_generation_quota(db, current_user.id)

    candidate_name = f"{candidate.name} {candidate.lastname}".strip() or "Kandydat"
    generated_id = await _create_pending_row(
        db,
        mode="new",
        candidate_id=payload.candidate_id,
        candidate_name=candidate_name,
        position=getattr(candidate, "current_position", None),
        language=payload.language,
        blind_cv=payload.blind_cv,
        user_id=current_user.id,
        content_mode=effective_mode,
        client_id=client_id,
        job_id=stage.job_id,
    )
    # Commit before scheduling/returning so the row is visible to both the poll
    # and the background job (which opens its own session).
    await db.commit()

    background_tasks.add_task(
        _run_declared,
        _run_generate_new_job,
        generated_id,
        quota_state=quota_state,
        quota_user_id=current_user.id,
        candidate_id=payload.candidate_id,
        stage_id=payload.stage_id,
        language=payload.language,
        blind_cv=payload.blind_cv,
        user_id=current_user.id,
        content_mode=effective_mode,
        client_id=client_id,
        project_ref=payload.project_ref or "",
        consent_screenshot=consent,
    )
    return GenerateEnqueuedResponse(
        id=generated_id, status="processing", candidate_name=candidate_name
    )


@router.post(
    "/generate-upload",
    response_model=GenerateEnqueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
@limiter.limit("10/minute")
async def generate_from_upload(
    request: Request,
    current_user: CandidateWriteAccess,
    background_tasks: BackgroundTasks,
    # No `from __future__ import annotations` in this module (see module docstring),
    # so this multipart marker resolves correctly even under the slowapi
    # `@limiter.limit` wrapper. Annotated form is the FastAPI-recommended style.
    cv_file: Annotated[UploadFile, File(description="Plik CV (PDF / DOCX)")],
    # Klient, pod którego idzie to CV. OPCJONALNY — generator służy też do CV
    # robionych poza konkretnym zleceniem, a wymuszony wybór zamieniłby brak
    # wiedzy w zgadywanie. Bez klienta wszystko działa jak dotąd.
    client_id: Optional[int] = Form(None),
    candidate_id: Annotated[Optional[int], Form(ge=1)] = None,
    stage_id: Annotated[Optional[int], Form(ge=1)] = None,
    # Upload nie ma oferty, więc stanowisko i numer projektu — jedyne źródła
    # tokenów {STANOWISKO} i {PROJEKT} we wzorze nazwy pliku — podaje rekruter.
    position: str = Form("", max_length=300),
    project_ref: str = Form("", max_length=120),
    language: Literal["pl", "en"] = Form("pl"),
    blind_cv: bool = Form(False),
    content_mode: Literal["basic", "polished", "tailored"] = Form(DEFAULT_CONTENT_MODE),
    screening_notes: str = Form(""),
    # Ręczne wymagania na kafelki interaktywnego CV (przecinki/nowe linie).
    # Upload nie ma joba, więc bez nich (i bez pliku championa) publiczny link
    # pokaże sam widok classic.
    must_requirements: str = Form("", max_length=2000),
    nice_requirements: str = Form("", max_length=2000),
    champion_file: Annotated[
        Optional[UploadFile],
        File(description="Opcjonalny plik DOCX z Profilem Championa"),
    ] = None,
    # Klucz z `POST /consent-screenshot`, nie kolejny `UploadFile`: obie ścieżki
    # generacji mają wtedy JEDEN mechanizm zamiast dwóch rozjeżdżających się.
    consent_screenshot_key: str = Form("", max_length=500),
    consent_screenshot_token: str = Form("", max_length=4096),
    db: AsyncSession = Depends(get_db),
) -> GenerateEnqueuedResponse:
    """1:1 odpowiednik external ``POST /api/v1/generate`` (multipart wariant),
    ale enqueue + 202 (generacja w tle).

    Old-mode: user wgrywa CV ręcznie, opcjonalnie DOCX championa i notatki ze
    screeningu. Bajty plików czytamy tu (``UploadFile`` nie przeżyje requestu)
    i przekazujemy do zadania w tle, dzięki czemu rekruter może zamknąć kartę —
    wynik ląduje na liście „Wygenerowane CV" z jawnie wybranym przypisaniem
    do osoby i rekrutacji. Dane źródłowe nadal pochodzą z wgranego pliku.
    """
    # A user explicitly binds the uploaded file; never match by parsed name.
    # Derive the client from a verified candidate-stage pair before rule/quota reads.
    job_id = None
    if stage_id is not None:
        if candidate_id is None:
            raise HTTPException(
                status_code=422, detail="Wybierz kandydata dla rekrutacji."
            )
        stage = await db.get(CandidateStage, stage_id)
        if stage is None or stage.candidate_id != candidate_id:
            raise HTTPException(
                status_code=404, detail="Rekrutacja nie należy do tego kandydata."
            )
        await ensure_job_membership(db, current_user, stage.job_id)
        job = await db.get(Job, stage.job_id)
        if job is None:
            raise HTTPException(
                status_code=404, detail="Rekrutacja nie została znaleziona."
            )
        if client_id is not None and client_id != job.client_id:
            raise HTTPException(
                status_code=422,
                detail="Klient nie zgadza się z rekrutacją. Odśwież formularz.",
            )
        job_id, client_id = job.id, job.client_id
    if candidate_id is not None and await db.get(Candidate, candidate_id) is None:
        raise HTTPException(status_code=404, detail="Kandydat nie został znaleziony.")

    # Sufit trybu treści obowiązuje teraz TAKŻE w uploadzie — o ile rekruter
    # wskazał klienta. Do tej pory ta ścieżka (99,9% ruchu) omijała go zawsze,
    # więc obietnica złożona klientowi działała dla 0,1% generacji.
    effective_mode: ContentMode = content_mode
    rule = None
    if client_id is not None:
        client = await db.get(Client, client_id)
        if client is None:
            raise HTTPException(status_code=404, detail="Klient nie został znaleziony.")
        effective_mode, _capped = apply_content_mode_cap(
            content_mode, client.cv_content_mode_cap
        )
        rule = await resolve_client_rule(db, client_id)
        rule_snapshot = snapshot_rule(rule)
        _enforce_client_language(rule_snapshot, language)
        # Blokada trybu (0267) PRZED sufitem — zablokowany tryb nadpisuje
        # żądanie, sufit nadal wygrywa z blokadą.
        locked_mode, _forced = resolve_content_mode(rule_snapshot, content_mode)
        effective_mode, _capped = apply_content_mode_cap(
            locked_mode, client.cv_content_mode_cap
        )
        has_champion = bool(
            champion_file is not None and champion_file.filename
        ) or bool(
            (must_requirements or "").strip() or (nice_requirements or "").strip()
        )
        _reject_missing_inputs(
            required_input_problems(
                rule_snapshot,
                mode="upload",
                screening_chars=len((screening_notes or "").strip()),
                has_project_ref=bool((project_ref or "").strip()),
                has_position=bool((position or "").strip()),
                has_champion=has_champion,
            )
        )

    # Kwota naliczana PO walidacjach — odrzucone żądanie nie może kosztować
    # rekrutera limitu, którego nie zużyło.
    cv_bytes = await cv_file.read(MAX_UPLOAD_BYTES + 1)
    consent = _verified_consent(
        rule,
        consent_screenshot_token,
        consent_screenshot_key,
        current_user.id,
        consent_binding.subject(
            cv_sha256=hashlib.sha256(cv_bytes).hexdigest(), client_id=client_id
        ),
    )
    champion_bytes: bytes | None = None
    champion_filename: str | None = None
    if champion_file is not None and champion_file.filename:
        champion_bytes = await champion_file.read(MAX_UPLOAD_BYTES + 1)
        champion_filename = champion_file.filename

    gen_payload = UploadGenerationInput(
        cv_bytes=cv_bytes,
        cv_filename=cv_file.filename or "cv.pdf",
        language=language,
        blind_cv=blind_cv,
        screening_notes=screening_notes or "",
        champion_bytes=champion_bytes,
        champion_filename=champion_filename,
        content_mode=effective_mode,
        must_requirements=must_requirements or "",
        nice_requirements=nice_requirements or "",
        client_rule=snapshot_rule(rule),
        position=position or "",
        project_ref=project_ref or "",
    )

    try:
        await run_in_threadpool(validate_upload_inputs, gen_payload)
    except StandaloneGenerationError as error:
        raise HTTPException(422, error.message) from error
    quota_state = await _charge_cv_generation_quota(db, current_user.id)

    # Provisional label until Claude parses the real name out of the CV.
    provisional = Path(cv_file.filename or "").stem or "Nowe CV"
    generated_id = await _create_pending_row(
        db,
        mode="upload",
        candidate_id=candidate_id,
        job_id=job_id,
        candidate_name=provisional,
        position=position or None,
        language=language,
        blind_cv=blind_cv,
        user_id=current_user.id,
        content_mode=effective_mode,
        client_id=client_id,
    )
    await db.commit()

    background_tasks.add_task(
        _run_declared,
        _run_generate_upload_job,
        generated_id,
        quota_state=quota_state,
        quota_user_id=current_user.id,
        payload=gen_payload,
        user_id=current_user.id,
        consent_screenshot=consent,
    )
    return GenerateEnqueuedResponse(
        id=generated_id, status="processing", candidate_name=provisional
    )


# ── Saved-CV list („Wygenerowane CV") ──────────────────────────────────────


async def _load_generated_document(
    db: AsyncSession, generated_id: int, user: User, *, write: bool = False
) -> CvGeneratedDocument:
    row = await db.get(CvGeneratedDocument, generated_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Wpis nie został znaleziony")
    if row.job_id is not None:
        guard = ensure_job_membership if write else ensure_job_read_access
        await guard(db, user, row.job_id)
    return row


@router.get("/generated", response_model=list[GeneratedCvItem])
async def list_generated_cvs(
    current_user: CandidateDocumentAccess,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(60, ge=1, le=200),
    candidate_id: Annotated[Optional[int], Query(ge=1)] = None,
    job_id: Annotated[Optional[int], Query(ge=1)] = None,
    before_id: Annotated[Optional[int], Query(ge=1)] = None,
):
    """Recently generated CVs for the panel list (newest first).

    ``status`` drives the row's look (spinner while „processing", the CV once
    „ready", the reason on „failed"); the UI polls this endpoint while any row
    is still „processing". ``can_download`` is true only for „ready" rows with a
    saved ``render_payload`` (rows from before this feature have none);
    ``can_delete`` whether the current user may remove the row (author or admin).
    """
    filters = [job_read_scope_clause(current_user, CvGeneratedDocument.job_id)]
    if candidate_id is not None:
        filters.append(CvGeneratedDocument.candidate_id == candidate_id)
    if job_id is not None:
        await ensure_job_read_access(db, current_user, job_id)
        filters.append(CvGeneratedDocument.job_id == job_id)
    if before_id is not None:
        filters.append(CvGeneratedDocument.id < before_id)
    is_admin = current_user.has_role(UserRole.admin)
    # `display_name` przed `name`: to drugie nadpisuje sync Traffita, więc
    # etykieta w panelu rozjeżdżałaby się z tą z pickera klienta.
    rows = (
        await db.execute(
            select(
                CvGeneratedDocument,
                User.name,
                func.coalesce(
                    func.nullif(func.trim(Client.display_name), ""), Client.name
                ),
            )
            .outerjoin(User, User.id == CvGeneratedDocument.created_by)
            .outerjoin(Client, Client.id == CvGeneratedDocument.client_id)
            .where(*filters)
            .order_by(CvGeneratedDocument.id.desc())
            .limit(limit)
        )
    ).all()
    return [
        GeneratedCvItem(
            id=r.id,
            candidate_id=r.candidate_id,
            job_id=r.job_id,
            client_id=r.client_id,
            client_name=client_name,
            candidate_name=r.candidate_name,
            position=r.position,
            language=r.language,
            blind=r.blind,
            mode=r.mode,
            content_mode=r.content_mode,
            filename=r.filename,
            status=r.status,
            error_message=r.error_message,
            warnings=list(r.warnings or []),
            created_at=r.created_at.isoformat() if r.created_at else None,
            created_by_name=creator_name,
            can_download=r.status == "ready" and r.render_payload is not None,
            can_delete=is_admin or r.created_by == current_user.id,
        )
        for r, creator_name, client_name in rows
    ]


@router.get("/generated/{generated_id}/docx")
async def download_generated_cv(
    generated_id: int,
    current_user: CandidateDocumentAccess,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Re-render a previously generated CV from its saved payload and return it.

    Deterministic render — no Claude call. Rows generated before this feature
    have no payload → 422 asking to generate again. Used for both inline preview
    and explicit download in the panel.
    """
    row = await _load_generated_document(db, generated_id, current_user, write=False)
    if not row.render_payload:
        raise HTTPException(
            status_code=422,
            detail=(
                "To CV wygenerowano zanim dodaliśmy zapis danych — nie można go "
                "odtworzyć. Wygeneruj je ponownie."
            ),
        )
    try:
        docx_bytes = await run_in_threadpool(
            rerender_docx_from_payload, row.render_payload
        )
    except Exception as err:  # noqa: BLE001 — python-docx raises various types
        logger.exception("[cv_b2b] Re-render of saved CV %s failed: %s", row.id, err)
        raise HTTPException(
            status_code=500, detail=f"Nie udało się odtworzyć DOCX: {err}"
        ) from err
    return _build_docx_response(
        docx_bytes=docx_bytes,
        filename=row.filename,
        candidate_name=row.candidate_name,
        warnings=[],
        processing_time_ms=0,
        generated_id=row.id,
    )


@router.get("/generated/{generated_id}/html")
async def download_generated_cv_html(
    generated_id: int,
    current_user: CandidateDocumentAccess,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Interaktywne CV jako JEDEN samodzielny plik HTML — do wysyłki mailem.

    Ten sam client-safe payload co publiczny link (bez warnings, blind
    zamaskowany) + zapisana mapa wymagań, spakowane w plik z inline
    stylami/JS: kafelki, przełącznik Klasyczne↔Interaktywne, druk = czysty
    dokument. Bez mapy plik degraduje do samego widoku klasycznego. Chat
    celowo nieobecny — wymaga serwera, żyje na linku /cv/i/{{token}}.
    """
    row = await _load_generated_document(db, generated_id, current_user, write=False)
    if row.status != "ready" or not row.render_payload:
        raise HTTPException(
            status_code=422,
            detail="CV nie jest gotowe (brak zapisanych danych) — wygeneruj ponownie.",
        )
    from app.services.cv_generator_b2b.html_export import render_interactive_html
    from app.services.cv_generator_b2b.public_view import build_public_payload

    html_str = render_interactive_html(
        build_public_payload(row.render_payload),
        ((row.requirement_map or {}).get("items") or [])
        if await _interactive_available(db, row)
        else [],
    )
    filename = (Path(row.filename).stem or "CV") + ".html"
    ascii_name = ascii_filename_fallback(filename)
    disposition = f'attachment; filename="{ascii_name}"'
    if filename != ascii_name:
        disposition += f"; filename*=UTF-8''{quote(filename, safe='')}"
    return Response(
        content=html_str.encode("utf-8"),
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Disposition": disposition,
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


@router.delete("/generated/{generated_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_generated_cv(
    generated_id: int,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Remove a row from the „Wygenerowane CV" list (author or admin only).

    Only the list entry is deleted; nothing irreplaceable is lost — the CV can be
    regenerated from the candidate's recruitment at any time.
    """
    row = await _load_generated_document(db, generated_id, current_user, write=True)
    if not current_user.has_role(UserRole.admin) and row.created_by != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="Możesz usunąć tylko CV, które samodzielnie wygenerowałeś.",
        )
    await db.delete(row)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Publiczny link do wygenerowanego CV (interaktywne CV) ──────────────────
#
# Mirror wzorca share-tokenów brandowanego CV (candidate_stage_cv.py, token v2)
# — ale od pierwszego dnia WYŁĄCZNIE hash-at-rest: sekret pokazany raz, w DB
# tylko SHA-256, PK = nie-sekretny revoke-key `v2$<hex>`. Strona kliencka:
# `/cv/i/{token}` (public), dane: GET /api/public/cv-i/{token}.

_SHARE_PATH_PREFIX = "/cv/i/"


class CvGeneratedShareCreateResponse(BaseModel):
    token: str
    expires_at: datetime
    share_url_suffix: str
    generated_id: int
    revoke_key: str
    max_views: Optional[int] = None
    # Czy link pokaże wersję interaktywną (kafelki; chat zależy dodatkowo od
    # toggle'a AI). False = klient zobaczy sam widok classic.
    interactive_available: bool


class CvGeneratedShareListItem(BaseModel):
    revoke_key: str
    token_preview: str
    created_at: Optional[str] = None
    created_by_name: Optional[str] = None
    expires_at: Optional[str] = None
    revoked: bool
    revoked_at: Optional[str] = None
    revoke_reason: Optional[str] = None
    view_count: int = 0
    max_views: Optional[int] = None
    last_viewed_at: Optional[str] = None


async def _interactive_available(db: AsyncSession, row: CvGeneratedDocument) -> bool:
    """Tiles require evidence and the same client policy as the public view."""
    from app.services.cv_generator_b2b.document_policy import (
        interactive_client_enabled,
    )

    return bool((row.requirement_map or {}).get("items")) and (
        await interactive_client_enabled(db, row)
    )


@router.post(
    "/generated/{generated_id}/share-token",
    response_model=CvGeneratedShareCreateResponse,
    status_code=201,
)
async def create_generated_cv_share_token(
    generated_id: int,
    current_user: CandidateWriteAccess,
    expires_in_days: int = Query(14, ge=1, le=90),
    max_views: Optional[int] = Query(None, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
) -> CvGeneratedShareCreateResponse:
    """Wygeneruj publiczny link do wygenerowanego CV dla hiring managera.

    Sekret NIE jest zapisywany (w DB tylko SHA-256); raw token zwracamy jeden
    raz. Przed wystawieniem — ostatnia linia obrony przed wysyłką CV osoby
    z wetem HM (ten sam gate co przy brandowanym CV).
    """
    row = await _load_generated_document(db, generated_id, current_user, write=True)
    if row.status != "ready" or not row.render_payload:
        raise HTTPException(
            status_code=409,
            detail="CV nie jest gotowe do udostępnienia (brak zapisanych danych).",
        )

    # Veto hiring managera — jak w share brandowanego CV. Wygenerowane CV zna
    # (candidate_id, job_id); etap wyprowadzamy z tej pary.
    if row.candidate_id is not None and row.job_id is not None:
        from app.services.hiring_manager_verdicts import veto_for_candidate_stage

        stage_id = await db.scalar(
            select(CandidateStage.id).where(
                CandidateStage.candidate_id == row.candidate_id,
                CandidateStage.job_id == row.job_id,
            )
        )
        if stage_id is not None:
            verdict = await veto_for_candidate_stage(db, candidate_stage_id=stage_id)
            if verdict is not None:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"{verdict.as_polish_detail()} "
                        "Nie udostępniaj ponownie tego CV."
                    ),
                )

    raw_token = secrets.token_urlsafe(36)
    revoke_key = f"v2${secrets.token_hex(16)}"
    token_digest = hashlib.sha256(raw_token.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)
    db.add(
        CvGeneratedShareToken(
            token=revoke_key,
            token_sha256=token_digest,
            generated_document_id=row.id,
            created_by=current_user.id,
            expires_at=expires_at,
            max_views=max_views,
        )
    )
    interactive = await _interactive_available(db, row)
    db.add(
        Activity(
            entity_type="cv_generated_document",
            entity_id=row.id,
            action="cv_generated_share_created",
            user_id=current_user.id,
            details={
                "expires_at": expires_at.isoformat(),
                "revoke_key": revoke_key,
                "max_views": max_views,
                "interactive_available": interactive,
            },
        )
    )
    await db.commit()

    return CvGeneratedShareCreateResponse(
        token=raw_token,
        expires_at=expires_at,
        share_url_suffix=f"{_SHARE_PATH_PREFIX}{raw_token}",
        generated_id=row.id,
        revoke_key=revoke_key,
        max_views=max_views,
        interactive_available=interactive,
    )


@router.get(
    "/generated/{generated_id}/share-tokens",
    response_model=list[CvGeneratedShareListItem],
)
async def list_generated_cv_share_tokens(
    generated_id: int,
    current_user: CandidateDocumentAccess,
    db: AsyncSession = Depends(get_db),
) -> list[CvGeneratedShareListItem]:
    """Lista linków (aktywnych i odwołanych) dla tego CV — bez sekretów."""
    await _load_generated_document(db, generated_id, current_user)
    rows = (
        (
            await db.execute(
                select(CvGeneratedShareToken)
                .options(selectinload(CvGeneratedShareToken.creator))
                .where(CvGeneratedShareToken.generated_document_id == generated_id)
                .order_by(CvGeneratedShareToken.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [
        CvGeneratedShareListItem(
            revoke_key=r.token,
            token_preview=f"v2 · {r.token_sha256[:6]}…",
            created_at=r.created_at.isoformat() if r.created_at else None,
            created_by_name=(r.creator.name if r.creator else None),
            expires_at=r.expires_at.isoformat() if r.expires_at else None,
            revoked=r.revoked,
            revoked_at=r.revoked_at.isoformat() if r.revoked_at else None,
            revoke_reason=r.revoke_reason,
            view_count=r.view_count or 0,
            max_views=r.max_views,
            last_viewed_at=(r.last_viewed_at.isoformat() if r.last_viewed_at else None),
        )
        for r in rows
    ]


@router.delete("/generated/share-token/{token}")
async def revoke_generated_cv_share_token(
    token: str,
    current_user: CandidateWriteAccess,
    reason: Optional[str] = Query(None, max_length=255),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Odwołaj link. Idempotentne. Przyjmuje revoke-key (`v2$…`) albo raw token
    (lookup po hashu — okładka, gdy caller ma tylko URL). Rewokacja zmniejsza
    ekspozycję, więc celowo nie wymaga bycia autorem linku."""
    digest = hashlib.sha256(token.encode()).hexdigest()
    row = await db.scalar(
        select(CvGeneratedShareToken).where(
            (CvGeneratedShareToken.token == token)
            | (CvGeneratedShareToken.token_sha256 == digest)
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Token nie znaleziony")
    await _load_generated_document(
        db, row.generated_document_id, current_user, write=True
    )
    if row.revoked:
        return {"ok": True, "already_revoked": True}
    row.revoked = True
    row.revoked_at = datetime.now(timezone.utc)
    row.revoked_by = current_user.id
    row.revoke_reason = reason
    db.add(
        Activity(
            entity_type="cv_generated_document",
            entity_id=row.generated_document_id,
            action="cv_generated_share_revoked",
            user_id=current_user.id,
            details={"revoke_key": row.token, "reason": reason},
        )
    )
    await db.commit()
    return {"ok": True, "already_revoked": False}
