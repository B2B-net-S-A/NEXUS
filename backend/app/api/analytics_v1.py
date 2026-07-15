"""Canonical, capability-gated analytics v1 API.

Mount this router at ``/api/analytics/v1``.  It intentionally contains no
legacy adapters; old dashboard/report endpoints can consume the same service
during their two-release deprecation window.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.capabilities import AnalyticsCapability
from app.analytics.cache import (
    analytics_cache_get,
    analytics_cache_key,
    analytics_cache_set,
    invalidate_analytics_cache,
)
from app.analytics.periods import (
    AnalyticsPeriod,
    AnalyticsPeriodKind,
    WARSAW,
    resolve_period,
)
from app.analytics.schemas import (
    AnalyticsEnvelope,
    AnalyticsPeriodSchema,
    AnalyticsQuality,
    AnalyticsQualityStatus,
    CallsData,
    ClientFinanceData,
    ClientOperationsData,
    DeliveryLeadPerformanceData,
    ExecutiveBoardData,
    FinanceClientsData,
    FinanceSummaryData,
    FinanceTrendData,
    FinancialAdjustmentCreate,
    FinancialAdjustmentRow,
    FinancialAdjustmentsData,
    FinancialAdjustmentStatus,
    MetricsMetaData,
    OverviewData,
    PersonalKpiData,
    PipelineSnapshotData,
    RecentHiresData,
    RecruitmentUserData,
    RecruitmentFunnelData,
    SourcesData,
    TeamCallsData,
    TeamKpisData,
    TendersData,
)
from app.analytics.scope import (
    delivery_lead_scope,
    require_client_scope,
    require_recruitment_user_scope,
    tender_client_scope,
)
from app.api.analytics_cutovers import router as analytics_cutovers_router
from app.api.deps import require_analytics_capabilities
from app.core.config import settings
from app.core.database import get_db
from app.models.user import User
from app.services.analytics_v1 import (
    AnalyticsManagerService,
    AnalyticsV1Service,
    FinancialAdjustmentConflictError,
    FinancialAdjustmentNotFoundError,
)


_CONTROL_PATH_PREFIXES = (
    "meta",
    "control",
    "cutovers",
    "admin/cutovers",
    "legacy-snapshots",
    "admin/legacy-snapshots",
)


def _analytics_module_candidates(path: str) -> tuple[str, ...]:
    prefix = "/api/analytics/v1/"
    relative = path[len(prefix) :] if path.startswith(prefix) else path.lstrip("/")
    if any(
        relative == control or relative.startswith(f"{control}/")
        for control in _CONTROL_PATH_PREFIXES
    ):
        return ()
    if relative == "overview":
        return ("overview",)
    if relative.startswith("pipeline/"):
        return ("pipeline",)
    if relative == "recruitment/funnel":
        # ``funnel`` remains an accepted rollout name for compatibility with
        # the first shadow configuration; ``recruitment`` is the canonical
        # module for all recruitment manager reads.
        return ("recruitment", "funnel")
    if relative.startswith("recruitment/"):
        return ("recruitment",)
    if relative == "sources":
        return ("sources",)
    if relative.startswith("calls/") or relative in {"me/calls", "team/calls"}:
        return ("calls",)
    if relative in {"me/kpis", "team/kpis"}:
        return ("kpis",)
    if relative.startswith("clients/"):
        return ("clients",)
    if relative.startswith("finance/"):
        return ("finance",)
    if relative.startswith("commercial/tenders"):
        return ("tenders",)
    if relative.startswith("delivery-leads/"):
        return ("delivery",)
    if relative.startswith("executive/"):
        return ("executive",)
    # Future routes fail closed unless their first segment is explicitly
    # enabled, preventing a newly-added surface from bypassing rollout gates.
    return (relative.split("/", 1)[0],) if relative else ()


async def require_enabled_analytics_module(request: Request) -> None:
    """Fail closed when the route's rollout module is not enabled."""

    required = _analytics_module_candidates(request.url.path)
    if not required:
        return
    enabled = {
        module.strip().lower()
        for module in settings.ANALYTICS_V1_MODULES.split(",")
        if module.strip()
    }
    if "*" in enabled or enabled.intersection(required):
        return
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "message": "Analytics module is disabled",
            "required_any": list(required),
            "enabled": sorted(enabled),
        },
    )


router = APIRouter(dependencies=[Depends(require_enabled_analytics_module)])
router.include_router(analytics_cutovers_router)


