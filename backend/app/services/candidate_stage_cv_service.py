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

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.recruitment_pipeline import CandidateStage
from app.services.cv_source import get_current_cv

logger = logging.getLogger(__name__)


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
    csv_row = CandidateStageCV(
        candidate_stage_id=stage.id,
        candidate_id=stage.candidate_id,
        job_id=stage.job_id,
        original_cv_filename=current.filename if current else None,
        original_cv_content=current.content if current else None,
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

    csv_row.original_cv_filename = current.filename
    csv_row.original_cv_content = current.content
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
