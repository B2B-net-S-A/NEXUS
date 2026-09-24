"""Logika tworzenia / odświeżania snapshotu oryginalnego CV per CandidateStage.

Główny invariant: każdy `CandidateStage` musi mieć dokładnie 1 wpis w
`candidate_stage_cvs`. Wszystkie miejsca tworzenia stage'a (pipeline.move,
pipeline_templates, recommendations.assign, public_share apply via invite)
wołają `create_original_cv_snapshot()` po `db.add(stage) + flush`.

Snapshot jest **niemutowalny** w polu `original_*` (poza explicit refresh
przez recruitera). Późniejsze zmiany `Candidate.cv_file_content` NIE wpływają
na snapshot — to jest the-feature, rozwiązuje pain point z Traffit.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.printable_html import printable_document
from app.services.html_sanitizer import sanitize_cv_html
from app.core.scheduling import business_today
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.recruitment_pipeline import CandidateStage
from app.services.cv_source import get_current_cv

logger = logging.getLogger(__name__)


# ── Snapshot jako wskaźnik do object storage (audyt 22.09 r2, PROD-02) ──────
#
# `original_cv_content` (BYTEA) zajmował 2,35 GB — 28% bazy — przy 8947
# wierszach i 3696 unikalnych plikach: jedno konto dodało w kilka dni 8752
# osób do 213 rekrutacji i każda para dostała WŁASNĄ kopię bajtów w bazie
# (i w każdym nocnym dumpie). Teraz snapshot to kopia w object storage pod
# kluczem `stage-cv/<candidate_id>/<sha256>`:
#
# * KOPIA, nie wskaźnik na dokument kandydata — dokument bywa usuwany albo
#   podmieniany, a snapshot jest niemutowalny z definicji;
# * klucz per KANDYDAT i treść — ta sama osoba w 50 rekrutacjach to jeden
#   obiekt, a usunięcie kandydata (RODO) może skasować wszystkie jego klucze
#   bez ryzyka, że ten sam obiekt trzyma snapshot innej osoby;
# * storage nieskonfigurowany albo niedostępny → bajty w bazie jak dotąd
#   (fail-soft: utworzenie etapu nie może paść na storage).

SNAPSHOT_KEY_PREFIX = "stage-cv"


def snapshot_storage_key(candidate_id: int, sha256: str) -> str:
    return f"{SNAPSHOT_KEY_PREFIX}/{int(candidate_id)}/{sha256}"


async def _store_snapshot(
    candidate_id: int, content: bytes, filename: Optional[str]
) -> tuple[Optional[str], str]:
    """(klucz w storage albo None, sha256). None = trzymaj bajty w bazie."""
    from app.services import object_storage

    digest = hashlib.sha256(content).hexdigest()
    if not object_storage.is_available():
        return None, digest
    key = snapshot_storage_key(candidate_id, digest)
    try:
        await run_in_threadpool(
            object_storage.upload_cv, content, filename or "cv", storage_key=key
        )
    except Exception:  # noqa: BLE001 — snapshot nie może blokować etapu
        logger.exception(
            "Snapshot CV: upload do storage nieudany (candidate=%s) — bajty w bazie",
            candidate_id,
        )
        return None, digest
    return key, digest


def snapshot_exists(csv_row: CandidateStageCV) -> bool:
    return (
        csv_row.original_cv_content is not None
        or csv_row.original_cv_storage_key is not None
    )


async def load_original_cv_bytes(csv_row: CandidateStageCV) -> Optional[bytes]:
    """Bajty snapshotu — z bazy (stare wiersze) albo z object storage."""
    if csv_row.original_cv_content is not None:
        return bytes(csv_row.original_cv_content)
    if csv_row.original_cv_storage_key:
        from app.services import object_storage

        return await run_in_threadpool(
            object_storage.download_cv, csv_row.original_cv_storage_key
        )
    return None


async def snapshot_keys_for_candidate(db: AsyncSession, candidate_id: int) -> list[str]:
    """Klucze snapshotów kandydata — do kasowania razem z nim (RODO).

    Klucz zawiera `candidate_id`, więc żaden inny kandydat go nie współdzieli.
    """
    rows = await db.scalars(
        select(CandidateStageCV.original_cv_storage_key)
        .where(
            CandidateStageCV.candidate_id == candidate_id,
            CandidateStageCV.original_cv_storage_key.is_not(None),
        )
        .distinct()
    )
    return [k for k in rows.all() if k]


async def create_original_cv_snapshot(
    db: AsyncSession,
    stage: CandidateStage,
    *,
    source: str = "auto_create",
) -> CandidateStageCV:
    """Idempotentnie utwórz `CandidateStageCV` z migawką CV kandydata.

    * Jeśli row istnieje (UNIQUE catch lub pre-check) → zwróć istniejący (no-op).
    * Jeśli `Candidate.cv_file_content is None` → row nadal tworzony, ale
      `original_cv_*` zostaje NULL (UI pokazuje "Brak CV w momencie zgłoszenia").
    * Aktywność: `Activity(entity_type="candidate_stage_cv", action="snapshot_created")`.

    Wymaga że `stage.id` jest już ustawione (po `db.flush()` w callsite).
    """
    if stage.id is None:
        raise RuntimeError(
            "create_original_cv_snapshot: stage.id is None — caller must "
            "db.flush() the CandidateStage first."
        )

    existing = await db.scalar(
        select(CandidateStageCV).where(CandidateStageCV.candidate_stage_id == stage.id)
    )
    if existing is not None:
        return existing

    candidate = await db.scalar(
        select(Candidate).where(Candidate.id == stage.candidate_id)
    )
    if candidate is None:  # defensywnie — FK constraint już to gwarantuje
        raise RuntimeError(
            f"Candidate {stage.candidate_id} missing for stage {stage.id}"
        )

    # Po migracji CV do Object Storage legacy `cv_file_content` jest NULL u
    # wszystkich kandydatów — bieżące CV rozwiązujemy przez cv_source
    # (CandidateDocument/storage → Candidate.cv_storage_key → legacy BYTEA).
    # Fail-soft: błąd pobrania nie może zablokować utworzenia stage'a.
    try:
        current = await get_current_cv(db, candidate)
    except Exception:  # noqa: BLE001
        logger.exception(
            "Snapshot CV: get_current_cv failed (candidate=%s, stage=%s) — "
            "tworzę pusty snapshot",
            candidate.id,
            stage.id,
        )
        current = None

    has_cv = current is not None
    storage_key: Optional[str] = None
    digest: Optional[str] = None
    if current is not None:
        storage_key, digest = await _store_snapshot(
            stage.candidate_id, current.content, current.filename
        )
    csv_row = CandidateStageCV(
        candidate_stage_id=stage.id,
        candidate_id=stage.candidate_id,
        job_id=stage.job_id,
        original_cv_filename=current.filename if current else None,
        original_cv_content=(
            current.content if current is not None and storage_key is None else None
        ),
        original_cv_storage_key=storage_key,
        original_cv_sha256=digest,
        original_cv_language=current.language if current else None,
        original_snapshot_at=datetime.now(tz=timezone.utc) if has_cv else None,
        original_snapshot_source=source if has_cv else None,
    )
    # SAVEPOINT: wstawiamy snapshot w zagnieżdżonej transakcji. Jeśli równoległy
    # create_stage zdążył wstawić snapshot dla tego samego stage_id (UNIQUE
    # łapie), rollback SAVEPOINT-u wycofuje TYLKO ten INSERT — transakcja
    # wołającego (nowy CandidateStage + reszta batcha w np. proposals_bulk)
    # PRZEŻYWA. NIE wolno tu robić `db.rollback()` na współdzielonej sesji: to
    # porzuciłoby całą operację biznesową wołającego (M3-TX-01 — pomocniczy
    # writer nie posiada transakcji requestu). Wzór z autenti/webhook_handler.py.
    try:
        async with db.begin_nested():
            db.add(csv_row)
            await db.flush()
    except IntegrityError:
        again = await db.scalar(
            select(CandidateStageCV).where(
                CandidateStageCV.candidate_stage_id == stage.id
            )
        )
        if again is None:  # paranoiczne — jeśli to się wydarzy, popsuło się DB
            raise
        return again

    db.add(
        Activity(
            entity_type="candidate_stage_cv",
            entity_id=csv_row.id,
            action="snapshot_created",
            details={
                "candidate_stage_id": stage.id,
                "candidate_id": stage.candidate_id,
                "job_id": stage.job_id,
                "has_snapshot": has_cv,
                "filename": current.filename if current else None,
                "cv_source": current.source if current else None,
                "source": source,
            },
            user_id=stage.moved_by,
        )
    )
    await db.flush()
    logger.info(
        "Snapshot CV stworzony stage=%s has_cv=%s source=%s",
        stage.id,
        has_cv,
        source,
    )
    return csv_row


async def refresh_original_cv_snapshot(
    db: AsyncSession,
    stage_id: int,
    *,
    user_id: Optional[int],
) -> CandidateStageCV:
    """Manual refresh przez rekrutera (button "Aktualizuj snapshot z bieżącego").

    Nadpisuje `original_*` aktualną zawartością `Candidate.cv_*`. Loguje stary
    filename/timestamp w `Activity.details` — audit trail dla "co było w
    snapshot przed odświeżeniem".

    Raises:
      LookupError — gdy CandidateStageCV dla stage_id nie istnieje.
      ValueError  — gdy kandydat aktualnie nie ma CV (nie ma czego odświeżać).
    """
    csv_row = await db.scalar(
        select(CandidateStageCV).where(CandidateStageCV.candidate_stage_id == stage_id)
    )
    if csv_row is None:
        raise LookupError(
            f"CandidateStageCV for stage_id={stage_id} not found — "
            "create_original_cv_snapshot() should have run when stage was created."
        )

    candidate = await db.scalar(
        select(Candidate).where(Candidate.id == csv_row.candidate_id)
    )
    current = await get_current_cv(db, candidate) if candidate is not None else None
    if current is None:
        raise ValueError(
            f"Candidate {csv_row.candidate_id} has no current CV to copy — "
            "upload CV first."
        )

    old_filename = csv_row.original_cv_filename
    old_at = csv_row.original_snapshot_at

    storage_key, digest = await _store_snapshot(
        csv_row.candidate_id, current.content, current.filename
    )
    csv_row.original_cv_filename = current.filename
    csv_row.original_cv_content = current.content if storage_key is None else None
    csv_row.original_cv_storage_key = storage_key
    csv_row.original_cv_sha256 = digest
    csv_row.original_cv_language = current.language
    csv_row.original_snapshot_at = datetime.now(tz=timezone.utc)
    csv_row.original_snapshot_source = "manual_refresh"
    await db.flush()

    db.add(
        Activity(
            entity_type="candidate_stage_cv",
            entity_id=csv_row.id,
            action="snapshot_refreshed",
            details={
                "candidate_stage_id": stage_id,
                "old_filename": old_filename,
                "new_filename": current.filename,
                "cv_source": current.source,
                "old_at": old_at.isoformat() if old_at else None,
            },
            user_id=user_id,
        )
    )
    await db.flush()
    logger.info(
        "Snapshot CV odświeżony stage=%s old=%s new=%s (source=%s)",
        stage_id,
        old_filename,
        current.filename,
        current.source,
    )
    return csv_row


# ── Zatwierdzenie brandowanego CV etapu (wyjęte z handlera, generator v3) ────
#
# Jedna ścieżka dla przycisku „Zatwierdź" (`POST …/cv/branded/finalize`) i dla
# ponownego zatwierdzenia po dołączeniu zgody RODO (`cv_consent_attach`).
# Wołający trzyma blokadę wiersza i sprawdził rewizję oraz stan szkicu.


def wrap_printable_cv(body_html: str, stage_id: int, candidate_label: str) -> str:
    """Printable wrapper z auto-print — wspólna otoczka z CSP w <meta>.

    ``candidate_label`` to imię i nazwisko z formularza kariery: escapuje je
    ``printable_document``, a treść idzie przez allowlistę (także przy
    snapshotcie, który otwiera się jako blob pod originem aplikacji).
    """
    return printable_document(
        sanitize_cv_html(body_html),
        f"CV — {candidate_label} (rekrutacja #{stage_id})",
    )


async def render_stage_editor_docx(csv, content_html: str) -> tuple[bytes, bytes]:
    """DOCX z treści edytora i ZAMROŻONYCH zasobów etapu (szablon, zgoda)."""
    from fastapi import HTTPException

    from app.services.cv_approved_docx import ApprovedDocxError, render_approved_docx
    from app.services.cv_document_assets import default_template
    from app.services.html_sanitizer import sanitize_cv_html

    template = csv.branded_template_content or await run_in_threadpool(default_template)
    try:
        docx = await run_in_threadpool(
            render_approved_docx,
            sanitize_cv_html(content_html),
            template,
            consent=csv.branded_consent_content,
            language=csv.branded_language or "pl",
        )
    except ApprovedDocxError as error:
        raise HTTPException(422, str(error)) from error
    return docx, template


def branded_cv_filename(candidate_label: str, version: int) -> str:
    """Nazwa pliku zatwierdzonego CV z datą w kalendarzu firmy (Europe/Warsaw)."""
    return f"cv_brandowane_{candidate_label}_v{version}_{business_today().isoformat()}.html"


async def finalize_stage_cv(
    db: AsyncSession,
    csv: CandidateStageCV,
    content_html: str,
    user_id: int,
    *,
    review_override: Optional[dict] = None,
    activity_details: Optional[dict] = None,
):
    """Szkic → zatwierdzona wersja (DOCX z zamrożonych zasobów). Bez commitu.

    ``review_override`` (wyłącznie ponowne zatwierdzenie po dołączeniu zgody,
    gdy treść jest bajt w bajt ta sama co w zatwierdzonej wersji): zapis
    poprzedniej kontroli treści zamiast nowej — BEZ wywołania AI. Treść się
    nie zmieniła, zmienił się tylko obraz zgody pod nią.

    Zwraca ``(version, snapshot_filename, snapshot_size)``.
    """
    from io import BytesIO

    from fastapi import HTTPException

    from app.services import storage_service
    from app.services.cv_approval_provenance import approval_provenance
    from app.services.cv_approved_docx import RENDERER_VERSION
    from app.services.cv_document_versions import freeze_approved_version
    from app.services.cv_version_map_jobs import schedule_approved_map
    from app.services.html_sanitizer import sanitize_cv_html

    stage_id = csv.candidate_stage_id
    csv.branded_draft_html = sanitize_cv_html(content_html)
    if not csv.branded_draft_html.strip():
        raise HTTPException(
            status_code=422,
            detail="Brandowane CV jest puste — wygeneruj treść przed finalize.",
        )

    candidate = await db.scalar(
        select(Candidate).where(Candidate.id == csv.candidate_id)
    )
    candidate_label = (
        f"{candidate.name}_{candidate.lastname}".replace(" ", "_")
        if candidate
        else f"stage_{stage_id}"
    )
    filename = branded_cv_filename(candidate_label, csv.branded_version)

    # Render the exact submitted/sanitized content once, before approval. The
    # stored bytes are subsequently downloaded without accessing live sources.
    docx, template = await render_stage_editor_docx(csv, csv.branded_draft_html)
    if review_override is not None:
        content_review = review_override
    else:
        from app.services.cv_approval_review import review_for_approval

        content_review = await review_for_approval(
            db, csv, csv.branded_draft_html, user_id
        )

    docx_filename = (
        csv.branded_docx_filename or filename.removesuffix(".html") + ".docx"
    )
    metadata = {
        **(csv.branded_render_metadata or {}),
        **approval_provenance(csv.branded_draft_html, csv.branded_render_metadata),
        "content_review": content_review,
        "requires_content_review": False,
        "renderer_version": RENDERER_VERSION,
        "template_sha256": hashlib.sha256(template).hexdigest(),
        "consent_sha256": hashlib.sha256(csv.branded_consent_content).hexdigest()
        if csv.branded_consent_content
        else None,
    }
    snapshot_html = wrap_printable_cv(csv.branded_draft_html, stage_id, candidate_label)
    blob = snapshot_html.encode("utf-8")
    relative_path, size = storage_service.save_branded_cv(
        candidate_stage_id=stage_id,
        upload_filename=filename,
        source=BytesIO(blob),
    )

    csv.edit_revision += 1
    csv.branded_updated_at = datetime.now(timezone.utc)
    csv.branded_updated_by = user_id
    csv.branded_status = "finalized"
    csv.branded_finalized_at = datetime.now(timezone.utc)
    csv.branded_finalized_by = user_id
    csv.branded_snapshot_path = relative_path
    csv.branded_snapshot_filename = filename
    csv.branded_snapshot_size_bytes = size

    csv.branded_docx_filename = docx_filename
    csv.branded_template_content = template
    csv.branded_render_metadata = metadata
    version = await freeze_approved_version(
        db,
        csv,
        docx_content=docx,
        docx_filename=docx_filename,
        render_metadata=metadata,
    )
    await schedule_approved_map(db, version, user_id)
    db.add(
        Activity(
            entity_type="candidate_stage_cv",
            entity_id=csv.id,
            action="branded_cv_finalized",
            user_id=user_id,
            details={
                "candidate_stage_id": stage_id,
                "snapshot_filename": filename,
                "size_bytes": size,
                "document_version_id": version.id,
                "version": version.version,
                "content_sha256": version.content_sha256,
                **(activity_details or {}),
            },
        )
    )
    return version, filename, size
