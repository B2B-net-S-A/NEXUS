"""Favorite-based sourcing pause; candidate follow-up and manual pauses survive."""

from __future__ import annotations

from sqlalchemy import or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.activity import Activity
from app.models.job import Job, JobStatus
from app.models.recruitment_pipeline import CandidateStage
from app.services.job_fill import open_vacancies, placements_by_job


def apply_favorite_work_state(job: Job, *, stage: str | None, vacancies: int) -> bool:
    previous = (
        job.favorite_candidate_id,
        job.needs_sourcing,
        job.favorite_sourcing_paused,
    )
    active = job.is_open and job.status != JobStatus.closed
    if job.favorite_candidate_id is not None and stage in {
        None,
        "rejected",
        "withdrawn",
    }:
        job.favorite_candidate_id = None
    valid_favorite = job.favorite_candidate_id is not None and stage not in {
        None,
        "rejected",
        "withdrawn",
        "hired",
    }
    if active and vacancies == 0:
        job.needs_sourcing = False
        job.favorite_sourcing_paused = False
    elif active and valid_favorite and vacancies == 1:
        if job.needs_sourcing:
            job.needs_sourcing = False
            job.favorite_sourcing_paused = True
    elif job.favorite_sourcing_paused:
        job.favorite_sourcing_paused = False
        if active and vacancies > 0:
            job.needs_sourcing = True
    return previous != (
        job.favorite_candidate_id,
        job.needs_sourcing,
        job.favorite_sourcing_paused,
    )


async def reconcile_favorite_work(
    db: AsyncSession, jobs: list[Job] | None = None
) -> int:
    if not settings.RECRUITMENT_ALLOCATION_ENABLED:
        return 0
    if jobs is None:
        jobs = list(
            (
                await db.scalars(
                    select(Job)
                    .where(
                        or_(
                            Job.is_open.is_(True),
                            Job.favorite_sourcing_paused.is_(True),
                        ),
                        or_(
                            Job.favorite_candidate_id.is_not(None),
                            Job.favorite_sourcing_paused.is_(True),
                        ),
                    )
                    .order_by(Job.id)
                    .with_for_update()
                )
            ).all()
        )
    if not jobs:
        return 0
    pairs = [
        (job.id, job.favorite_candidate_id)
        for job in jobs
        if job.favorite_candidate_id is not None
    ]
    stages = {}
    if pairs:
        rows = (
            await db.execute(
                select(
                    CandidateStage.job_id,
                    CandidateStage.candidate_id,
                    CandidateStage.stage,
                )
                .where(
                    tuple_(CandidateStage.job_id, CandidateStage.candidate_id).in_(
                        pairs
                    )
                )
                .distinct(CandidateStage.job_id, CandidateStage.candidate_id)
                .order_by(
                    CandidateStage.job_id,
                    CandidateStage.candidate_id,
                    CandidateStage.moved_at.desc(),
                    CandidateStage.id.desc(),
                )
            )
        ).all()
        stages = {
            (job, candidate): getattr(stage, "value", stage)
            for job, candidate, stage in rows
        }
    filled = await placements_by_job(db, [job.id for job in jobs])
    changed = 0
    for job in jobs:
        previous_favorite = job.favorite_candidate_id
        if apply_favorite_work_state(
            job,
            stage=stages.get((job.id, previous_favorite)),
            vacancies=open_vacancies(job.headcount, filled.get(job.id, 0)),
        ):
            changed += 1
            db.add(
                Activity(
                    entity_type="job",
                    entity_id=job.id,
                    action="favorite_sourcing_reconciled",
                    details={
                        "previous_favorite_id": previous_favorite,
                        "favorite_id": job.favorite_candidate_id,
                        "needs_sourcing": job.needs_sourcing,
                        "favorite_sourcing_paused": job.favorite_sourcing_paused,
                    },
                )
            )
    await db.flush()
    return changed
