"""Analytics v1 — wersjonowany kontrakt statystyk (plan §4.4, PR 3).

Wszystkie endpointy:
- zwracają wspólną kopertę (app.analytics.schemas, §4.5),
- są gate'owane capabilities (app.analytics.capabilities, §4.3),
- liczą WYŁĄCZNIE przez kanoniczne metryki (app.analytics.metrics, §4.2),
- cache'ują pod kluczem z kontraktem §4.6 (capability set w kluczu),
- respektują ANALYTICS_V1_MODE: off → 503 (feature nieaktywna),
  shadow/live → serwują (shadow nie zmienia ŻADNEJ legacy odpowiedzi —
  stare endpointy pozostają nietknięte aż do cutoveru).

Propagacja quality: wyłączony CloudTalk ⇒ rozmowy quality=unavailable;
waluty ≠ PLN bez kursu ⇒ finanse partial z warningiem (pełny FX = PR 6).
"""

from __future__ import annotations

from datetime import date
from datetime import date as date_type
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import metrics
from app.analytics.cache import (
    METRIC_VERSION,
    analytics_cache_get,
    analytics_cache_set,
    build_cache_key,
)
from app.analytics.capabilities import (
    AnalyticsCapability,
    capabilities_for,
    require_capability,
    user_has_capability,
)
from app.analytics.periods import Period, PeriodError, resolve_period
from app.analytics.schemas import (
    AnalyticsEnvelope,
    QualityPayload,
    QualityStatus,
    build_envelope,
)
from app.analytics.scope import (
    Scope,
    ensure_client_scope,
    ensure_user_scope,
    organization_scope,
)
from app.api.deps import CurrentUser
from app.core.config import settings
from app.core.database import get_db
from app.models.user import User

router = APIRouter()

_CACHE_TTL_SECONDS = 120


def _require_enabled() -> None:
    """Gate trybu rolloutu. UWAGA: to NIE jest guard bezpieczeństwa —
    RBAC/capabilities działają niezależnie i są niewyłączalne (R0)."""
    if settings.ANALYTICS_V1_MODE == "off":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Analytics v1 nie jest aktywne (ANALYTICS_V1_MODE=off)",
        )


async def _analytics_enabled() -> None:
    _require_enabled()


