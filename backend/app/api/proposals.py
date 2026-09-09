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

from app.api.deps import OperationalUser, RecruiterPlus
from app.api.recruitment_access import ensure_job_membership, ensure_job_read_access
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.config import settings
from app.core.database import get_db
from app.services.proposal_contract import snapshot_is_stale
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

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)


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
                total_score=breakdown.get("total"),
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


async def _hydrate_current_items(db, job, snap, *, context_stale=False):
    """Recheck visibility on every read; stored annotations are historical only."""
    from datetime import datetime, timezone
    from app.api.matching import _eligibility_annotation
    from app.services.pipeline_eligibility import evaluate_candidates_for_job
    from app.services.candidate_job_eligibility import Visibility

    candidates = await _load_snapshot_candidates(db, snap)
    if not candidates:
        return []
    decisions = await evaluate_candidates_for_job(
        db, job=job, candidate_ids=list(candidates), now=datetime.now(timezone.utc)
    )
    visible = {
        cid: candidate
        for cid, candidate in candidates.items()
        if cid in decisions and decisions[cid].visibility != Visibility.hidden
    }
    items = _hydrate_items(snap, visible)
    for item in items:
        item.eligibility = _eligibility_annotation(decisions[item.candidate.id])
        candidate = visible[item.candidate.id]
        saved_version = item.breakdown.get("candidate_version")
        if (
            context_stale
            or not saved_version
            or candidate.updated_at is None
            or saved_version != str(candidate.updated_at)
        ):
            item.total_score = None
            item.breakdown = {
                "candidate_id": item.candidate.id,
                "total": None,
                "measurement": "context_changed"
                if context_stale
                else "candidate_changed",
                "eligibility": item.eligibility,
            }
        else:
            # Stored authorization is never current, even when fit is fresh.
            item.breakdown = {**item.breakdown, "eligibility": item.eligibility}
    items.sort(
        key=lambda item: (
            item.total_score is None,
            -(item.total_score or 0),
            item.candidate.id,
        )
    )
    return items


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
    job = await _ensure_job_exists(db, job_id)
    # Read scope preserves the normal membership boundary for operational
    # roles and adds Finance's organization-wide business-data view. The
    # regenerate command below deliberately keeps ensure_job_membership.
    await ensure_job_read_access(db, current_user, job_id)
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
    from app.services.proposal_contract import snapshot_is_stale_for_viewer

    context_stale = await snapshot_is_stale_for_viewer(db, snap, job, current_user.id)
    items = await _hydrate_current_items(db, job, snap, context_stale=context_stale)
    candidates_stale = any(
        item.breakdown.get("measurement") == "candidate_changed" for item in items
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
        degraded=snap.degraded or context_stale or candidates_stale,
        stale=context_stale or candidates_stale,
        hidden=snap.hidden,
        run_id=snap.run_id,
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
    # Same read scope as latest: Finance is organization-wide, while other
    # roles still honour the job/client boundary (RBAC #1031).
    await ensure_job_read_access(db, current_user, job_id)

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
            degraded=r.degraded,
            stale=snapshot_is_stale(r),
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
    current_user: RecruiterPlus,
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
    """Trigger a new proposal snapshot. Returns the pending row (poll until ready).

    P0-A: guarded by RecruiterPlus + ensure_job_membership so the ASSIGNED
    recruiter can refresh their own recruitment (previously TacPlus → the button
    always 403'd for recruiters), while a non-member (incl. a Delivery Lead whose
    client is out of scope) is blocked — closing the "regenerate is less scoped
    than read" hole.
    """
    await ensure_job_membership(db, current_user, job_id)

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
        degraded=snap.degraded,
        stale=snapshot_is_stale(snap),
        hidden=snap.hidden,
        run_id=snap.run_id,
        candidates=[],
    )
