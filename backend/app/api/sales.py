from typing import Optional
from datetime import datetime, date

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.core.database import get_db
from app.models.sales_opportunity import SalesOpportunity, SalesStage
from app.models.job import Job, JobStatus
from app.api.deps import CurrentUser

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────────────

class SalesOpportunityCreate(BaseModel):
    client_id: int
    title: str
    contact_person: Optional[str] = None
    description: Optional[str] = None
    stage: SalesStage = SalesStage.lead
    value: Optional[float] = None
    currency: str = "PLN"
    probability: int = 50
    expected_close_date: Optional[date] = None
    assigned_to: Optional[int] = None


class SalesOpportunityUpdate(BaseModel):
    title: Optional[str] = None
    contact_person: Optional[str] = None
    description: Optional[str] = None
    stage: Optional[SalesStage] = None
    value: Optional[float] = None
    currency: Optional[str] = None
    probability: Optional[int] = None
    expected_close_date: Optional[date] = None
    assigned_to: Optional[int] = None
    lost_reason: Optional[str] = None


class SalesOpportunityResponse(BaseModel):
    id: int
    client_id: int
    contact_person: Optional[str]
    title: str
    description: Optional[str]
    stage: SalesStage
    value: Optional[float]
    currency: str
    probability: int
    expected_close_date: Optional[date]
    assigned_to: Optional[int]
    lost_reason: Optional[str]
    converted_job_id: Optional[int]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/sales", response_model=list[SalesOpportunityResponse])
async def list_sales_opportunities(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    stage: Optional[SalesStage] = None,
    assigned_to: Optional[int] = None,
):
    query = select(SalesOpportunity).order_by(SalesOpportunity.updated_at.desc())
    if stage:
        query = query.where(SalesOpportunity.stage == stage)
    if assigned_to:
        query = query.where(SalesOpportunity.assigned_to == assigned_to)

    result = await db.execute(query)
    return list(result.scalars().all())


@router.post("/sales", response_model=SalesOpportunityResponse, status_code=status.HTTP_201_CREATED)
async def create_sales_opportunity(
    data: SalesOpportunityCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    opp = SalesOpportunity(**data.model_dump())
    db.add(opp)
    await db.flush()
    await db.refresh(opp)
    return opp


@router.put("/sales/{opp_id}", response_model=SalesOpportunityResponse)
async def update_sales_opportunity(
    opp_id: int,
    data: SalesOpportunityUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(SalesOpportunity).where(SalesOpportunity.id == opp_id))
    opp = result.scalar_one_or_none()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(opp, k, v)

    await db.flush()
    await db.refresh(opp)
    return opp


@router.post("/sales/{opp_id}/convert", response_model=dict)
async def convert_opportunity_to_job(
    opp_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(SalesOpportunity).where(SalesOpportunity.id == opp_id))
    opp = result.scalar_one_or_none()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    if opp.stage != SalesStage.won:
        raise HTTPException(status_code=400, detail="Only won opportunities can be converted to jobs")

    if opp.converted_job_id:
        raise HTTPException(status_code=400, detail="Opportunity already converted")

    # Create job from opportunity
    job = Job(
        title=opp.title,
        description=opp.description,
        client_id=opp.client_id,
        recruiter_id=opp.assigned_to,
        created_by=current_user.id,
        status=JobStatus.draft,
    )
    db.add(job)
    await db.flush()

    opp.converted_job_id = job.id
    await db.flush()
    await db.refresh(opp)

    return {"success": True, "job_id": job.id, "opportunity_id": opp.id}


@router.get("/sales/stats")
async def get_sales_stats(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(SalesOpportunity))
    opportunities = list(result.scalars().all())

    stats_by_stage: dict[str, dict] = {}
    for stage in SalesStage:
        stage_opps = [o for o in opportunities if o.stage == stage]
        total_value = sum((float(o.value) if o.value else 0) for o in stage_opps)
        stats_by_stage[stage.value] = {
            "count": len(stage_opps),
            "total_value": total_value,
        }

    all_values = [float(o.value) if o.value else 0 for o in opportunities if o.stage not in (SalesStage.lost,)]
    total_pipeline = sum(all_values)

    won_this_month_opps = [
        o for o in opportunities
        if o.stage == SalesStage.won
        and o.updated_at.month == datetime.now().month
        and o.updated_at.year == datetime.now().year
    ]
    won_this_month_value = sum(float(o.value) if o.value else 0 for o in won_this_month_opps)

    total = len(opportunities)
    won = len([o for o in opportunities if o.stage == SalesStage.won])
    conversion_rate = round(won / total * 100, 1) if total > 0 else 0

    return {
        "by_stage": stats_by_stage,
        "total_pipeline_value": total_pipeline,
        "won_this_month_count": len(won_this_month_opps),
        "won_this_month_value": won_this_month_value,
        "conversion_rate": conversion_rate,
        "total_opportunities": total,
    }