def analytics_period(
    period: AnalyticsPeriodKind = Query(AnalyticsPeriodKind.month),
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
) -> AnalyticsPeriod:
    """FastAPI dependency for canonical Warsaw half-open periods."""

    return resolve_period(period, date_from=date_from, date_to=date_to)


Period = Annotated[AnalyticsPeriod, Depends(analytics_period)]
Database = Annotated[AsyncSession, Depends(get_db)]
OperationalViewer = Annotated[
    User,
    Depends(
        require_analytics_capabilities(AnalyticsCapability.view_operational_aggregates)
    ),
]
PersonalKpiViewer = Annotated[
    User,
    Depends(
        require_analytics_capabilities(
            AnalyticsCapability.view_personal_recruitment_kpis,
            AnalyticsCapability.view_personal_delivery_kpis,
            require_all=False,
        )
    ),
]
RecruitmentTeamViewer = Annotated[
    User,
    Depends(require_analytics_capabilities(AnalyticsCapability.view_recruitment_team)),
]
ClientOperationsViewer = Annotated[
    User,
    Depends(require_analytics_capabilities(AnalyticsCapability.view_client_operations)),
]
FinanceViewer = Annotated[
    User,
    Depends(require_analytics_capabilities(AnalyticsCapability.view_finance)),
]
AnalyticsAdmin = Annotated[
    User,
    Depends(require_analytics_capabilities(AnalyticsCapability.manage_analytics)),
]
TenderViewer = Annotated[
    User,
    Depends(require_analytics_capabilities(AnalyticsCapability.view_tenders)),
]
RecruitmentDetailsViewer = Annotated[
    User,
    Depends(
        require_analytics_capabilities(
            AnalyticsCapability.view_personal_recruitment_kpis,
            AnalyticsCapability.view_recruitment_team,
            require_all=False,
        )
    ),
]


T = TypeVar("T")
_ANALYTICS_CACHE_TTL_SECONDS = 60
_ANALYTICS_FINANCE_CACHE_TTL_SECONDS = 30


def _envelope(
    data: T,
    *,
    period: AnalyticsPeriod,
    scope: str,
    generated_at: datetime,
    warnings: list[str] | None = None,
    quality_status: AnalyticsQualityStatus = AnalyticsQualityStatus.complete,
) -> AnalyticsEnvelope[T]:
    return AnalyticsEnvelope[T](
        generated_at=generated_at,
        scope=scope,
        period=AnalyticsPeriodSchema(
            kind=period.kind,
            start=period.start,
            end=period.end,
            timezone=period.timezone,
        ),
        quality=AnalyticsQuality(status=quality_status, warnings=warnings or []),
        data=data,
    )


def _cloudtalk_available() -> bool:
    return bool(
        settings.CLOUDTALK_ENABLED
        and settings.CLOUDTALK_API_KEY_ID
        and settings.CLOUDTALK_API_KEY_SECRET
        and settings.CLOUDTALK_WEBHOOK_SECRET
    )


def _unavailable_calls() -> CallsData:
    return CallsData(
        completed=None,
        inbound=None,
        outbound=None,
        total_duration_seconds=None,
        average_duration_seconds=None,
    )


@router.get("/overview", response_model=AnalyticsEnvelope[OverviewData])
async def overview(
    period: Period,
    user: OperationalViewer,
    db: Database,
) -> AnalyticsEnvelope[OverviewData]:
    """Organization-wide counts with no person, client or financial fields."""

    cache_key = analytics_cache_key(
        "overview",
        user=user,
        scope="organization_redacted",
        period=period,
    )
    cached = await analytics_cache_get(cache_key, AnalyticsEnvelope[OverviewData])
    if cached is not None:
        return cached
    generated_at = datetime.now(WARSAW)
    data = await AnalyticsV1Service(db).overview(
        period,
        generated_at=generated_at,
    )
    response = _envelope(
        data,
        period=period,
        scope="organization_redacted",
        generated_at=generated_at,
        warnings=(
            []
            if data.contracts.incomplete_date_data == 0
            else [
                f"{data.contracts.incomplete_date_data} active/ending contract(s) "
                "have no start date and are excluded from active totals."
            ]
        ),
        quality_status=(
            AnalyticsQualityStatus.complete
            if data.contracts.incomplete_date_data == 0
            else AnalyticsQualityStatus.partial
        ),
    )
    await analytics_cache_set(
        cache_key,
        response,
        ttl_seconds=_ANALYTICS_CACHE_TTL_SECONDS,
    )
    return response


