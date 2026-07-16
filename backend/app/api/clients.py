from datetime import date, datetime, timezone
from typing import Optional

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
from app.api.deps import OperationalUser, TacPlus, DeliveryLeadPlus

router = APIRouter()


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
    days = (boundary - start).days
    return max(0, days // 30)


def _contract_total_revenue(
    contract: Contract, boundary: Optional[date] = None
) -> Optional[int]:
    """Cumulative revenue from a contract up to a boundary date (exclusive).

    For active contracts the caller passes `boundary=date.today()` so LTV keeps
    ticking. For ended contracts the caller passes the actual end date
    (terminated_at preferred, falls back to end_date, then today).
    """
    monthly = contract.monthly_rate_client
    if monthly is None or contract.start_date is None:
        return None
    months = _duration_months(contract.start_date, boundary)
    if months is None:
        return None
    return int(monthly) * int(months)


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
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: Optional[str] = None,
):
    query = select(Client)
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
    client_id: int, current_user: OperationalUser, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


@router.get("/{client_id}/profile", response_model=ClientProfileResponse)
async def get_client_profile(
    client_id: int,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
):
    """Aggregated profile view — open jobs + active consultants + history.

    Powers the "Profil" tab in the client detail page. One endpoint replaces
    four round-trips from the frontend. MRR/LTV are computed from the
    Contract model's own `monthly_rate_client` / `monthly_margin` properties
    so the math stays consistent with the Contracts module.
    """
    # 404 early so we don't hand back empty sections for a phantom client.
    client_exists = (
        await db.execute(select(Client.id).where(Client.id == client_id))
    ).scalar_one_or_none()
    if not client_exists:
        raise HTTPException(status_code=404, detail="Client not found")

    today = date.today()

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
                salary_min=job.salary_min,
                salary_max=job.salary_max,
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
                monthly_rate_client=c.monthly_rate_client,
                monthly_margin=c.monthly_margin,
                currency=c.currency or "PLN",
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
                total_revenue=_contract_total_revenue(c, end_boundary),
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
    active_mrr = sum((c.monthly_margin or 0) for c in active_contracts)

    # LTV = cumulative revenue so far. For active contracts use today as the
    # boundary so the number keeps ticking; for ended use the real end date.
    ltv = 0
    for c in active_contracts:
        rev = _contract_total_revenue(c, today)
        if rev:
            ltv += rev
    for c in ended_contracts:
        rev = _contract_total_revenue(c, c.terminated_at or c.end_date or today)
        if rev:
            ltv += rev

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
        active_mrr=int(active_mrr),
        ltv=int(ltv),
        avg_time_to_fill_days=round(avg_ttf, 1) if avg_ttf is not None else None,
    )

    response = ClientProfileResponse(
        summary=summary,
        open_jobs=open_jobs,
        active_consultants=active_consultants,
        historical=ClientProfileHistory(placements=placements, lost_jobs=lost_jobs),
    )

    # R0 (plan 2026-07-16): stawki/marże/MRR/LTV tylko dla VIEW_FINANCE
    # (delivery_lead, admin). Pozostałe role widzą profil operacyjny.
    from app.analytics.capabilities import AnalyticsCapability, user_has_capability

    if not user_has_capability(current_user, AnalyticsCapability.VIEW_FINANCE):
        response.summary.active_mrr = None
        response.summary.ltv = None
        for consultant in response.active_consultants:
            consultant.monthly_rate_client = None
            consultant.monthly_margin = None
        for placement in response.historical.placements:
            placement.total_revenue = None

    return response


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
