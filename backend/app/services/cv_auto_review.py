"""„Auto-CV czeka na przegląd" — JEDNA definicja dla listy generatora i tablicy.

Dokument zakolejkowany przez system po ruchu na „Zweryfikowany"
(``origin="auto"``) wymaga przeglądu, dopóki człowiek go nie zatwierdził
istniejącą ścieżką: nie ma zatwierdzonej wersji z tej generacji
(``cv_document_versions``) i żaden etap nie ma go jako ZATWIERDZONEGO
brandowanego CV. Automat nigdy nie zatwierdza sam. Odrzucone w karcie
„CV do klienta” (audyt 22.10, F64) nie czeka na przegląd.
"""

from sqlalchemy import and_, exists, or_, select

from app.models.candidate_stage_cv import CandidateStageCV
from app.models.cv_document_version import CvDocumentVersion
from app.models.cv_generated_document import (
    CvGeneratedDocument,
    not_discarded_clause,
)


def needs_review_clause():
    approved_version = exists(
        select(CvDocumentVersion.id).where(
            CvDocumentVersion.generated_document_id == CvGeneratedDocument.id
        )
    )
    finalized_on_stage = exists(
        select(CandidateStageCV.id).where(
            CandidateStageCV.generated_document_id == CvGeneratedDocument.id,
            CandidateStageCV.branded_status == "finalized",
        )
    )
    return and_(
        CvGeneratedDocument.origin == "auto",
        ~approved_version,
        ~finalized_on_stage,
        not_discarded_clause(),
    )


async def job_stages_with_ready_auto_cv(db, job_id: int) -> set[int]:
    """Etapy rekrutacji z GOTOWYM auto-CV czekającym na przegląd.

    Jedno zapytanie na tablicę (``auto_cv_ready`` na karcie) — bez N+1.
    """
    rows = await db.scalars(
        select(CvGeneratedDocument.stage_id)
        .where(
            CvGeneratedDocument.job_id == job_id,
            CvGeneratedDocument.stage_id.is_not(None),
            CvGeneratedDocument.status == "ready",
            needs_review_clause(),
        )
        .distinct()
    )
    return {int(stage_id) for stage_id in rows.all()}


async def job_stages_auto_cv(
    db, job_id: int, *, with_processing: bool
) -> tuple[set[int], set[int]]:
    """Tablica: ``(etapy z gotowym auto-CV do przeglądu, etapy, dla których
    automat właśnie generuje CV)`` — jedno zapytanie zamiast dwóch.

    Gotowe = ta sama reguła co :func:`job_stages_with_ready_auto_cv`;
    w przygotowaniu = ``origin="auto"`` i ``status="processing"`` (zadanie
    przerwane utratą wykonawcy ``recovery_loop`` przestawia na ``failed``).
    ``with_processing=False`` pomija drugi stan (pusty zbiór).
    """
    ready = and_(CvGeneratedDocument.status == "ready", needs_review_clause())
    processing = and_(
        CvGeneratedDocument.origin == "auto",
        CvGeneratedDocument.status == "processing",
    )
    rows = await db.execute(
        select(CvGeneratedDocument.stage_id, CvGeneratedDocument.status)
        .where(
            CvGeneratedDocument.job_id == job_id,
            CvGeneratedDocument.stage_id.is_not(None),
            or_(ready, processing) if with_processing else ready,
        )
        .distinct()
    )
    ready_ids: set[int] = set()
    processing_ids: set[int] = set()
    for stage_id, status in rows.all():
        (ready_ids if status == "ready" else processing_ids).add(int(stage_id))
    return ready_ids, processing_ids
