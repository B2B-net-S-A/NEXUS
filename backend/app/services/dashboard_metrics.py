"""KPI snapshot helpers shared between /api/dashboard/stats and /api/admin/snapshot.

Same SQL counts feed both endpoints. UI calls /api/dashboard/stats (any user, 2-min
cache). Ops/cron calls /api/admin/snapshot (token or admin, 30-sec cache).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate, CandidateStatus
from app.models.client import Client, ClientStatus
from app.models.contract import Contract, ContractStatus
from app.models.job import Job, JobStatus
from app.models.recruitment_pipeline import CandidateStage, PipelineStage


WARSAW = ZoneInfo("Europe/Warsaw")


async def compute_kpi_snapshot(db: AsyncSession) -> dict[str, Any]:
    """Aggregate ATS KPI counts. Returns nested dict matching dashboard.get_stats shape."""
    now_warsaw = datetime.now(WARSAW)
    today = now_warsaw.date()
    candidates_total = (await db.execute(select(func.count(Candidate.id)))).scalar()
    candidates_active = (
        await db.execute(
            select(func.count(Candidate.id)).where(
                Candidate.status == CandidateStatus.active
            )
        )
    ).scalar()
    jobs_open = (
        await db.execute(
            select(func.count(Job.id)).where(Job.status == JobStatus.published)
        )
    ).scalar()
    jobs_total = (await db.execute(select(func.count(Job.id)))).scalar()
    clients_total = (await db.execute(select(func.count(Client.id)))).scalar()
    clients_active = (
        await db.execute(
            select(func.count(Client.id)).where(Client.status == ClientStatus.active)
        )
    ).scalar()
    contracts_active = (
        await db.execute(
            select(func.count(Contract.id)).where(
                Contract.status.in_([ContractStatus.active, ContractStatus.ending]),
                Contract.start_date.is_not(None),
                Contract.start_date <= today,
                (Contract.end_date.is_(None)) | (Contract.end_date >= today),
            )
        )
    ).scalar()

    cutoff = today + timedelta(days=30)
    # active + ending: the cron promotes active→ending at the 30-day mark, so
    # an active-only count under-reports (often to 0). Keep this in sync with
    # the /api/contracts/expiring banner.
    contracts_expiring = (
        await db.execute(
            select(func.count(Contract.id)).where(
                Contract.end_date <= cutoff,
                Contract.end_date >= today,
                Contract.start_date.is_not(None),
                Contract.start_date <= today,
                Contract.status.in_([ContractStatus.active, ContractStatus.ending]),
            )
        )
    ).scalar()

    first_of_month = now_warsaw.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    if first_of_month.month == 12:
        next_month = first_of_month.replace(year=first_of_month.year + 1, month=1)
    else:
        next_month = first_of_month.replace(month=first_of_month.month + 1)
    first_hired_pairs = (
        select(
            CandidateStage.candidate_id,
            CandidateStage.job_id,
            func.min(CandidateStage.moved_at).label("first_hired_at"),
        )
        .where(CandidateStage.stage == PipelineStage.hired)
        .group_by(CandidateStage.candidate_id, CandidateStage.job_id)
        .subquery()
    )
    hired_this_month = (
        await db.execute(
            select(func.count())
            .select_from(first_hired_pairs)
            .where(
                first_hired_pairs.c.first_hired_at >= first_of_month,
                first_hired_pairs.c.first_hired_at < next_month,
            )
        )
    ).scalar()

    return {
        "candidates": {
            "total": candidates_total or 0,
            "active": candidates_active or 0,
        },
        "jobs": {"open": jobs_open or 0, "total": jobs_total or 0},
        "clients": {
            "total": clients_total or 0,
            "active": clients_active or 0,
        },
        "contracts": {
            "active": contracts_active or 0,
            "expiring_soon": contracts_expiring or 0,
        },
        "pipeline": {"hired_this_month": hired_this_month or 0},
    }
