"""„Auto-CV czeka na przegląd" — JEDNA definicja dla listy generatora i tablicy.

Dokument zakolejkowany przez system po ruchu na „Zweryfikowany"
(``origin="auto"``) wymaga przeglądu, dopóki człowiek go nie zatwierdził
istniejącą ścieżką: nie ma zatwierdzonej wersji z tej generacji
(``cv_document_versions``) i żaden etap nie ma go jako ZATWIERDZONEGO
brandowanego CV. Automat nigdy nie zatwierdza sam.
"""

from sqlalchemy import and_, exists, select

from app.models.candidate_stage_cv import CandidateStageCV
from app.models.cv_document_version import CvDocumentVersion
from app.models.cv_generated_document import CvGeneratedDocument


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
        CvGeneratedDocument.origin == "auto", ~approved_version, ~finalized_on_stage
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
