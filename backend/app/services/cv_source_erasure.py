"""Remove private job inputs through the caller's candidate erasure transaction."""

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.exc import DBAPIError

from app.models.client_cv_rule_preview import ClientCvRulePreview
from app.models.cv_generated_document import CvGeneratedDocument
from app.models.cv_generation_job import CvGenerationJob


async def detach_candidate_job_sources(db, candidate_id: int) -> list[str]:
    """Caller holds the candidate row lock and deletes returned storage keys.

    Retained generated documents follow their existing retention policy. Only
    temporary source jobs are removed here; no storage mutation happens before
    the surrounding erasure flow flushes and verifies its database changes.
    """
    documents = select(CvGeneratedDocument.id).where(
        CvGeneratedDocument.candidate_id == candidate_id
    )
    previews = select(ClientCvRulePreview.id).where(
        ClientCvRulePreview.candidate_id == candidate_id
    )
    try:
        jobs = list(
            (
                await db.scalars(
                    select(CvGenerationJob)
                    .where(
                        or_(
                            CvGenerationJob.generated_id.in_(documents),
                            CvGenerationJob.second_generated_id.in_(documents),
                            CvGenerationJob.preview_id.in_(previews),
                        )
                    )
                    .order_by(CvGenerationJob.id)
                    .with_for_update(nowait=True)
                )
            ).all()
        )
    except DBAPIError as exc:
        # The worker can hold the job before inserting a candidate-linked result.
        # Do not wait while holding the candidate lock in the opposite order.
        code = getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)
        if code != "55P03":
            raise
        raise HTTPException(
            409, "Generator aktualizuje CV kandydata. Ponów usunięcie za chwilę."
        ) from exc
    if any(job.status in {"queued", "running"} for job in jobs):
        raise HTTPException(
            409,
            "Generacja CV kandydata nadal trwa. Ponów usunięcie po jej zakończeniu.",
        )
    keys = sorted({job.input_storage_key for job in jobs if job.input_storage_key})
    for job in jobs:
        await db.delete(job)
    return keys
