"""CV dla klienta w API v1: generowanie, stan i pobranie gotowego CV.

Para = osoba w rekrutacji. CV powstaje dla bieżącej karty pary — tak samo
jak „Generuj CV” w karcie „CV do klienta”:

* ``POST /recruitments/{job_id}/candidates/{candidate_id}/cv`` — scope
  ``cv:generate``. Ta sama ścieżka co ekran
  (``cv_generator_b2b.enqueue_candidate_generation``): reguła klienta, polityka
  centralna, wymagane wejścia, odmowy 422 PRZED naliczeniem AI, zgoda RODO.
  Ustawienia, które karta zaznacza sama (plik, język, tryb, stanowisko, numer
  projektu, źródła dla AI), liczy ``services/integration_cv``. Wynik 202
  ``processing``; generacja biegnie w tle (trwałe zadanie, ``execute_job``),
  gotowe CV podpina się jako SZKIC, gdy para nie ma jeszcze CV — jak po
  kliknięciu. Zatwierdza i wysyła człowiek.
* ``GET …/cv`` — scope ``cv:generate``. Sam stan: CV pary (szkic /
  zatwierdzone, wersja, daty, zgoda), zatwierdzone wersje, ostatnie generacje
  (stan, kod błędu) i QC jako liczby. Bez treści CV, więc bez
  ``candidates:cv`` — integracja, która zleca CV, widzi, kiedy jest gotowe.
* ``GET …/cv/file?format=docx|pdf`` — ``cv:generate`` I ``candidates:cv``
  (plik to dane osobowe). Ten sam plik i ta sama nazwa co „Pobierz” w panelu
  osoby: zatwierdzone CV — Word zatwierdzonej wersji, szkic — Word z bieżącej
  treści edytora (``SZKIC_…``); PDF z tego samego pliku Word. Ta sama bramka
  zgody RODO (409 ``consent_required``) i ten sam wpis ``cv_file_downloaded``
  co ekran, do tego ślad ``cv_downloaded`` w dzienniku kandydata; osoby nie
  ma, ``details.via`` niesie stempel konta serwisowego.

Decyzje (15.10.2026):

* **Autor = konto serwisowe.** Dokument, zadanie i szkic mają ``created_by``
  / ``branded_updated_by`` = ``NULL``; kwota AI idzie na ``actor_key =
  "system"`` (``check_and_increment`` z ``user_id=None``), nie na Delivery
  Leada — nikt z ludzi tej generacji nie zlecił, a lista „Moje CV” i ranking
  są ludzi. Kto zlecił, mówi wpis ``cv_generation_requested`` z
  ``details.via``. Bez ``UserActivity`` i bez dzwonka ``cv_ready`` (dzwoni
  tylko automat, do osoby, która przesunęła kartę).
* **Zgoda RODO jak na ekranie.** Bez polityki centralnej klient z wymogiem
  zrzutu (PKO BP) odmawia generacji (422, ten sam komunikat). Pod polityką
  centralną CV powstaje, a pobranie blokuje 409 ``consent_required``, dopóki
  ktoś nie dołączy zgody w NEXUSIE — klucz zrzutu nie wgrywa.
* **Uwaga dla generatora** (``note_for_generator``, „Napisz od nowa”) idzie
  jako ``instruction`` — forma i akcenty, nigdy fakty. Notatki „Uwaga do CV”
  klucz nie zapisuje: notatka z klucza jest systemowa, a model takich nie
  czyta (0412).
* **Nowa wersja nie zastępuje istniejącego szkicu.** Podpięcie tylko do pary
  bez CV (``attach_as_stage_draft``); inaczej generacja czeka w karcie na
  „Użyj nowej wersji” (``generations[].attached = false``).
* **Odmowy, których serwer ekranu nie ma, bo pilnuje ich karta:** 409
  ``cv_locked_after_send`` (karta na „CV wysłane” albo dalej — karta nie
  generuje, ``lockedAfterSend``) i 409 ``cv_generation_in_progress`` (karta
  nie daje drugiej generacji w trakcie pierwszej).
* Rekrutacja ukrytego albo usuniętego klienta nie istnieje (404,
  ``jobs_register_base_clause``); osoba spoza rekrutacji — 404.

Moduł NIE MOŻE mieć ``from __future__ import annotations`` (slowapi #579).
"""