@router.get(
    "/pipeline/snapshot", response_model=AnalyticsEnvelope[PipelineSnapshotData]
)
async def pipeline_snapshot(
    period: Period,
    user: OperationalViewer,
    db: Database,
) -> AnalyticsEnvelope[PipelineSnapshotData]:
    cache_key = analytics_cache_key(
        "pipeline.snapshot",
        user=user,
        scope="organization_redacted",
        period=period,
    )
    cached = await analytics_cache_get(
        cache_key,
        AnalyticsEnvelope[PipelineSnapshotData],
    )
    if cached is not None:
        return cached
    generated_at = datetime.now(WARSAW)
    data = await AnalyticsV1Service(db).pipeline_snapshot()
    response = _envelope(
        data,
        period=period,
        scope="organization_redacted",
        generated_at=generated_at,
        warnings=["Point-in-time snapshot; requested period is not applied."],
    )
    await analytics_cache_set(
        cache_key,
        response,
        ttl_seconds=_ANALYTICS_CACHE_TTL_SECONDS,
    )
    return response


@router.get(
    "/recruitment/funnel", response_model=AnalyticsEnvelope[RecruitmentFunnelData]
)
async def recruitment_funnel(
    period: Period,
    user: OperationalViewer,
    db: Database,
) -> AnalyticsEnvelope[RecruitmentFunnelData]:
    cache_key = analytics_cache_key(
        "recruitment.funnel",
        user=user,
        scope="organization_redacted",
        period=period,
    )
    cached = await analytics_cache_get(
        cache_key,
        AnalyticsEnvelope[RecruitmentFunnelData],
    )
    if cached is not None:
        return cached
    generated_at = datetime.now(WARSAW)
    data = await AnalyticsV1Service(db).recruitment_funnel(period)
    response = _envelope(
        data,
        period=period,
        scope="organization_redacted",
        generated_at=generated_at,
    )
    await analytics_cache_set(
        cache_key,
        response,
        ttl_seconds=_ANALYTICS_CACHE_TTL_SECONDS,
    )
    return response


@router.get(
    "/recruitment/recent-hires",
    response_model=AnalyticsEnvelope[RecentHiresData],
)
async def recent_hires(
    period: Period,
    user: RecruitmentTeamViewer,
    db: Database,
    limit: int = Query(10, ge=1, le=100),
) -> AnalyticsEnvelope[RecentHiresData]:
    cache_key = analytics_cache_key(
        "recruitment.recent_hires",
        user=user,
        scope="recruitment_team",
        period=period,
        params={"limit": limit},
    )
    cached = await analytics_cache_get(
        cache_key,
        AnalyticsEnvelope[RecentHiresData],
    )
    if cached is not None:
        return cached
    generated_at = datetime.now(WARSAW)
    data = await AnalyticsV1Service(db).recent_hires(period, limit=limit)
    response = _envelope(
        data,
        period=period,
        scope="recruitment_team",
        generated_at=generated_at,
    )
    await analytics_cache_set(
        cache_key,
        response,
        ttl_seconds=_ANALYTICS_CACHE_TTL_SECONDS,
    )
    return response


@router.get("/sources", response_model=AnalyticsEnvelope[SourcesData])
async def sources(
    period: Period,
    user: OperationalViewer,
    db: Database,
) -> AnalyticsEnvelope[SourcesData]:
    cache_key = analytics_cache_key(
        "sources",
        user=user,
        scope="organization_redacted",
        period=period,
    )
    cached = await analytics_cache_get(cache_key, AnalyticsEnvelope[SourcesData])
    if cached is not None:
        return cached
    generated_at = datetime.now(WARSAW)
    data = await AnalyticsV1Service(db).sources(period)
    response = _envelope(
        data,
        period=period,
        scope="organization_redacted",
        generated_at=generated_at,
    )
    await analytics_cache_set(
        cache_key,
        response,
        ttl_seconds=_ANALYTICS_CACHE_TTL_SECONDS,
    )
    return response


