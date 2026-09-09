"""Version snapshots created while holding the stage-CV row lock."""

import hashlib
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select, update

from app.models.candidate import Candidate
from app.models.cv_document_version import CvDocumentVersion
from app.models.cv_share_token import CVShareToken
from app.models.job import Job


def check_revision(csv, expected: int) -> None:
    if expected != (csv.edit_revision or 0):
        raise HTTPException(
            409,
            "CV zostało zmienione w innej sesji. Zachowaj swoje poprawki i wczytaj aktualną wersję.",
        )


async def freeze_approved_version(
    db, csv, *, docx_content=None, docx_filename=None, render_metadata=None
):
    """Also pins legacy tokens before creating a new draft. No token is revoked."""
    if csv.branded_status != "finalized":
        raise HTTPException(409, "Najpierw zatwierdź bieżącą wersję CV.")
    version = await db.scalar(
        select(CvDocumentVersion).where(
            CvDocumentVersion.candidate_stage_cv_id == csv.id,
            CvDocumentVersion.version == csv.branded_version,
        )
    )
    if version is None:
        candidate = await db.get(Candidate, csv.candidate_id)
        job = await db.get(Job, csv.job_id)
        html = csv.branded_draft_html or ""
        version = CvDocumentVersion(
            candidate_stage_cv_id=csv.id,
            version=csv.branded_version,
            generated_document_id=csv.generated_document_id,
            content_html=html,
            docx_content=docx_content,
            docx_sha256=hashlib.sha256(docx_content).hexdigest()
            if docx_content
            else None,
            docx_filename=docx_filename,
            render_metadata=render_metadata,
            content_sha256=hashlib.sha256(html.encode()).hexdigest(),
            template=csv.branded_template,
            language=csv.branded_language,
            candidate_first_name=candidate.name if candidate else None,
            job_title=job.title if job else None,
            snapshot_path=csv.branded_snapshot_path,
            snapshot_filename=csv.branded_snapshot_filename,
            snapshot_size_bytes=csv.branded_snapshot_size_bytes,
            approved_at=csv.branded_finalized_at or datetime.now(timezone.utc),
            approved_by=csv.branded_finalized_by,
        )
        db.add(version)
        await db.flush()
    await db.execute(
        update(CVShareToken)
        .where(
            CVShareToken.candidate_stage_cv_id == csv.id,
            CVShareToken.document_version_id.is_(None),
        )
        .values(document_version_id=version.id)
    )
    return version