from datetime import datetime
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import candidate_stage_cv as stage_cv_api
from app.api import cv_generator_b2b as cv_api
from app.api.cv_pdf_preview import _pdf, _pdf_name, _response
from app.api.deps import Caller, require_service_scope
from app.api.integrations_v1.common import (
    CvGenerate,
    IdPath,
    IntegrationRoute,
    idempotent_write,
    integration_actor,
    principal_rate_key,
    read_rate_limit,
    write_rate_limit,
)
from app.api.jobs import jobs_register_base_clause
from app.core.database import get_db
from app.core.http_headers import content_disposition_attachment
from app.core.rate_limit import limiter
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage
from app.models.service_account import ServiceScope
from app.services import candidate_audit, cv_consent_gate, integration_cv
from app.services.candidate_claim import stage_column
from app.services.cv_document_versions import stage_versions
from app.services.cv_download_log import log_cv_download

router = APIRouter(route_class=IntegrationRoute)

# Plik CV to dane osobowe: obok zlecania CV także odczyt plików kandydata.
CvFile = Annotated[
    Caller,
    Depends(
        require_service_scope(
            ServiceScope.cv_generate, ServiceScope.candidates_cv, allow_admin_jwt=False
        )
    ),
]

REQUESTED_ACTION = "cv_generation_requested"
AUDIT_ENDPOINT = "integrations_v1_client_cv"


# ── Wejście i wyjście ───────────────────────────────────────────────────────


class CvGenerateIn(BaseModel):
    # Literówka w nazwie pola nie może przejść po cichu jako „bez uwagi”.
    model_config = ConfigDict(extra="forbid")

    note_for_generator: str = Field(
        "",
        max_length=300,
        description=(
            "Uwaga dla generatora („Napisz od nowa”): forma i akcenty, np. "
            "„krócej, więcej o Kafce”. Nie jest źródłem faktów; stawki "
            "i dostępność serwer wycina."
        ),
    )


class CvGenerateOut(BaseModel):
    job_id: int
    candidate_id: int
    stage_id: int = Field(description="Wiersz bieżącej karty, dla której powstaje CV.")
    generation_id: int
    status: Literal["processing"]


class CvVersionOut(BaseModel):
    version: int
    approved_at: Optional[datetime]
    language: Optional[str]
    docx_available: bool
    is_current: bool


class CvGenerationOut(BaseModel):
    id: int
    status: Literal["processing", "ready", "failed"]
    language: str
    content_mode: str
    origin: str = Field(description="manual | auto (automat po „Zweryfikowany”).")
    created_at: Optional[datetime]
    attached: bool = Field(
        description="Wynik jest CV pary (szkic albo zatwierdzone). ``false`` przy "
        "gotowej generacji = czeka w karcie na „Użyj nowej wersji”."
    )
    error_code: Optional[str]


class CvQcOut(BaseModel):
    status: Literal["unchecked", "passed", "failed", "overridden"]
    blocking_failed: int
    warnings_count: int
    ok_at: Optional[datetime]


class CvStatusOut(BaseModel):
    job_id: int
    candidate_id: int
    stage_id: int = Field(description="Wiersz bieżącej karty pary.")
    status: Literal["none", "processing", "ready", "failed"]
    cv_stage_id: Optional[int] = Field(description="Wiersz etapu, na którym leży CV.")
    cv_state: Literal["none", "draft", "finalized"]
    finalized: bool
    version: Optional[int]
    updated_at: Optional[datetime]
    finalized_at: Optional[datetime]
    consent_required: bool
    consent_missing: bool = Field(
        description="Klient wymaga zrzutu zgody RODO, a CV go nie ma — pobranie "
        "da 409 ``consent_required``."
    )
    versions: list[CvVersionOut]
    generations: list[CvGenerationOut]
    qc: CvQcOut