@router.get("/calls/aggregate", response_model=AnalyticsEnvelope[CallsData])
async def calls_aggregate(
    period: Period,
    user: OperationalViewer,
    db: Database,
) -> AnalyticsEnvelope[CallsData]:
    available = _cloudtalk_available()
    cache_key = analytics_cache_key(
        "calls.aggregate",
        user=user,
        scope="organization_redacted",
        period=period,
        params={"cloudtalk_available": available},
    )
    cached = await analytics_cache_get(cache_key, AnalyticsEnvelope[CallsData])
    if cached is not None:
        return cached
    generated_at = datetime.now(WARSAW)
    data = (
        await AnalyticsV1Service(db).calls(period)
        if available
        else _unavailable_calls()
    )
    response = _envelope(
        data,
        period=period,
        scope="organization_redacted",
        generated_at=generated_at,
        warnings=[] if available else ["CloudTalk is disabled or unconfigured."],
        quality_status=(
            AnalyticsQualityStatus.complete
            if available
            else AnalyticsQualityStatus.unavailable
        ),
    )
    await analytics_cache_set(
        cache_key,
        response,
        ttl_seconds=_ANALYTICS_CACHE_TTL_SECONDS,
    )
    return response


@router.get("/me/kpis", response_model=AnalyticsEnvelope[PersonalKpiData])
async def my_kpis(
    period: Period,
    user: PersonalKpiViewer,
    db: Database,
) -> AnalyticsEnvelope[PersonalKpiData]:
    calls_available = _cloudtalk_available()
    cache_key = analytics_cache_key(
        "kpis.personal",
        user=user,
        scope=f"self:{user.id}",
        period=period,
        params={
            "primary_role": user.role.value,
            "calls_available": calls_available,
        },
    )
    cached = await analytics_cache_get(
        cache_key,
        AnalyticsEnvelope[PersonalKpiData],
    )
    if cached is not None:
        return cached
    generated_at = datetime.now(WARSAW)
    data = await AnalyticsV1Service(db).personal_kpis(
        period,
        user_id=user.id,
        primary_role=user.role.value,
        generated_at=generated_at,
        calls_available=calls_available,
    )
    response = _envelope(
        data,
        period=period,
        scope="self",
        generated_at=generated_at,
        warnings=(
            []
            if data.calls_available
            else ["CloudTalk is disabled or unconfigured; call KPI is unavailable."]
        ),
        quality_status=(
            AnalyticsQualityStatus.complete
            if data.calls_available
            else AnalyticsQualityStatus.partial
        ),
    )
    await analytics_cache_set(
        cache_key,
        response,
        ttl_seconds=_ANALYTICS_CACHE_TTL_SECONDS,
    )
    return response


@router.get("/me/calls", response_model=AnalyticsEnvelope[CallsData])
async def my_calls(
    period: Period,
    user: PersonalKpiViewer,
    db: Database,
) -> AnalyticsEnvelope[CallsData]:
    available = _cloudtalk_available()
    cache_key = analytics_cache_key(
        "calls.personal",
        user=user,
        scope=f"self:{user.id}",
        period=period,
        params={"cloudtalk_available": available},
    )
    cached = await analytics_cache_get(cache_key, AnalyticsEnvelope[CallsData])
    if cached is not None:
        return cached
    generated_at = datetime.now(WARSAW)
    data = (
        await AnalyticsV1Service(db).calls(period, user_id=user.id)
        if available
        else _unavailable_calls()
    )
    response = _envelope(
        data,
        period=period,
        scope="self",
        generated_at=generated_at,
        warnings=[] if available else ["CloudTalk is disabled or unconfigured."],
        quality_status=(
            AnalyticsQualityStatus.complete
            if available
            else AnalyticsQualityStatus.unavailable
        ),
    )
    await analytics_cache_set(
        cache_key,
        response,
        ttl_seconds=_ANALYTICS_CACHE_TTL_SECONDS,
    )
    return response


@router.get("/team/kpis", response_model=AnalyticsEnvelope[TeamKpisData])
async def team_kpis(
    period: Period,
    user: RecruitmentTeamViewer,
    db: Database,
) -> AnalyticsEnvelope[TeamKpisData]:
    available = _cloudtalk_available()
    cache_key = analytics_cache_key(
        "kpis.team",
        user=user,
        scope="recruitment_team",
        period=period,
        params={"cloudtalk_available": available},
    )
    cached = await analytics_cache_get(cache_key, AnalyticsEnvelope[TeamKpisData])
    if cached is not None:
        return cached
    generated_at = datetime.now(WARSAW)
    data = await AnalyticsV1Service(db).team_kpis(
        period,
        generated_at=generated_at,
        calls_available=available,
    )
    response = _envelope(
        data,
        period=period,
        scope="recruitment_team",
        generated_at=generated_at,
        warnings=(
            []
            if available
            else ["CloudTalk is disabled or unconfigured; call KPI is unavailable."]
        ),
        quality_status=(
            AnalyticsQualityStatus.complete
            if available
            else AnalyticsQualityStatus.partial
        ),
    )
    await analytics_cache_set(
        cache_key,
        response,
        ttl_seconds=_ANALYTICS_CACHE_TTL_SECONDS,
    )
    return response


