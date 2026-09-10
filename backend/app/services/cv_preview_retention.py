"""Retire old previews and enqueue private source deletion atomically."""

from sqlalchemy import select

from app.models.client_cv_rule_preview import ClientCvRulePreview
from app.models.cv_generation_job import CvGenerationJob
from app.services.cv_source_cleanup import schedule_source_cleanup


async def retire_previews(db, client_id, before):
    previews = list(
        (
            await db.scalars(
                select(ClientCvRulePreview)
                .where(
                    ClientCvRulePreview.client_id == client_id,
                    ClientCvRulePreview.created_at < before,
                )
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
