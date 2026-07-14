from datetime import date, datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus
from app.models.job import Job, JobStatus
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User
from app.models.user import UserRole
from app.schemas.client import ClientCreate, ClientList, ClientResponse, ClientUpdate
from app.schemas.client_profile import (
    ActiveConsultantItem,
    CandidateBrief,
    ClientProfileHistory,
    ClientProfileResponse,
    ClientProfileSummary,
    HistoricalPlacementItem,
    LostJobItem,
    OpenJobItem,
    RecruiterBrief,
)
from app.analytics.capabilities import AnalyticsCapability
from app.analytics.scope import operations_client_scope, require_client_scope
from app.api.deps import (
    DeliveryLeadPlus,
    TacPlus,
    require_analytics_capabilities,
)

router = APIRouter()

ClientOperationsViewer = Annotated[
    User,
    Depends(
        require_analytics_capabilities(AnalyticsCapability.view_client_operations)
    ),
]


# ── Profile helpers ───────────────────────────────────────────────────────────
#
# The Client Profile endpoint aggregates everything the UI needs in one call:
# open jobs, active consultants, historical placements, lost jobs, and a
# summary bar (MRR, LTV, avg time-to-fill). Kept as private functions to make
# the endpoint body readable — they use the Contract model's existing
# `monthly_rate_client` / `monthly_margin` properties rather than duplicating
# `_sql_monthly()` from reports.py.


def _duration_months(start: date, end: Optional[date]) -> Optional[int]:
    """Whole months between two dates (floor). None when start is missing."""
    if start is None:
        return None
    boundary = end or date.today()
    if boundary < start:
        return 0
    months = (boundary.year - start.year) * 12 + boundary.month - start.month
    if boundary.day < start.day:
        months -= 1
    return max(0, months)


def _candidate_brief(candidate: Candidate) -> CandidateBrief:
    full_name = f"{candidate.name or ''} {candidate.lastname or ''}".strip() or "?"
    return CandidateBrief(
        id=candidate.id,
        name=full_name,
        avatar_url=candidate.avatar_url,
        competence_category=candidate.competence_category,
        linkedin=candidate.linkedin,
    )


def _recruiter_brief(user: Optional[User]) -> Optional[RecruiterBrief]:
    if user is None:
        return None
    # User model has `name` (or similar); guard against schema drift.
    name = getattr(user, "name", None) or getattr(user, "full_name", None) or user.email
    avatar = getattr(user, "avatar_url", None)
    return RecruiterBrief(id=user.id, name=name, email=user.email, avatar_url=avatar)


def _days_to(target: Optional[date]) -> Optional[int]:
    if target is None:
        return None
    return (target - date.today()).days


@router.get("", response_model=ClientList)
async def list_clients(
    current_user: ClientOperationsViewer,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: Optional[str] = None,
):
    query = select(Client)
    visible_client_ids = await operations_client_scope(db, user=current_user)
    if visible_client_ids is not None:
        query = query.where(Client.id.in_(visible_client_ids))
    if q:
        query = query.where(Client.name.ilike(f"%{q}%"))
    total = (
        await db.execute(select(func.count()).select_from(query.subquery()))
    ).scalar()
    result = await db.execute(query.offset((page - 1) * page_size).limit(page_size))
    return ClientList(
        items=list(result.scalars().all()), total=total, page=page, page_size=page_size
    )


@router.post("", response_model=ClientResponse, status_code=status.HTTP_201_CREATED)
async def create_client(
    data: ClientCreate, current_user: TacPlus, db: AsyncSession = Depends(get_db)
):
    client = Client(**data.model_dump())
    db.add(client)
    await db.flush()
    db.add(
        Activity(
            entity_type="client",
            entity_id=client.id,
            action="created",
            user_id=current_user.id,
        )
    )
    await db.refresh(client)
    return client


@router.get("/{client_id}", response_model=ClientResponse)
async def get_client(
    client_id: int,
    current_user: ClientOperationsViewer,
    db: AsyncSession = Depends(get_db),
):
    await require_client_scope(
        db, user=current_user, client_id=client_id, finance=False
    )
    result = await db.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


