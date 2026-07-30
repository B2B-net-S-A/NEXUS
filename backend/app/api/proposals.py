"""AI candidate proposal snapshots (Phase 13).

Exposes read + regenerate endpoints for `ProposalSnapshot`. The write path
(initial snapshot creation) lives inside `POST /api/jobs` via FastAPI
`BackgroundTasks`.
"""

import logging
from typing import Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Request,
    status,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import OperationalUser, TacPlus
from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.proposal_snapshot import (
    ProposalSnapshot,
)
from app.schemas.proposal import (
    ProposalCandidate,
    ProposalCandidateItem,
    ProposalListResponse,
    ProposalSnapshotResponse,
    ProposalSnapshotSummary,
)
from app.tasks.compute_proposals import (
    compute_proposal_for_job,
    create_pending_snapshot,
)

logger = logging.getLogger(__name__)

router = APIRouter()


async def _ensure_job_exists(db: AsyncSession, job_id: int) -> Job:
    job = await db.scalar(select(Job).where(Job.id == job_id))
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def _hydrate_items(
    snap: ProposalSnapshot, candidates_by_id: dict[int, Candidate]
) -> list[ProposalCandidateItem]:
    """Fuse breakdowns (from the snapshot) with live candidate rows (for the UI)."""
    items: list[ProposalCandidateItem] = []
    for breakdown in snap.breakdowns or []:
        cid = breakdown.get("candidate_id")
        cand = candidates_by_id.get(cid) if cid is not None else None
        if cand is None:
            # Candidate was deleted since snapshot creation — skip.
            continue
        items.append(
            ProposalCandidateItem(
                candidate=ProposalCandidate(
                    id=cand.id,
                    name=cand.name,
                    lastname=cand.lastname,
                    email=cand.email,
                    phone=cand.phone,
                    location=cand.location,
                    avatar_url=cand.avatar_url,
                    competence_category=cand.competence_category,
                    years_it_experience=cand.years_it_experience,
                    status=cand.status.value if cand.status else None,
                    champion=cand.champion,
                ),
                total_score=float(breakdown.get("total", 0.0)),
                breakdown=breakdown,
            )
        )
    return items


async def _load_snapshot_candidates(
    db: AsyncSession, snap: ProposalSnapshot
) -> dict[int, Candidate]:
    ids = list(snap.candidate_ids or [])
    if not ids:
        return {}
    result = await db.execute(select(Candidate).where(Candidate.id.in_(ids)))
    return {c.id: c for c in result.scalars().all()}


@router.get("/jobs/{job_id}/proposals/latest", response_model=ProposalSnapshotResponse)
@limiter.limit("30/minute")
async def get_latest_proposal(
    request: Request,
    job_id: int,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
):
    """Return the latest proposal snapshot for `job_id` (any status).

    UI polls this while `status="pending"`. Returns 404 only if the job has
    never had a snapshot (e.g. legacy jobs created before Phase 13).
    """
    await _ensure_job_exists(db, job_id)
    snap = await db.scalar(
        select(ProposalSnapshot)
        .where(ProposalSnapshot.job_id == job_id)
        .order_by(ProposalSnapshot.created_at.desc())
        .limit(1)
    )
    if snap is None:
        raise HTTPException(
            status_code=404, detail="No proposal snapshot yet for this job"
        )
    candidates_by_id = await _load_snapshot_candidates(db, snap)
    items = _hydrate_items(snap, candidates_by_id)
    return ProposalSnapshotResponse(
        id=snap.id,
        job_id=snap.job_id,
        status=snap.status,
        source=snap.source,
        top_k=snap.top_k,
        profile_id=snap.profile_id,
        created_at=snap.created_at,
        error_message=snap.error_message,
        candidates=items,
    )


@router.get("/jobs/{job_id}/proposals", response_model=ProposalListResponse)
@limiter.limit("20/minute")
async def list_proposals(
    request: Request,
    job_id: int,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
):
    """Paginated history of proposal snapshots for `job_id`."""
    await _ensure_job_exists(db, job_id)

    base_query = select(ProposalSnapshot).where(ProposalSnapshot.job_id == job_id)
    total = (
        await db.execute(select(func.count()).select_from(base_query.subquery()))
    ).scalar() or 0

    result = await db.execute(
        base_query.order_by(ProposalSnapshot.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = result.scalars().all()

    items = [
        ProposalSnapshotSummary(
            id=r.id,
            job_id=r.job_id,
            status=r.status,
            source=r.source,
            top_k=r.top_k,
            created_at=r.created_at,
            candidate_count=len(r.candidate_ids or []),
            error_message=r.error_message,
        )
        for r in rows
    ]
    return ProposalListResponse(
        items=items, total=total, page=page, page_size=page_size
    )


@router.post(
    "/jobs/{job_id}/proposals/regenerate",
    response_model=ProposalSnapshotResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
@limiter.limit("10/minute")
async def regenerate_proposals(
    request: Request,
    job_id: int,
    current_user: TacPlus,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    top_k: int = Query(
        settings.MATCH_MAX_RESULTS,
        ge=1,
        le=settings.MATCH_MAX_RESULTS,
        description="Hard cap on stored proposals (payload safety bound).",
    ),
    profile_id: Optional[int] = Query(None),
):
    """Trigger a new proposal snapshot. Returns the pending row (poll until ready)."""
    await _ensure_job_exists(db, job_id)

    snapshot_id = await create_pending_snapshot(
        job_id,
        top_k=top_k,
        source="manual_regenerate",
        created_by=current_user.id,
        profile_id=profile_id or 0,
    )
    background_tasks.add_task(
        compute_proposal_for_job, snapshot_id, job_id, top_k=top_k
    )

    snap = await db.scalar(
        select(ProposalSnapshot).where(ProposalSnapshot.id == snapshot_id)
    )
    if snap is None:  # pragma: no cover — defensive
        raise HTTPException(
            status_code=500, detail="Snapshot disappeared after creation"
        )
    return ProposalSnapshotResponse(
        id=snap.id,
        job_id=snap.job_id,
        status=snap.status,
        source=snap.source,
        top_k=snap.top_k,
        profile_id=snap.profile_id,
        created_at=snap.created_at,
        error_message=snap.error_message,
        candidates=[],
    )