@router.get("/team/calls", response_model=AnalyticsEnvelope[TeamCallsData])
async def team_calls(
    period: Period,
    user: RecruitmentTeamViewer,
    db: Database,
) -> AnalyticsEnvelope[TeamCallsData]:
    available = _cloudtalk_available()
    cache_key = analytics_cache_key(
        "calls.team",
        user=user,
        scope="recruitment_team",
        period=period,
        params={"cloudtalk_available": available},
    )
    cached = await analytics_cache_get(cache_key, AnalyticsEnvelope[TeamCallsData])
    if cached is not None:
        return cached
    generated_at = datetime.now(WARSAW)
    data = (
        await AnalyticsV1Service(db).team_calls(period)
        if available
        else TeamCallsData(users=[])
    )
    response = _envelope(
        data,
        period=period,
        scope="recruitment_team",
        generated_at=generated_at,
        warnings=[] if available else ["CloudTalk is disabled or unconfigured."],
        quality_status=(
            AnalyticsQualityStatus.complete
            if available
            else AnalyticsQualityStatus.unavailable
        ),
    )
    await analytics_cache_set(
        cache_key,
        response,
        ttl_seconds=_ANALYTICS_CACHE_TTL_SECONDS,
    )
    return response


@router.get("/meta/metrics", response_model=AnalyticsEnvelope[MetricsMetaData])
async def metric_definitions(
    period: Period,
    _user: OperationalViewer,
) -> AnalyticsEnvelope[MetricsMetaData]:
    generated_at = datetime.now(WARSAW)
    return _envelope(
        AnalyticsV1Service.metric_definitions(),
        period=period,
        scope="system",
        generated_at=generated_at,
        warnings=["Metric definitions are not period-dependent."],
    )


# ── Manager, client and finance endpoints ──────────────────────────────────


@router.get(
    "/clients/{client_id}/operations",
    response_model=AnalyticsEnvelope[ClientOperationsData],
)
async def client_operations(
    client_id: int,
    period: Period,
    user: ClientOperationsViewer,
    db: Database,
) -> AnalyticsEnvelope[ClientOperationsData]:
    await require_client_scope(db, user=user, client_id=client_id, finance=False)
    cache_scope = f"client:{client_id}:operations"
    cache_key = analytics_cache_key(
        "clients.operations",
        user=user,
        scope=cache_scope,
        period=period,
        params={"client_id": client_id},
    )
    cached = await analytics_cache_get(
        cache_key,
        AnalyticsEnvelope[ClientOperationsData],
    )
    if cached is not None:
        return cached
    generated_at = datetime.now(WARSAW)
    data = await AnalyticsManagerService(db).client_operations(
        period,
        client_id=client_id,
        generated_at=generated_at,
    )
    response = _envelope(
        data,
        period=period,
        scope=cache_scope,
        generated_at=generated_at,
    )
    await analytics_cache_set(
        cache_key,
        response,
        ttl_seconds=_ANALYTICS_CACHE_TTL_SECONDS,
    )
    return response


@router.get(
    "/clients/{client_id}/finance",
    response_model=AnalyticsEnvelope[ClientFinanceData],
)
async def client_finance(
    client_id: int,
    period: Period,
    user: FinanceViewer,
    db: Database,
) -> AnalyticsEnvelope[ClientFinanceData]:
    await require_client_scope(db, user=user, client_id=client_id, finance=True)
    cache_scope = f"client:{client_id}:finance"
    cache_key = analytics_cache_key(
        "clients.finance",
        user=user,
        scope=cache_scope,
        period=period,
        params={"client_id": client_id},
    )
    cached = await analytics_cache_get(
        cache_key,
        AnalyticsEnvelope[ClientFinanceData],
    )
    if cached is not None:
        return cached
    generated_at = datetime.now(WARSAW)
    result = await AnalyticsManagerService(db).client_finance(
        period,
        client_id=client_id,
        generated_at=generated_at,
    )
    response = _envelope(
        result.data,
        period=period,
        scope=cache_scope,
        generated_at=generated_at,
        warnings=list(result.warnings),
        quality_status=result.quality_status,
    )
    await analytics_cache_set(
        cache_key,
        response,
        ttl_seconds=_ANALYTICS_FINANCE_CACHE_TTL_SECONDS,
    )
    return response


