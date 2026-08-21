"""KPI snapshot helpers shared between /api/dashboard/stats and /api/admin/snapshot.

Same SQL counts feed both endpoints. UI calls /api/dashboard/stats (any user, 2-min
cache). Ops/cron calls /api/admin/snapshot (token or admin, 30-sec cache).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today, local_month_bounds
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
    # PR 4 (plan analytics §3.2): prawdziwy jobs.total + rozdzielenie
    # clients total/active (aktywny = date-effective kontrakt DZIŚ).
    jobs_total = (await db.execute(select(func.count(Job.id)))).scalar()
    clients_total = (await db.execute(select(func.count(Client.id)))).scalar()
    # Dzień roboczy firmy, nie dzień zegara kontenera: Dockerfile nie ustawia
    # TZ, więc `date.today()` zwraca datę UTC — przez pierwsze 1–2 godziny
    # polskiej doby jest to WCZORAJ.
    today_d = business_today()
    clients_active = (
        await db.execute(
            select(func.count(distinct(Contract.client_id))).where(
                Contract.status != ContractStatus.draft,
                Contract.start_date.isnot(None),
                Contract.start_date <= today_d,
                (Contract.end_date.is_(None)) | (Contract.end_date >= today_d),
            )
        )
    ).scalar()
    contracts_active = (
        await db.execute(
            select(func.count(Contract.id)).where(
                Contract.status == ContractStatus.active
            )
        )
    ).scalar()

    cutoff = today_d + timedelta(days=30)
    # active + ending: the cron promotes active→ending at the 30-day mark, so
    # an active-only count under-reports (often to 0). Keep this in sync with
    # the /api/contracts/expiring banner.
    contracts_expiring = (
        await db.execute(
            select(func.count(Contract.id)).where(
                Contract.end_date <= cutoff,
                Contract.end_date >= today_d,
                Contract.status.in_([ContractStatus.active, ContractStatus.ending]),
            )
        )
    ).scalar()

    # `moved_at` to `timestamptz`, a naiwna data w bindzie kompiluje się do
    # `$1::DATE` i granica wypada o północy UTC sesji — nie o północy
    # warszawskiej. Zatrudnienie ostemplowane 31.08 o 23:00Z (= 1.09 o 01:00
    # w Warszawie) wypadało wtedy z SIERPNIA po tej stronie granicy i z
    # WRZEŚNIA po drugiej, czyli znikało z KPI na stałe. Samo `ENV TZ` tego nie
    # naprawia — o granicy decyduje strefa sesji Postgresa, nie procesu.
    month = local_month_bounds(today_d)
    hired_this_month = (
        await db.execute(
            select(func.count(CandidateStage.id)).where(
                CandidateStage.stage == PipelineStage.hired,
                CandidateStage.moved_at >= month.start_utc,
                CandidateStage.moved_at < month.end_utc,
            )
        )
    ).scalar()

    return {
        "candidates": {
            "total": candidates_total or 0,
            "active": candidates_active or 0,
        },
        "jobs": {"open": jobs_open or 0, "total": jobs_total or 0},
        "clients": {"total": clients_total or 0, "active": clients_active or 0},
        "contracts": {
            "active": contracts_active or 0,
            "expiring_soon": contracts_expiring or 0,
        },
        "pipeline": {"hired_this_month": hired_this_month or 0},
    }
