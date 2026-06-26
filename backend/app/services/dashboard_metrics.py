"""KPI snapshot helpers shared between /api/dashboard/stats and /api/admin/snapshot.

Same SQL counts feed both endpoints. UI calls /api/dashboard/stats (any user, 2-min
cache). Ops/cron calls /api/admin/snapshot (token or admin, 30-sec cache).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate, CandidateStatus
from app.models.client import Client
from app.models.contract import Contract, ContractStatus
from app.models.job import Job, JobStatus
from app.models.recruitment_pipeline import CandidateStage, PipelineStage


async def compute_kpi_snapshot(db: AsyncSession) -> dict[str, Any]:
    """Aggregate ATS KPI counts. Returns nested dict matching dashboard.get_stats shape."""
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
    clients_total = (await db.execute(select(func.count(Client.id)))).scalar()
    contracts_active = (
        await db.execute(
            select(func.count(Contract.id)).where(
                Contract.status == ContractStatus.active
            )
        )
    ).scalar()

    cutoff = date.today() + timedelta(days=30)
    # active + ending: the cron promotes active→ending at the 30-day mark, so
    # an active-only count under-reports (often to 0). Keep this in sync with
    # the /api/contracts/expiring banner.
    contracts_expiring = (
        await db.execute(
            select(func.count(Contract.id)).where(
                Contract.end_date <= cutoff,
                Contract.end_date >= date.today(),
                Contract.status.in_([ContractStatus.active, ContractStatus.ending]),
            )
        )
    ).scalar()

    first_of_month = date.today().replace(day=1)
    hired_this_month = (
        await db.execute(
            select(func.count(CandidateStage.id)).where(
                CandidateStage.stage == PipelineStage.hired,
                CandidateStage.moved_at >= first_of_month,
            )
        )
    ).scalar()

    return {
        "candidates": {
            "total": candidates_total or 0,
            "active": candidates_active or 0,
        },
        "jobs": {"open": jobs_open or 0},
        "clients": {"total": clients_total or 0},
        "contracts": {
            "active": contracts_active or 0,
            "expiring_soon": contracts_expiring or 0,
        },
        "pipeline": {"hired_this_month": hired_this_month or 0},
    }