@router.get(
    "/finance/summary",
    response_model=AnalyticsEnvelope[FinanceSummaryData],
)
async def finance_summary(
    period: Period,
    user: FinanceViewer,
    db: Database,
) -> AnalyticsEnvelope[FinanceSummaryData]:
    cache_key = analytics_cache_key(
        "finance.summary",
        user=user,
        scope="organization_finance",
        period=period,
    )
    cached = await analytics_cache_get(
        cache_key,
        AnalyticsEnvelope[FinanceSummaryData],
    )
    if cached is not None:
        return cached
    generated_at = datetime.now(WARSAW)
    result = await AnalyticsManagerService(db).finance_summary(
        period, generated_at=generated_at
    )
    response = _envelope(
        result.data,
        period=period,
        scope="organization_finance",
        generated_at=generated_at,
        warnings=list(result.warnings),
        quality_status=result.quality_status,
    )
    await analytics_cache_set(
        cache_key,
        response,
        ttl_seconds=_ANALYTICS_FINANCE_CACHE_TTL_SECONDS,
    )
    return response


@router.get(
    "/finance/trend",
    response_model=AnalyticsEnvelope[FinanceTrendData],
)
async def finance_trend(
    period: Period,
    user: FinanceViewer,
    db: Database,
) -> AnalyticsEnvelope[FinanceTrendData]:
    cache_key = analytics_cache_key(
        "finance.trend",
        user=user,
        scope="organization_finance",
        period=period,
    )
    cached = await analytics_cache_get(
        cache_key,
        AnalyticsEnvelope[FinanceTrendData],
    )
    if cached is not None:
        return cached
    generated_at = datetime.now(WARSAW)
    result = await AnalyticsManagerService(db).finance_trend(period)
    response = _envelope(
        result.data,
        period=period,
        scope="organization_finance",
        generated_at=generated_at,
        warnings=list(result.warnings),
        quality_status=result.quality_status,
    )
    await analytics_cache_set(
        cache_key,
        response,
        ttl_seconds=_ANALYTICS_FINANCE_CACHE_TTL_SECONDS,
    )
    return response


@router.get(
    "/finance/clients",
    response_model=AnalyticsEnvelope[FinanceClientsData],
)
async def finance_clients(
    period: Period,
    user: FinanceViewer,
    db: Database,
) -> AnalyticsEnvelope[FinanceClientsData]:
    cache_key = analytics_cache_key(
        "finance.clients",
        user=user,
        scope="organization_finance",
        period=period,
    )
    cached = await analytics_cache_get(
        cache_key,
        AnalyticsEnvelope[FinanceClientsData],
    )
    if cached is not None:
        return cached
    generated_at = datetime.now(WARSAW)
    result = await AnalyticsManagerService(db).finance_clients(
        period, generated_at=generated_at
    )
    response = _envelope(
        result.data,
        period=period,
        scope="organization_finance",
        generated_at=generated_at,
        warnings=list(result.warnings),
        quality_status=result.quality_status,
    )
    await analytics_cache_set(
        cache_key,
        response,
        ttl_seconds=_ANALYTICS_FINANCE_CACHE_TTL_SECONDS,
    )
    return response


@router.get(
    "/finance/adjustments",
    response_model=AnalyticsEnvelope[FinancialAdjustmentsData],
)
async def financial_adjustments(
    period: Period,
    user: FinanceViewer,
    db: Database,
    adjustment_status: FinancialAdjustmentStatus | None = Query(
        None,
        alias="status",
    ),
    limit: int = Query(200, ge=1, le=500),
) -> AnalyticsEnvelope[FinancialAdjustmentsData]:
    cache_key = analytics_cache_key(
        "finance.adjustments",
        user=user,
        scope="organization_finance",
        period=period,
        params={
            "status": adjustment_status.value if adjustment_status else None,
            "limit": limit,
        },
    )
    cached = await analytics_cache_get(
        cache_key,
        AnalyticsEnvelope[FinancialAdjustmentsData],
    )
    if cached is not None:
        return cached
    generated_at = datetime.now(WARSAW)
    data = await AnalyticsManagerService(db).financial_adjustments(
        period,
        adjustment_status=(
            adjustment_status.value if adjustment_status is not None else None
        ),
        limit=limit,
    )
    response = _envelope(
        data,
        period=period,
        scope="organization_finance",
        generated_at=generated_at,
    )
    await analytics_cache_set(
        cache_key,
        response,
        ttl_seconds=_ANALYTICS_FINANCE_CACHE_TTL_SECONDS,
    )
    return response


