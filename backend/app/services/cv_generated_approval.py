"""Resolve an explicitly selected approved version of an authorized generation."""

import hashlib

from fastapi import HTTPException
from sqlalchemy import select

from app.models.candidate_stage_cv import CandidateStageCV
from app.models.cv_document_version import CvDocumentVersion
from app.models.recruitment_pipeline import CandidateStage


async def approved_version_for_generation(db, generated, version_id: int):
    """Caller authorizes generated first; never substitute another/latest version."""
    if generated.candidate_id is None or generated.job_id is None:
        raise HTTPException(409, "CV nie jest przypisane do procesu zatwierdzania.")
    version = await db.scalar(
        select(CvDocumentVersion)
        .join(
            CandidateStageCV,
            CandidateStageCV.id == CvDocumentVersion.candidate_stage_cv_id,
        )
        .join(CandidateStage, CandidateStage.id == CandidateStageCV.candidate_stage_id)
        .where(
            CvDocumentVersion.id == version_id,
            CvDocumentVersion.generated_document_id == generated.id,
            CandidateStage.candidate_id == generated.candidate_id,
            CandidateStage.job_id == generated.job_id,
        )
    )
    if version is None:
        raise HTTPException(404, "Nie znaleziono zatwierdzonej wersji tego CV.")
    if (
        not version.docx_content
        or hashlib.sha256(version.docx_content).hexdigest() != version.docx_sha256
        or hashlib.sha256(version.content_html.encode()).hexdigest()
        != version.content_sha256
    ):
        raise HTTPException(
            409, "Nie można potwierdzić integralności zatwierdzonej wersji CV."
        )
    return version