# ── Wspólne ─────────────────────────────────────────────────────────────────


async def _job_or_404(db: AsyncSession, job_id: int) -> Job:
    # Rekrutacja ukrytego albo usuniętego klienta nie istnieje dla klucza.
    job = await db.scalar(
        select(Job).where(Job.id == job_id, jobs_register_base_clause())
    )
    if job is None:
        raise HTTPException(404, detail="Rekrutacja nie istnieje.")
    return job


async def _pair_stage_or_404(
    db: AsyncSession, *, job_id: int, candidate_id: int
) -> CandidateStage:
    stage = await integration_cv.current_stage(
        db, candidate_id=candidate_id, job_id=job_id
    )
    if stage is None:
        raise HTTPException(404, detail="Osoby nie ma w tej rekrutacji.")
    return stage


def _consent_flags(csv) -> tuple[bool, bool]:
    metadata = (csv.branded_render_metadata or {}) if csv is not None else {}
    required = bool(metadata.get(cv_consent_gate.FROZEN_REQUIREMENT_KEY))
    attached = bool(csv is not None and csv.branded_consent_content)
    return required, cv_consent_gate.gate_enabled() and required and not attached


# ── Generowanie ─────────────────────────────────────────────────────────────


@router.post(
    "/recruitments/{job_id}/candidates/{candidate_id}/cv",
    response_model=CvGenerateOut,
    status_code=202,
    summary="Wygeneruj CV dla klienta",
)
@limiter.limit(write_rate_limit, key_func=principal_rate_key)
async def generate_client_cv(
    request: Request,
    job_id: IdPath,
    candidate_id: IdPath,
    caller: CvGenerate,
    background_tasks: BackgroundTasks,
    body: Optional[CvGenerateIn] = None,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Zleca CV dla klienta dla bieżącej karty pary — jak „Generuj CV” w karcie
    „CV do klienta”. 202 ``processing``; stan: ``GET …/cv``. Odmowy reguły
    klienta (zgoda RODO, numer projektu, notatki, język) — 422 z komunikatem
    ekranu, zanim cokolwiek zostanie naliczone."""
    payload = body or CvGenerateIn()
    queued: list[int] = []

    async def run():
        job = await _job_or_404(db, job_id)
        stage = await _pair_stage_or_404(db, job_id=job_id, candidate_id=candidate_id)
        if integration_cv.locked_after_send(await stage_column(db, stage)):
            raise HTTPException(
                409,
                detail={
                    "error": "cv_locked_after_send",
                    "message": "CV jest już u klienta — od „CV wysłane” nowe CV "
                    "generuje się w NEXUSIE.",
                },
            )
        if await integration_cv.generation_in_progress(
            db, candidate_id=candidate_id, job_id=job_id
        ):
            raise HTTPException(
                409,
                detail={
                    "error": "cv_generation_in_progress",
                    "message": "CV tej osoby właśnie się generuje — sprawdź stan "
                    "i spróbuj po jego zakończeniu.",
                },
            )
        candidate = await db.get(Candidate, candidate_id)
        settings = await integration_cv.generation_settings(db, job=job, stage=stage)
        generated_id, durable_id, _name = await cv_api.enqueue_candidate_generation(
            db,
            # Konto serwisowe: dokument bez autora, kwota AI na „system”.
            user_id=None,  # type: ignore[arg-type]
            candidate=candidate,
            stage=stage,
            client_id=job.client_id,
            cv_document_id=settings.cv_document_id,
            language=settings.language,
            blind_cv=False,
            content_mode=settings.content_mode,
            project_ref=settings.project_ref,
            languages=settings.languages,
            position=settings.position,
            attach_stage_draft=True,
            sources=settings.sources,
            instruction=payload.note_for_generator.strip(),
        )
        # Kto zlecił: wpis bez osoby, ``details.via`` dopisuje sesja klucza.
        db.add(
            Activity(
                entity_type="cv_generated_document",
                entity_id=generated_id,
                action=REQUESTED_ACTION,
                user_id=None,
                details={
                    "candidate_id": candidate_id,
                    "job_id": job_id,
                    "stage_id": stage.id,
                },
            )
        )
        queued.append(durable_id)
        return 202, {
            "job_id": job_id,
            "candidate_id": candidate_id,
            "stage_id": stage.id,
            "generation_id": generated_id,
            "status": "processing",
        }

    response = await idempotent_write(
        request,
        db,
        caller,
        payload={
            "job_id": job_id,
            "candidate_id": candidate_id,
            **payload.model_dump(mode="json"),
        },
        run=run,
    )
    # Po commicie (powtórka z paragonu nie woła `run`): zadanie w tle, jak
    # po kliknięciu. Gdy proces padnie, zadanie podejmie `recovery_loop`.
    from app.services.cv_generator_b2b import durable_jobs

    for durable_id in queued:
        background_tasks.add_task(durable_jobs.execute_job, durable_id)
    return response


# ── Stan ────────────────────────────────────────────────────────────────────


@router.get(
    "/recruitments/{job_id}/candidates/{candidate_id}/cv",
    response_model=CvStatusOut,
    summary="Stan CV dla klienta",
)
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def client_cv_status(
    request: Request,
    job_id: IdPath,
    candidate_id: IdPath,
    _caller: CvGenerate,
    db: AsyncSession = Depends(get_db),
) -> CvStatusOut:
    """Stan CV pary bez treści: ``status`` (``processing`` / ``ready`` /
    ``failed`` / ``none``), CV pary (szkic albo zatwierdzone), zatwierdzone
    wersje, ostatnie generacje i QC jako liczby."""
    from app.services import cv_qc

    await _job_or_404(db, job_id)
    stage = await _pair_stage_or_404(db, job_id=job_id, candidate_id=candidate_id)
    csv = await integration_cv.pair_stage_cv(
        db, candidate_id=candidate_id, job_id=job_id, current_stage_id=stage.id
    )
    cv_state = csv.branded_status if csv is not None else "none"
    has_cv = cv_state in ("draft", "finalized")
    versions = await stage_versions(db, csv) if has_cv else []
    generations = await integration_cv.pair_generations(
        db, candidate_id=candidate_id, job_id=job_id
    )
    qc = (await cv_qc.pair_statuses(db, [(candidate_id, job_id)]))[
        (candidate_id, job_id)
    ]
    consent_required, consent_missing = _consent_flags(csv if has_cv else None)
    return CvStatusOut(
        job_id=job_id,
        candidate_id=candidate_id,
        stage_id=stage.id,
        status=integration_cv.overall_status(
            cv_state, generations[0]["status"] if generations else None
        ),
        cv_stage_id=csv.candidate_stage_id if has_cv else None,
        cv_state=cv_state if has_cv else "none",
        finalized=cv_state == "finalized",
        version=csv.branded_version if has_cv else None,
        updated_at=csv.branded_updated_at if has_cv else None,
        finalized_at=csv.branded_finalized_at if cv_state == "finalized" else None,
        consent_required=consent_required,
        consent_missing=consent_missing,
        versions=[
            CvVersionOut(
                version=item["version"],
                approved_at=item["approved_at"],
                language=item["language"],
                docx_available=item["docx_available"],
                is_current=item["is_current"],
            )
            for item in versions
        ],
        generations=[CvGenerationOut(**item) for item in generations],
        qc=CvQcOut(
            status=qc["status"],
            blocking_failed=qc["blocking_failed"],
            warnings_count=qc["warnings_count"],
            ok_at=qc["ok_at"],
        ),
    )


# ── Plik ────────────────────────────────────────────────────────────────────


@router.get(
    "/recruitments/{job_id}/candidates/{candidate_id}/cv/file",
    summary="Pobranie CV dla klienta",
    response_class=Response,
    responses={
        200: {
            "content": {
                stage_cv_api.DOCX_MEDIA_TYPE: {},
                "application/pdf": {},
            }
        }
    },
)
# Limit zapisu, nie odczytu: każdy plik to render Worda, a PDF dodatkowo
# konwersja w LibreOffice (wspólna kolejka z ekranem, który ma 20/min).
@limiter.limit(write_rate_limit, key_func=principal_rate_key)
async def download_client_cv(
    request: Request,
    job_id: IdPath,
    candidate_id: IdPath,
    caller: CvFile,
    db: AsyncSession = Depends(get_db),
    file_format: Literal["docx", "pdf"] = Query(
        "docx", alias="format", description="docx (domyślnie) albo pdf."
    ),
) -> Response:
    """Plik CV dla klienta — ten sam co „Pobierz” w panelu osoby: zatwierdzone
    CV albo szkic z bieżącej treści (nazwa ``SZKIC_…``, nagłówek
    ``X-CV-State``). Para bez CV — 404 ``cv_not_ready``; brak zrzutu zgody
    RODO — 409 ``consent_required``; PDF chwilowo niedostępny — 503."""
    await _job_or_404(db, job_id)
    stage = await _pair_stage_or_404(db, job_id=job_id, candidate_id=candidate_id)
    csv = await integration_cv.pair_stage_cv(
        db, candidate_id=candidate_id, job_id=job_id, current_stage_id=stage.id
    )
    if csv is None or csv.branded_status not in ("draft", "finalized"):
        raise HTTPException(
            404,
            detail={
                "error": "cv_not_ready",
                "message": "Ta osoba nie ma jeszcze CV dla klienta w tej "
                "rekrutacji — sprawdź stan generacji.",
            },
        )
    if csv.branded_status == "finalized":
        state = "approved"
        version = await stage_cv_api.approved_version_for_download(
            db, csv, csv.branded_version
        )
        version_number = version.version
        docx = version.docx_content
        docx_headers = stage_cv_api.approved_docx_headers(version)
        pdf_name = _pdf_name(version.docx_filename, "CV")
    else:
        state = "draft"
        version_number = csv.branded_version
        docx = await stage_cv_api.draft_docx_for_download(
            db, csv, csv.branded_draft_html or ""
        )
        docx_headers = {
            "Content-Disposition": content_disposition_attachment(
                stage_cv_api.draft_docx_filename(csv)
            ),
            "Cache-Control": "private, no-store",
        }
        pdf_name = "SZKIC_" + _pdf_name(
            csv.branded_docx_filename, f"CV_v{csv.branded_version}"
        )
    csv_id = csv.id
    content = await _pdf(db, docx) if file_format == "pdf" else docx
    # Ślad dopiero przy oddanym pliku (odmowa zgody nie jest pobraniem). Osoby
    # nie ma — ``details.via`` dopisuje nasłuch sesji klucza.
    await log_cv_download(
        db,
        intent="download",
        surface=None,
        entity_type="candidate_stage_cv",
        entity_id=csv_id,
        user=integration_actor(caller),
        file_format=file_format,
        state=state,
        version=version_number,
    )
    candidate_audit.record_candidate_audit(
        db,
        action=candidate_audit.CV_DOWNLOADED,
        user_id=None,
        entity_id=candidate_id,
        details={"endpoint": AUDIT_ENDPOINT, "format": file_format, "state": state},
    )
    await db.commit()
    extra = {"X-CV-State": state, "X-CV-Version": str(version_number)}
    if file_format == "pdf":
        return _response(content, pdf_name, extra)
    return Response(
        content=content,
        media_type=stage_cv_api.DOCX_MEDIA_TYPE,
        headers={**docx_headers, **extra},
    )