@router.post(
    "/finance/adjustments",
    response_model=AnalyticsEnvelope[FinancialAdjustmentRow],
    status_code=status.HTTP_201_CREATED,
)
async def create_financial_adjustment(
    payload: FinancialAdjustmentCreate,
    period: Period,
    user: AnalyticsAdmin,
    db: Database,
) -> AnalyticsEnvelope[FinancialAdjustmentRow]:
    generated_at = datetime.now(WARSAW)
    data = await AnalyticsManagerService(db).create_financial_adjustment(
        payload,
        created_by_user_id=user.id,
    )
    # Commit before invalidation so another request cannot repopulate the
    # cache from pre-mutation data in the auto-commit gap of ``get_db``.
    await db.commit()
    await invalidate_analytics_cache()
    return _envelope(
        data,
        period=period,
        scope="organization_finance_admin",
        generated_at=generated_at,
        warnings=["Draft adjustment is excluded from finance totals until approved."],
    )


@router.post(
    "/finance/adjustments/{adjustment_id}/approve",
    response_model=AnalyticsEnvelope[FinancialAdjustmentRow],
)
async def approve_financial_adjustment(
    adjustment_id: int,
    period: Period,
    user: AnalyticsAdmin,
    db: Database,
) -> AnalyticsEnvelope[FinancialAdjustmentRow]:
    generated_at = datetime.now(WARSAW)
    try:
        data = await AnalyticsManagerService(db).approve_financial_adjustment(
            adjustment_id,
            approved_by_user_id=user.id,
        )
    except FinancialAdjustmentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except FinancialAdjustmentConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    await db.commit()
    await invalidate_analytics_cache()
    return _envelope(
        data,
        period=period,
        scope="organization_finance_admin",
        generated_at=generated_at,
    )


@router.get(
    "/commercial/tenders",
    response_model=AnalyticsEnvelope[TendersData],
)
async def commercial_tenders(
    period: Period,
    user: TenderViewer,
    db: Database,
    limit: int = Query(200, ge=1, le=500),
) -> AnalyticsEnvelope[TendersData]:
    client_ids = await tender_client_scope(db, user=user)
    resolved_scope = (
        "organization_tenders"
        if client_ids is None
        else "assigned_tenders:" + ",".join(str(value) for value in sorted(client_ids))
    )
    cache_key = analytics_cache_key(
        "commercial.tenders",
        user=user,
        scope=resolved_scope,
        period=period,
        params={"limit": limit},
    )
    cached = await analytics_cache_get(cache_key, AnalyticsEnvelope[TendersData])
    if cached is not None:
        return cached
    generated_at = datetime.now(WARSAW)
    data = await AnalyticsManagerService(db).tenders(
        period,
        client_ids=client_ids,
        limit=limit,
    )
    scope = "organization_tenders" if client_ids is None else "assigned_tenders"
    response = _envelope(
        data,
        period=period,
        scope=scope,
        generated_at=generated_at,
    )
    await analytics_cache_set(
        cache_key,
        response,
        ttl_seconds=_ANALYTICS_CACHE_TTL_SECONDS,
    )
    return response


