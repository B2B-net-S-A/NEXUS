"""Multi-source attribution per candidate (#4 from Traffit gap roadmap).

Endpoints:
- GET  /api/candidates/{cid}/sources       — list sources for candidate
- POST /api/candidates/{cid}/sources       — record a new touch (recruiter)
- GET  /api/reports/sources                — aggregated channel + UTM funnel

The aggregated /reports/sources endpoint groups source events by
(channel, utm_source, utm_campaign) and joins to CandidateStage to compute
hire counts. Reports module owns its routing prefix; we mount the
candidate-scoped routes on the candidates router via include below.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.database import get_db
from app.models.candidate import Candidate
from app.models.candidate_source_event import (
    CHANNEL_LABELS,
    CandidateSourceEvent,
)
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.schemas.candidate_source_event import (
    CandidateSourceEventCreate,
    CandidateSourceEventOut,
    SourceFunnelRow,
    SourceReportResponse,
)

router = APIRouter()
WARSAW = ZoneInfo("Europe/Warsaw")


def _serialize(row: CandidateSourceEvent) -> CandidateSourceEventOut:
    return CandidateSourceEventOut(
        id=row.id,
        candidate_id=row.candidate_id,
        channel=row.channel,
        channel_label=CHANNEL_LABELS.get(row.channel, row.channel.value),
        job_id=row.job_id,
        utm_source=row.utm_source,
        utm_medium=row.utm_medium,
        utm_campaign=row.utm_campaign,
        utm_term=row.utm_term,
        utm_content=row.utm_content,
        note=row.note,
        captured_at=row.captured_at,
        created_at=row.created_at,
    )


@router.get(
    "/candidates/{candidate_id}/sources",
    response_model=List[CandidateSourceEventOut],
)
async def list_candidate_sources(
    candidate_id: int,
    _: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> List[CandidateSourceEventOut]:
    """Return source events for a candidate, newest first.

    Used by the candidate profile sidebar to render the multi-line "Źródła
    aplikacji" block.
    """
    candidate = await db.scalar(select(Candidate).where(Candidate.id == candidate_id))
    if candidate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found"
        )

    rows = await db.execute(
        select(CandidateSourceEvent)
        .where(CandidateSourceEvent.candidate_id == candidate_id)
        .order_by(CandidateSourceEvent.captured_at.desc())
    )
    return [_serialize(r) for r in rows.scalars().all()]


@router.post(
    "/candidates/{candidate_id}/sources",
    response_model=CandidateSourceEventOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_candidate_source(
    candidate_id: int,
    payload: CandidateSourceEventCreate,
    _: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> CandidateSourceEventOut:
    """Record a new source touch (recruiter manual or import script).

    Public ``/apply`` form will call this server-side from the application
    handler with UTM query params extracted from the candidate's landing URL.
    """
    candidate = await db.scalar(select(Candidate).where(Candidate.id == candidate_id))
    if candidate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found"
        )

    row = CandidateSourceEvent(
        candidate_id=candidate_id,
        channel=payload.channel,
        job_id=payload.job_id,
        utm_source=payload.utm_source,
        utm_medium=payload.utm_medium,
        utm_campaign=payload.utm_campaign,
        utm_term=payload.utm_term,
        utm_content=payload.utm_content,
        note=payload.note,
        captured_at=payload.captured_at or datetime.now(timezone.utc),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _serialize(row)


# ── /reports/sources aggregation ─────────────────────────────────────────────

reports_router = APIRouter()


@reports_router.get("/sources", response_model=SourceReportResponse)
async def report_sources(
    _: CurrentUser,
    db: AsyncSession = Depends(get_db),
    days: int = Query(30, ge=1, le=365),
    group_by_utm: bool = Query(
        False,
        description=(
            "When true, additionally split rows by utm_source + utm_campaign. "
            "Use to see top-performing campaigns within a channel."
        ),
    ),
) -> SourceReportResponse:
    """Aggregated source funnel: how many candidates per channel/UTM, hire rate.

    Uses the first source touch and the first ``hired`` occurrence per
    candidate. Both numerator and denominator are therefore distinct
    candidates and the conversion rate cannot exceed 100%.
    """
    now_warsaw = datetime.now(WARSAW)
    period_end_local = now_warsaw.replace(
        hour=0, minute=0, second=0, microsecond=0
    ) + timedelta(days=1)
    period_start_local = period_end_local - timedelta(days=days)
    period_start = period_start_local.astimezone(timezone.utc)
    period_end = period_end_local.astimezone(timezone.utc)

    # A candidate can have many source touches. Reports use the canonical
    # first-touch event only, so a single candidate cannot inflate a channel's
    # hired numerator above its distinct-candidate denominator.
    ranked_sources = select(
        CandidateSourceEvent.candidate_id.label("candidate_id"),
        CandidateSourceEvent.channel.label("channel"),
        CandidateSourceEvent.utm_source.label("utm_source"),
        CandidateSourceEvent.utm_campaign.label("utm_campaign"),
        CandidateSourceEvent.captured_at.label("captured_at"),
        func.row_number()
        .over(
            partition_by=CandidateSourceEvent.candidate_id,
            order_by=(
                CandidateSourceEvent.captured_at.asc(),
                CandidateSourceEvent.id.asc(),
            ),
        )
        .label("source_rank"),
    ).subquery()

    first_hire = (
        select(
            CandidateStage.candidate_id.label("candidate_id"),
            func.min(CandidateStage.moved_at).label("first_hired_at"),
        )
        .where(CandidateStage.stage == PipelineStage.hired)
        .group_by(CandidateStage.candidate_id)
        .subquery()
    )
    hired_subq = select(first_hire.c.candidate_id).where(
        first_hire.c.first_hired_at >= period_start,
        first_hire.c.first_hired_at < period_end,
    )

    hired_flag = case(
        (ranked_sources.c.candidate_id.in_(hired_subq), 1),
        else_=0,
    )

    if group_by_utm:
        group_cols = [
            ranked_sources.c.channel,
            ranked_sources.c.utm_source,
            ranked_sources.c.utm_campaign,
        ]
    else:
        group_cols = [ranked_sources.c.channel]

    stmt = (
        select(
            *group_cols,
            func.count(ranked_sources.c.candidate_id).label("candidates_total"),
            func.sum(hired_flag).label("hired"),
        )
        .where(ranked_sources.c.source_rank == 1)
        .where(ranked_sources.c.captured_at >= period_start)
        .where(ranked_sources.c.captured_at < period_end)
        .group_by(*group_cols)
        .order_by(func.count(ranked_sources.c.candidate_id).desc())
    )

    result = await db.execute(stmt)
    rows: List[SourceFunnelRow] = []
    for r in result.all():
        if group_by_utm:
            channel, utm_source, utm_campaign, total, hired = r
        else:
            channel = r[0]
            utm_source = utm_campaign = None
            total = r[1]
            hired = r[2]

        total = int(total or 0)
        hired = int(hired or 0)
        rate = round(hired / total * 100, 1) if total else 0.0

        rows.append(
            SourceFunnelRow(
                channel=channel,
                channel_label=CHANNEL_LABELS.get(channel, channel.value),
                utm_source=utm_source,
                utm_campaign=utm_campaign,
                candidates_total=total,
                hired=hired,
                hire_rate_pct=rate,
            )
        )

    return SourceReportResponse(
        period_start=period_start,
        period_end=period_end,
        rows=rows,
    )
