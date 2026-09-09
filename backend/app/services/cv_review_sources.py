"""Read immutable inputs for an already authorized generated document."""

from dataclasses import dataclass

from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.models.cv_generation_job import CvGenerationJob
from app.services import object_storage
from app.services.cv_generator_b2b.job_snapshot import deserialize_job_inputs
from app.services.cv_generator_b2b.standalone_service import (
    CandidateGenerationSource,
    UploadGenerationInput,
)


class ReviewSourceUnavailable(ValueError):
    pass


@dataclass(frozen=True)
class ReviewSource:
    cv_bytes: bytes
    cv_filename: str
    screening_notes: str
    identity: str
    snapshot_sha256: str


async def load_review_source(db, generated_id: int) -> ReviewSource:
    """Caller must first authorize the concrete generated document resource.

    No fallback to current candidate files or current notes: that would silently
    change the evidence supporting an older document.
    """
    job = await db.scalar(
        select(CvGenerationJob).where(
            (CvGenerationJob.generated_id == generated_id)
            | (CvGenerationJob.second_generated_id == generated_id)
        )
    )
    if job is None:
        raise ReviewSourceUnavailable(
            "Brak zamrożonych źródeł tej generacji. Wybierz źródła i wygeneruj CV ponownie."
        )
    try:
        raw = await run_in_threadpool(object_storage.download_cv, job.input_storage_key)
        kind, inputs = deserialize_job_inputs(raw, job.input_sha256)
    except Exception as exc:
        raise ReviewSourceUnavailable(
            "Nie można potwierdzić zapisanych źródeł CV."
        ) from exc
    if kind != job.kind:
        raise ReviewSourceUnavailable("Niezgodny typ zapisanego wejścia CV.")
    source = inputs.get("source") if kind == "new" else inputs.get("payload")
    if kind == "new" and isinstance(source, CandidateGenerationSource):
        return ReviewSource(
            source.cv_bytes,
            source.cv_filename,
            source.screening_notes_text,
            source.fallback_name or "",
            job.input_sha256,
        )
    if kind == "upload" and isinstance(source, UploadGenerationInput):
        return ReviewSource(
            source.cv_bytes,
            source.cv_filename,
            source.screening_notes,
            "",
            job.input_sha256,
        )
    raise ReviewSourceUnavailable("Zapisane wejście nie zawiera źródeł do kontroli CV.")
