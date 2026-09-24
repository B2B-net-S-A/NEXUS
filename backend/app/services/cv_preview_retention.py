"""Retire old previews and enqueue private source deletion atomically."""

from datetime import timedelta

from sqlalchemy import select

from app.models.client_cv_rule_preview import ClientCvRulePreview
from app.models.cv_generation_job import CvGenerationJob
from app.services.cv_source_cleanup import schedule_source_cleanup


PREVIEW_RETENTION = timedelta(days=7)


async def retire_previews(db, client_id, before):
    """Usuń podglądy starsze niż ``before`` (``client_id=None`` = wszyscy klienci).

    Od 23.09.2026 CV próbnych nie da się zlecić, więc zbiorczą retencję woła
    pętla ``cv_source_cleanup`` — wiersze niosą pełne CV kandydatów.
    """
    filters = [ClientCvRulePreview.created_at < before]
    if client_id is not None:
        filters.append(ClientCvRulePreview.client_id == client_id)
    previews = list(
        (
            await db.scalars(
                select(ClientCvRulePreview)
                .where(*filters)
                .order_by(ClientCvRulePreview.created_at)
                .limit(100)
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    for preview in previews:
        job = await db.scalar(
            select(CvGenerationJob)
            .where(CvGenerationJob.preview_id == preview.id)
            .with_for_update(skip_locked=True)
        )
        if job is None:
            # A locked job is not a legacy preview without a durable input.
            exists = await db.scalar(
                select(CvGenerationJob.id).where(
                    CvGenerationJob.preview_id == preview.id
                )
            )
            if exists is not None:
                continue
        elif job.status in {"queued", "running"}:
            continue
        if job is not None:
            await schedule_source_cleanup(db, job.input_storage_key)
        await db.delete(preview)
    # Caller commits retention together with admitting the new preview.
