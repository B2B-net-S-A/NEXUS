"""Jedna ścieżka po odczycie CV — dla każdego wejścia, które zapisuje profil z pliku.

Do 17.09.2026 sześć miejsc wołało `_apply_cv_enrichment` i każde robiło po nim
co innego: upload odświeżał wektor, ale nie kategorię; „Odśwież z CV” kategorię,
ale nie wektor; załącznik z maila ani jednego, ani drugiego. Ten moduł jest jedyną
kolejnością kroków:

    pola profilu → języki → indeks technologii → kategoria kompetencji
    → wektor (outbox albo inline) → unieważnienie cache wyników
    → zgłoszenie do auto-dopasowania z otwartymi rekrutacjami

Nie commituje — wołający decyduje o granicy transakcji. Kroki po zapisie pól
są dodatkami: awaria któregokolwiek zostawia ślad w logu, a profil i tak się
zapisuje. Pilnuje tego `tests/test_cv_ingest_service.py` (także skan AST, że
nikt poza tym modułem nie woła `_apply_cv_enrichment`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.services.cv_enrichment import CvWritePolicy, _apply_cv_enrichment

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestOutcome:
    companies_written: int
    skill_usage_rows: int
    embedded: bool
    auto_match_queued: bool


async def assign_primary_cc_if_empty(candidate: Candidate, db: AsyncSession) -> None:
    """Klasyfikacja do kategorii kompetencji, tylko gdy kandydat jej nie ma.

    `overwrite=False` zachowuje ręcznie wybrane kategorie. Kategoria to
    wzbogacenie, nie warunek zapisu — błąd jest logowany i połykany.
    """
    try:
        from app.services.candidate_cc_assignment import apply_candidate_cc_scores
        from app.services.cc_classifier import classify_candidate_to_cc

        scores = await classify_candidate_to_cc(candidate, db)
        summary = await apply_candidate_cc_scores(
            candidate, scores, db, overwrite=False
        )
        if summary:
            logger.info(
                "[cv_cc] auto-assigned CC candidate=%s primary=%s score=%.3f "
                "secondary=%s",
                candidate.id,
                summary["primary"],
                summary["primary_score"],
                summary["secondary"],
            )
    except Exception as exc:  # noqa: BLE001 — wzbogacenie, nie warunek
        logger.warning("[cv_cc] classify failed candidate=%s: %s", candidate.id, exc)


async def finish_cv_ingest(
    db: AsyncSession,
    *,
    candidate: Candidate,
    parsed: dict[str, Any],
    source_document_id: Optional[int],
    source_hash: Optional[str],
    policy: CvWritePolicy,
    trigger: str,
    language_source_ref: Optional[str] = None,
) -> IngestOutcome:
    """Zapisz odczyt CV do profilu i uruchom wszystko, co z niego wynika."""
    from app.services.auto_match_outbox import (
        auto_match_enabled,
        candidate_revision,
        enqueue_candidate,
    )
    from app.services.candidate_language_writer import (
        sync_candidate_languages_from_source,
    )
    from app.services.index_outbox_service import schedule_or_embed_candidate
    from app.services.match_score_cache import mark_stale_for_candidate
    from app.services.profile_projection import replace_skill_usage

    written = _apply_cv_enrichment(
        candidate,
        parsed,
        source_document_id=source_document_id,
        source_hash=source_hash,
        policy=policy,
    )
    if parsed.get("languages"):
        await sync_candidate_languages_from_source(
            db,
            candidate_id=candidate.id,
            raw_languages=parsed["languages"],
            provenance="cv",
            source_ref=language_source_ref
            or source_hash
            or (
                f"document:{source_document_id}"
                if source_document_id is not None
                else f"legacy-cv:{candidate.id}"
            ),
        )
    await db.flush()

    usage_rows = 0
    try:
        async with db.begin_nested():
            usage_rows = await replace_skill_usage(db, candidate)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[cv_ingest] skill usage index failed candidate=%s: %s", candidate.id, exc
        )

    # Wektor PRZED kategorią: klasyfikator czyta aktualny profil, a przy
    # wyłączonym outboxie wektor liczy się tu inline.
    embedded = False
    try:
        async with db.begin_nested():
            embedded = bool(await schedule_or_embed_candidate(candidate.id, db))
    except Exception as exc:  # noqa: BLE001 — wektor dogoni reconciler
        logger.warning("[cv_ingest] embed failed candidate=%s: %s", candidate.id, exc)

    # Każdy dodatek w SAVEPOINCIE: błąd bazy w jednym z nich nie może zatruć
    # sesji, w której leży zapis profilu — commit wołającego by go zgubił.
    try:
        async with db.begin_nested():
            await assign_primary_cc_if_empty(candidate, db)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[cv_ingest] CC savepoint failed candidate=%s: %s", candidate.id, exc
        )

    try:
        async with db.begin_nested():
            await mark_stale_for_candidate(db, candidate.id)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[cv_ingest] cache invalidation failed candidate=%s: %s", candidate.id, exc
        )

    queued = auto_match_enabled()
    try:
        await enqueue_candidate(
            db,
            candidate_id=candidate.id,
            trigger=trigger,
            profile_revision=candidate_revision(candidate),
        )
    except Exception as exc:  # noqa: BLE001
        queued = False
        logger.warning(
            "[cv_ingest] auto-match enqueue failed candidate=%s: %s", candidate.id, exc
        )

    logger.info(
        "[cv_ingest] candidate=%s trigger=%s source=%s companies=%d skills_idx=%d "
        "embedded=%s auto_match=%s",
        candidate.id,
        trigger,
        parsed.get("_source"),
        written,
        usage_rows,
        embedded,
        queued,
    )
    return IngestOutcome(
        companies_written=written,
        skill_usage_rows=usage_rows,
        embedded=embedded,
        auto_match_queued=queued,
    )