def _parse_period(
    period: str = Query("month"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
) -> Period:
    try:
        return resolve_period(period, date_from=date_from, date_to=date_to)
    except PeriodError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


def _calls_quality() -> QualityPayload:
    """CloudTalk off/misconfigured ⇒ unavailable — NIGDY 'zero rozmów'."""
    if not settings.CLOUDTALK_ENABLED:
        return QualityPayload(
            status=QualityStatus.unavailable,
            warnings=[
                "CloudTalk wyłączony (CLOUDTALK_ENABLED=false) — dane o "
                "rozmowach są niedostępne, nie zerowe"
            ],
        )
    return QualityPayload()


async def _cached_envelope(
    *,
    endpoint: str,
    user: User,
    scope: Scope,
    period: Period,
    compute,
    quality: QualityPayload | None = None,
    filters: dict[str, Any] | None = None,
) -> AnalyticsEnvelope:
    """Wspólny szkielet: cache (§4.6) → kanoniczna metryka → koperta (§4.5).

    ``compute`` może zwrócić dict (dane) ALBO krotkę (dane, QualityPayload) —
    quality liczone w compute jest cache'owane razem z kopertą, więc cache
    hit nie przelicza metryk.
    """
    caps = capabilities_for(user)
    key = build_cache_key(
        endpoint, capabilities=caps, scope=scope, period=period, filters=filters
    )
    cached = await analytics_cache_get(key)
    if cached is not None:
        try:
            return AnalyticsEnvelope(**cached)
        except ValidationError:
            # Niekompatybilny wpis (np. stara wersja koperty po deployu) —
            # traktuj jak cache miss i przelicz zamiast 500.
            pass
    result = await compute()
    if isinstance(result, tuple):
        data, quality = result
    else:
        data = result
    envelope = build_envelope(
        metric_version=METRIC_VERSION,
        scope=scope.as_payload(),
        period=period.as_payload(),
        data=data,
        quality=quality,
    )
    await analytics_cache_set(key, envelope.model_dump(mode="json"), _CACHE_TTL_SECONDS)
    return envelope


# ── Viewer-safe (§4.4) — VIEW_OPERATIONAL_AGGREGATES ─────────────────────────


@router.get("/overview", response_model=AnalyticsEnvelope)
async def get_overview(
    current_user: User = Depends(
        require_capability(AnalyticsCapability.VIEW_OPERATIONAL_AGGREGATES)
    ),
    _: None = Depends(_analytics_enabled),
    period: Period = Depends(_parse_period),
    db: AsyncSession = Depends(get_db),
):
    return await _cached_envelope(
        endpoint="overview",
        user=current_user,
        scope=organization_scope(),
        period=period,
        compute=lambda: metrics.overview(db, period),
    )


@router.get("/pipeline/snapshot", response_model=AnalyticsEnvelope)
async def get_pipeline_snapshot(
    current_user: User = Depends(
        require_capability(AnalyticsCapability.VIEW_OPERATIONAL_AGGREGATES)
    ),
    _: None = Depends(_analytics_enabled),
    period: Period = Depends(_parse_period),
    db: AsyncSession = Depends(get_db),
):
    return await _cached_envelope(
        endpoint="pipeline-snapshot",
        user=current_user,
        scope=organization_scope(),
        period=period,
        compute=lambda: metrics.pipeline_snapshot(db),
    )


@router.get("/recruitment/funnel", response_model=AnalyticsEnvelope)
async def get_recruitment_funnel(
    current_user: User = Depends(
        require_capability(AnalyticsCapability.VIEW_OPERATIONAL_AGGREGATES)
    ),
    _: None = Depends(_analytics_enabled),
    period: Period = Depends(_parse_period),
    db: AsyncSession = Depends(get_db),
):
    return await _cached_envelope(
        endpoint="recruitment-funnel",
        user=current_user,
        scope=organization_scope(),
        period=period,
        compute=lambda: metrics.recruitment_funnel(db, period),
    )


@router.get("/sources", response_model=AnalyticsEnvelope)
async def get_sources(
    current_user: User = Depends(
        require_capability(AnalyticsCapability.VIEW_OPERATIONAL_AGGREGATES)
    ),
    _: None = Depends(_analytics_enabled),
    period: Period = Depends(_parse_period),
    db: AsyncSession = Depends(get_db),
):
    return await _cached_envelope(
        endpoint="sources",
        user=current_user,
        scope=organization_scope(),
        period=period,
        compute=lambda: metrics.sources(db, period),
    )


@router.get("/calls/aggregate", response_model=AnalyticsEnvelope)
async def get_calls_aggregate(
    current_user: User = Depends(
        require_capability(AnalyticsCapability.VIEW_OPERATIONAL_AGGREGATES)
    ),
    _: None = Depends(_analytics_enabled),
    period: Period = Depends(_parse_period),
    db: AsyncSession = Depends(get_db),
):
    return await _cached_envelope(
        endpoint="calls-aggregate",
        user=current_user,
        scope=organization_scope(),
        period=period,
        compute=lambda: metrics.calls_aggregate(db, period),
        quality=_calls_quality(),
    )


# ── Osobiste ─────────────────────────────────────────────────────────────────


@router.get("/me/kpis", response_model=AnalyticsEnvelope)
async def get_my_kpis(
    current_user: CurrentUser,
    _: None = Depends(_analytics_enabled),
    period: Period = Depends(_parse_period),
    db: AsyncSession = Depends(get_db),
):
    """Własne KPI — dostępne dla każdego zalogowanego (zakres = self)."""
    scope = ensure_user_scope(current_user, current_user.id)
    return await _cached_envelope(
        endpoint="me-kpis",
        user=current_user,
        scope=scope,
        period=period,
        compute=lambda: metrics.user_kpis(db, period, current_user.id),
        quality=_calls_quality(),
    )


@router.get("/me/calls", response_model=AnalyticsEnvelope)
async def get_my_calls(
    current_user: CurrentUser,
    _: None = Depends(_analytics_enabled),
    period: Period = Depends(_parse_period),
    db: AsyncSession = Depends(get_db),
):
    scope = ensure_user_scope(current_user, current_user.id)
    return await _cached_envelope(
        endpoint="me-calls",
        user=current_user,
        scope=scope,
        period=period,
        compute=lambda: metrics.calls_aggregate(db, period, user_id=current_user.id),
        quality=_calls_quality(),
    )


# ── Managerskie — VIEW_TEAM_KPI ──────────────────────────────────────────────


@router.get("/team/kpis", response_model=AnalyticsEnvelope)
async def get_team_kpis(
    current_user: User = Depends(require_capability(AnalyticsCapability.VIEW_TEAM_KPI)),
    _: None = Depends(_analytics_enabled),
    period: Period = Depends(_parse_period),
    db: AsyncSession = Depends(get_db),
):
    return await _cached_envelope(
        endpoint="team-kpis",
        user=current_user,
        scope=organization_scope(),
        period=period,
        compute=lambda: metrics.team_kpis(db, period),
        quality=_calls_quality(),
    )


@router.get("/team/calls", response_model=AnalyticsEnvelope)
async def get_team_calls(
    current_user: User = Depends(require_capability(AnalyticsCapability.VIEW_TEAM_KPI)),
    _: None = Depends(_analytics_enabled),
    period: Period = Depends(_parse_period),
    db: AsyncSession = Depends(get_db),
):
    async def _compute():
        team = await metrics.team_kpis(db, period)
        return {
            "rows": [
                {
                    "user_id": r["user_id"],
                    "user_name": r["user_name"],
                    "completed_calls": r["completed_calls"],
                }
                for r in team["rows"]
            ],
            "total_completed_calls": team["totals"]["completed_calls"],
        }

    return await _cached_envelope(
        endpoint="team-calls",
        user=current_user,
        scope=organization_scope(),
        period=period,
        compute=_compute,
        quality=_calls_quality(),
    )


@router.get("/recruitment/users/{user_id}", response_model=AnalyticsEnvelope)
async def get_user_recruitment(
    user_id: int,
    current_user: CurrentUser,
    _: None = Depends(_analytics_enabled),
    period: Period = Depends(_parse_period),
    db: AsyncSession = Depends(get_db),
):
    """KPI wskazanego usera: self zawsze; cudze — VIEW_TEAM_KPI (scope.py)."""
    scope = ensure_user_scope(current_user, user_id)
    return await _cached_envelope(
        endpoint="user-recruitment",
        user=current_user,
        scope=scope,
        period=period,
        compute=lambda: metrics.user_kpis(db, period, user_id),
        quality=_calls_quality(),
    )


# ── Klienci ──────────────────────────────────────────────────────────────────


@router.get("/clients/{client_id}/operations", response_model=AnalyticsEnvelope)
async def get_client_operations(
    client_id: int,
    current_user: User = Depends(
        require_capability(AnalyticsCapability.VIEW_CLIENT_OPERATIONS)
    ),
    _: None = Depends(_analytics_enabled),
    period: Period = Depends(_parse_period),
    db: AsyncSession = Depends(get_db),
):
    scope = await ensure_client_scope(db, current_user, client_id)
    return await _cached_envelope(
        endpoint="client-operations",
        user=current_user,
        scope=scope,
        period=period,
        compute=lambda: metrics.client_operations(db, period, client_id),
    )


@router.get("/clients/{client_id}/finance", response_model=AnalyticsEnvelope)
async def get_client_finance(
    client_id: int,
    current_user: User = Depends(require_capability(AnalyticsCapability.VIEW_FINANCE)),
    _: None = Depends(_analytics_enabled),
    period: Period = Depends(_parse_period),
    db: AsyncSession = Depends(get_db),
):
    scope = await ensure_client_scope(db, current_user, client_id)

    async def _compute():
        data, warnings, flag = await metrics.client_finance(db, client_id)
        return data, _finance_quality(warnings, flag)

    return await _cached_envelope(
        endpoint="client-finance",
        user=current_user,
        scope=scope,
        period=period,
        compute=_compute,
    )


def _finance_quality(warnings: list[str], flag: str = "complete") -> QualityPayload:
    if flag == "unavailable":
        status = QualityStatus.unavailable
    elif warnings or flag == "partial":
        status = QualityStatus.partial
    else:
        status = QualityStatus.complete
    return QualityPayload(status=status, warnings=warnings)


# ── Finanse i zarząd — VIEW_FINANCE ──────────────────────────────────────────


@router.get("/finance/summary", response_model=AnalyticsEnvelope)
async def get_finance_summary(
    current_user: User = Depends(require_capability(AnalyticsCapability.VIEW_FINANCE)),
    _: None = Depends(_analytics_enabled),
    period: Period = Depends(_parse_period),
    db: AsyncSession = Depends(get_db),
):
    async def _compute():
        data, warnings, flag = await metrics.finance_summary(db)
        return data, _finance_quality(warnings, flag)

    return await _cached_envelope(
        endpoint="finance-summary",
        user=current_user,
        scope=organization_scope(),
        period=period,
        compute=_compute,
    )


@router.get("/finance/trend", response_model=AnalyticsEnvelope)
async def get_finance_trend(
    current_user: User = Depends(require_capability(AnalyticsCapability.VIEW_FINANCE)),
    _: None = Depends(_analytics_enabled),
    period: Period = Depends(_parse_period),
    months: int = Query(12, ge=1, le=36),
    db: AsyncSession = Depends(get_db),
):
    """Miesięczny trend MRR/marży — date-effective na 1. dzień miesiąca,
    prawdziwa arytmetyka kalendarza, FX po kursie z danej daty (plan PR 6)."""

    async def _compute():
        data, warnings, flag = await metrics.finance_trend(db, months=months)
        return data, _finance_quality(warnings, flag)

    return await _cached_envelope(
        endpoint="finance-trend",
        user=current_user,
        scope=organization_scope(),
        period=period,
        compute=_compute,
        filters={"months": months},
    )


@router.get("/finance/clients", response_model=AnalyticsEnvelope)
async def get_finance_clients(
    current_user: User = Depends(require_capability(AnalyticsCapability.VIEW_FINANCE)),
    _: None = Depends(_analytics_enabled),
    period: Period = Depends(_parse_period),
    db: AsyncSession = Depends(get_db),
):
    async def _compute():
        data, warnings, flag = await metrics.finance_clients(db)
        return data, _finance_quality(warnings, flag)

    return await _cached_envelope(
        endpoint="finance-clients",
        user=current_user,
        scope=organization_scope(),
        period=period,
        compute=_compute,
    )


@router.get("/executive/board", response_model=AnalyticsEnvelope)
async def get_executive_board(
    current_user: User = Depends(require_capability(AnalyticsCapability.VIEW_FINANCE)),
    _: None = Depends(_analytics_enabled),
    period: Period = Depends(_parse_period),
    db: AsyncSession = Depends(get_db),
):
    async def _compute():
        ov = await metrics.overview(db, period)
        funnel = await metrics.recruitment_funnel(db, period)
        finance, warnings, flag = await metrics.finance_summary(db)
        data = {"overview": ov, "funnel": funnel["funnel"], "finance": finance}
        return data, _finance_quality(warnings, flag)

    return await _cached_envelope(
        endpoint="executive-board",
        user=current_user,
        scope=organization_scope(),
        period=period,
        compute=_compute,
    )


@router.get("/commercial/tenders", response_model=AnalyticsEnvelope)
async def get_commercial_tenders(
    current_user: User = Depends(
        require_capability(AnalyticsCapability.VIEW_TENDERS_OPERATIONAL)
    ),
    _: None = Depends(_analytics_enabled),
    period: Period = Depends(_parse_period),
    db: AsyncSession = Depends(get_db),
):
    """Przetargi: operacyjnie dla TAC+ (bez kwot); kwoty tylko z VIEW_FINANCE."""
    include_values = user_has_capability(current_user, AnalyticsCapability.VIEW_FINANCE)
    return await _cached_envelope(
        endpoint="commercial-tenders",
        user=current_user,
        scope=organization_scope(),
        period=period,
        compute=lambda: metrics.tenders(db, period, include_values=include_values),
        filters={"include_values": include_values},
    )


# ── Admin (plan PR 7): backfill snapshotów + cutover ─────────────────────────
# Celowo BEZ mode-gate (_analytics_enabled): przygotowanie historii i
# ustawienie cutoveru dzieje się w shadow, zanim v1 pójdzie live.


@router.post("/admin/backfill-board-snapshots")
async def admin_backfill_board_snapshots(
    current_user: User = Depends(
        require_capability(AnalyticsCapability.ADMIN_ANALYTICS)
    ),
    db: AsyncSession = Depends(get_db),
):
    """Idempotentny backfill nieodtwarzalnej historii Board/P&L
    (dr_board_monthly_report → analytics_metric_snapshots)."""
    from app.services.analytics_snapshots import backfill_board_snapshots

    return await backfill_board_snapshots(db)


class _CutoverPayload(BaseModel):
    module: str
    # Początek pełnego miesiąca Warsaw (plan PR 7 pkt 4).
    cutover_date: date_type


@router.post("/admin/cutover")
async def admin_set_cutover(
    payload: _CutoverPayload,
    current_user: User = Depends(
        require_capability(AnalyticsCapability.ADMIN_ANALYTICS)
    ),
    db: AsyncSession = Depends(get_db),
):
    """Ustaw/zmień datę cutoveru modułu. Wymusza 1. dzień miesiąca."""
    from app.models.analytics_snapshot import AnalyticsCutover

    if payload.cutover_date.day != 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="cutover_date musi być 1. dniem miesiąca (pełny miesiąc Warsaw)",
        )
    existing = await db.scalar(
        select(AnalyticsCutover).where(AnalyticsCutover.module == payload.module)
    )
    if existing is None:
        db.add(
            AnalyticsCutover(module=payload.module, cutover_date=payload.cutover_date)
        )
    else:
        existing.cutover_date = payload.cutover_date
    await db.commit()
    return {"module": payload.module, "cutover_date": payload.cutover_date.isoformat()}


# ── Meta ─────────────────────────────────────────────────────────────────────


@router.get("/meta/metrics")
async def get_meta_metrics(
    current_user: CurrentUser,
    _: None = Depends(_analytics_enabled),
):
    """Rejestr definicji metryk — definicja, jednostka, źródło, wersja."""
    return {
        "metric_version": METRIC_VERSION,
        "timezone": "Europe/Warsaw",
        "period_semantics": "[start, end) — kalendarz Europe/Warsaw",
        "metrics": metrics.METRIC_DEFINITIONS,
    }
