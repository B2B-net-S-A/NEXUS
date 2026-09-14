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

import logging
from datetime import date, datetime, timedelta, timezone
from datetime import date as date_type
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
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
    ScopeKind,
    ensure_client_scope,
    ensure_finance_client_scope,
    ensure_recruitment_user_scope,
    ensure_team_scope,
    ensure_user_scope,
    organization_scope,
)
from app.api.deps import CurrentUser
from app.api.section_access import INSIGHTS_SECTION_DEPENDENCIES
from app.core.config import settings
from app.core.database import get_db
from app.models.call import Call
from app.models.traffit_sync_state import TraffitSyncState
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=INSIGHTS_SECTION_DEPENDENCIES)

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


# Ta sama granica świeżości co `checks.traffit` w /api/health.
_TRAFFIT_MAX_AGE = timedelta(hours=36)
# Wiersz znacznika dziennego syncu (app.tasks.traffit_sync.DAILY_MARKER —
# literał, żeby moduł API nie importował pętli tła).
_TRAFFIT_DAILY_MARKER = "__daily__"


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


async def _traffit_freshness(
    db: AsyncSession,
) -> tuple[dict[str, str], list[str], bool]:
    """Watermark ostatniego udanego importu Traffita (audyt statystyk A08).

    Zwraca ``(watermarki, ostrzeżenia, stale)``. Sync wyłączony = same żywe
    dane ATS, więc pusto. Włączony bez udanego biegu, z błędem albo starszy niż
    36 h = ostrzeżenie i obniżona jakość: „wygenerowano teraz" nie dowodzi, że
    źródło jest aktualne, a zero z nieudanego importu nie jest potwierdzonym
    zerem.
    """
    if not settings.TRAFFIT_SYNC_ENABLED:
        return {}, [], False
    row = (
        await db.execute(
            select(
                TraffitSyncState.last_run_finished_at, TraffitSyncState.last_status
            ).where(TraffitSyncState.phase == _TRAFFIT_DAILY_MARKER)
        )
    ).first()
    if row is None or row[0] is None:
        return (
            {},
            [
                "Import z Traffita jest włączony, ale nie ma jeszcze udanego "
                "biegu — dane importowane mogą być niekompletne, zero nie jest "
                "potwierdzone"
            ],
            True,
        )
    finished_at = _as_utc(row[0])
    last_status = row[1]
    watermark = {"traffit": finished_at.isoformat()}
    label = finished_at.strftime("%Y-%m-%d %H:%M UTC")
    if last_status not in ("ok", None):
        return (
            watermark,
            [
                f"Ostatni import z Traffita ({label}) zakończył się statusem "
                f"'{last_status}' — dane importowane mogą być niekompletne"
            ],
            True,
        )
    if datetime.now(timezone.utc) - finished_at > _TRAFFIT_MAX_AGE:
        return (
            watermark,
            [
                f"Ostatni udany import z Traffita: {label} (ponad 36 h temu) — "
                "dane importowane mogą być nieaktualne"
            ],
            True,
        )
    return watermark, [], False


def _with_source_freshness(
    quality: QualityPayload | None,
    watermarks: dict[str, str],
    warnings: list[str],
    stale: bool,
) -> QualityPayload:
    base = quality or QualityPayload()
    merged_warnings = list(base.warnings)
    merged_warnings.extend(w for w in warnings if w not in merged_warnings)
    status = base.status
    if stale and status == QualityStatus.complete:
        status = QualityStatus.partial
    return base.model_copy(
        update={
            "status": status,
            "warnings": merged_warnings,
            "source_watermarks": {**base.source_watermarks, **watermarks},
        }
    )


async def _calls_quality(db: AsyncSession) -> QualityPayload:
    """CloudTalk off/misconfigured ⇒ unavailable — NIGDY 'zero rozmów'.

    Włączony: watermark = ostatnia zsynchronizowana rozmowa (pętla syncu nie
    zapisuje znacznika udanego biegu, więc to jedyny trwały ślad źródła);
    brak jakiejkolwiek rozmowy = partial — zero rozmów nie jest potwierdzone
    (audyt statystyk A08).
    """
    if not settings.CLOUDTALK_ENABLED:
        return QualityPayload(
            status=QualityStatus.unavailable,
            warnings=[
                "CloudTalk wyłączony (CLOUDTALK_ENABLED=false) — dane o "
                "rozmowach są niedostępne, nie zerowe"
            ],
        )
    last_synced = await db.scalar(select(func.max(Call.updated_at)))
    if last_synced is None:
        return QualityPayload(
            status=QualityStatus.partial,
            warnings=[
                "CloudTalk jest włączony, ale żadna rozmowa nie została jeszcze "
                "zsynchronizowana — zero rozmów nie jest potwierdzone"
            ],
        )
    return QualityPayload(
        source_watermarks={"cloudtalk": _as_utc(last_synced).isoformat()}
    )