@router.get("/{client_id}/profile", response_model=ClientProfileResponse)
async def get_client_profile(
    client_id: int,
    current_user: ClientOperationsViewer,
    db: AsyncSession = Depends(get_db),
):
    """Aggregated profile view — open jobs + active consultants + history.

    Powers the "Profil" tab in the client detail page. One endpoint replaces
    four round-trips from the frontend. MRR/LTV are computed from the
    Contract model's own `monthly_rate_client` / `monthly_margin` properties
    so the math stays consistent with the Contracts module.
    """
    await require_client_scope(
        db, user=current_user, client_id=client_id, finance=False
    )

    # 404 early so we don't hand back empty sections for a phantom client.
    client_exists = (
        await db.execute(select(Client.id).where(Client.id == client_id))
    ).scalar_one_or_none()
    if not client_exists:
        raise HTTPException(status_code=404, detail="Client not found")

    today = date.today()
    can_view_finance = current_user.has_any_role(
        UserRole.admin, UserRole.delivery_lead
    )

    # ── 1. Open jobs ──────────────────────────────────────────────────────
    # `published` jobs with a candidate-count subquery + recruiter join.
    candidate_count_sq = (
        select(
            CandidateStage.job_id,
            func.count(distinct(CandidateStage.candidate_id)).label("cnt"),
        )
        .group_by(CandidateStage.job_id)
        .subquery()
    )

    open_jobs_stmt = (
        select(Job, candidate_count_sq.c.cnt, User)
        .outerjoin(candidate_count_sq, candidate_count_sq.c.job_id == Job.id)
        .outerjoin(User, User.id == Job.recruiter_id)
        .where(Job.client_id == client_id, Job.status == JobStatus.published)
        .order_by(Job.created_at.desc())
    )
    open_rows = (await db.execute(open_jobs_stmt)).all()

    open_jobs: list[OpenJobItem] = []
    for job, cnt, recruiter_user in open_rows:
        created = job.created_at
        days_open = (datetime.now(timezone.utc) - created).days if created else 0
        open_jobs.append(
            OpenJobItem(
                id=job.id,
                title=job.title,
                seniority=job.seniority,
                priority=job.priority,
                days_open=max(0, days_open),
                candidate_count=int(cnt or 0),
                salary_min=job.salary_min if can_view_finance else None,
                salary_max=job.salary_max if can_view_finance else None,
                recruiter=_recruiter_brief(recruiter_user),
                created_at=created,
            )
        )

    # ── 2. Active consultants ─────────────────────────────────────────────
    active_stmt = (
        select(Contract)
        .where(
            Contract.client_id == client_id,
            Contract.status.in_((ContractStatus.active, ContractStatus.ending)),
            Contract.start_date.is_not(None),
            Contract.start_date <= today,
            (Contract.end_date.is_(None)) | (Contract.end_date >= today),
        )
        .options(
            selectinload(Contract.candidate),
            selectinload(Contract.job),
        )
        .order_by(Contract.start_date.desc())
    )
    active_contracts = list((await db.execute(active_stmt)).scalars().all())

    active_consultants: list[ActiveConsultantItem] = []
    for c in active_contracts:
        if c.candidate is None:
            continue
        active_consultants.append(
            ActiveConsultantItem(
                contract_id=c.id,
                candidate=_candidate_brief(c.candidate),
                job_id=c.job_id,
                job_title=c.job.title if c.job else None,
                start_date=c.start_date,
                end_date=c.end_date,
                days_to_end=_days_to(c.end_date),
                monthly_rate_client=(
                    c.monthly_rate_client if can_view_finance else None
                ),
                monthly_margin=c.monthly_margin if can_view_finance else None,
                currency=(c.currency or "PLN") if can_view_finance else None,
            )
        )

    # ── 3. Historical placements (ended contracts) ────────────────────────
    ended_stmt = (
        select(Contract)
        .where(
            Contract.client_id == client_id,
            Contract.status == ContractStatus.ended,
        )
        .options(
            selectinload(Contract.candidate),
            selectinload(Contract.job),
        )
        .order_by(
            func.coalesce(Contract.terminated_at, Contract.end_date).desc().nullslast(),
            Contract.id.desc(),
        )
        .limit(100)
    )
    ended_contracts = list((await db.execute(ended_stmt)).scalars().all())

    placements: list[HistoricalPlacementItem] = []
    for c in ended_contracts:
        if c.candidate is None:
            continue
        end_boundary = c.terminated_at or c.end_date or today
        duration = _duration_months(c.start_date, end_boundary)
        placements.append(
            HistoricalPlacementItem(
                contract_id=c.id,
                candidate=_candidate_brief(c.candidate),
                job_title=c.job.title if c.job else None,
                start_date=c.start_date,
                end_date=c.end_date,
                terminated_at=c.terminated_at,
                termination_reason=c.termination_reason,
                duration_months=duration,
                # Legacy cumulative revenue used 30-day pseudo-months and
                # nominally mixed currencies. The canonical finance endpoint
                # replaces it; do not emit a value that looks factual here.
                total_revenue=None,
            )
        )

    # ── 4. Lost jobs (closed without matching contract) ───────────────────
    placed_job_ids_stmt = select(distinct(Contract.job_id)).where(
        Contract.client_id == client_id, Contract.job_id.is_not(None)
    )
    placed_job_ids = {
        row for row in (await db.execute(placed_job_ids_stmt)).scalars().all() if row
    }

    lost_stmt = (
        select(Job, candidate_count_sq.c.cnt)
        .outerjoin(candidate_count_sq, candidate_count_sq.c.job_id == Job.id)
        .where(Job.client_id == client_id, Job.status == JobStatus.closed)
        .order_by(Job.closed_at.desc().nullslast(), Job.updated_at.desc())
        .limit(100)
    )
    lost_rows = (await db.execute(lost_stmt)).all()

    lost_jobs: list[LostJobItem] = []
    for job, cnt in lost_rows:
        if job.id in placed_job_ids:
            continue  # closed + placed = shown under placements, not lost
        lost_jobs.append(
            LostJobItem(
                job_id=job.id,
                title=job.title,
                closed_at=job.closed_at,
                close_reason=job.close_reason,
                close_notes=job.close_notes,
                candidate_count_reached=int(cnt or 0),
            )
        )

    # ── 5. Summary metrics ────────────────────────────────────────────────
    # avg_time_to_fill = mean (Contract.start_date - Job.created_at) for placed
    # jobs. Uses both active and ended contracts that have a job_id.
    fill_days: list[int] = []
    for c in list(active_contracts) + list(ended_contracts):
        if c.job is None or c.start_date is None or c.job.created_at is None:
            continue
        job_created = (
            c.job.created_at.date()
            if hasattr(c.job.created_at, "date")
            else c.job.created_at
        )
        delta = (c.start_date - job_created).days
        if delta >= 0:
            fill_days.append(delta)
    avg_ttf = (sum(fill_days) / len(fill_days)) if fill_days else None

    total_placements = len(active_consultants) + len(placements)

    summary = ClientProfileSummary(
        open_jobs=len(open_jobs),
        active_consultants=len(active_consultants),
        total_placements=total_placements,
        # Legacy finance mixed currencies and used 30-day pseudo-months. The
        # canonical `/analytics/v1/clients/{id}/finance` endpoint replaces it.
        active_mrr=None,
        ltv=None,
        avg_time_to_fill_days=round(avg_ttf, 1) if avg_ttf is not None else None,
    )

    return ClientProfileResponse(
        summary=summary,
        open_jobs=open_jobs,
        active_consultants=active_consultants,
        historical=ClientProfileHistory(placements=placements, lost_jobs=lost_jobs),
    )


@router.patch("/{client_id}", response_model=ClientResponse)
async def update_client(
    client_id: int,
    data: ClientUpdate,
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    updates = data.model_dump(exclude_unset=True)
    for k, v in updates.items():
        setattr(client, k, v)
    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="updated",
            user_id=current_user.id,
            details=updates,
        )
    )
    await db.flush()
    await db.refresh(client)
    return client


@router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_client(
    client_id: int, current_user: DeliveryLeadPlus, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="deleted",
            user_id=current_user.id,
        )
    )
    await db.delete(client)