@router.get(
    "/delivery-leads/performance",
    response_model=AnalyticsEnvelope[DeliveryLeadPerformanceData],
)
async def delivery_lead_performance(
    period: Period,
    user: ClientOperationsViewer,
    db: Database,
) -> AnalyticsEnvelope[DeliveryLeadPerformanceData]:
    delivery_lead_ids = await delivery_lead_scope(db, user=user)
    resolved_scope = (
        "delivery_organization"
        if delivery_lead_ids is None
        else "assigned_delivery_leads:"
        + ",".join(str(value) for value in sorted(delivery_lead_ids))
    )
    cache_key = analytics_cache_key(
        "delivery.performance",
        user=user,
        scope=resolved_scope,
        period=period,
    )
    cached = await analytics_cache_get(
        cache_key,
        AnalyticsEnvelope[DeliveryLeadPerformanceData],
    )
    if cached is not None:
        return cached
    generated_at = datetime.now(WARSAW)
    data = await AnalyticsManagerService(db).delivery_leads(
        period, delivery_lead_ids=delivery_lead_ids
    )
    scope = (
        "delivery_organization"
        if delivery_lead_ids is None
        else "assigned_delivery_leads"
    )
    response = _envelope(
        data,
        period=period,
        scope=scope,
        generated_at=generated_at,
    )
    await analytics_cache_set(
        cache_key,
        response,
        ttl_seconds=_ANALYTICS_CACHE_TTL_SECONDS,
    )
    return response


@router.get(
    "/recruitment/users/{user_id}",
    response_model=AnalyticsEnvelope[RecruitmentUserData],
)
async def recruitment_user_details(
    user_id: int,
    period: Period,
    viewer: RecruitmentDetailsViewer,
    db: Database,
) -> AnalyticsEnvelope[RecruitmentUserData]:
    target = await require_recruitment_user_scope(
        db,
        viewer=viewer,
        target_user_id=user_id,
    )
    calls_available = _cloudtalk_available()
    cache_key = analytics_cache_key(
        "recruitment.user",
        user=viewer,
        scope=f"recruitment_user:{target.id}",
        period=period,
        params={
            "target_primary_role": target.role.value,
            "calls_available": calls_available,
        },
    )
    cached = await analytics_cache_get(
        cache_key,
        AnalyticsEnvelope[RecruitmentUserData],
    )
    if cached is not None:
        return cached
    generated_at = datetime.now(WARSAW)
    data = await AnalyticsManagerService(db).recruitment_user(
        period,
        target=target,
        generated_at=generated_at,
        calls_available=calls_available,
    )
    response = _envelope(
        data,
        period=period,
        scope=f"recruitment_user:{user_id}",
        generated_at=generated_at,
        warnings=(
            []
            if data.kpis.calls_available
            else ["CloudTalk is disabled or unconfigured; call KPI is unavailable."]
        ),
        quality_status=(
            AnalyticsQualityStatus.complete
            if data.kpis.calls_available
            else AnalyticsQualityStatus.partial
        ),
    )
    await analytics_cache_set(
        cache_key,
        response,
        ttl_seconds=_ANALYTICS_CACHE_TTL_SECONDS,
    )
    return response


@router.get(
    "/executive/board",
    response_model=AnalyticsEnvelope[ExecutiveBoardData],
)
async def executive_board(
    period: Period,
    user: FinanceViewer,
    db: Database,
) -> AnalyticsEnvelope[ExecutiveBoardData]:
    cache_key = analytics_cache_key(
        "executive.board",
        user=user,
        scope="organization_executive",
        period=period,
    )
    cached = await analytics_cache_get(
        cache_key,
        AnalyticsEnvelope[ExecutiveBoardData],
    )
    if cached is not None:
        return cached
    generated_at = datetime.now(WARSAW)
    manager = AnalyticsManagerService(db)
    overview_data = await AnalyticsV1Service(db).overview(
        period,
        generated_at=generated_at,
    )
    finance_result = await manager.finance_summary(period, generated_at=generated_at)
    tender_data = await manager.tenders(period, client_ids=None, limit=200)
    overview_warning = (
        []
        if overview_data.contracts.incomplete_date_data == 0
        else [
            f"{overview_data.contracts.incomplete_date_data} active/ending "
            "contract(s) have no start date and are excluded from active totals."
        ]
    )
    board_quality = finance_result.quality_status
    if (
        board_quality is AnalyticsQualityStatus.complete
        and overview_data.contracts.incomplete_date_data
    ):
        board_quality = AnalyticsQualityStatus.partial
    response = _envelope(
        ExecutiveBoardData(
            overview=overview_data,
            finance=finance_result.data,
            tenders=tender_data,
        ),
        period=period,
        scope="organization_executive",
        generated_at=generated_at,
        warnings=[*finance_result.warnings, *overview_warning],
        quality_status=board_quality,
    )
    await analytics_cache_set(
        cache_key,
        response,
        ttl_seconds=_ANALYTICS_FINANCE_CACHE_TTL_SECONDS,
    )
    return response
