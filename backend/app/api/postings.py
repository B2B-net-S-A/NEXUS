"""
Job Multi-Posting API
Integracja z portalami w przygotowaniu — dane symulowane.
"""
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: F401 (used via Depends)

from app.api.deps import CurrentUser
from app.core.database import get_db
from app.models.job import Job
from app.models.job_posting import JobPosting, Portal, PostingStatus

router = APIRouter()

now_utc = lambda: datetime.now(timezone.utc)


# ── Schemas ────────────────────────────────────────────────────────────────────

class PostingOut(BaseModel):
    id: int
    job_id: int
    portal: Portal
    external_id: Optional[str]
    status: PostingStatus
    published_at: Optional[datetime]
    expires_at: Optional[datetime]
    url: Optional[str]
    views: int
    applications: int

    model_config = {"from_attributes": True}


class PostingCreate(BaseModel):
    portal: Portal
    expires_days: int = 30  # how many days until expiry


class PostingUpdate(BaseModel):
    status: Optional[PostingStatus] = None
    views: Optional[int] = None
    applications: Optional[int] = None


class PublishAllRequest(BaseModel):
    portals: List[Portal]
    expires_days: int = 30


class PortalStat(BaseModel):
    portal: str
    total_postings: int
    active_postings: int
    total_views: int
    total_applications: int


class PostingsStats(BaseModel):
    total_postings: int
    active_postings: int
    total_views: int
    total_applications: int
    by_portal: List[PortalStat]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _simulate_url(portal: Portal, job_id: int, posting_id: int) -> str:
    """Generate a simulated external URL for the posting."""
    base_urls = {
        Portal.pracuj_pl: f"https://pracuj.pl/praca/{job_id}-oferta-{posting_id}",
        Portal.justjoinit: f"https://justjoin.it/offers/dynaminds-{job_id}-{posting_id}",
        Portal.linkedin: f"https://linkedin.com/jobs/view/{1000000 + posting_id}",
        Portal.nofluffjobs: f"https://nofluffjobs.com/job/dynaminds-{job_id}-{posting_id}",
        Portal.bulldogjob: f"https://bulldogjob.pl/companies/jobs/dynaminds-{posting_id}",
    }
    return base_urls.get(portal, "#")


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("/jobs/{job_id}/postings", response_model=List[PostingOut])
async def list_postings(
    job_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """List all postings for a given job."""
    # Verify job exists
    job = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    result = await db.execute(
        select(JobPosting).where(JobPosting.job_id == job_id).order_by(JobPosting.id.desc())
    )
    return list(result.scalars().all())


@router.post("/jobs/{job_id}/postings", response_model=PostingOut, status_code=status.HTTP_201_CREATED)
async def create_posting(
    job_id: int,
    data: PostingCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a simulated posting for a given portal.
    Publishing is SIMULATED — just creates a database record.
    """
    job = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    now = now_utc()
    posting = JobPosting(
        job_id=job_id,
        portal=data.portal,
        status=PostingStatus.published,
        published_at=now,
        expires_at=now + timedelta(days=data.expires_days),
        views=0,
        applications=0,
    )
    db.add(posting)
    await db.flush()

    # Assign simulated URL and external_id
    posting.url = _simulate_url(data.portal, job_id, posting.id)
    posting.external_id = f"SIM-{data.portal.upper()}-{posting.id:06d}"

    await db.commit()
    await db.refresh(posting)
    return posting


@router.put("/postings/{posting_id}", response_model=PostingOut)
async def update_posting(
    posting_id: int,
    data: PostingUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Update posting status or metrics."""
    posting = (await db.execute(select(JobPosting).where(JobPosting.id == posting_id))).scalar_one_or_none()
    if not posting:
        raise HTTPException(status_code=404, detail="Posting not found")

    if data.status is not None:
        posting.status = data.status
    if data.views is not None:
        posting.views = data.views
    if data.applications is not None:
        posting.applications = data.applications

    await db.commit()
    await db.refresh(posting)
    return posting


@router.delete("/postings/{posting_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_posting(
    posting_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Remove a posting."""
    posting = (await db.execute(select(JobPosting).where(JobPosting.id == posting_id))).scalar_one_or_none()
    if not posting:
        raise HTTPException(status_code=404, detail="Posting not found")

    await db.delete(posting)
    await db.commit()


@router.post("/jobs/{job_id}/publish-all", response_model=List[PostingOut])
async def publish_all(
    job_id: int,
    data: PublishAllRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Publish to multiple portals at once (simulated).
    Skips portals that already have an active posting.
    """
    job = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Get existing active postings for this job
    existing = (await db.execute(
        select(JobPosting).where(
            JobPosting.job_id == job_id,
            JobPosting.status == PostingStatus.published,
        )
    )).scalars().all()
    existing_portals = {p.portal for p in existing}

    now = now_utc()
    created = []
    for portal in data.portals:
        if portal in existing_portals:
            continue  # Already published on this portal
        posting = JobPosting(
            job_id=job_id,
            portal=portal,
            status=PostingStatus.published,
            published_at=now,
            expires_at=now + timedelta(days=data.expires_days),
            views=0,
            applications=0,
        )
        db.add(posting)
        await db.flush()
        posting.url = _simulate_url(portal, job_id, posting.id)
        posting.external_id = f"SIM-{portal.upper()}-{posting.id:06d}"
        created.append(posting)

    await db.commit()
    for p in created:
        await db.refresh(p)
    return created


@router.get("/postings/stats", response_model=PostingsStats)
async def get_postings_stats(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Aggregated stats: total postings, views, applications per portal."""
    # Total counts
    total_result = await db.execute(
        select(
            func.count(JobPosting.id).label("total"),
            func.sum(JobPosting.views).label("views"),
            func.sum(JobPosting.applications).label("applications"),
        )
    )
    totals = total_result.one()

    active_count = (await db.execute(
        select(func.count(JobPosting.id)).where(JobPosting.status == PostingStatus.published)
    )).scalar() or 0

    # Per-portal breakdown
    portal_result = await db.execute(
        select(
            JobPosting.portal,
            func.count(JobPosting.id).label("total_postings"),
            func.sum(JobPosting.views).label("total_views"),
            func.sum(JobPosting.applications).label("total_applications"),
        ).group_by(JobPosting.portal)
    )

    by_portal = []
    for row in portal_result.all():
        by_portal.append(PortalStat(
            portal=row.portal,
            total_postings=row.total_postings or 0,
            active_postings=0,  # computed separately below
            total_views=row.total_views or 0,
            total_applications=row.total_applications or 0,
        ))

    # Compute active per portal separately (simpler query)
    active_by_portal_result = await db.execute(
        select(
            JobPosting.portal,
            func.count(JobPosting.id).label("active"),
        ).where(JobPosting.status == PostingStatus.published)
        .group_by(JobPosting.portal)
    )
    active_map = {row.portal: row.active for row in active_by_portal_result.all()}
    for stat in by_portal:
        stat.active_postings = active_map.get(stat.portal, 0)

    return PostingsStats(
        total_postings=totals.total or 0,
        active_postings=active_count,
        total_views=totals.views or 0,
        total_applications=totals.applications or 0,
        by_portal=by_portal,
    )
