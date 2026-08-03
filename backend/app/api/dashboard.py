from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.capabilities import (
    AnalyticsCapability,
    user_has_capability,
)
from app.api.deps import OperationalUser, require_roles
from app.api.financial_access import has_financial_access, redact_feed_activity
from app.core.cache import cache_get, cache_set
from app.core.database import get_db
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.contract import Contract, ContractStatus
from app.models.user import User, UserRole
from app.services.access_scope import apply_activity_feed_scope
from app.services.dashboard_metrics import compute_kpi_snapshot

router = APIRouter()

_legacy_organization_dashboard_guard = require_roles(
    UserRole.admin,
    UserRole.head_of_recruitment,
)
LegacyOrganizationDashboardUser = Annotated[
    User,
    Depends(_legacy_organization_dashboard_guard),
]


@router.get("/stats")
async def get_stats(
    current_user: LegacyOrganizationDashboardUser,
    db: AsyncSession = Depends(get_db),
):
    """Frozen organization-wide KPI snapshot for Admin/HoR only.

    Role dashboards use ``/api/dashboard/v2/*``. Keeping this legacy aggregate
    behind an explicit organization-level gate prevents a viewer, Finance, or
    a client-scoped Delivery Lead from bypassing the five dashboard presets.
    """
    return await compute_kpi_snapshot(db)


@router.get("/kpis")
async def get_kpis(
    current_user: LegacyOrganizationDashboardUser,
    db: AsyncSession = Depends(get_db),
):
    """Frozen ATS aggregate and recruiter ranking for Admin/HoR only.

    R0 (plan 2026-07-16): InfraReporter wycięty — zewnętrzny serwis z
    hardcoded API key nie jest źródłem statystyk NEXUS-a. Imienny ranking
    ``top_recruiters`` widzą tylko role z VIEW_RECRUITMENT_RANKING. Cały
    legacy endpoint jest dodatkowo zamknięty do Admin/HoR, ponieważ zawiera
    organization-wide agregaty niezgodne ze scope Delivery Leada.
    GET /api/dashboard/kpis
    """
    include_ranking = user_has_capability(
        current_user, AnalyticsCapability.VIEW_RECRUITMENT_RANKING
    )
    cache_key = f"dashboard:kpis:{'ranking' if include_ranking else 'aggregates'}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached

    # ATS stats
    contracts_active = (
        await db.execute(
            select(func.count(Contract.id)).where(
                Contract.status == ContractStatus.active
            )
        )
    ).scalar()

    first_of_month = date.today().replace(day=1)
    # PR 4: pierwsze osiągnięcia `hired` (kanoniczny view) zamiast liczenia
    # każdego ruchu na etap hired (multi-count przy cofnięciach).
    placements_this_month = (
        await db.execute(
            text(
                "SELECT COUNT(*) FROM analytics_first_milestones "
                "WHERE stage = 'hired' AND first_reached_at >= :start"
            ),
            {"start": first_of_month},
        )
    ).scalar()

    # PR 4: kanonicznie z tabeli candidates (created_by/created_at) —
    # UserActivity to log pomocniczy, nie źródło metryk (plan §4.1).
    candidates_added_this_month = (
        await db.execute(
            select(func.count(Candidate.id)).where(
                Candidate.created_at >= first_of_month,
                Candidate.created_by.isnot(None),
            )
        )
    ).scalar()

    top_recruiters: list[dict] = []
    if include_ranking:
        # PR 4 (plan analytics): ranking z kanonicznej atrybucji
        # (VERIFIER_ANCHORED_CTE / view analytics_first_milestones) —
        # te same liczby co panel „Moje KPI" i panel zespołu.
        from app.services.kpi_panel import VERIFIER_ANCHORED_CTE

        leaderboard_result = await db.execute(
            text(
                VERIFIER_ANCHORED_CTE
                + """
                SELECT u.id, u.name,
                       count(*) AS total_milestones,
                       count(*) FILTER (WHERE c.stage = 'hired') AS placements
                FROM credited c
                JOIN users u ON u.id = c.credit_user
                WHERE c.reached_at >= :month_start
                  AND u.is_active IS TRUE
                GROUP BY u.id, u.name
                ORDER BY placements DESC, total_milestones DESC
                LIMIT 5
                """
            ),
            {"month_start": first_of_month},
        )
        top_recruiters = [
            {
                "user_id": row.id,
                "user_name": row.name,
                "total_actions": row.total_milestones,
                "placements": row.placements,
            }
            for row in leaderboard_result.all()
        ]

    result_data = {
        "ats": {
            "active_consultants": contracts_active,
            "placements_this_month": placements_this_month,
            "candidates_added_this_month": candidates_added_this_month,
            "top_recruiters": top_recruiters,
        },
    }
    await cache_set(cache_key, result_data, ttl_seconds=120)  # cache 2 min
    return result_data


