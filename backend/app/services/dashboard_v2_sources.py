"""Adapters from canonical domain services into Dashboard v2.

This module contains no authorization fallback.  Every builder resolves its
scope through ``app.services.access_scope.resolve_dashboard_scope``.  The import
is intentionally lazy so this branch can be merged independently from the RBAC
branch, but a missing resolver fails closed at request time.

The adapters call existing analytics and domain functions instead of copying
their metric definitions into the dashboard layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fastapi import HTTPException, Request, status
from sqlalchemy import select, text, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import metrics
from app.analytics.periods import Period
from app.api import (
    admin_index_coverage,
    admin_schema_drift,
    admin_snapshot,
    admin_traffit,
    candidate_contact,
    contract_analytics,
    invoices,
    linkedin_metrics,
    priority_work,
)
from app.core.config import settings
from app.models.client import Client
from app.models.invoice import InvoiceDirection
from app.models.job import Job, JobStatus
from app.models.recruitment_priority import RecruitmentPriorityDemand
from app.models.user import User, UserRole
from app.schemas.dashboard_v2 import DashboardScopePayload


@dataclass(frozen=True)
class ResolvedDashboardScope:
    raw: Any
    payload: DashboardScopePayload


@dataclass(frozen=True)
class DeliveryJobSnapshot:
    client_id: int
    client_name: str
    job_id: int
    job_title: str
    priority: str
    open_vacancies: int
    tac_user_id: int | None
    created_at: datetime
    # Data otwarcia rekrutacji u klienta (0270). `None` = nie wiemy; wiek
    # liczony wtedy od `created_at` mierzyłby czas od importu, nie od startu.
    opened_at: datetime | None
    first_recommendation_at: datetime | None


@dataclass(frozen=True)
class DeliveryMetricsSnapshot:
    jobs: list[DeliveryJobSnapshot]
    placements: int


def _scope_kind(scope: Any) -> str:
    raw = scope.kind
    return raw.value if hasattr(raw, "value") else str(raw)


async def resolve_scope(user: User, db: AsyncSession) -> ResolvedDashboardScope:
    """Resolve and validate the shared RBAC scope, with no permissive fallback."""

    try:
        from app.services.access_scope import resolve_dashboard_scope
    except ImportError as exc:  # pragma: no cover - merge-order safety
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dashboard access-scope resolver is unavailable",
        ) from exc

    scope = await resolve_dashboard_scope(user, db)
    try:
        payload = DashboardScopePayload(
            kind=_scope_kind(scope),
            user_id=scope.user_id,
            client_ids=sorted(scope.allowed_client_ids),
            tac_user_ids=sorted(scope.allowed_tac_user_ids),
            operator_user_ids=sorted(scope.allowed_operator_user_ids),
            client_tac_pairs=[
                {"client_id": client_id, "tac_user_id": tac_user_id}
                for client_id, tac_user_id in sorted(scope.allowed_client_tac_pairs)
            ],
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dashboard access-scope resolver returned an invalid contract",
        ) from exc
    return ResolvedDashboardScope(raw=scope, payload=payload)


def require_scope(scope: ResolvedDashboardScope, *allowed: str) -> None:
    if scope.payload.kind not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Dashboard context is outside the resolved access scope",
        )


def narrow_to_self(
    user: User,
    scope: ResolvedDashboardScope,
) -> ResolvedDashboardScope:
    """Return only the current user's projection, including for superadmin.

    Admin resolves to organization scope globally, but the My Work preset is
    intentionally personal.  This transformation never retains organization
    IDs and never permits selecting another user.
    """

    if user.has_any_role(UserRole.finance, UserRole.user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="My Work is unavailable for exclusive non-recruitment roles",
        )
    if scope.payload.kind == "self" and scope.payload.user_id == user.id:
        return scope
    if user.has_role(UserRole.admin) or user.has_any_role(
        UserRole.tac,
        UserRole.recruiter,
        UserRole.sourcer,
    ):
        return ResolvedDashboardScope(
            raw=None,
            payload=DashboardScopePayload(
                kind="self",
                user_id=user.id,
                tac_user_ids=[user.id],
                operator_user_ids=[user.id],
            ),
        )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="My Work requires the current user's self scope",
    )


# ── Existing Admin Ops sources ───────────────────────────────────────────────


async def load_admin_snapshot(request: Request, db: AsyncSession) -> dict[str, Any]:
    return await admin_snapshot.admin_snapshot(request, auth_mode="jwt", db=db)


async def load_admin_schema_drift(db: AsyncSession) -> dict[str, Any]:
    return await admin_schema_drift.schema_drift(auth_mode="jwt", db=db)


async def load_admin_index_coverage(db: AsyncSession) -> dict[str, Any]:
    return await admin_index_coverage.index_coverage(auth_mode="jwt", db=db)


async def load_traffit_status(user: User, db: AsyncSession) -> dict[str, Any]:
    return await admin_traffit.traffit_sync_status(user, db)


async def load_priority_status(user: User, db: AsyncSession) -> dict[str, Any]:
    return await priority_work.get_priority_status(user, db)


async def load_priority_alerts(user: User, db: AsyncSession) -> list[dict[str, Any]]:
    return await priority_work.list_priority_alerts(user, db, include_resolved=False)


# ── Delivery sources ─────────────────────────────────────────────────────────


def _delivery_job_conditions(
    user: User,
    scope: ResolvedDashboardScope,
) -> list[Any]:
    conditions: list[Any] = [Job.status == JobStatus.published]
    if scope.payload.kind == "organization":
        return conditions

    # Defense in depth: the canonical Delivery Lead assignment is an exact set
    # of client–TAC relationships.  Filtering the client and TAC unions
    # independently would create a cartesian product and expose e.g. TAC B's
    # job for client A when only (A, TAC A) and (B, TAC B) are assigned.
    # Empty relationship scope means no rows, never "all".
    allowed_pairs = [
        (pair.client_id, pair.tac_user_id) for pair in scope.payload.client_tac_pairs
    ]
    conditions.append(
        tuple_(Job.client_id, Job.tac_id).in_(allowed_pairs or [(-1, -1)])
    )
    if scope.payload.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Delivery scope belongs to a different user",
        )
    return conditions


def _delivery_milestone_job_actor_pairs(
    job_rows: list[Any],
    scope: ResolvedDashboardScope,
) -> list[tuple[int, int]]:
    """Map each selected job to TACs assigned to that job's client.

    Keeping the job id and actor id paired prevents an actor assigned only to
    client B from contributing milestones to client A merely because both
    actors occur in the Delivery Lead's overall TAC union.
    """

    actors_by_client: dict[int, set[int]] = {}
    for pair in scope.payload.client_tac_pairs:
        actors_by_client.setdefault(pair.client_id, set()).add(pair.tac_user_id)

    return sorted(
        {
            (int(row.id), actor_id)
            for row in job_rows
            for actor_id in actors_by_client.get(int(row.client_id), set())
        }
    )


async def load_delivery_metrics(
    user: User,
    db: AsyncSession,
    period: Period,
    scope: ResolvedDashboardScope,
) -> DeliveryMetricsSnapshot:
    """Read delivery facts with client AND TAC/actor scope enforced server-side."""

    conditions = _delivery_job_conditions(user, scope)
    rows = (
        await db.execute(
            select(
                Job.id,
                Job.title,
                Job.priority,
                Job.headcount,
                Job.tac_id,
                Job.client_id,
                Job.created_at,
                Job.opened_at,
                Client.name.label("client_name"),
            )
            .join(Client, Client.id == Job.client_id)
            .where(*conditions)
            .order_by(Job.priority.desc(), Job.created_at)
        )
    ).all()
    job_ids = [int(row.id) for row in rows]

    first_recommendations: dict[int, datetime] = {}
    filled_vacancies: dict[int, int] = {}
    placements = 0
    if job_ids:
        job_actor_pairs = _delivery_milestone_job_actor_pairs(rows, scope)
        if scope.payload.kind == "organization" or job_actor_pairs:
            actor_clause = (
                ""
                if scope.payload.kind == "organization"
                else (
                    "AND (job_id, first_moved_by) IN ("
                    "SELECT allowed.job_id, allowed.actor_id "
                    "FROM UNNEST("
                    "CAST(:actor_job_ids AS integer[]), "
                    "CAST(:actor_ids AS integer[])"
                    ") AS allowed(job_id, actor_id)"
                    ")"
                )
            )
            params = {
                "job_ids": job_ids,
                "actor_job_ids": [job_id for job_id, _ in job_actor_pairs],
                "actor_ids": [actor_id for _, actor_id in job_actor_pairs],
                "start": period.start,
                "end": period.end,
            }
            rec_rows = (
                await db.execute(
                    text(
                        "SELECT job_id, MIN(first_reached_at) AS reached_at "
                        "FROM analytics_first_milestones "
                        "WHERE job_id = ANY(CAST(:job_ids AS integer[])) "
                        "AND stage = 'cv_sent' "
                        f"{actor_clause} "
                        "GROUP BY job_id"
                    ),
                    params,
                )
            ).all()
            first_recommendations = {
                int(row.job_id): row.reached_at for row in rec_rows
            }
            filled_rows = (
                await db.execute(
                    text(
                        "SELECT job_id, COUNT(*) AS placements "
                        "FROM analytics_first_milestones "
                        "WHERE job_id = ANY(CAST(:job_ids AS integer[])) "
                        "AND stage = 'hired' "
                        f"{actor_clause} "
                        "GROUP BY job_id"
                    ),
                    params,
                )
            ).all()
            filled_vacancies = {
                int(row.job_id): int(row.placements) for row in filled_rows
            }
            placements = int(
                (
                    await db.execute(
                        text(
                            "SELECT COUNT(*) "
                            "FROM analytics_first_milestones "
                            "WHERE job_id = ANY(CAST(:job_ids AS integer[])) "
                            "AND stage = 'hired' "
                            "AND first_reached_at >= :start "
                            "AND first_reached_at < :end "
                            f"{actor_clause}"
                        ),
                        params,
                    )
                ).scalar()
                or 0
            )

    jobs = [
        DeliveryJobSnapshot(
            client_id=int(row.client_id),
            client_name=row.client_name,
            job_id=int(row.id),
            job_title=row.title,
            priority=(
                row.priority.value
                if hasattr(row.priority, "value")
                else str(row.priority)
            ),
            open_vacancies=max(
                0,
                int(row.headcount or 0) - filled_vacancies.get(int(row.id), 0),
            ),
            tac_user_id=row.tac_id,
            created_at=row.created_at,
            opened_at=row.opened_at,
            first_recommendation_at=first_recommendations.get(int(row.id)),
        )
        for row in rows
    ]
    return DeliveryMetricsSnapshot(jobs=jobs, placements=placements)


async def load_delivery_demands(
    _user: User,
    db: AsyncSession,
    allowed_job_ids: set[int],
) -> list[dict[str, Any]]:
    if not allowed_job_ids:
        return []
    rows = (
        (
            await db.execute(
                select(RecruitmentPriorityDemand)
                .where(RecruitmentPriorityDemand.job_id.in_(allowed_job_ids))
                .order_by(RecruitmentPriorityDemand.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [await priority_work._serialize_demand(db, row) for row in rows]


# ── Recruitment sources ──────────────────────────────────────────────────────


async def load_team_priority_work(user: User, db: AsyncSession) -> dict[str, Any]:
    return await priority_work.get_team_priority_work(user, db)


async def load_contact_oversight(user: User, db: AsyncSession) -> dict[str, Any]:
    result = await candidate_contact.get_contact_oversight(
        user, cursor=None, limit=8, db=db
    )
    return result.model_dump(mode="python")


async def load_user_kpis(
    user_id: int, db: AsyncSession, period: Period
) -> dict[str, Any]:
    return await metrics.user_kpis(db, period, user_id)


def cloudtalk_calls_available() -> bool:
    return settings.CLOUDTALK_ENABLED


# ── My Work sources ──────────────────────────────────────────────────────────


async def load_my_priority_work(user: User, db: AsyncSession) -> dict[str, Any]:
    return await priority_work.get_my_priority_work(user, db)


async def load_contact_feature_status(user: User) -> dict[str, Any]:
    result = await candidate_contact.get_candidate_contact_status(user)
    return result.model_dump(mode="python")


async def load_my_contact_queue(user: User, db: AsyncSession) -> dict[str, Any]:
    result = await candidate_contact.get_my_contact_queue(
        user, cursor=None, limit=100, db=db
    )
    return result.model_dump(mode="python")


# ── Finance sources ──────────────────────────────────────────────────────────


async def load_finance_summary(
    db: AsyncSession, *, as_of
) -> tuple[dict[str, Any], list[str], str]:
    return await metrics.finance_summary(db, as_of=as_of)


def finance_as_of(period: Period):
    return metrics.finance_as_of(period)


async def load_finance_trend(
    db: AsyncSession, *, months: int = 12
) -> tuple[dict[str, Any], list[str], str]:
    return await metrics.finance_trend(db, months=months)


async def load_finance_clients(
    db: AsyncSession, *, as_of
) -> tuple[dict[str, Any], list[str], str]:
    return await metrics.finance_clients(db, as_of=as_of)


async def load_finance_dso(user: User, db: AsyncSession) -> list[Any]:
    return await invoices.dso_by_client(user, db)


async def load_overdue_invoices(user: User, db: AsyncSession) -> list[Any]:
    return await invoices.list_invoices(
        current_user=user,
        db=db,
        contract_id=None,
        status_filter=None,
        direction=InvoiceDirection.to_client,
        overdue_only=True,
    )


async def load_revenue_forecast(user: User, db: AsyncSession) -> Any:
    return await contract_analytics.revenue_forecast(
        current_user=user,
        db=db,
        horizon_months=3,
        convert_currency=True,
    )


# ── Statystyki rekrutacji (sekcja wspólna wszystkich presetów) ──────────────
#
# Dane są org-wide by design (decyzja właściciela 2026-08-07) — adaptery nie
# przyjmują scope'u. Autoryzację robi guard endpointu (OperationalUser).


async def load_recruitment_team_panel(db: AsyncSession, period: Period) -> Any:
    """Lejek per osoba + totals w kanonicznym oknie `[start, end)`."""
    from app.services.kpi_team import compute_team_panel

    return await compute_team_panel(
        db,
        bounds=(period.start, period.end),
        period_label=period.kind.value,
    )


async def load_quarterly_league(db: AsyncSession) -> dict[str, Any]:
    """Liga Mistrzów rekruterów — ZAWSZE bieżący kwartał (reguła konkursu),
    niezależnie od okresu sekcji."""
    from datetime import date as _date

    from app.services import competitions as comp
    from app.services.insights_scoring_config import (
        get_scoring_config,
        league_points_formula,
    )

    period = comp.current_quarter_period()
    ranked = await comp.quarterly_champions_recruiter(db, period)
    _config = await get_scoring_config(db)
    _year, _quarter = comp.parse_quarter(period)
    _required_placements = comp.required_placements_for_quarter(
        _year, _quarter, _config
    )
    return {
        "period": period,
        "days_remaining": comp.days_left_in_quarter(_date.today()),
        "points_formula": league_points_formula(_config),
        "prizes_pln": {str(k): v for k, v in comp.QUARTERLY_PRIZES_PLN.items()},
        # Ten sam tekst co /api/competitions/current?type=quarterly_champions_recruiter.
        # Prog jest PROGRESYWNY (1/2/3 wg miesiaca kwartalu) — napis musi mowic
        # to samo, co kwalifikacja. Plaskie „3" oswiadczalo w styczniu wymog,
        # ktorego silnik wtedy nie stosuje.
        "requirement": (
            f"Wymagane minimum {_required_placements} "
            f"{'placement' if _required_placements == 1 else 'placementów'} "
            "w kwartale (próg rośnie z każdym miesiącem kwartału)."
        ),
        "ranked": [r.to_dict() for r in ranked],
    }


async def load_monthly_races(db: AsyncSession) -> dict[str, Any]:
    """Oba wyścigi miesięczne — ta sama kompozycja co /api/competitions."""
    from app.services import competitions as comp

    return await comp.compose_monthly_races(db)


async def load_hall_of_fame(db: AsyncSession) -> dict[str, Any]:
    """All-time TOP 5 (live) + zamrożone podia ligi kwartalnej z historii."""
    from sqlalchemy import desc

    from app.models.competition_winner import CompetitionType, CompetitionWinner
    from app.services import competitions as comp

    all_time = await comp.hall_of_fame(db, limit=5)

    frozen = (
        await db.execute(
            select(CompetitionWinner, User.name.label("user_name"))
            .join(User, CompetitionWinner.user_id == User.id)
            .where(
                CompetitionWinner.competition_type
                == CompetitionType.quarterly_champions_recruiter.value
            )
            .order_by(desc(CompetitionWinner.period), CompetitionWinner.rank)
            .limit(12)  # 4 okresy × podium
        )
    ).all()
    history: dict[str, list[dict[str, Any]]] = {}
    for winner, user_name in frozen:
        history.setdefault(winner.period, []).append(
            {
                "rank": winner.rank,
                "user_id": winner.user_id,
                "name": user_name,
                "metric_value": winner.metric_value,
                "points": winner.points,
                "prize_pln": winner.prize_pln,
            }
        )
    return {
        "all_time": [r.to_dict() for r in all_time],
        "history": [
            {"period": period, "top3": history[period]}
            for period in sorted(history.keys(), reverse=True)
        ],
    }


async def load_linkedin_summary(db: AsyncSession, period: Period) -> dict[str, Any]:
    """Agregacja LinkedIn w kanonicznym oknie sekcji (kalendarz Warsaw).

    `linkedin_daily_metrics.report_date` to DATE, a filtr `compute_summary`
    jest domknięty z obu stron — end (exclusive datetime) mapujemy na
    ostatni dzień W oknie.
    """
    from datetime import timedelta

    date_from = period.start.date()
    date_to = (period.end - timedelta(microseconds=1)).date()
    per_user, totals = await linkedin_metrics.compute_summary(db, date_from, date_to)
    return {
        "date_from": date_from,
        "date_to": date_to,
        "per_user": per_user,
        "totals": totals,
    }


async def load_recruitment_trend(db: AsyncSession) -> Any:
    """Trend 12-mies. kamieni milowych (zawsze pełne okno, nie okres sekcji)."""
    from app.services.recruitment_trend import monthly_milestone_trend

    return await monthly_milestone_trend(db, months=12)
