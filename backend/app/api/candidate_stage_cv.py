"""Endpointy CV per rekrutacja.

Faza 2 (PR1) — `original` snapshot:
  GET    /api/candidates/stages/{stage_id}/cv/original
  GET    /api/candidates/stages/{stage_id}/cv/original/download
  POST   /api/candidates/stages/{stage_id}/cv/original/refresh
  POST   /api/candidates/stages/{stage_id}/cv/original/upload
         (nowe CV z rekrutacji: główne CV profilu + kopia etapu, 13.10.2026;
         plik nazwany jak CV do klienta → CV do klienta etapu, 15.10.2026)

Faza 3 (PR2) — `branded` draft + finalize (mirror Contract Draft). Od
generatora v3 (23.09.2026) szkic pochodzi wyłącznie z generatora; stary
szablon „CV firmowe" wycofany (GET `none` = pusty stan, zmiana szablonu 410):
  GET    /api/candidates/stages/{stage_id}/cv/branded
  GET    /api/candidates/stages/{stage_id}/cv/branded/issues
  PATCH  /api/candidates/stages/{stage_id}/cv/branded
  GET    /api/candidates/stages/{stage_id}/cv/branded/render-pdf
  POST   /api/candidates/stages/{stage_id}/cv/branded/finalize

Wybór gotowego CV z profilu kandydata (09.10.2026):
  POST   /api/candidates/stages/{stage_id}/cv/branded/select-generated
  POST   /api/candidates/stages/{stage_id}/cv/branded/discard
         (CV z generatora, także z innej rekrutacji tej osoby)
  POST   /api/candidates/stages/{stage_id}/cv/branded/select-document
         (plik Word z profilu, wczytany do edytora bez AI)

„Użyj innego CV” w karcie „CV do klienta” (12.10.2026):
  GET    /api/candidates/stages/{stage_id}/cv/branded/sources
         (gotowe CV etapu tej osoby z innych rekrutacji)
  POST   /api/candidates/stages/{stage_id}/cv/branded/select-stage-cv
         (kopia CV etapu z innej rekrutacji — z poprawkami rekrutera)
  POST   /api/candidates/stages/{stage_id}/cv/branded/upload
         (plik Word z dysku; nie trafia do plików kandydata)
  POST   /api/candidates/stages/{stage_id}/cv/branded/consent
         (zrzut zgody RODO dla CV bez dokumentu generatora)

Historia wersji w edytorze CV (Edytor CV 2, PR 5) — tylko odczyt:
  GET    /api/candidates/stages/{stage_id}/cv/branded/versions
  GET    /api/candidates/stages/{stage_id}/cv/branded/versions/{n}
  Podgląd importu pliku Word (`…/cv/branded/import-preview`) ma limit żądań,
  więc stoi w `cv_editor_import.py`: ten moduł ma `from __future__ import
  annotations`, którego nie wolno łączyć z `@limiter.limit`.

Faza 4 (PR2) — public share:
  POST   /api/candidates/stages/{stage_id}/cv/share-token
  DELETE /api/candidates/stages/cv/share-token/{token}
  GET    /api/pipeline/candidates/{candidate_id}/jobs/{job_id}/cv-share-tokens
         (linki ze WSZYSTKICH etapów pary, tylko odczyt, bez sekretów)
  GET    /api/public/cv/{token}                          (osobny router public_share)
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Path,
    Query,
    Response,
    UploadFile,
)
from fastapi.responses import HTMLResponse
from starlette.concurrency import run_in_threadpool
from app.core.printable_html import printable_document
from app.models.cv_document_version import CvDocumentVersion
from app.services.cv_document_assets import (
    generated_assets,
    CvAssetsError,
)
from app.core.http_headers import content_disposition_attachment
from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer, selectinload

from app.services.html_sanitizer import sanitize_cv_html
from app.services import candidate_audit, cv_editor_issues
from app.services.cv_download_log import log_cv_download
from app.services.cv_rodo_clause import keep_rodo_clause
from app.services.cv_rewrite_merge import MergeResult, merge_rewrite
from app.services.cv_draft_snapshots import (
    latest_restorable,
    mark_restored,
    snapshot_draft,
)
from app.services.cv_document_versions import (
    check_revision,
    freeze_approved_version,
    stage_version_content,
    stage_versions,
)

# M2 audit follow-up (PR1b): the stage-CV snapshot router serves the SAME
# candidate CV bytes that PR1 closed on /api/candidates/*, but only its
# write routes were gated - the reads stayed open to any logged-in role.
# A read-only viewer/client could enumerate sequential stage_id values and
# download every candidate's original + branded CV. Reads now require the
# same CandidateDocumentAccess capability as the canonical document routes.
from app.api.candidate_access import CandidateDocumentAccess, CandidateWriteAccess
from app.api.recruitment_access import ensure_job_membership, ensure_job_read_access
from app.api.section_access import SOURCING_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.cv_share_token import CVShareToken
from app.models.cv_generated_document import CvGeneratedDocument
from app.models.pipeline_template import PipelineStageDef
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User
from app.schemas.candidate_stage_cv import (
    CVBrandedConsentAttach,
    CVBrandedFinalize,
    CVBrandedReview,
    CVBrandedNewDraft,
    CVBrandedFinalizeResponse,
    CVBrandedResponse,
    CVBrandedUpdate,
    CVBrandedSelectDocument,
    CVEditorDismissRequest,
    CVEditorIssues,
    CVBrandedDiscard,
    CVBrandedRestorePrevious,
    CVBrandedRewrite,
    CVBrandedSelectGenerated,
    CVBrandedSelectStageCv,
    CVOriginalSnapshotResponse,
    StageCvUploadResponse,
    CVShareTokenJobListItem,
    CVShareTokensForRecruitment,
    CVShareTokenListItem,
    CVShareTokenResponse,
    CVVersionContent,
    CVVersionsResponse,
    RecruitmentBrandedCvSummary,
    StageCvSourcesResponse,
)

# Testy podmieniają `api.storage_service.save_branded_cv` — moduł zostaje w
# przestrzeni nazw, choć zapis robi teraz `finalize_stage_cv`.
from app.services import storage_service  # noqa: F401
from app.services.candidate_stage_cv_service import (
    finalize_stage_cv,
    load_original_cv_bytes,
    refresh_original_cv_snapshot,
    render_stage_editor_docx,
    snapshot_exists,
)
from app.services import cv_consent_gate as consent_gate
from app.services.hiring_manager_verdicts import veto_for_candidate_stage
from app.services.stage_cv_copy import (
    copy_origin,
    copy_stage_cv,
    detached_metadata,
    job_label,
    list_reusable_stage_cvs,
    reusable_pair_cv,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# Stary szablon „CV firmowe" (HTML bez AI, z e-mailem i telefonem kandydata)
# został wycofany w generatorze v3 (23.09.2026): CV etapu powstaje wyłącznie
# z generatora (`select-generated` albo podpięcie po generacji). Etap bez CV
# zwraca pusty stan, a zapisy na nim odsyłają do generatora. Istniejące szkice
# i wersje ze starego szablonu zostają czytelne (tylko do odczytu w UI).
NO_GENERATED_CV_MESSAGE = (
    "Najpierw wygeneruj CV w generatorze — stary szablon „CV firmowe” został wycofany."
)
LEGACY_TEMPLATE_GONE_MESSAGE = (
    "Szablon „CV firmowe” został wycofany. Wygeneruj CV w generatorze i edytuj "
    "je w edytorze."
)


async def _generated_for_stage_cv(
    db: AsyncSession, csv: CandidateStageCV
) -> Optional[CvGeneratedDocument]:
    """Wygenerowane CV, z którego pochodzi szkic etapu (blokada zgody RODO)."""
    if not csv.generated_document_id:
        return None
    return await db.get(CvGeneratedDocument, csv.generated_document_id)


def _build_original_response(csv: CandidateStageCV) -> CVOriginalSnapshotResponse:
    # PROD-02: snapshot bywa w object storage (bajty w bazie = NULL).
    has_snapshot = snapshot_exists(csv)
    return CVOriginalSnapshotResponse(
        candidate_stage_id=csv.candidate_stage_id,
        candidate_id=csv.candidate_id,
        job_id=csv.job_id,
        has_snapshot=has_snapshot,
        original_cv_filename=csv.original_cv_filename,
        original_cv_language=csv.original_cv_language,
        original_snapshot_at=csv.original_snapshot_at,
        original_snapshot_source=csv.original_snapshot_source,
        download_url=(
            f"/api/candidates/stages/{csv.candidate_stage_id}/cv/original/download"
            if has_snapshot
            else None
        ),
    )


async def _load_csv_for_stage(
    db: AsyncSession,
    stage_id: int,
    user: User,
    *,
    read_access: bool = False,
    lock: bool = False,
    create_missing: bool = False,
) -> CandidateStageCV:
    """Wczytaj CandidateStageCV dla stage_id, 404 gdy brak. Sprawdza tez czy
    sam stage istnieje — żeby rozróżnić "stage nie istnieje" od "stage bez CV".

    ``create_missing`` (wybór gotowego CV): etap bez wiersza CV dostaje pusty
    wiersz zamiast 404. Import Traffita pisze etapy surowym SQL-em, więc
    większość wierszy „Nowi”/„Screening” go nie ma (09.10.2026: 5 837 z 5 958).

    Egzekwuje też **resource scope**: `stage_id` niesie `job_id`, więc dostęp do
    CV tej rekrutacji wymaga przynależności do jej zespołu. Rola
    (`CandidateDocumentAccess` / `CandidateWriteAccess`) odpowiada tylko na pytanie
    „czy wolno ci oglądać CV", nie „czy wolno ci oglądać CV **tej**
    rekrutacji" — i to jest dokładnie ta różnica, przez którą łatanie kolejnych
    routerów nigdy nie trzymało (#791 → #815 → #819).

    Guard siedzi TUTAJ, bo to jedyne wejście do CV dla 9 z 11 tras tego
    routera. Gdyby stał w każdej trasie z osobna, następna dopisana trasa
    musiałaby o nim pamiętać — a „trzeba pamiętać" jest właśnie tym trybem
    awarii, który zamykamy.

    Jedno zapytanie (LEFT JOIN), żeby zachować rozróżnienie 404 bez dokładania
    round-tripa do bazy na każdy odczyt CV.
    """
    row = (
        await db.execute(
            select(CandidateStage.job_id, CandidateStage.candidate_id, CandidateStageCV)
            .select_from(CandidateStage)
            .outerjoin(
                CandidateStageCV,
                CandidateStageCV.candidate_stage_id == CandidateStage.id,
            )
            .where(CandidateStage.id == stage_id)
        )
    ).first()

    if row is None:
        raise HTTPException(status_code=404, detail="Stage nie znaleziony")

    job_id, candidate_id, csv = row
    if read_access:
        await ensure_job_read_access(db, user, job_id)
    else:
        await ensure_job_membership(db, user, job_id)

    if csv is None and create_missing:
        csv = await _create_stage_cv_row(db, stage_id, candidate_id, job_id)
    if csv is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "CV instance nie istnieje dla tego stage. "
                "Snapshot powinien być utworzony przy CREATE stage'a — "
                "jeśli stage jest historyczny, uruchom backfill 0070."
            ),
        )
    if lock:
        csv = await db.scalar(
            select(CandidateStageCV)
            .where(CandidateStageCV.id == csv.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    return csv


async def _create_stage_cv_row(
    db: AsyncSession, stage_id: int, candidate_id: int, job_id: int
) -> CandidateStageCV:
    """Pusty wiersz CV etapu; przy wyścigu dwóch żądań wygrywa pierwszy."""
    try:
        async with db.begin_nested():
            csv = CandidateStageCV(
                candidate_stage_id=stage_id, candidate_id=candidate_id, job_id=job_id
            )
            db.add(csv)
            await db.flush()
        return csv
    except IntegrityError:
        return await db.scalar(
            select(CandidateStageCV).where(
                CandidateStageCV.candidate_stage_id == stage_id
            )
        )


@router.get(
    "/candidates/stages/{stage_id}/cv/original",
    response_model=CVOriginalSnapshotResponse,
)
async def get_original_cv(
    stage_id: int,
    current_user: CandidateDocumentAccess,
    db: AsyncSession = Depends(get_db),
) -> CVOriginalSnapshotResponse:
    # Metadane snapshotu NIE idą przez ``_load_csv_for_stage``: tamten helper
    # zamienia brak wiersza ``CandidateStageCV`` (etap sprzed backfillu 0070,
    # etap założony ścieżką bez snapshotu) na 404 — dokładnie ten sam kod,
    # który front dostaje przy nieistniejącym etapie, więc „Pokaż CV obok"
    # w screeningu kończyło się „Nie udało się wczytać CV" u kandydata, którego
    # aktualne CV działało na profilu (audyt B19). Brak wiersza jest STANEM
    # („brak snapshotu"), nie awarią — wraca jako 200 ``has_snapshot=False``,
    # tak jak wiersz z pustą treścią. Bramka zakresu zostaje ta sama.
    row = (
        await db.execute(
            select(CandidateStage.candidate_id, CandidateStage.job_id, CandidateStageCV)
            .select_from(CandidateStage)
            .outerjoin(
                CandidateStageCV,
                CandidateStageCV.candidate_stage_id == CandidateStage.id,
            )
            .where(CandidateStage.id == stage_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Stage nie znaleziony")
    candidate_id, job_id, csv = row
    await ensure_job_read_access(db, current_user, job_id)
    if csv is None:
        return CVOriginalSnapshotResponse(
            candidate_stage_id=stage_id,
            candidate_id=candidate_id,
            job_id=job_id,
            has_snapshot=False,
        )
    return _build_original_response(csv)


@router.get("/candidates/stages/{stage_id}/cv/original/download")
async def download_original_cv(
    stage_id: int,
    current_user: CandidateDocumentAccess,
    db: AsyncSession = Depends(get_db),
    disposition: Literal["attachment", "inline"] = Query(
        "attachment",
        description=(
            "Tylko do dziennika dostępu: `inline` — podgląd w NEXUSIE, "
            "`attachment` (domyślnie) — zapis na dysk."
        ),
    ),
) -> Response:
    csv = await _load_csv_for_stage(db, stage_id, current_user, read_access=True)
    if not snapshot_exists(csv):
        raise HTTPException(
            status_code=404,
            detail="Kandydat nie miał CV w momencie utworzenia rekrutacji.",
        )
    try:
        content = await load_original_cv_bytes(csv)
    except Exception as exc:  # noqa: BLE001 — storage chwilowo niedostępny
        logger.warning(
            "Snapshot CV stage=%s: pobranie z object storage nieudane: %r",
            stage_id,
            exc,
        )
        raise HTTPException(
            status_code=503,
            detail="Nie udało się pobrać pliku CV z magazynu. Spróbuj ponownie.",
        ) from exc
    if content is None:
        raise HTTPException(
            status_code=404,
            detail="Kandydat nie miał CV w momencie utworzenia rekrutacji.",
        )

    # Ślad dla alarmu masowego przeglądania CV (0508) — jak każda inna droga
    # do pliku kandydata (audyt 22.10, F25).
    candidate_audit.record_candidate_audit(
        db,
        action=candidate_audit.DOCUMENT_DOWNLOADED,
        user_id=current_user.id,
        entity_id=csv.candidate_id,
        details={
            "stage_id": stage_id,
            "endpoint": "stage-cv-original",
            "disposition": disposition,
        },
    )
    await db.commit()

    filename = csv.original_cv_filename or f"cv_stage_{stage_id}.pdf"
    media_type, _ = mimetypes.guess_type(filename)
    if not media_type:
        media_type = "application/octet-stream"

    return Response(
        content,
        media_type=media_type,
        headers={
            "Content-Disposition": content_disposition_attachment(filename),
            "Content-Length": str(len(content)),
        },
    )


@router.post(
    "/candidates/stages/{stage_id}/cv/original/refresh",
    response_model=CVOriginalSnapshotResponse,
)
async def refresh_original_cv(
    stage_id: int,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> CVOriginalSnapshotResponse:
    """Nadpisz snapshot aktualną zawartością CV kandydata (manual refresh).

    Idempotent w tym sensie, że można wołać wielokrotnie — każdorazowo nadpisuje.
    Jeśli kandydat aktualnie nie ma CV → 422 (nie ma czego skopiować).

    Etap bez wiersza CV (import Traffita) dostaje wiersz — do 13.10.2026
    dostawał 404, więc „Użyj w tej rekrutacji” w panelu osoby nie działało
    na większości kart z „Nowych” i „Screeningu”.
    """
    await _load_csv_for_stage(db, stage_id, current_user, create_missing=True)
    try:
        csv = await refresh_original_cv_snapshot(db, stage_id, user_id=current_user.id)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail="Kandydat nie ma w profilu CV w formacie PDF, DOC ani DOCX — nie ma czego skopiować do tej rekrutacji.",
        ) from exc

    await db.commit()
    await db.refresh(csv)
    return _build_original_response(csv)


# Formaty, które `get_current_cv` widzi jako CV — kopia etapu bierze się
# z głównego CV, więc ODT/RTF/TXT dałyby kopię ze starszego pliku.
_STAGE_UPLOAD_CV_EXT = frozenset({".pdf", ".doc", ".docx"})


@router.post(
    "/candidates/stages/{stage_id}/cv/original/upload",
    response_model=StageCvUploadResponse,
    dependencies=SOURCING_SECTION_DEPENDENCIES,
)
async def upload_original_cv(
    stage_id: int,
    current_user: CandidateWriteAccess,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(
        ...,
        description="Nowe CV kandydata (PDF, DOC, DOCX) albo gotowe CV do klienta (DOCX)",
    ),
    mode: Literal["auto", "original"] = Form("auto"),
    replace_client_cv: bool = Form(False),
    db: AsyncSession = Depends(get_db),
) -> StageCvUploadResponse:
    """Nowe CV z rekrutacji: główne CV profilu i kopia CV etapu naraz (13.10.2026).

    15.10.2026 (zgłoszenie rekrutera, D1–D3): plik Word nazwany jak CV do
    klienta („…B2B…” albo wzór nazwy klienta rekrutacji) staje się od razu
    CV do klienta tej rekrutacji (`_upload_client_cv`) — bez głównego CV,
    bez odczytu AI i bez kopii oryginału. ``mode="original"`` wymusza
    dzisiejszą ścieżkę; tak działa „Cofnij” po wgraniu CV do klienta.

    Kafelek „Wgraj nowe CV” w panelu osoby i okno „Dodaj z CV”. Plik idzie tą
    samą ścieżką co `POST /api/candidates/{id}/documents` z `is_primary`
    (deduplikacja po SHA, odczyt AI i bramka tożsamości w tle), a kopia etapu
    powstaje z niego w tej samej transakcji — dwa żądania z przeglądarki mogły
    zostawić CV w profilu bez kopii w rekrutacji. Bramka sekcji Sourcing jak
    przy `/documents`, bo trasa ustawia główne CV profilu.

    Wszystkie odmowy padają PRZED zapisem pliku na dysk (`_ingest_candidate_cv_file`),
    którego rollback nie cofa.

    Kopia etapu powstaje z bajtów tego żądania, nie z ponownego odczytu
    głównego CV (audyt 13.10.2026): przy awarii magazynu odczyt schodził do
    wskaźnika kandydata i kopia dostawała starsze CV pod nazwą nowego pliku.
    """
    import os

    from app.api.candidates import (
        _DOCUMENT_CONTENT_TYPES,
        _after_cv_commit,
        _ingest_candidate_cv_file,
        _primary_cv_before_change,
        _read_upload_bounded,
        _sanitize_upload_filename,
    )
    from app.services.cv_source import CurrentCV

    csv_row = await _load_csv_for_stage(db, stage_id, current_user, create_missing=True)
    candidate = await db.scalar(
        select(Candidate).where(Candidate.id == csv_row.candidate_id)
    )
    if candidate is None:
        raise HTTPException(status_code=404, detail="Kandydat nie znaleziony")

    content = await _read_upload_bounded(file, label="Plik CV")
    safe_filename = _sanitize_upload_filename(file.filename, fallback="CV")
    ext = os.path.splitext(safe_filename.lower())[1]
    if ext not in _STAGE_UPLOAD_CV_EXT:
        raise HTTPException(
            status_code=415,
            detail="W rekrutacji wgraj CV jako PDF, DOC albo DOCX. Inne formaty dodaj w profilu kandydata.",
        )

    if mode == "auto":
        from app.models.job import Job
        from app.services.client_cv_upload import (
            client_filename_pattern,
            looks_like_client_cv,
        )

        job = await db.get(Job, csv_row.job_id)
        pattern = await client_filename_pattern(db, job.client_id if job else None)
        if looks_like_client_cv(safe_filename, pattern):
            return await _upload_client_cv(
                db,
                background_tasks,
                csv_row=csv_row,
                candidate=candidate,
                content=content,
                filename=safe_filename,
                user_id=current_user.id,
                replace=replace_client_cv,
            )
    else:
        await _undo_client_cv_upload(db, csv_row, content, user_id=current_user.id)

    replaced_primary = await _primary_cv_before_change(db, candidate.id)
    document = await _ingest_candidate_cv_file(
        db,
        candidate=candidate,
        content=content,
        safe_filename=safe_filename,
        content_type=_DOCUMENT_CONTENT_TYPES[ext],
        user_id=current_user.id,
    )
    csv = await refresh_original_cv_snapshot(
        db,
        stage_id,
        user_id=current_user.id,
        source="manual_upload",
        # Deduplikacja po SHA mogła wskazać istniejący wiersz — te same bajty,
        # nazwa z wiersza, jak przy odczycie głównego CV.
        current=CurrentCV(
            content=content,
            filename=document.filename,
            language=candidate.cv_language,
            source="stage_upload",
        ),
    )
    await db.commit()
    await db.refresh(candidate)
    await db.refresh(document)
    await db.refresh(csv)
    await _after_cv_commit(
        db,
        background_tasks,
        candidate=candidate,
        document=document,
        actor_user_id=current_user.id,
        replaced_primary=replaced_primary,
    )
    return StageCvUploadResponse(
        **_build_original_response(csv).model_dump(),
        outcome="original",
        uploaded_filename=document.filename,
        stored_in_profile=True,
    )


CLIENT_CV_LOCKED_MESSAGE = (
    "Klient ma już CV tej osoby, więc nie podmieniam go innym. Poprawki zrobisz "
    "w edytorze — zapisze je w historii wersji."
)


async def _ensure_client_cv_replaceable(
    db: AsyncSession, csv: CandidateStageCV
) -> None:
    """Od „CV wysłane” CV do klienta się nie podmienia (409, 15.10.2026).

    Karta chowa wtedy „Użyj innego CV” (`lockedAfterSend`), ale trasy
    przyjmowały podmianę z każdego klienta HTTP. Stan karty czytamy z jej
    bieżącego wiersza, tak jak Tablica.
    """
    from app.services import integration_cv
    from app.services.candidate_claim import stage_column

    stage = await integration_cv.current_stage(
        db, candidate_id=csv.candidate_id, job_id=csv.job_id
    )
    if stage is not None and integration_cv.locked_after_send(
        await stage_column(db, stage)
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "client_cv_locked_after_send",
                "message": CLIENT_CV_LOCKED_MESSAGE,
            },
        )


def _local_label(value: Optional[datetime]) -> str:
    """„15.10.2026, 14:20” w czasie firmy; pusty napis bez daty."""
    from zoneinfo import ZoneInfo

    from app.core.scheduling import DEFAULT_TZ

    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(ZoneInfo(DEFAULT_TZ)).strftime("%d.%m.%Y, %H:%M")


def _replace_question(csv: CandidateStageCV) -> str:
    """Treść pytania „Zastąpić CV do klienta?” — co dokładnie zastąpi plik."""
    if csv.branded_status == "finalized":
        when = _local_label(csv.branded_finalized_at)
        return (
            f"Ta rekrutacja ma już zatwierdzone CV do klienta{f' ({when})' if when else ''}. "
            "Wgrany plik zastąpi je nowym szkicem. Zatwierdzone wersje i wysłane "
            "linki zostają w historii."
        )
    when = _local_label(csv.branded_updated_at)
    return (
        f"Ta rekrutacja ma już CV do klienta{f' (szkic, zmieniony {when})' if when else ''}. "
        "Wgrany plik je zastąpi, a obecny szkic zostanie w historii."
    )


async def _upload_client_cv(
    db: AsyncSession,
    background_tasks: BackgroundTasks,
    *,
    csv_row: CandidateStageCV,
    candidate: Candidate,
    content: bytes,
    filename: str,
    user_id: int,
    replace: bool,
) -> StageCvUploadResponse:
    """Gotowe CV do klienta z kafelka „Wgraj nowe CV” (15.10.2026, D1–D3).

    Plik staje się szkicem CV do klienta pary (ten sam import Worda co „Użyj
    tego CV”), a nie głównym CV i oryginałem kandydata. Wszystkie odmowy
    padają przed zapisem pliku w magazynie:

    * plik z nagłówkiem innej osoby → 422 (bramka tożsamości oryginału go nie
      zobaczy);
    * karta na „CV wysłane” i dalej → CV do klienta zostaje, plik idzie tylko
      do profilu (``client_cv_kept``);
    * CV, które ktoś poprawiał, wybrał albo zatwierdził → 409 z pytaniem;
      nieprzejrzane auto-CV podmieniamy bez pytania (D2).

    W profilu plik zostaje jako „CV dla klientów” (niegłówny, bez odczytu AI)
    tylko wtedy, gdy osoba ma główne CV. Bez niego najnowszy plik CV staje
    się „bieżącym CV” (`cv_source.current_cv_ordering`) — źródłem generatora
    i kopii oryginału — tak jak plik z dysku w karcie (12.10.2026).
    """
    import os

    from app.api.candidates import _DOCUMENT_CONTENT_TYPES, _attach_candidate_document
    from app.models.candidate_document import CandidateDocument, CandidateDocumentKind
    from app.services.client_cv_upload import (
        UPLOAD_ACTION,
        cv_header,
        is_untouched_auto_cv,
        other_person_name,
    )
    from app.services import integration_cv
    from app.services.candidate_claim import stage_column

    imported = await word_to_editor_html(content)
    observed = other_person_name(
        header=cv_header(imported.html),
        filename=filename,
        first_name=candidate.name,
        last_name=candidate.lastname,
    )
    if observed:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "client_cv_other_person",
                "message": (
                    f"To CV innej osoby: w pliku jest „{observed[:80]}”. Nie podpiąłem go "
                    "jako CV do klienta. Jeśli to ta sama osoba (np. po zmianie "
                    "nazwiska), wgraj plik w karcie „CV do klienta” → „Użyj innego CV” "
                    "→ „Gotowe CV do klienta z dysku (bez AI)”."
                ),
            },
        )

    # Główne CV, które `get_current_cv` widzi (PDF/DOC/DOCX). Główne w ODT czy
    # TXT nie wygrywa, więc zapisany plik do klienta zostałby „bieżącym CV”.
    primary_name = await db.scalar(
        select(CandidateDocument.filename).where(
            CandidateDocument.candidate_id == candidate.id,
            CandidateDocument.document_kind == CandidateDocumentKind.cv,
            CandidateDocument.is_primary.is_(True),
            CandidateDocument.source_deleted_at.is_(None),
        )
    )
    has_primary = os.path.splitext((primary_name or "").lower())[1] in (
        _STAGE_UPLOAD_CV_EXT
    )

    async def store_in_profile():
        return await _attach_candidate_document(
            db,
            candidate_id=candidate.id,
            safe_filename=filename,
            content=content,
            content_type=_DOCUMENT_CONTENT_TYPES[".docx"],
            kind=CandidateDocumentKind.cv,
            user_id=user_id,
        )

    # Wiersz z CV do klienta pary — tak jak karta (`cvStageId`): bieżący, a gdy
    # pusty, wiersz sprzed ruchu karty z szkicem albo zatwierdzonym CV.
    target_stage_id = csv_row.candidate_stage_id
    if (csv_row.branded_status or "none") == "none":
        pair = await _branded_cv_summary_for_pair(
            db, csv_row.candidate_id, csv_row.job_id
        )
        if pair.stage_id is not None:
            target_stage_id = pair.stage_id
    target = await db.scalar(
        select(CandidateStageCV)
        .where(CandidateStageCV.candidate_stage_id == target_stage_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )

    # Stan karty czytany PO blokadzie wiersza CV — jak najbliżej zapisu.
    stage = await integration_cv.current_stage(
        db, candidate_id=csv_row.candidate_id, job_id=csv_row.job_id
    )
    if stage is not None and integration_cv.locked_after_send(
        await stage_column(db, stage)
    ):
        if not has_primary:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "client_cv_locked_after_send",
                    "message": (
                        "Klient ma już CV tej osoby, więc go nie podmieniam. Plik nie "
                        "został zapisany: osoba nie ma głównego CV w profilu, a ten "
                        "plik zająłby jego miejsce."
                    ),
                },
            )
        document = await store_in_profile()
        await db.commit()
        await db.refresh(csv_row)
        return StageCvUploadResponse(
            **_build_original_response(csv_row).model_dump(),
            outcome="client_cv_kept",
            uploaded_filename=document.filename,
            stored_in_profile=True,
        )

    prior_status = target.branded_status or "none"
    prior_generated_id = target.generated_document_id
    if prior_status == "none":
        replaced = "none"
    elif await is_untouched_auto_cv(db, target):
        replaced = "auto_cv"
    elif not replace:
        changed = (
            target.branded_finalized_at
            if prior_status == "finalized"
            else target.branded_updated_at
        )
        raise HTTPException(
            status_code=409,
            detail={
                "code": "client_cv_replace_confirm",
                "message": _replace_question(target),
                "status": prior_status,
                "updated_at": changed.isoformat() if changed else None,
            },
        )
    else:
        replaced = "confirmed"
    if prior_status == "draft":
        snapshot_draft(db, target, user_id=user_id, reason="replaced")

    document = await store_in_profile() if has_primary else None
    sha256 = hashlib.sha256(content).hexdigest()
    target = await _write_imported_draft(
        db,
        target,
        imported,
        expected_revision=target.edit_revision or 0,
        user_id=user_id,
        origin=copy_origin("upload", label=filename),
        activity_action=UPLOAD_ACTION,
        activity_details={"upload_filename": filename, "upload_sha256": sha256},
        activity_only={
            "source_document_id": document.id if document is not None else None,
            "replaced": replaced,
            "prior": {
                "status": prior_status,
                "generated_document_id": prior_generated_id,
            },
        },
    )
    await db.commit()
    await db.refresh(target)
    await db.refresh(csv_row)
    _schedule_qc_after_attach(background_tasks, target.candidate_stage_id, user_id)
    return StageCvUploadResponse(
        **_build_original_response(csv_row).model_dump(),
        outcome="client_cv",
        uploaded_filename=filename,
        client_cv=_build_branded_response(target),
        client_cv_stage_id=target.candidate_stage_id,
        replaced=replaced,
        undo_available=replaced in ("none", "auto_cv"),
        stored_in_profile=document is not None,
    )


def _clear_stage_draft(
    db: AsyncSession, csv: CandidateStageCV, *, user_id: int, action: str
) -> None:
    """CV do klienta wraca do „brak” (cofnięcie wgrania z kafelka). Bez commitu."""
    csv.generated_document_id = None
    csv.branded_from_generator = False
    csv.branded_template_content = None
    csv.branded_consent_content = None
    csv.branded_docx_filename = None
    csv.branded_render_metadata = None
    csv.branded_draft_html = None
    csv.branded_template = None
    csv.branded_language = None
    csv.branded_status = "none"
    csv.edit_revision = (csv.edit_revision or 0) + 1
    csv.branded_updated_at = datetime.now(timezone.utc)
    csv.branded_updated_by = user_id
    csv.branded_finalized_at = None
    csv.branded_finalized_by = None
    csv.branded_snapshot_path = None
    csv.branded_snapshot_filename = None
    csv.branded_snapshot_size_bytes = None
    db.add(
        Activity(
            entity_type="candidate_stage_cv",
            entity_id=csv.id,
            action=action,
            user_id=user_id,
            details={
                "candidate_stage_id": csv.candidate_stage_id,
                "edit_revision": csv.edit_revision,
            },
        )
    )


async def _undo_client_cv_upload(
    db: AsyncSession, csv_row: CandidateStageCV, content: bytes, *, user_id: int
) -> None:
    """„Cofnij” po wgraniu CV do klienta: poprzednie CV do klienta wraca. Bez commitu.

    Działa tylko, gdy CV do klienta pary to wciąż ten plik w nietkniętej
    wersji i wgranie niczego czyjegoś nie zastąpiło (brak CV albo nieprzejrzane
    auto-CV) — inaczej cofnięcie skasowałoby czyjąś pracę. Auto-CV wraca
    z dokumentu generatora (szablon i zgoda jak przy podpięciu), a brak CV —
    jako pusty stan. Sam plik idzie dalej zwykłą ścieżką CV kandydata.
    """
    from app.services import integration_cv
    from app.services.candidate_claim import stage_column
    from app.services.client_cv_upload import UNDO_ACTION, last_upload_if_current

    # Po „CV wysłane” klient ma już to CV — cofnięcie robi z pliku tylko CV
    # kandydata, CV do klienta zostaje.
    stage = await integration_cv.current_stage(
        db, candidate_id=csv_row.candidate_id, job_id=csv_row.job_id
    )
    if stage is not None and integration_cv.locked_after_send(
        await stage_column(db, stage)
    ):
        return
    sha256 = hashlib.sha256(content).hexdigest()
    rows = (
        await db.scalars(
            select(CandidateStageCV)
            .where(
                CandidateStageCV.candidate_id == csv_row.candidate_id,
                CandidateStageCV.job_id == csv_row.job_id,
            )
            .order_by(CandidateStageCV.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).all()
    for row in rows:
        details = await last_upload_if_current(db, row, sha256)
        if details is None or details.get("replaced") not in ("none", "auto_cv"):
            continue
        prior = details.get("prior") or {}
        generated = None
        if prior.get("status") == "draft" and prior.get("generated_document_id"):
            generated = await db.get(
                CvGeneratedDocument, prior["generated_document_id"]
            )
        if generated is not None and generated.status == "ready":
            try:
                async with db.begin_nested():
                    await apply_generated_to_stage_cv(
                        db, row, generated, user_id=user_id, activity_action=UNDO_ACTION
                    )
                return
            except HTTPException:
                # Szablonu auto-CV już nie da się odtworzyć — zostaje pusty stan.
                await db.refresh(row)
        _clear_stage_draft(db, row, user_id=user_id, action=UNDO_ACTION)
        return


# ── Branded CV — draft + finalize (Faza 3) ─────────────────────────────────


def _wrap_printable_cv(body_html: str, stage_id: int, candidate_label: str) -> str:
    """Printable wrapper z auto-print — wspólna otoczka z CSP w <meta>.

    ``candidate_label`` to imię i nazwisko z formularza kariery: escapuje je
    ``printable_document``, a treść idzie przez allowlistę (także przy
    snapshotcie, który otwiera się jako blob pod originem aplikacji).
    """
    return printable_document(
        sanitize_cv_html(body_html),
        f"CV — {candidate_label} (rekrutacja #{stage_id})",
    )


def _draft_source(csv: CandidateStageCV) -> Optional[str]:
    """Skąd pochodzi treść CV etapu: generator, plik Word czy stary szablon."""
    if csv.branded_status == "none":
        return None
    if (csv.branded_render_metadata or {}).get("source") == "document":
        return "document"
    return "generator" if csv.branded_from_generator else "legacy"


def _build_branded_response(
    csv: CandidateStageCV,
    *,
    updated_by_name: Optional[str] = None,
    finalized_by_name: Optional[str] = None,
    rendered_from_default: bool = False,
) -> CVBrandedResponse:
    from app.services.cv_editor_rules import editor_rule_feedback
    from app.services.cv_text_align import cv_text_align

    metadata = csv.branded_render_metadata or {}
    origin = metadata.get("origin")
    consent_required = bool(metadata.get(consent_gate.FROZEN_REQUIREMENT_KEY))
    consent_attached = bool(csv.branded_consent_content)
    return CVBrandedResponse(
        presentation_review=editor_rule_feedback(
            csv.branded_draft_html, csv.branded_render_metadata
        ),
        text_align=cv_text_align(metadata),
        candidate_stage_id=csv.candidate_stage_id,
        generated_document_id=csv.generated_document_id,
        from_generator=bool(csv.branded_from_generator),
        source=_draft_source(csv),
        origin=origin if isinstance(origin, dict) and origin.get("kind") else None,
        consent_required=consent_required,
        consent_attached=consent_attached,
        consent_missing=consent_gate.gate_enabled()
        and consent_required
        and not consent_attached,
        docx_available=csv.branded_status == "finalized"
        and bool((csv.branded_render_metadata or {}).get("renderer_version")),
        docx_filename=csv.branded_docx_filename
        if csv.branded_status == "finalized"
        else None,
        edit_revision=csv.edit_revision or 0,
        version=csv.branded_version or 1,
        status=csv.branded_status,  # type: ignore[arg-type]
        content_html=csv.branded_draft_html,
        template=csv.branded_template,
        language=csv.branded_language,
        updated_at=csv.branded_updated_at,
        updated_by=csv.branded_updated_by,
        updated_by_name=updated_by_name,
        finalized_at=csv.branded_finalized_at,
        finalized_by=csv.branded_finalized_by,
        finalized_by_name=finalized_by_name,
        snapshot_filename=csv.branded_snapshot_filename,
        rendered_from_default=rendered_from_default,
    )


def with_pair_source(
    response: CVBrandedResponse, pair: RecruitmentBrandedCvSummary
) -> CVBrandedResponse:
    """Pusty stan etapu + wskazanie CV firmowego pary z innego etapu.

    Runda 11 (PIPE-3, F23): ruch na kolejną kolumnę zakłada nowy wiersz etapu
    bez CV, a dokument zostaje na wierszu, na którym powstał. Nic nie jest
    kopiowane ani przenoszone (edycje, wersje i linki zostają przy jednym
    wierszu, bramka QC i tak czyta CV pary) — odpowiedź tylko mówi, gdzie
    dokument leży, żeby karta nie proponowała generacji od nowa."""
    if (
        response.status != "none"
        or pair.status not in ("draft", "finalized")
        or pair.stage_id is None
        or pair.stage_id == response.candidate_stage_id
    ):
        return response
    return response.model_copy(
        update={
            "pair_source_stage_id": pair.stage_id,
            "pair_source_status": pair.status,
        }
    )


def _build_empty_branded_response(csv: CandidateStageCV) -> CVBrandedResponse:
    """Etap bez CV (``none``) — pusty stan, bez renderu i bez zapisu.

    Do 23.09.2026 GET renderował tu stary szablon „CV firmowe" (HTML z danymi
    kontaktowymi kandydata). Szablon wycofano: CV etapu powstaje w generatorze
    i trafia tu przez podpięcie szkicu. ``edit_revision`` jest prawdziwe, żeby
    późniejszy wybór z generatora przeszedł kontrolę rewizji.
    """
    return CVBrandedResponse(
        candidate_stage_id=csv.candidate_stage_id,
        edit_revision=csv.edit_revision or 0,
        version=csv.branded_version or 1,
        status="none",
        content_html=None,
        template=None,
        language=None,
        rendered_from_default=False,
    )


@router.get(
    "/candidates/stages/{stage_id}/cv/branded",
    response_model=CVBrandedResponse,
)
async def get_branded_cv(
    stage_id: int,
    current_user: CandidateDocumentAccess,
    db: AsyncSession = Depends(get_db),
) -> CVBrandedResponse:
    """Brandowane CV etapu. W stanie ``none`` zwraca pusty stan (bez renderu,
    bez zapisu — CV-01 i wycofanie starego szablonu, generator v3). Szkic
    powstaje z generatora: podpięcie po generacji albo ``select-generated``."""
    # Nie przez ``_load_csv_for_stage``: brak wiersza ``CandidateStageCV`` jest
    # STANEM („nie ma jeszcze CV”), nie awarią — jak w ``get_original_cv``.
    # Etapy z importu Traffita go nie mają (09.10.2026: 5 837 z 5 958 wierszy
    # „Nowi”/„Screening”), a karta „CV do klienta” jest od 12.10.2026 widoczna
    # także przed „Zweryfikowany” i 404 rysowało w niej błąd wczytania.
    row = (
        await db.execute(
            select(CandidateStage.candidate_id, CandidateStage.job_id, CandidateStageCV)
            .select_from(CandidateStage)
            .outerjoin(
                CandidateStageCV,
                CandidateStageCV.candidate_stage_id == CandidateStage.id,
            )
            .where(CandidateStage.id == stage_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Stage nie znaleziony")
    candidate_id, job_id, csv = row
    await ensure_job_read_access(db, current_user, job_id)

    if csv is None or csv.branded_status == "none":
        return with_pair_source(
            _build_empty_branded_response(csv)
            if csv is not None
            else CVBrandedResponse(candidate_stage_id=stage_id, status="none"),
            await _branded_cv_summary_for_pair(db, candidate_id, job_id),
        )

    updated_by_name: Optional[str] = None
    if csv.branded_updated_by:
        updated_by_name = await db.scalar(
            select(User.email).where(User.id == csv.branded_updated_by)
        )
    finalized_by_name: Optional[str] = None
    if csv.branded_finalized_by:
        finalized_by_name = await db.scalar(
            select(User.email).where(User.id == csv.branded_finalized_by)
        )

    return _build_branded_response(
        csv,
        updated_by_name=updated_by_name,
        finalized_by_name=finalized_by_name,
    )


@router.get(
    "/candidates/stages/{stage_id}/cv/branded/issues",
    response_model=CVEditorIssues,
)
async def get_branded_cv_issues(
    stage_id: int,
    current_user: CandidateDocumentAccess,
    db: AsyncSession = Depends(get_db),
) -> CVEditorIssues:
    """Panel „Do poprawy” w edytorze CV: uwagi generatora i kontroli AI.

    Osobna trasa, nie pole stanu: stan wraca z każdego autozapisu, a te dane
    zmieniają się tylko po generacji i po zatwierdzeniu. Ta sama bramka co
    odczyt CV etapu; etap bez CV to pusta lista, nie błąd. QC ma własną trasę
    (``/api/pipeline/stages/{id}/qc``).
    """
    candidate_id, job_id, csv = await _issues_stage(db, stage_id)
    await ensure_job_read_access(db, current_user, job_id)
    if csv is None:
        return CVEditorIssues()
    return CVEditorIssues(
        **await cv_editor_issues.stage_issues(db, csv, (candidate_id, job_id))
    )


async def _issues_stage(
    db: AsyncSession, stage_id: int
) -> tuple[int, int, Optional[CandidateStageCV]]:
    row = (
        await db.execute(
            select(CandidateStage.candidate_id, CandidateStage.job_id, CandidateStageCV)
            .select_from(CandidateStage)
            .outerjoin(
                CandidateStageCV,
                CandidateStageCV.candidate_stage_id == CandidateStage.id,
            )
            .where(CandidateStage.id == stage_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Stage nie znaleziony")
    return row[0], row[1], row[2]


@router.post(
    "/candidates/stages/{stage_id}/cv/branded/issues/dismiss",
    response_model=CVEditorIssues,
)
async def dismiss_branded_cv_issue(
    stage_id: int,
    payload: CVEditorDismissRequest,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> CVEditorIssues:
    """„To nieprawda” przy uwadze generatora albo kontroli AI w edytorze (D5).

    Pominięcie dotyczy pary (kandydat, rekrutacja); 422, gdy tej uwagi już
    nie ma na liście.
    """
    from app.services.cv_finding_dismissals import DismissError

    candidate_id, job_id, csv = await _issues_stage(db, stage_id)
    await ensure_job_membership(db, current_user, job_id)
    if csv is None:
        raise HTTPException(status_code=404, detail="Etap nie ma CV firmowego")
    try:
        issues = await cv_editor_issues.dismiss(
            db,
            csv,
            pair=(candidate_id, job_id),
            stage_id=stage_id,
            source=payload.source,
            text=payload.text,
            status=payload.status,
            reason=payload.reason,
            note=payload.note,
            user_id=current_user.id,
        )
    except DismissError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "CV_ISSUE_DISMISS_FAILED", "message": str(exc)},
        ) from exc
    await db.commit()
    return CVEditorIssues(**issues)


@router.post(
    "/candidates/stages/{stage_id}/cv/branded/issues/dismissals/{dismissal_id}/restore",
    response_model=CVEditorIssues,
)
async def restore_branded_cv_issue(
    stage_id: int,
    current_user: CandidateWriteAccess,
    dismissal_id: int = Path(ge=1, le=9_223_372_036_854_775_807),
    db: AsyncSession = Depends(get_db),
) -> CVEditorIssues:
    """Przywróć uwagę generatora albo kontroli AI oznaczoną „To nieprawda”."""
    from app.services.cv_finding_dismissals import DismissError

    candidate_id, job_id, csv = await _issues_stage(db, stage_id)
    await ensure_job_membership(db, current_user, job_id)
    if csv is None:
        raise HTTPException(status_code=404, detail="Etap nie ma CV firmowego")
    try:
        issues = await cv_editor_issues.restore(
            db,
            csv,
            pair=(candidate_id, job_id),
            dismissal_id=dismissal_id,
            user_id=current_user.id,
        )
    except DismissError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "CV_ISSUE_RESTORE_FAILED", "message": str(exc)},
        ) from exc
    await db.commit()
    return CVEditorIssues(**issues)


async def apply_generated_to_stage_cv(
    db: AsyncSession,
    csv: CandidateStageCV,
    generated: CvGeneratedDocument,
    *,
    user_id: Optional[int],
    approved=None,
    activity_action: str = "branded_cv_selected_from_generator",
    keep_edits: bool = False,
) -> Optional[MergeResult]:
    """Wczytaj wygenerowane CV jako SZKIC brandowanego CV etapu. Bez commitu.

    Jedna ścieżka dla kliknięcia „Zastąp szkic i otwórz edytor" i dla auto-CV po
    ruchu na „Zweryfikowany" (`services/cv_auto_generate.py`). Wynik to zawsze
    ``branded_status="draft"`` — zatwierdza wyłącznie człowiek (`finalize`).
    Wołający trzyma blokadę wiersza i sprawdził rewizję / stan.

    ``keep_edits`` („Napisz od nowa”, PR 5): części szkicu poprawione ręcznie
    zostają w wersji rekrutera; zwraca wynik scalenia (co zostało).
    """
    from app.services.cv_generator_b2b.html_export import render_interactive_html
    from app.services.cv_generator_b2b.public_view import build_public_payload

    from app.services.cv_approval_provenance import capture_editor_origin

    public = build_public_payload(generated.render_payload)
    try:
        if approved is not None:
            from app.services.cv_document_assets import approved_assets

            template, consent, metadata = approved_assets(approved)
            html = sanitize_cv_html(approved.content_html)
            public["language"] = approved.language or public["language"]
            public["blind"] = approved.template == "blind"
            metadata.update(
                {
                    "source_document_version_id": approved.id,
                    "source_document_content_sha256": approved.content_sha256,
                    "source_document_docx_sha256": approved.docx_sha256,
                }
            )
        else:
            template, consent, metadata = await run_in_threadpool(
                generated_assets, generated
            )
            html = sanitize_cv_html(
                render_interactive_html(public, [], document_only=True)
            )
            metadata.update(capture_editor_origin(html, generated.render_payload))
    except CvAssetsError as error:
        raise HTTPException(
            422, {"code": "cv_editor_assets_unavailable", "message": str(error)}
        ) from error
    merge = None
    if keep_edits and approved is None and (csv.branded_draft_html or "").strip():
        # Pochodzenie (`capture_editor_origin`) liczymy z czystej generacji —
        # scalony szkic to już treść poprawiana przez człowieka.
        previous = await _generated_document_html(db, csv.generated_document_id)
        merge = merge_rewrite(previous, csv.branded_draft_html, html)
        html = sanitize_cv_html(merge.html)
    # Runda 7 (R7-X4-1): wymóg zgody zamrożony na kopii — usunięcie
    # wygenerowanego CV (FK SET NULL) nie może zdjąć blokady pobrania.
    await _write_stage_draft(
        db,
        csv,
        html=html,
        template=template,
        consent=consent,
        filename=generated.filename,
        metadata=consent_gate.with_frozen_requirement(metadata, generated),
        blind=bool(public["blind"]),
        language=public["language"],
        generated_document_id=generated.id,
        from_generator=True,
        user_id=user_id,
        activity_action=activity_action,
        activity_details={"generated_document_id": generated.id}
        | (
            {"kept_parts": len(merge.kept), "edits_recognized": merge.recognized}
            if merge is not None
            else {}
        ),
    )
    return merge


async def _generated_document_html(
    db: AsyncSession, generated_document_id: Optional[int]
) -> str:
    """HTML generacji, z której powstał szkic — „przed poprawkami rekrutera”."""
    from app.services.cv_generator_b2b.html_export import render_interactive_html
    from app.services.cv_generator_b2b.public_view import build_public_payload

    if generated_document_id is None:
        return ""
    generated = await db.get(CvGeneratedDocument, generated_document_id)
    if generated is None or not generated.render_payload:
        return ""
    public = build_public_payload(generated.render_payload)
    return sanitize_cv_html(render_interactive_html(public, [], document_only=True))


async def _write_stage_draft(
    db: AsyncSession,
    csv: CandidateStageCV,
    *,
    html: str,
    template: Optional[bytes],
    consent: Optional[bytes],
    filename: Optional[str],
    metadata: dict,
    blind: bool,
    language: str,
    generated_document_id: Optional[int],
    from_generator: bool,
    user_id: Optional[int],
    activity_action: str,
    activity_details: dict,
) -> None:
    """Zapisz SZKIC CV firmowego etapu (jedno miejsce dla każdego źródła).

    Zatwierdzona wersja jest najpierw zamrażana — jej linki i pobrania zostają
    przy starej treści. Bez commitu; wołający trzyma blokadę wiersza.
    """
    if csv.branded_status == "finalized":
        await freeze_approved_version(db, csv)
        csv.branded_version += 1
    csv.generated_document_id = generated_document_id
    csv.branded_from_generator = from_generator
    csv.branded_template_content = template
    csv.branded_consent_content = consent
    csv.branded_docx_filename = filename
    csv.branded_render_metadata = metadata
    csv.branded_draft_html = html
    csv.branded_template = "blind" if blind else "standard"
    csv.branded_language = language
    csv.branded_status = "draft"
    csv.edit_revision = (csv.edit_revision or 0) + 1
    csv.branded_updated_at = datetime.now(timezone.utc)
    csv.branded_updated_by = user_id
    csv.branded_finalized_at = None
    csv.branded_finalized_by = None
    csv.branded_snapshot_path = None
    csv.branded_snapshot_filename = None
    csv.branded_snapshot_size_bytes = None
    db.add(
        Activity(
            entity_type="candidate_stage_cv",
            entity_id=csv.id,
            action=activity_action,
            user_id=user_id,
            details={
                "candidate_stage_id": csv.candidate_stage_id,
                "version": csv.branded_version,
                "edit_revision": csv.edit_revision,
                **activity_details,
            },
        )
    )


async def _apply_generated_from_other_job(
    db: AsyncSession,
    csv: CandidateStageCV,
    generated: CvGeneratedDocument,
    *,
    user_id: int,
) -> None:
    """CV z generatora z INNEJ rekrutacji tej osoby → kopia odłączona.

    Treść i szablon idą z dokumentu; nazwa pliku i wymóg zgody RODO z klienta
    TEJ rekrutacji, a zrzut zgody i reguły klienta źródłowego zostają przy
    źródle (zgoda dla jednego banku nie może trafić do CV dla innego). Bez
    ``generated_document_id``: blokada pobrania i pakiet liczą się z wiersza
    generatora, czyli z cudzego klienta.
    """
    from app.services.candidate_stage_cv_service import detached_copy_settings
    from app.services.cv_approval_provenance import capture_editor_origin
    from app.services.cv_document_assets import default_template
    from app.services.cv_generator_b2b.html_export import render_interactive_html
    from app.services.cv_generator_b2b.public_view import build_public_payload

    public = build_public_payload(generated.render_payload)
    masked_name = None
    if public["blind"]:
        masked_name = "Candidate" if public["language"] == "en" else "Kandydat"
    settings = await detached_copy_settings(db, csv, masked_name=masked_name)
    # Nagłówek i „Rozważany na stanowisko” niosą tytuł rekrutacji źródłowej
    # (bywa w nim numer zapytania innego klienta) — w kopii stoi tytuł tej.
    public["considered_for"] = None
    if settings.job_title:
        public["position"] = settings.job_title
    html = sanitize_cv_html(render_interactive_html(public, [], document_only=True))
    template = generated.template_content or await run_in_threadpool(default_template)
    origin = capture_editor_origin(html, generated.render_payload)
    source_job = None
    if generated.job_id is not None:
        from app.models.job import Job

        source_job = await db.get(Job, generated.job_id)
    await _write_stage_draft(
        db,
        csv,
        html=html,
        template=template,
        consent=None,
        filename=settings.filename,
        metadata=detached_metadata(
            settings,
            source="generated_other_job",
            template=template,
            origin=copy_origin(
                "generated_other_job",
                label=job_label(source_job),
                job_id=generated.job_id,
            ),
            source_generated_id=generated.id,
            source_job_id=generated.job_id,
            blind_identity_guard=origin["blind_identity_guard"],
            blind_identity_terms=origin["blind_identity_terms"],
        ),
        blind=bool(public["blind"]),
        language=public["language"],
        generated_document_id=None,
        from_generator=True,
        user_id=user_id,
        activity_action="branded_cv_selected_from_other_job",
        activity_details={
            "source_generated_id": generated.id,
            "source_job_id": generated.job_id,
        },
    )


@router.post(
    "/candidates/stages/{stage_id}/cv/branded/select-generated",
    response_model=CVBrandedResponse,
)
async def select_generated_cv(
    stage_id: int,
    payload: CVBrandedSelectGenerated,
    current_user: CandidateWriteAccess,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> CVBrandedResponse:
    """Explicitly replace the current draft with one of the candidate's generated CVs.

    Row lock + revision prevent overwriting edits made since selection. Previous
    approvals and their public links remain pinned before a new draft is opened.
    No model call and no regeneration from Candidate fields occurs here.

    Od 09.10.2026 także CV tej osoby z INNEJ rekrutacji (albo „bez procesu”):
    trafia tu jako kopia odłączona (`_apply_generated_from_other_job`).
    """
    csv = await _load_csv_for_stage(
        db, stage_id, current_user, lock=True, create_missing=True
    )
    check_revision(csv, payload.expected_revision)
    generated = await db.get(CvGeneratedDocument, payload.generated_document_id)
    if generated is None or generated.candidate_id != csv.candidate_id:
        raise HTTPException(404, "Nie znaleziono CV tego kandydata.")
    if generated.status != "ready" or not generated.render_payload:
        raise HTTPException(422, "Wybierz zakończoną generację CV.")
    # PR 5: szkic sprzed podmiany zostaje w migawce („Wróć do poprzedniej”) —
    # do 14.10.2026 niezatwierdzony szkic znikał bez śladu.
    snapshot = snapshot_draft(db, csv, user_id=current_user.id, reason="replaced")
    merge = None
    if generated.job_id != csv.job_id:
        if payload.document_version_id is not None:
            raise HTTPException(
                422,
                "Zatwierdzoną wersję można wybrać tylko dla rekrutacji, w której powstała.",
            )
        await _apply_generated_from_other_job(
            db, csv, generated, user_id=current_user.id
        )
    else:
        approved = None
        if payload.document_version_id is not None:
            from app.services.cv_generated_approval import (
                approved_version_for_generation,
            )

            approved = await approved_version_for_generation(
                db, generated, payload.document_version_id
            )
        merge = await apply_generated_to_stage_cv(
            db,
            csv,
            generated,
            user_id=current_user.id,
            approved=approved,
            keep_edits=payload.keep_edits,
        )
    await db.commit()
    await db.refresh(csv)
    # CV w procesie (13.10.2026): QC nowej wersji liczy się w tle, jak po
    # podpięciu z generatora — plakietka na Tablicy nie czeka na okno QC.
    _schedule_qc_after_attach(background_tasks, stage_id, current_user.id)
    response = _build_branded_response(csv)
    if payload.keep_edits:
        response.rewrite = CVBrandedRewrite(
            kept=list(merge.kept) if merge else [],
            recognized=merge.recognized if merge else False,
            can_restore=snapshot is not None,
        )
    return response


@router.post(
    "/candidates/stages/{stage_id}/cv/branded/restore-previous",
    response_model=CVBrandedResponse,
)
async def restore_previous_branded_draft(
    stage_id: int,
    payload: CVBrandedRestorePrevious,
    current_user: CandidateWriteAccess,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> CVBrandedResponse:
    """„Wróć do poprzedniej” (Edytor CV 3, PR 5): szkic sprzed ostatniej podmiany.

    Treść, pochodzenie, metadane, „anonimowe” i język wracają z migawki; plik
    szablonu i zgoda zostają bieżące (zamrożone na etapie). Bieżący szkic idzie do migawki
    ``restore`` — nic nie ginie. Zatwierdzona wersja zamraża się jak przy
    każdej zmianie szkicu.
    """
    csv = await _load_csv_for_stage(db, stage_id, current_user, lock=True)
    check_revision(csv, payload.expected_revision)
    previous = await latest_restorable(db, csv.id)
    if previous is None:
        raise HTTPException(404, "Nie ma poprzedniej wersji szkicu do przywrócenia.")
    snapshot_draft(db, csv, user_id=current_user.id, reason="restore")
    mark_restored(previous, user_id=current_user.id)
    await _write_stage_draft(
        db,
        csv,
        html=previous.content_html,
        template=csv.branded_template_content,
        consent=csv.branded_consent_content,
        filename=csv.branded_docx_filename,
        metadata=dict(previous.render_metadata or csv.branded_render_metadata or {}),
        # Anonimowe i język wracają z migawki razem z treścią (przegląd PR 5:
        # z bieżącej wersji dawały CV z nazwiskiem oznaczone jako anonimowe).
        blind=(previous.branded_template or csv.branded_template) == "blind",
        language=previous.branded_language or csv.branded_language or "pl",
        generated_document_id=previous.generated_document_id,
        from_generator=previous.branded_from_generator,
        user_id=current_user.id,
        activity_action="branded_cv_previous_restored",
        activity_details={"snapshot_id": previous.id},
    )
    await db.commit()
    await db.refresh(csv)
    _schedule_qc_after_attach(background_tasks, stage_id, current_user.id)
    return _build_branded_response(csv)


DISCARD_ACTION = "branded_cv_discarded"


@router.post(
    "/candidates/stages/{stage_id}/cv/branded/discard",
    response_model=CVBrandedResponse,
)
async def discard_branded_cv(
    stage_id: int,
    payload: CVBrandedDiscard,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> CVBrandedResponse:
    """„Odrzuć to CV i zacznij od nowa” (21.10.2026, zgłoszenie zespołu).

    CV do klienta powstało z błędnego pliku albo bez notatki — karta wraca do
    stanu „brak” i do potwierdzeń przed generacją. Nic nie jest kasowane:
    treść idzie do migawki (`replaced`, „Historia wersji” i „Wróć do
    poprzedniej”), zatwierdzone wersje zostają w `cv_document_versions`,
    dokument generatora zostaje w plikach kandydata. Od „CV wysłane” klient ma
    już to CV — 409 jak przy każdej podmianie.
    """
    csv = await _load_csv_for_stage(db, stage_id, current_user, lock=True)
    check_revision(csv, payload.expected_revision)
    if csv.branded_status == "none":
        raise HTTPException(409, "Ta rekrutacja nie ma CV do klienta do odrzucenia.")
    await _ensure_client_cv_replaceable(db, csv)
    snapshot_draft(db, csv, user_id=current_user.id, reason="replaced")
    await _mark_pair_generations_discarded(db, csv)
    _clear_stage_draft(db, csv, user_id=current_user.id, action=DISCARD_ACTION)
    await db.commit()
    await db.refresh(csv)
    return _build_branded_response(csv)


async def _mark_pair_generations_discarded(
    db: AsyncSession, csv: CandidateStageCV
) -> None:
    """Gotowe CV generatora tej pary przestają być CV pary (audyt 22.10, F64).

    Bez znacznika karta proponowała odrzucone CV jako „Użyj tej wersji”,
    a wymagania ruchu, kolejki DL/Cpro i QC CV brały je jako CV firmowe pary
    (fallback do najnowszej gotowej generacji). „Zacznij od nowa” dotyczy
    wszystkich dotychczasowych generacji pary, nie tylko podpiętej; nowa
    generacja jest znowu CV pary. Dokumenty zostają w plikach kandydata.
    Bez commitu.
    """
    from app.models.cv_generated_document import DISCARDED_KEY, not_discarded_clause

    stage = await db.get(CandidateStage, csv.candidate_stage_id)
    scope = []
    if csv.generated_document_id is not None:
        scope.append(CvGeneratedDocument.id == csv.generated_document_id)
    if stage is not None and stage.candidate_id and stage.job_id:
        scope.append(
            and_(
                CvGeneratedDocument.candidate_id == stage.candidate_id,
                CvGeneratedDocument.job_id == stage.job_id,
            )
        )
    if not scope:
        return
    docs = (
        await db.scalars(
            select(CvGeneratedDocument)
            .options(
                defer(CvGeneratedDocument.docx_content),
                defer(CvGeneratedDocument.template_content),
                defer(CvGeneratedDocument.consent_content),
            )
            .where(
                or_(*scope),
                CvGeneratedDocument.status == "ready",
                CvGeneratedDocument.render_payload.is_not(None),
                not_discarded_clause(),
            )
        )
    ).all()
    discarded_at = datetime.now(timezone.utc).isoformat()
    for doc in docs:
        # Nowy słownik — kolumna JSON bez śledzenia mutacji.
        doc.render_payload = {**doc.render_payload, DISCARDED_KEY: discarded_at}


def _schedule_qc_after_attach(
    background_tasks: BackgroundTasks, stage_id: int, user_id: int
) -> None:
    """QC nowego szkicu etapu po odpowiedzi (`cv_auto_generate.qc_after_attach`).

    Każde źródło CV firmowego — wersja z generatora, plik z profilu, plik
    z dysku i CV z innej rekrutacji — dostaje to samo: QC od razu, a na
    „Zweryfikowanym” i dalej także poprawki AI w pamięci edytora (14.10.2026).
    Bez dzwonka: rekruter sam właśnie wybrał to CV. Wyjątek po odpowiedzi
    niczego nie cofa — `qc_after_attach` nigdy nie rzuca.
    """
    from app.services.cv_auto_generate import qc_after_attach

    background_tasks.add_task(qc_after_attach, stage_id, user_id)


async def read_word_upload(file: UploadFile) -> tuple[bytes, str]:
    """Bajty i nazwa pliku Word wgranego z dysku; 422, gdy pusty albo za duży.

    Jedno wejście dla `…/upload` (zapis szkicu) i `…/import-preview` (sam
    podgląd w edytorze): ten sam limit i te same komunikaty.
    """
    from app.services.cv_docx_import import MAX_BYTES

    # Odczyt z limitem: `MAX_BYTES + 1` wystarcza, żeby odmówić bez wczytania
    # całego (dowolnie dużego) pliku. Format sprawdza konwerter (ZIP + OOXML).
    content = await file.read(MAX_BYTES + 1)
    if not content:
        raise HTTPException(422, "Plik jest pusty.")
    if len(content) > MAX_BYTES:
        raise HTTPException(
            422, "Plik jest za duży, żeby wczytać go do edytora (limit 10 MB)."
        )
    filename = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    return content, filename[:200] or "CV.docx"


async def word_to_editor_html(content: bytes):
    """Plik Word → HTML edytora, bez AI (`cv_docx_import`). Konwersja w wątku.

    Plik, którego nie da się wczytać, kończy się 422 z komunikatem dla
    rekrutera (`CvImportError` niesie tylko taki tekst). Do logu idzie sam
    rodzaj przyczyny — bez nazwy pliku i bez treści (obie niosą dane osoby).
    """
    from app.services.cv_docx_import import CvImportError, docx_to_editor_html

    try:
        return await run_in_threadpool(docx_to_editor_html, content)
    except CvImportError as error:
        logger.info(
            "[stage_cv] word import refused: %s (%s)",
            error,
            type(error.__cause__).__name__ if error.__cause__ else "rule",
        )
        raise HTTPException(422, str(error)) from error


async def _import_docx_as_draft(
    db: AsyncSession,
    csv: CandidateStageCV,
    content: bytes,
    *,
    expected_revision: int,
    user_id: int,
    origin: dict,
    activity_action: str,
    activity_details: dict,
) -> CVBrandedResponse:
    """Plik Word → SZKIC CV firmowego etapu, bez AI (`cv_docx_import`).

    Jedna ścieżka dla pliku z profilu kandydata i pliku wgranego z dysku.
    Blokadę wiersza bierzemy dopiero PO konwersji — konwersja bywa wolna,
    a zablokowany wiersz zatrzymałby edytor i automat.
    """
    imported = await word_to_editor_html(content)
    csv = await _write_imported_draft(
        db,
        csv,
        imported,
        expected_revision=expected_revision,
        user_id=user_id,
        origin=origin,
        activity_action=activity_action,
        activity_details=activity_details,
    )
    await db.commit()
    await db.refresh(csv)
    return _build_branded_response(csv)


async def _write_imported_draft(
    db: AsyncSession,
    csv: CandidateStageCV,
    imported,
    *,
    expected_revision: int,
    user_id: int,
    origin: dict,
    activity_action: str,
    activity_details: dict,
    activity_only: Optional[dict] = None,
) -> CandidateStageCV:
    """Wczytany plik Word (`word_to_editor_html`) → szkic etapu. Bez commitu.

    Wgranie CV do klienta z kafelka (15.10.2026) zapisuje w tej samej
    transakcji także plik w profilu, więc konwersja i commit są po stronie
    wołającego. ``activity_details`` trafiają też do metadanych szkicu,
    ``activity_only`` (stan sprzed podmiany dla „Cofnij”) — tylko do śladu.
    """
    from app.services.candidate_stage_cv_service import detached_copy_settings
    from app.services.cv_document_assets import default_template

    settings = await detached_copy_settings(db, csv)
    csv = await db.scalar(
        select(CandidateStageCV)
        .where(CandidateStageCV.id == csv.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    check_revision(csv, expected_revision)
    template = await run_in_threadpool(default_template)
    await _write_stage_draft(
        db,
        csv,
        html=imported.html,
        template=template,
        consent=None,
        filename=settings.filename,
        metadata=detached_metadata(
            settings,
            source="document",
            template=template,
            origin=origin,
            import_stats=imported.stats,
            **activity_details,
        ),
        blind=False,
        language=imported.language,
        generated_document_id=None,
        from_generator=False,
        user_id=user_id,
        activity_action=activity_action,
        activity_details={**activity_details, **(activity_only or {})},
    )
    return csv


@router.post(
    "/candidates/stages/{stage_id}/cv/branded/select-document",
    response_model=CVBrandedResponse,
)
async def select_document_cv(
    stage_id: int,
    payload: CVBrandedSelectDocument,
    current_user: CandidateWriteAccess,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> CVBrandedResponse:
    """Wczytaj plik Word z profilu kandydata jako SZKIC CV firmowego etapu.

    Gotowe CV dla klientów leżą w profilach jako pliki „…B2B…” (09.10.2026:
    34 z 50 osób w screeningu). Plik jest tylko czytany — w profilu zostaje
    bez zmian; treść trafia do edytora bez AI (`cv_docx_import`). QC w tle
    jak po `select-generated` (14.10.2026).
    """
    from app.models.candidate_document import (
        CandidateDocument,
        CandidateDocumentKind,
    )
    from app.services.cv_docx_import import MAX_BYTES

    csv = await _load_csv_for_stage(db, stage_id, current_user, create_missing=True)
    await _ensure_client_cv_replaceable(db, csv)
    check_revision(csv, payload.expected_revision)
    document = await db.get(CandidateDocument, payload.document_id)
    if (
        document is None
        or document.candidate_id != csv.candidate_id
        or document.source_deleted_at is not None
        or document.document_kind
        in (CandidateDocumentKind.cover_letter, CandidateDocumentKind.certificate)
    ):
        raise HTTPException(404, "Nie znaleziono pliku CV tego kandydata.")
    if (document.size_bytes or 0) > MAX_BYTES:
        raise HTTPException(
            422, "Plik jest za duży, żeby wczytać go do edytora (limit 10 MB)."
        )
    document_id = document.id
    document_name = document.filename
    try:
        if document.storage_key:
            from app.services.object_storage import download_cv

            content = await run_in_threadpool(download_cv, document.storage_key)
        else:
            await db.refresh(document, attribute_names=["file_content"])
            content = bytes(document.file_content) if document.file_content else b""
    except Exception as error:  # noqa: BLE001 — magazyn chwilowo niedostępny
        logger.warning(
            "[stage_cv] document=%s unavailable (%s)",
            document_id,
            type(error).__name__,
        )
        raise HTTPException(
            503, "Nie udało się pobrać pliku z magazynu. Spróbuj ponownie za chwilę."
        ) from error
    response = await _import_docx_as_draft(
        db,
        csv,
        content,
        expected_revision=payload.expected_revision,
        user_id=current_user.id,
        origin=copy_origin("profile_file", label=document_name),
        activity_action="branded_cv_imported_from_document",
        activity_details={
            "source_document_id": document_id,
            "source_document_sha256": hashlib.sha256(content).hexdigest(),
        },
    )
    _schedule_qc_after_attach(background_tasks, stage_id, current_user.id)
    return response


@router.post(
    "/candidates/stages/{stage_id}/cv/branded/upload",
    response_model=CVBrandedResponse,
)
async def upload_stage_cv(
    stage_id: int,
    current_user: CandidateWriteAccess,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Gotowe CV dla klienta (.docx)"),
    expected_revision: int = Form(..., ge=0),
    db: AsyncSession = Depends(get_db),
) -> CVBrandedResponse:
    """Wczytaj plik Word z DYSKU jako SZKIC CV firmowego etapu (12.10.2026).

    Rekruter ma gotowe CV poza NEXUS-em i nie chce generować nowego. Plik
    NIE trafia do plików kandydata: w teczce mógłby stać się „aktualnym CV”
    osoby i źródłem dla generatora oraz auto-CV, a powtórne wgranie tych
    samych bajtów przemianowałoby istniejący plik. Zostaje po nim nazwa
    i skrót treści w śladzie; ponowne użycie w innej rekrutacji daje
    `select-stage-cv`. QC w tle jak po `select-generated` (14.10.2026).
    """
    csv = await _load_csv_for_stage(db, stage_id, current_user, create_missing=True)
    await _ensure_client_cv_replaceable(db, csv)
    check_revision(csv, expected_revision)
    content, filename = await read_word_upload(file)
    response = await _import_docx_as_draft(
        db,
        csv,
        content,
        expected_revision=expected_revision,
        user_id=current_user.id,
        origin=copy_origin("upload", label=filename),
        activity_action="branded_cv_uploaded_from_disk",
        activity_details={
            "upload_filename": filename,
            "upload_sha256": hashlib.sha256(content).hexdigest(),
        },
    )
    _schedule_qc_after_attach(background_tasks, stage_id, current_user.id)
    return response


@router.get(
    "/candidates/stages/{stage_id}/cv/branded/sources",
    response_model=StageCvSourcesResponse,
)
async def list_stage_cv_sources(
    stage_id: int,
    current_user: CandidateDocumentAccess,
    db: AsyncSession = Depends(get_db),
) -> StageCvSourcesResponse:
    """Gotowe CV etapu tej osoby z INNYCH rekrutacji (12.10.2026).

    Odczyt bez zapisu: nie przez ``_load_csv_for_stage`` — etap bez wiersza CV
    (import Traffita) dostałby 404, a ``create_missing`` pisałby w GET.
    """
    stage = (
        await db.execute(
            select(CandidateStage.candidate_id, CandidateStage.job_id).where(
                CandidateStage.id == stage_id
            )
        )
    ).first()
    if stage is None:
        raise HTTPException(status_code=404, detail="Stage nie znaleziony")
    await ensure_job_read_access(db, current_user, stage.job_id)
    return StageCvSourcesResponse(
        items=await list_reusable_stage_cvs(
            db,
            candidate_id=stage.candidate_id,
            target_job_id=stage.job_id,
            user=current_user,
        )
    )


@router.post(
    "/candidates/stages/{stage_id}/cv/branded/select-stage-cv",
    response_model=CVBrandedResponse,
)
async def select_stage_cv(
    stage_id: int,
    payload: CVBrandedSelectStageCv,
    current_user: CandidateWriteAccess,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> CVBrandedResponse:
    """CV etapu tej osoby z INNEJ rekrutacji → szkic tej (12.10.2026).

    Kopia bierze treść po poprawkach rekrutera (zatwierdzoną, a bez niej
    szkic) — `select-generated` dla innej rekrutacji renderuje wynik
    generatora od nowa i je gubi. Źródło zostaje nietknięte. QC w tle jak po
    `select-generated` (14.10.2026).
    """
    csv = await _load_csv_for_stage(
        db, stage_id, current_user, lock=True, create_missing=True
    )
    await _ensure_client_cv_replaceable(db, csv)
    check_revision(csv, payload.expected_revision)
    if payload.source_job_id == csv.job_id:
        raise HTTPException(422, "Wybierz CV z innej rekrutacji tej osoby.")
    # Treść CV powstała dla innej rekrutacji — czyta ją ten, kto czyta tamtą.
    await ensure_job_read_access(db, current_user, payload.source_job_id)
    source = await reusable_pair_cv(
        db, candidate_id=csv.candidate_id, job_id=payload.source_job_id
    )
    if source is None:
        raise HTTPException(
            404, "Nie znaleziono gotowego CV tej osoby w tamtej rekrutacji."
        )
    await copy_stage_cv(db, csv, source, user_id=current_user.id)
    await db.commit()
    await db.refresh(csv)
    _schedule_qc_after_attach(background_tasks, stage_id, current_user.id)
    return _build_branded_response(csv)


@router.post(
    "/candidates/stages/{stage_id}/cv/branded/consent",
    response_model=CVBrandedResponse,
)
async def attach_stage_cv_consent(
    stage_id: int,
    payload: CVBrandedConsentAttach,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> CVBrandedResponse:
    """Dołącz albo wymień zrzut zgody RODO w CV etapu BEZ dokumentu generatora.

    Kopia (plik Word, CV z innej rekrutacji, przepięcie) nie ma wiersza
    generatora, do którego dołącza się zgodę trasą generatora. Pokwitowanie
    wystawia ta sama trasa `/api/cv-generator/consent-screenshot`
    (kandydat + etap); 409, gdy CV pochodzi z generatora albo klient zgody
    nie wymaga, 422 przy pokwitowaniu z innego etapu albo innej osoby.
    """
    from app.services.cv_consent_attach import attach_to_stage_copy

    csv = await _load_csv_for_stage(db, stage_id, current_user, lock=True)
    await attach_to_stage_copy(
        db,
        csv,
        token=payload.consent_screenshot_token,
        user_id=current_user.id,
    )
    await db.commit()
    await db.refresh(csv)
    return _build_branded_response(csv)


@router.patch(
    "/candidates/stages/{stage_id}/cv/branded",
    response_model=CVBrandedResponse,
)
async def update_branded_cv(
    stage_id: int,
    payload: CVBrandedUpdate,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> CVBrandedResponse:
    """Zapis treści brandowanego CV (`content_html`). Po finalize 409.

    Gałąź `template`/`language` (ponowny render starego szablonu „CV firmowe")
    wycofana w generatorze v3 — 410. Walidacja XOR zostaje w
    `CVBrandedUpdate.model_validator` (starsi klienci API dostają 422 jak dotąd).
    """
    if payload.content_html is None:
        # Zmiana szablonu/języka renderowała stary szablon „CV firmowe" —
        # wycofany w generatorze v3. 410, nie 409: tej operacji już nie ma.
        raise HTTPException(status_code=410, detail=LEGACY_TEMPLATE_GONE_MESSAGE)
    csv = await _load_csv_for_stage(db, stage_id, current_user, lock=True)
    check_revision(csv, payload.expected_revision)
    if csv.branded_status == "none":
        # Szkic powstaje wyłącznie z generatora (select-generated / podpięcie
        # po generacji). Ręczny HTML na pustym etapie omijałby reguły klienta
        # i blokadę zgody RODO (brak `generated_document_id`).
        raise HTTPException(status_code=409, detail=NO_GENERATED_CV_MESSAGE)
    if csv.branded_status == "finalized":
        raise HTTPException(
            status_code=409,
            detail=(
                "CV jest zatwierdzone. Utwórz nową wersję, aby wprowadzić poprawki; "
                "dotychczasowe linki zachowają wcześniejszą treść."
            ),
        )

    cleaned = keep_rodo_clause(
        csv.branded_draft_html, sanitize_cv_html(payload.content_html)
    )
    if not cleaned.strip():
        # Pusty szkic zdejmował ochronę klauzuli RODO: następny zapis
        # z podmienioną klauzulą przechodził (audyt 13.10.2026). Jak przy
        # zatwierdzeniu i w edytorze generatora.
        raise HTTPException(status_code=422, detail="CV nie może być puste.")
    csv.branded_draft_html = cleaned
    action = "branded_cv_edited"
    details = {"length": len(csv.branded_draft_html)}
    csv.edit_revision += 1
    csv.branded_updated_at = datetime.now(timezone.utc)
    csv.branded_updated_by = current_user.id
    db.add(
        Activity(
            entity_type="candidate_stage_cv",
            entity_id=csv.id,
            action=action,
            user_id=current_user.id,
            details={"candidate_stage_id": stage_id, **details},
        )
    )
    await db.commit()
    await db.refresh(csv)

    updated_by_name = await db.scalar(
        select(User.email).where(User.id == current_user.id)
    )
    return _build_branded_response(csv, updated_by_name=updated_by_name)


@router.get(
    "/candidates/stages/{stage_id}/cv/branded/render-pdf",
    response_class=HTMLResponse,
)
async def render_branded_cv_for_print(
    stage_id: int,
    current_user: CandidateDocumentAccess,
    db: AsyncSession = Depends(get_db),
    intent: Optional[str] = None,
    surface: Optional[str] = None,
) -> HTMLResponse:
    """Wrap brandowane CV w printable HTML z auto window.print() — FE otwiera w
    nowej karcie i drukuje (Save as PDF)."""
    csv = await _load_csv_for_stage(db, stage_id, current_user, read_access=True)
    draft_html = csv.branded_draft_html
    if csv.branded_status == "none" or not draft_html:
        # Stary szablon wycofany (generator v3): etap bez CV nie ma czego
        # drukować — CV powstaje w generatorze.
        raise HTTPException(status_code=404, detail=NO_GENERATED_CV_MESSAGE)
    # Wydruk nie niesie obrazu zgody — przy wymogu zgody zablokowany (R7-X4-3).
    consent_gate.ensure_printable(await _generated_for_stage_cv(db, csv), csv)
    candidate = await db.scalar(
        select(Candidate).where(Candidate.id == csv.candidate_id)
    )
    label = (
        f"{candidate.name} {candidate.lastname}" if candidate else f"stage_{stage_id}"
    )
    await log_cv_download(
        db,
        intent=intent,
        surface=surface,
        entity_type="candidate_stage_cv",
        entity_id=csv.id,
        user=current_user,
        file_format="print",
        state="draft" if csv.branded_status == "draft" else "approved",
        version=csv.branded_version,
    )
    # M4 PR-04 (audyt P1.9): printable HTML przechodzi allowlist sanitizer —
    # authenticated flow otwiera blob text/html w nowej karcie.
    return HTMLResponse(content=_wrap_printable_cv(draft_html, stage_id, label))


_render_editor_docx = render_stage_editor_docx

DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


def draft_docx_filename(csv: CandidateStageCV) -> str:
    """Nazwa pliku Word szkicu CV etapu: „SZKIC_” + nazwa z reguły klienta."""
    return "SZKIC_" + (csv.branded_docx_filename or f"CV_v{csv.branded_version}.docx")


async def draft_docx_for_download(
    db: AsyncSession, csv: CandidateStageCV, content_html: str
) -> bytes:
    """Plik Word SZKICU CV etapu z podanej treści edytora. Bez commitu i bez
    wpisu pobrania — robi je wołający, dopiero gdy plik wychodzi.

    Wspólne dla „Pobierz” na ekranie (``preview-docx``) i pobrania kluczem
    API v1 (``integrations_v1/cv.py``), żeby oba dawały ten sam plik i tę
    samą odmowę: etap bez CV i CV zatwierdzone — 409, brak zrzutu zgody
    RODO — 409 ``consent_required``. Wołający sprawdził dostęp do etapu.
    """
    if csv.branded_status == "none":
        raise HTTPException(409, NO_GENERATED_CV_MESSAGE)
    if csv.branded_status != "draft":
        raise HTTPException(
            409, "Podgląd dotyczy szkicu. Pobierz zatwierdzoną wersję CV."
        )
    # DOCX renderuje się z obrazu zgody KOPII etapu (R7-X4-4).
    consent_gate.ensure_copy_downloadable(await _generated_for_stage_cv(db, csv), csv)
    docx, _ = await _render_editor_docx(csv, content_html)
    return docx


@router.post("/candidates/stages/{stage_id}/cv/branded/preview-docx")
async def preview_branded_docx(
    stage_id: int,
    payload: CVBrandedFinalize,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
    intent: Optional[str] = None,
    surface: Optional[str] = None,
) -> Response:
    """Render the current editor contents and frozen assets without approval."""
    csv = await _load_csv_for_stage(db, stage_id, current_user, lock=True)
    check_revision(csv, payload.expected_revision)
    docx = await draft_docx_for_download(db, csv, payload.content_html)
    await log_cv_download(
        db,
        intent=intent,
        surface=surface,
        entity_type="candidate_stage_cv",
        entity_id=csv.id,
        user=current_user,
        file_format="docx",
        state="draft",
        version=csv.branded_version,
    )
    return Response(
        content=docx,
        media_type=DOCX_MEDIA_TYPE,
        headers={
            "Content-Disposition": content_disposition_attachment(
                draft_docx_filename(csv)
            ),
            "Cache-Control": "private, no-store",
        },
    )


@router.post(
    "/candidates/stages/{stage_id}/cv/branded/finalize",
    response_model=CVBrandedFinalizeResponse,
)
async def finalize_branded_cv(
    stage_id: int,
    payload: CVBrandedFinalize,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> CVBrandedFinalizeResponse:
    """Snapshot brandowanego draftu → storage_service + status `draft → finalized`.

    Po finalize:
    * `branded_draft_html` zostaje w DB (ostatnia edytowalna wersja, do podglądu),
    * `branded_snapshot_path/filename/size` wskazuje na plik HTML w storage,
    * 409 przy próbie kolejnego PATCH — immutable.
    """
    csv = await _load_csv_for_stage(db, stage_id, current_user, lock=True)
    check_revision(csv, payload.expected_revision)
    if csv.branded_status == "none":
        # Stary szablon wycofany (generator v3): zatwierdzić można wyłącznie
        # CV z generatora, podpięte do etapu jako szkic.
        raise HTTPException(status_code=409, detail=NO_GENERATED_CV_MESSAGE)
    if csv.branded_status != "draft":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Branded CV is in status '{csv.branded_status}', "
                "expected 'draft' to finalize."
            ),
        )
    version, filename, size = await finalize_stage_cv(
        db, csv, payload.content_html, current_user.id
    )
    metadata = version.render_metadata
    await db.commit()
    await db.refresh(csv)

    from app.services.cv_approval_review import review_outcome

    review_status, review_findings = review_outcome(metadata)
    return CVBrandedFinalizeResponse(
        candidate_stage_id=csv.candidate_stage_id,
        edit_revision=csv.edit_revision or 0,
        version=csv.branded_version or 1,
        status=csv.branded_status,  # type: ignore[arg-type]
        snapshot_filename=filename,
        snapshot_size_bytes=size,
        document_version_id=version.id,
        content_review_status=review_status,
        content_review_findings=review_findings,
    )


async def _stage_job_and_cv(
    db: AsyncSession, stage_id: int
) -> tuple[int, Optional[CandidateStageCV]]:
    """Rekrutacja etapu i jego CV (albo ``None``) dla tras TYLKO DO ODCZYTU.

    Brak wiersza CV to stan, nie błąd (etapy z importu Traffita go nie mają),
    więc nie przez ``_load_csv_for_stage``. Zakresu rekrutacji ta funkcja NIE
    sprawdza — wołający robi to od razu (``ensure_job_read_access``), zanim
    cokolwiek z wyniku przeczyta.
    """
    row = (
        await db.execute(
            select(CandidateStage.job_id, CandidateStageCV)
            .select_from(CandidateStage)
            .outerjoin(
                CandidateStageCV,
                CandidateStageCV.candidate_stage_id == CandidateStage.id,
            )
            .where(CandidateStage.id == stage_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Stage nie znaleziony")
    return row[0], row[1]


@router.get(
    "/candidates/stages/{stage_id}/cv/branded/versions",
    response_model=CVVersionsResponse,
)
async def list_branded_cv_versions(
    stage_id: int,
    current_user: CandidateDocumentAccess,
    db: AsyncSession = Depends(get_db),
) -> CVVersionsResponse:
    """Historia wersji w edytorze CV: zatwierdzone wersje etapu, od najnowszej.

    Ta sama bramka co odczyt CV etapu; etap bez CV albo bez zatwierdzonej
    wersji to pusta lista, nie błąd. Trasa niczego nie zapisuje.
    """
    job_id, csv = await _stage_job_and_cv(db, stage_id)
    await ensure_job_read_access(db, current_user, job_id)
    if csv is None:
        return CVVersionsResponse(versions=[])
    return CVVersionsResponse(versions=await stage_versions(db, csv))


@router.get(
    "/candidates/stages/{stage_id}/cv/branded/versions/{version_number}",
    response_model=CVVersionContent,
)
async def get_branded_cv_version(
    stage_id: int,
    version_number: int,
    current_user: CandidateDocumentAccess,
    db: AsyncSession = Depends(get_db),
) -> CVVersionContent:
    """Treść jednej zatwierdzonej wersji CV — do podglądu i przywrócenia w edytorze.

    Przywrócenie robi edytor jedną cofalną zmianą, a utrwala je autozapis; ta
    trasa niczego nie zapisuje.
    """
    # Bramka jak przy `GET …/cv/branded`, które oddaje treść CV w tym samym
    # kształcie: odczyt dokumentów + odczyt TEJ rekrutacji. Blokada zgody RODO
    # pilnuje plików wychodzących do klienta (Word, wydruk, link), a treść
    # w edytorze widać i bez zrzutu zgody — pobranie Worda tej wersji dalej
    # idzie przez `…/versions/{n}/docx` z blokadą.
    job_id, csv = await _stage_job_and_cv(db, stage_id)
    await ensure_job_read_access(db, current_user, job_id)
    content = (
        await stage_version_content(db, csv, version_number)
        if csv is not None
        else None
    )
    if content is None:
        raise HTTPException(404, "Nie znaleziono zatwierdzonej wersji CV.")
    # Starsze wersje powstały przed dzisiejszym sanitizerem; edytor dostaje
    # treść w tej samej postaci, jaką przyjąłby przy zapisie.
    content["content_html"] = sanitize_cv_html(content["content_html"])
    return CVVersionContent(**content)


async def approved_version_for_download(
    db: AsyncSession, csv: CandidateStageCV, version_number: int
) -> CvDocumentVersion:
    """Zatwierdzona wersja CV etapu, której plik Word wolno wydać. Bez commitu
    i bez wpisu pobrania — robi je wołający, dopiero gdy plik wychodzi.

    Wspólne dla „Pobierz” na ekranie (``…/versions/{n}/docx``) i pobrania
    kluczem API v1 (``integrations_v1/cv.py``): brak wersji — 404, brak
    zrzutu zgody RODO w TEJ wersji — 409 ``consent_required``, wersja bez
    zamrożonego pliku Word — 409. Wołający sprawdził dostęp do etapu.
    """
    version = await db.scalar(
        select(CvDocumentVersion).where(
            CvDocumentVersion.candidate_stage_cv_id == csv.id,
            CvDocumentVersion.version == version_number,
        )
    )
    if version is None:
        raise HTTPException(404, "Nie znaleziono zatwierdzonej wersji CV.")
    consent_gate.ensure_copy_downloadable(
        await db.get(CvGeneratedDocument, version.generated_document_id)
        if version.generated_document_id
        else None,
        csv,
        version,
    )
    if not version.docx_content:
        raise HTTPException(
            409,
            "Ta historyczna wersja nie ma zatwierdzonego DOCX. Utwórz i zatwierdź nową wersję.",
        )
    return version


def approved_docx_headers(version: CvDocumentVersion) -> dict[str, str]:
    """Nagłówki pliku Word zatwierdzonej wersji (nazwa z reguły klienta)."""
    return {
        "Content-Disposition": content_disposition_attachment(
            version.docx_filename or "CV.docx"
        ),
        "ETag": f'"{version.docx_sha256}"',
        "X-CV-Version": str(version.version),
        "X-CV-Content-SHA256": version.content_sha256,
        "Cache-Control": "private, no-store",
    }


@router.get("/candidates/stages/{stage_id}/cv/branded/versions/{version_number}/docx")
async def download_approved_docx(
    stage_id: int,
    version_number: int,
    current_user: CandidateDocumentAccess,
    db: AsyncSession = Depends(get_db),
    intent: Optional[str] = None,
    surface: Optional[str] = None,
) -> Response:
    csv = await _load_csv_for_stage(db, stage_id, current_user, read_access=True)
    version = await approved_version_for_download(db, csv, version_number)
    await log_cv_download(
        db,
        intent=intent,
        surface=surface,
        entity_type="candidate_stage_cv",
        entity_id=csv.id,
        user=current_user,
        file_format="docx",
        state="approved",
        version=version.version,
    )
    return Response(
        content=version.docx_content,
        media_type=DOCX_MEDIA_TYPE,
        headers=approved_docx_headers(version),
    )


@router.post(
    "/candidates/stages/{stage_id}/cv/branded/new-draft",
    response_model=CVBrandedResponse,
)
async def new_branded_cv_draft(
    stage_id: int,
    payload: CVBrandedNewDraft,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> CVBrandedResponse:
    csv = await _load_csv_for_stage(db, stage_id, current_user, lock=True)
    check_revision(csv, payload.expected_revision)
    previous = await freeze_approved_version(db, csv)
    csv.branded_version += 1
    csv.edit_revision += 1
    csv.branded_status = "draft"
    csv.branded_updated_at = datetime.now(timezone.utc)
    csv.branded_updated_by = current_user.id
    csv.branded_finalized_at = None
    csv.branded_finalized_by = None
    csv.branded_snapshot_path = None
    csv.branded_snapshot_filename = None
    csv.branded_snapshot_size_bytes = None
    db.add(
        Activity(
            entity_type="candidate_stage_cv",
            entity_id=csv.id,
            action="branded_cv_new_version",
            user_id=current_user.id,
            details={
                "candidate_stage_id": stage_id,
                "previous_version_id": previous.id,
                "version": csv.branded_version,
            },
        )
    )
    await db.commit()
    return _build_branded_response(csv)


# ── Public share token (Faza 4 — auth side) ────────────────────────────────


_SHARE_PATH_PREFIX = "/cv/"


@router.post(
    "/candidates/stages/{stage_id}/cv/share-token",
    response_model=CVShareTokenResponse,
    status_code=201,
)
async def create_cv_share_token(
    stage_id: int,
    current_user: CandidateWriteAccess,
    expires_in_days: int = Query(14, ge=1, le=90),
    max_views: Optional[int] = Query(None, ge=1, le=1000),
    purpose: Optional[str] = Query(None, max_length=120),
    db: AsyncSession = Depends(get_db),
) -> CVShareTokenResponse:
    """Generuje token-link do brandowanego CV. Wymaga statusu `finalized`.

    M4 PR-04 (audyt P1.9, token v2): sekret NIE jest zapisywany — w DB ląduje
    wyłącznie SHA-256 (`token_sha256`), a PK dostaje nie-sekretny identyfikator
    `v2$<hex>` (revoke-key). Raw token zwracamy jeden raz. Domyślny TTL
    skrócony 30 → 14 dni (max 90); opcjonalny limit wyświetleń i purpose.
    """
    csv = await _load_csv_for_stage(db, stage_id, current_user, lock=True)
    if csv.branded_status != "finalized":
        raise HTTPException(
            status_code=409,
            detail=("Nie można udostępnić draftu — najpierw zfinalizuj brandowane CV."),
        )

    # Last line before the CV reaches the client. The assignment gate does not
    # cover pipelines created before this feature, nor a reason flagged
    # disqualifying after the fact.
    verdict = await veto_for_candidate_stage(db, candidate_stage_id=stage_id)
    if verdict is not None:
        raise HTTPException(
            status_code=409,
            detail=f"{verdict.as_polish_detail()} Nie wysyłaj mu ponownie tego CV.",
        )

    version = await freeze_approved_version(db, csv)
    from app.models.cv_generated_document import CvGeneratedDocument
    from app.services.cv_packages import require_ready

    generated = (
        await db.get(CvGeneratedDocument, csv.generated_document_id)
        if csv.generated_document_id
        else None
    )
    # Bez wiersza generatora (usunięty) wymóg zgody czytamy z kopii (R7-X4-1).
    consent_gate.ensure_copy_downloadable(generated, csv, version)
    package_versions = (
        await require_ready(db, generated, version.id) if generated else None
    )
    raw_token = secrets.token_urlsafe(36)
    revoke_key = f"v2${secrets.token_hex(16)}"
    token_digest = hashlib.sha256(raw_token.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)
    db.add(
        CVShareToken(
            token=revoke_key,
            token_sha256=token_digest,
            candidate_stage_cv_id=csv.id,
            document_version_id=version.id,
            package_versions=package_versions,
            created_by=current_user.id,
            expires_at=expires_at,
            max_views=max_views,
            purpose=purpose,
        )
    )
    db.add(
        Activity(
            entity_type="candidate_stage_cv",
            entity_id=csv.id,
            action="cv_share_created",
            user_id=current_user.id,
            details={
                "candidate_stage_id": stage_id,
                "expires_at": expires_at.isoformat(),
                "revoke_key": revoke_key,
                "max_views": max_views,
                "purpose": purpose,
            },
        )
    )
    await db.commit()

    return CVShareTokenResponse(
        token=raw_token,
        expires_at=expires_at,
        share_url_suffix=f"{_SHARE_PATH_PREFIX}{raw_token}",
        candidate_stage_cv_id=csv.id,
        revoke_key=revoke_key,
        max_views=max_views,
    )


def _token_list_item(row: CVShareToken) -> CVShareTokenListItem:
    is_v2 = row.token_sha256 is not None
    return CVShareTokenListItem(
        revoke_key=row.token,
        token_preview=(
            f"v2 · {row.token_sha256[:6]}…" if is_v2 else f"{row.token[:8]}…"
        ),
        is_v2=is_v2,
        created_at=row.created_at,
        created_by_name=(row.creator.name if row.creator else None),
        expires_at=row.expires_at,
        revoked=row.revoked,
        revoked_at=row.revoked_at,
        revoke_reason=row.revoke_reason,
        view_count=row.view_count or 0,
        max_views=row.max_views,
        last_viewed_at=row.last_viewed_at,
        purpose=row.purpose,
        # Legacy: raw w DB — URL odtwarzalny (i tak jest w obiegu).
        # v2: sekret nieodtwarzalny — None.
        share_url_suffix=(None if is_v2 else f"{_SHARE_PATH_PREFIX}{row.token}"),
    )


@router.get(
    "/candidates/stages/{stage_id}/cv/share-tokens",
    response_model=list[CVShareTokenListItem],
)
async def list_cv_share_tokens(
    stage_id: int,
    current_user: CandidateDocumentAccess,
    db: AsyncSession = Depends(get_db),
) -> list[CVShareTokenListItem]:
    """Lista linków (aktywnych i odwołanych) dla CV tego stage'a — bez
    sekretów. M4 PR-04: dotąd modal gubił token po zamknięciu i nie dało się
    odwołać wcześniejszych linków (audyt P1.9 dead-end)."""
    csv = await _load_csv_for_stage(db, stage_id, current_user, read_access=True)
    rows = (
        (
            await db.execute(
                select(CVShareToken)
                .options(selectinload(CVShareToken.creator))
                .where(CVShareToken.candidate_stage_cv_id == csv.id)
                .order_by(CVShareToken.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [_token_list_item(r) for r in rows]


async def _branded_cv_summary_for_pair(
    db: AsyncSession, candidate_id: int, job_id: int
) -> RecruitmentBrandedCvSummary:
    """CV firmowe pary (kandydat, rekrutacja): sfinalizowane wygrywa ze szkicem.

    Samo „najnowszy etap z CV firmowym" nie wystarcza: szkic założony
    pierwszą edycją na PÓŹNIEJSZYM etapie przykrywałby sfinalizowane CV
    wysłane klientowi (GET niczego nie zapisuje od audytu 22.09.2026). W obrębie
    tego samego statusu wygrywa najnowszy etap. Wołający sprawdził już dostęp
    do rekrutacji.
    """
    row = (
        await db.execute(
            select(
                CandidateStageCV.branded_status,
                CandidateStageCV.branded_finalized_at,
                CandidateStage.id,
                CandidateStage.stage,
                PipelineStageDef.name,
            )
            .join(
                CandidateStage,
                CandidateStage.id == CandidateStageCV.candidate_stage_id,
            )
            .outerjoin(
                PipelineStageDef,
                PipelineStageDef.id == CandidateStage.stage_def_id,
            )
            .where(
                CandidateStage.candidate_id == candidate_id,
                CandidateStage.job_id == job_id,
                CandidateStageCV.branded_status.in_(("draft", "finalized")),
            )
            .order_by(
                (CandidateStageCV.branded_status == "finalized").desc(),
                CandidateStage.moved_at.desc(),
                CandidateStage.id.desc(),
            )
            .limit(1)
        )
    ).first()
    if row is None:
        return RecruitmentBrandedCvSummary()
    status, finalized_at, stage_id, stage_enum, stage_def_name = row
    return RecruitmentBrandedCvSummary(
        status=status,
        stage_id=stage_id,
        stage_name=stage_def_name
        or getattr(stage_enum, "value", None)
        or str(stage_enum),
        finalized_at=finalized_at if status == "finalized" else None,
    )


@router.get(
    "/pipeline/candidates/{candidate_id}/jobs/{job_id}/cv-share-tokens",
    response_model=CVShareTokensForRecruitment,
)
async def list_cv_share_tokens_for_recruitment(
    candidate_id: int,
    job_id: int,
    current_user: CandidateDocumentAccess,
    db: AsyncSession = Depends(get_db),
) -> CVShareTokensForRecruitment:
    """Linki do CV ze WSZYSTKICH etapów pary (kandydat, rekrutacja) — bez sekretów.

    Odpowiedź niesie też ``branded_cv``: stan CV firmowego PARY, nie bieżącego
    etapu. Sfinalizowane CV leży na etapie sprzed ruchu, więc odznaka czytana
    per etap mówiła po „CV Wysłane" „brak".

    Link dla klienta leży na etapie SPRZED ruchu na „CV Wysłane" (ruch tworzy
    nowy ``CandidateStage`` bez dokumentu), więc lista per etap jest dla osoby
    na późniejszym etapie zwykle pusta, choć klient ma działający link.

    Bramka jest TA SAMA co w ``list_cv_share_tokens``: rola
    ``CandidateDocumentAccess`` + odczyt TEJ rekrutacji
    (``ensure_job_read_access``). Sprawdzana PRZED zapytaniem o etapy, żeby
    osoba spoza zespołu nie odróżniała „nie ma takiej pary" od „nie wolno".
    """
    await ensure_job_read_access(db, current_user, job_id)

    has_stage = await db.scalar(
        select(CandidateStage.id)
        .where(
            CandidateStage.candidate_id == candidate_id,
            CandidateStage.job_id == job_id,
        )
        .limit(1)
    )
    if has_stage is None:
        raise HTTPException(
            status_code=404, detail="Kandydat nie jest w tej rekrutacji"
        )

    rows = (
        await db.execute(
            select(
                CVShareToken,
                CandidateStage.id,
                CandidateStage.stage,
                PipelineStageDef.name,
            )
            .join(
                CandidateStageCV,
                CandidateStageCV.id == CVShareToken.candidate_stage_cv_id,
            )
            .join(
                CandidateStage,
                CandidateStage.id == CandidateStageCV.candidate_stage_id,
            )
            .outerjoin(
                PipelineStageDef,
                PipelineStageDef.id == CandidateStage.stage_def_id,
            )
            .options(selectinload(CVShareToken.creator))
            .where(
                CandidateStage.candidate_id == candidate_id,
                CandidateStage.job_id == job_id,
            )
            .order_by(CVShareToken.created_at.desc(), CVShareToken.token)
        )
    ).all()

    items: list[CVShareTokenJobListItem] = []
    for token_row, stage_id, stage_enum, stage_def_name in rows:
        stage_name = (
            stage_def_name or getattr(stage_enum, "value", None) or str(stage_enum)
        )
        base = _token_list_item(token_row).model_dump()
        if not base["is_v2"]:
            # Link legacy trzyma SEKRET w kluczu głównym — lista per etap
            # oddaje go jako `revoke_key`/`share_url_suffix`, bo tam służy do
            # odwołania. Ten widok jest tylko do odczytu, więc sekretu nie
            # niesie wcale: identyfikator to skrót, adresu nie ma.
            digest = hashlib.sha256(token_row.token.encode()).hexdigest()
            base["revoke_key"] = f"legacy${digest[:16]}"
            base["token_preview"] = f"legacy · {digest[:6]}…"
            base["share_url_suffix"] = None
        items.append(
            CVShareTokenJobListItem(**base, stage_id=stage_id, stage_name=stage_name)
        )
    return CVShareTokensForRecruitment(
        items=items,
        branded_cv=await _branded_cv_summary_for_pair(db, candidate_id, job_id),
    )


@router.delete("/candidates/stages/cv/share-token/{token}")
async def revoke_cv_share_token(
    token: str,
    current_user: CandidateWriteAccess,
    reason: Optional[str] = Query(None, max_length=255),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Odwołaj share token. Idempotent.

    Przyjmuje revoke-key (`v2$...`), legacy raw token (BC) albo raw token v2
    (lookup po hashu — okładka na wypadek, gdy caller ma tylko link).
    """
    digest = hashlib.sha256(token.encode()).hexdigest()
    row = await db.scalar(
        select(CVShareToken).where(
            (CVShareToken.token == token) | (CVShareToken.token_sha256 == digest)
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Token nie znaleziony")

    # Resource scope — ta trasa jako jedyna w routerze adresuje zasób tokenem,
    # nie `stage_id`, więc nie przechodzi przez `_load_csv_for_stage`.
    # Rekrutację wyprowadzamy z łańcucha token → CandidateStageCV → CandidateStage.
    # Sprawdzenie idzie PRZED wyjściem po `already_revoked`, żeby ta gałąź nie
    # potwierdzała obcemu użytkownikowi istnienia i stanu cudzego tokenu.
    job_id = await db.scalar(
        select(CandidateStage.job_id)
        .select_from(CandidateStageCV)
        .join(CandidateStage, CandidateStage.id == CandidateStageCV.candidate_stage_id)
        .where(CandidateStageCV.id == row.candidate_stage_cv_id)
    )
    if job_id is None:
        raise HTTPException(status_code=404, detail="Token nie znaleziony")
    await ensure_job_membership(db, current_user, job_id)

    if row.revoked:
        return {"status": "already_revoked", "token": row.token}

    await db.execute(
        update(CVShareToken)
        .where(CVShareToken.token == row.token)
        .values(
            revoked=True,
            revoked_at=datetime.now(timezone.utc),
            revoked_by=current_user.id,
            revoke_reason=reason,
        )
    )
    db.add(
        Activity(
            entity_type="candidate_stage_cv",
            entity_id=row.candidate_stage_cv_id,
            action="cv_share_revoked",
            user_id=current_user.id,
            details={"revoke_key": row.token, "reason": reason},
        )
    )
    await db.commit()
    return {"status": "revoked", "token": row.token}


@router.delete("/candidates/stages/{stage_id}/cv/share-tokens")
async def revoke_all_cv_share_tokens(
    stage_id: int,
    current_user: CandidateWriteAccess,
    reason: Optional[str] = Query(None, max_length=255),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Odwołaj WSZYSTKIE aktywne linki CV tego stage'a (M4 PR-04)."""
    csv = await _load_csv_for_stage(db, stage_id, current_user)
    result = await db.execute(
        update(CVShareToken)
        .where(
            CVShareToken.candidate_stage_cv_id == csv.id,
            CVShareToken.revoked.is_(False),
        )
        .values(
            revoked=True,
            revoked_at=datetime.now(timezone.utc),
            revoked_by=current_user.id,
            revoke_reason=reason,
        )
    )
    db.add(
        Activity(
            entity_type="candidate_stage_cv",
            entity_id=csv.id,
            action="cv_share_revoked_all",
            user_id=current_user.id,
            details={"count": result.rowcount or 0, "reason": reason},
        )
    )
    await db.commit()
    return {"status": "revoked_all", "count": result.rowcount or 0}


@router.post("/candidates/stages/{stage_id}/cv/branded/review")
async def start_stage_cv_review(
    stage_id: int,
    payload: CVBrandedReview,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
):
    from app.services.cv_approval_queue import enqueue_review

    draft = await _load_csv_for_stage(db, stage_id, current_user, lock=True)
    if draft.branded_status == "none":
        # Stary szablon wycofany (generator v3): kontrola dotyczy CV
        # z generatora podpiętego do etapu jako szkic.
        raise HTTPException(409, NO_GENERATED_CV_MESSAGE)
    result = await enqueue_review(db, draft, payload, current_user.id)
    await db.commit()
    return result


@router.get("/candidates/stages/{stage_id}/cv/branded/review/{review_id}")
async def get_stage_cv_review(
    stage_id: int,
    review_id: int,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
):
    from app.services.cv_approval_queue import review_state

    draft = await _load_csv_for_stage(db, stage_id, current_user)
    result = await review_state(db, draft, review_id, current_user.id)
    await db.commit()
    return result


@router.delete("/candidates/stages/{stage_id}/cv/branded/review/{review_id}")
async def cancel_stage_cv_review(
    stage_id: int,
    review_id: int,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
):
    from app.services.cv_approval_queue import review_state

    draft = await _load_csv_for_stage(db, stage_id, current_user, lock=True)
    result = await review_state(db, draft, review_id, current_user.id, cancel=True)
    await db.commit()
    return result