def _require_personal_kpis(user: User) -> None:
    """Reject retired Viewer/Finance personas from personal recruitment data."""

    if not (
        user_has_capability(user, AnalyticsCapability.VIEW_OWN_RECRUITMENT_KPI)
        or user_has_capability(user, AnalyticsCapability.VIEW_OWN_DELIVERY_KPI)
        or user_has_capability(user, AnalyticsCapability.ADMIN_ANALYTICS)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Brak uprawnień do osobistych KPI",
        )


async def _cached_envelope(
    *,
    endpoint: str,
    user: User,
    scope: Scope,
    period: Period,
    compute,
    quality: QualityPayload | None = None,
    filters: dict[str, Any] | None = None,
    db: AsyncSession | None = None,
    sources: tuple[str, ...] = ("traffit",),
) -> AnalyticsEnvelope:
    """Wspólny szkielet: cache (§4.6) → kanoniczna metryka → koperta (§4.5).

    ``compute`` może zwrócić dict (dane) ALBO krotkę (dane, QualityPayload) —
    quality liczone w compute jest cache'owane razem z kopertą, więc cache
    hit nie przelicza metryk.

    ``sources`` = zewnętrzne źródła, których świeżość ma trafić do
    ``quality.source_watermarks`` (A08). Domyślnie Traffit — kandydaci, etapy
    i rekrutacje są w części importem; finanse liczą z kontraktów NEXUSA,
    więc przekazują ``sources=()``.
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
    if db is not None and "traffit" in sources:
        quality = _with_source_freshness(quality, *await _traffit_freshness(db))
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
        db=db,
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
        db=db,
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
        db=db,
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
        db=db,
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
        db=db,
        compute=lambda: metrics.calls_aggregate(db, period),
        quality=await _calls_quality(db),
    )


# ── Osobiste ─────────────────────────────────────────────────────────────────


@router.get("/me/kpis", response_model=AnalyticsEnvelope)
async def get_my_kpis(
    current_user: CurrentUser,
    _: None = Depends(_analytics_enabled),
    period: Period = Depends(_parse_period),
    db: AsyncSession = Depends(get_db),
):
    """Własne KPI aktywnej persony operacyjnej (zakres = self)."""
    _require_personal_kpis(current_user)
    scope = ensure_user_scope(current_user, current_user.id)
    return await _cached_envelope(
        endpoint="me-kpis",
        user=current_user,
        scope=scope,
        period=period,
        db=db,
        compute=lambda: metrics.user_kpis(db, period, current_user.id),
        quality=await _calls_quality(db),
    )


@router.get("/me/calls", response_model=AnalyticsEnvelope)
async def get_my_calls(
    current_user: CurrentUser,
    _: None = Depends(_analytics_enabled),
    period: Period = Depends(_parse_period),
    db: AsyncSession = Depends(get_db),
):
    _require_personal_kpis(current_user)
    scope = ensure_user_scope(current_user, current_user.id)
    return await _cached_envelope(
        endpoint="me-calls",
        user=current_user,
        scope=scope,
        period=period,
        db=db,
        compute=lambda: metrics.calls_aggregate(db, period, user_id=current_user.id),
        quality=await _calls_quality(db),
    )


# ── Managerskie — VIEW_TEAM_KPI ──────────────────────────────────────────────


@router.get("/team/kpis", response_model=AnalyticsEnvelope)
async def get_team_kpis(
    current_user: User = Depends(require_capability(AnalyticsCapability.VIEW_TEAM_KPI)),
    _: None = Depends(_analytics_enabled),
    period: Period = Depends(_parse_period),
    db: AsyncSession = Depends(get_db),
):
    scope = await ensure_team_scope(db, current_user)
    scoped_user_ids = (
        scope.allowed_user_ids if scope.kind is ScopeKind.delivery_clients else None
    )
    return await _cached_envelope(
        endpoint="team-kpis",
        user=current_user,
        scope=scope,
        period=period,
        db=db,
        compute=lambda: metrics.team_kpis(
            db,
            period,
            user_ids=scoped_user_ids,
        ),
        quality=await _calls_quality(db),
    )


@router.get("/team/calls", response_model=AnalyticsEnvelope)
async def get_team_calls(
    current_user: User = Depends(require_capability(AnalyticsCapability.VIEW_TEAM_KPI)),
    _: None = Depends(_analytics_enabled),
    period: Period = Depends(_parse_period),
    db: AsyncSession = Depends(get_db),
):
    scope = await ensure_team_scope(db, current_user)
    scoped_user_ids = (
        scope.allowed_user_ids if scope.kind is ScopeKind.delivery_clients else None
    )

    async def _compute():
        team = await metrics.team_kpis(
            db,
            period,
            user_ids=scoped_user_ids,
        )
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
        scope=scope,
        period=period,
        db=db,
        compute=_compute,
        quality=await _calls_quality(db),
    )


@router.get("/recruitment/users/{user_id}", response_model=AnalyticsEnvelope)
async def get_user_recruitment(
    user_id: int,
    current_user: CurrentUser,
    _: None = Depends(_analytics_enabled),
    period: Period = Depends(_parse_period),
    db: AsyncSession = Depends(get_db),
):
    """KPI wskazanego usera z relacyjnym zakresem managerskim."""
    scope = await ensure_recruitment_user_scope(db, current_user, user_id)
    return await _cached_envelope(
        endpoint="user-recruitment",
        user=current_user,
        scope=scope,
        period=period,
        db=db,
        compute=lambda: metrics.user_kpis(db, period, user_id),
        quality=await _calls_quality(db),
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
        db=db,
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
    scope = ensure_finance_client_scope(current_user, client_id)

    async def _compute():
        data, warnings, flag = await metrics.client_finance(
            db, client_id, as_of=metrics.finance_as_of(period)
        )
        return data, _finance_quality(warnings, flag)

    return await _cached_envelope(
        endpoint="client-finance",
        user=current_user,
        scope=scope,
        period=period,
        db=db,
        sources=(),
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
        data, warnings, flag = await metrics.finance_summary(
            db, as_of=metrics.finance_as_of(period)
        )
        return data, _finance_quality(warnings, flag)

    return await _cached_envelope(
        endpoint="finance-summary",
        user=current_user,
        scope=organization_scope(),
        period=period,
        db=db,
        sources=(),
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
    prawdziwa arytmetyka kalendarza, FX po kursie z danej daty (plan PR 6).

    Seria kończy się miesiącem ostatniego dnia ``period`` (A09) — koperta
    i punkty opisują to samo okno; ``data.window`` podaje je wprost.
    """

    async def _compute():
        data, warnings, flag = await metrics.finance_trend(
            db, months=months, end=metrics.finance_as_of(period)
        )
        return data, _finance_quality(warnings, flag)

    return await _cached_envelope(
        endpoint="finance-trend",
        user=current_user,
        scope=organization_scope(),
        period=period,
        db=db,
        sources=(),
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
        data, warnings, flag = await metrics.finance_clients(
            db, as_of=metrics.finance_as_of(period)
        )
        return data, _finance_quality(warnings, flag)

    return await _cached_envelope(
        endpoint="finance-clients",
        user=current_user,
        scope=organization_scope(),
        period=period,
        db=db,
        sources=(),
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
        finance, warnings, flag = await metrics.finance_summary(
            db, as_of=metrics.finance_as_of(period)
        )
        data = {"overview": ov, "funnel": funnel["funnel"], "finance": finance}
        return data, _finance_quality(warnings, flag)

    return await _cached_envelope(
        endpoint="executive-board",
        user=current_user,
        scope=organization_scope(),
        period=period,
        db=db,
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
        db=db,
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
    """Ustaw/zmień datę cutoveru modułu. Wymusza 1. dzień miesiąca.

    Audyt M7 PR-05 (P1.7): endpoint jest ZAMROŻONY (412) do czasu readiness
    manifestu / state machine z PR-39 — dziś nadpisuje boundary bez dowodu
    parity i bez audytu rewizji. Break-glass (`ANALYTICS_CUTOVER_BREAKGLASS`)
    pozwala na awaryjne ustawienie w shadow-prep; każde użycie jest logowane
    z operatorem.
    """
    from app.models.analytics_snapshot import AnalyticsCutover

    if not settings.ANALYTICS_CUTOVER_BREAKGLASS:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail=(
                "Cutover zamrożony: brak readiness manifestu (M7 PR-39). "
                "Awaryjne ustawienie wymaga ANALYTICS_CUTOVER_BREAKGLASS=true."
            ),
        )
    logger.warning(
        "analytics cutover set via break-glass: module=%s cutover_date=%s user_id=%s",
        payload.module,
        payload.cutover_date.isoformat(),
        current_user.id,
    )

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
    current_user: User = Depends(
        require_capability(AnalyticsCapability.VIEW_OPERATIONAL_AGGREGATES)
    ),
    _: None = Depends(_analytics_enabled),
):
    """Rejestr definicji metryk — definicja, jednostka, źródło, wersja."""
    return {
        "metric_version": METRIC_VERSION,
        "timezone": "Europe/Warsaw",
        "period_semantics": "[start, end) — kalendarz Europe/Warsaw",
        "metrics": metrics.METRIC_DEFINITIONS,
    }
