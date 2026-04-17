import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.job import Job, JobStatus, RecruitmentType
from app.models.activity import Activity
from app.schemas.job import JobCreate, JobResponse, JobUpdate
from app.api.deps import CurrentUser, TacPlus

logger = logging.getLogger(__name__)

router = APIRouter()


# Fields that, when changed, should trigger re-embedding the job (Phase 2).
_EMBED_TRIGGER_FIELDS = {
    "title",
    "description",
    "requirements",
    "must_skills",
    "nice_skills",
    "seniority",
    "subcategory",
    "industry",
}


async def _maybe_embed_job(job_id: int, db: AsyncSession) -> None:
    """Fire-and-log job embedding; never raises."""
    try:
        from app.services.embedding_service import embed_job

        await embed_job(job_id, db)
    except Exception as e:  # pragma: no cover
        logger.warning(f"[Job] embedding failed for job {job_id}: {e}")


@router.get("")
async def list_jobs(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[JobStatus] = None,
    recruitment_type: Optional[RecruitmentType] = None,
    client_id: Optional[int] = None,
    q: Optional[str] = None,
):
    from app.models.recruitment_pipeline import CandidateStage

    query = select(Job)
    if status:
        query = query.where(Job.status == status)
    if recruitment_type:
        query = query.where(Job.recruitment_type == recruitment_type)
    if client_id:
        query = query.where(Job.client_id == client_id)
    if q:
        query = query.where(Job.title.ilike(f"%{q}%"))
    total = (
        await db.execute(select(func.count()).select_from(query.subquery()))
    ).scalar()
    result = await db.execute(query.offset((page - 1) * page_size).limit(page_size))
    jobs = list(result.scalars().all())

    # Candidate counts per job (distinct candidates in pipeline)
    job_ids = [j.id for j in jobs]
    counts: dict[int, int] = {}
    if job_ids:
        count_result = await db.execute(
            select(
                CandidateStage.job_id,
                func.count(func.distinct(CandidateStage.candidate_id)),
            )
            .where(CandidateStage.job_id.in_(job_ids))
            .group_by(CandidateStage.job_id)
        )
        counts = dict(count_result.all())

    items = []
    for j in jobs:
        d = JobResponse.model_validate(j).model_dump()
        d["candidate_count"] = counts.get(j.id, 0)
        items.append(d)

    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    data: JobCreate, current_user: TacPlus, db: AsyncSession = Depends(get_db)
):
    job = Job(**data.model_dump(), created_by=current_user.id)
    db.add(job)
    await db.flush()
    db.add(
        Activity(
            entity_type="job",
            entity_id=job.id,
            action="created",
            user_id=current_user.id,
        )
    )
    await db.commit()
    await db.refresh(job)

    # Phase 2: embed the job so reverse matching picks it up.
    await _maybe_embed_job(job.id, db)
    return job


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.patch("/{job_id}", response_model=JobResponse)
async def update_job(
    job_id: int,
    data: JobUpdate,
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    updates = data.model_dump(exclude_unset=True)
    for k, v in updates.items():
        setattr(job, k, v)
    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action="updated",
            user_id=current_user.id,
            details=updates,
        )
    )
    await db.commit()
    await db.refresh(job)

    # Phase 2: re-embed if any embed-relevant field changed
    changed = set(updates.keys())
    if _EMBED_TRIGGER_FIELDS & changed:
        await _maybe_embed_job(job_id, db)

    # Phase C1: invalidate cached (*, job) match scores when any scoring input
    # changes (_EMBED_TRIGGER_FIELDS covers must/nice, seniority, salary, etc.)
    if _EMBED_TRIGGER_FIELDS & changed:
        from app.services.match_score_cache import mark_stale_for_job

        await mark_stale_for_job(db, job_id)
        await db.commit()
    return job


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job(
    job_id: int, current_user: TacPlus, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action="deleted",
            user_id=current_user.id,
        )
    )
    await db.delete(job)


@router.post("/{job_id}/publish")
async def publish_job(
    job_id: int, current_user: TacPlus, db: AsyncSession = Depends(get_db)
):
    """Publish job — mark as published and queue portal syndication."""
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.status = JobStatus.published
    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action="published",
            user_id=current_user.id,
        )
    )
    return {"status": "published", "job_id": job_id}


@router.get("/{job_id}/match-candidates")
async def match_candidates(
    job_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    """Placeholder: semantic match of candidates to job (Qdrant + Voyage)."""
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    # TODO: embed job requirements -> query Qdrant -> return ranked candidates
    return {"job_id": job_id, "matches": [], "message": "Semantic matching coming soon"}