@router.get("/recent-activity")
async def recent_activity(
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
    limit: int = 20,
):
    """Recent activity feed for dashboard.

    R0: feed zawiera surowe ``details`` (nazwiska kandydatów, nazwy klientów,
    e-maile) — to nie są „bezpieczne agregaty", więc rola ``user`` (read-only
    viewer) nie ma tu wstępu. Guard = OperationalUser.
    """
    query = await apply_activity_feed_scope(
        select(Activity),
        current_user,
        db,
    )
    result = await db.execute(query.order_by(Activity.created_at.desc()).limit(limit))
    activities = result.scalars().all()
    # Finance protection (P1): raw ``details`` can carry rate amounts. Non-finance
    # readers get rate-change audit rows omitted + finance keys stripped, mirroring
    # the candidate timeline redaction.
    finance_ok = has_financial_access(current_user)
    feed = []
    for a in activities:
        details = redact_feed_activity(a.action, a.details, finance_ok=finance_ok)
        if details is None:
            continue
        feed.append(
            {
                "id": a.id,
                "entity_type": a.entity_type,
                "entity_id": a.entity_id,
                "action": a.action,
                "user_id": a.user_id,
                "details": details,
                "created_at": a.created_at,
            }
        )
    return feed


@router.get("/pipeline-funnel")
async def pipeline_funnel(
    current_user: LegacyOrganizationDashboardUser,
    db: AsyncSession = Depends(get_db),
):
    """Frozen organization-wide pipeline counts for Admin/HoR only.

    PR 4 (plan analytics): aktualny pipeline = OSTATNI stage per
    kandydat × job (view analytics_current_pipeline), nie suma
    historycznych ruchów (§3.2 — kandydat cofnięty i ruszony ponownie
    liczył się wielokrotnie).
    """
    result = await db.execute(
        text(
            "SELECT stage, COUNT(*) AS cnt FROM analytics_current_pipeline "
            "GROUP BY stage"
        )
    )
    return {row.stage: row.cnt for row in result.all()}


@router.get("/recent-hires")
async def recent_hires(
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(8, ge=1, le=50),
):
    """Ostatnie zatrudnienia — dedykowany, typowany endpoint (plan PR 4 §3).

    Wcześniej frontend filtrował luźny activity feed po action == 'hired';
    tu źródłem jest kanoniczny view (pierwsze osiągnięcie `hired` per
    kandydat × job) + nazwiska/oferta/klient jednym zapytaniem.
    """
    rows = (
        (
            await db.execute(
                text(
                    """
                SELECT
                    fm.candidate_id,
                    fm.job_id,
                    fm.first_reached_at AS hired_at,
                    (c.name || ' ' || c.lastname) AS candidate_name,
                    j.title AS job_title,
                    cl.name AS client_name
                FROM analytics_first_milestones fm
                JOIN candidates c ON c.id = fm.candidate_id
                JOIN jobs j ON j.id = fm.job_id
                JOIN clients cl ON cl.id = j.client_id
                WHERE fm.stage = 'hired'
                ORDER BY fm.first_reached_at DESC
                LIMIT :limit
                """
                ),
                {"limit": limit},
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]
