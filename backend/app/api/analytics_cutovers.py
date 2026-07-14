"""R5 control plane for immutable legacy snapshots and module cutovers."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.capabilities import AnalyticsCapability
from app.analytics.cutover_schemas import (
    AnalyticsCutoverList,
    AnalyticsCutoverResolution,
    AnalyticsCutoverRow,
    AnalyticsCutoverUpsert,
    LegacySnapshotImportRequest,
    LegacySnapshotImportResult,
    LegacySnapshotList,
    MODULE_KEY_PATTERN,
    METRIC_KEY_PATTERN,
)
from app.analytics.periods import AnalyticsPeriod, AnalyticsPeriodKind, resolve_period
from app.api.deps import AdminUser, require_analytics_capabilities
from app.core.database import get_db
from app.models.user import User
from app.services.analytics_v1.cutover import (
    AnalyticsCutoverService,
    CutoverBoundaryError,
)


router = APIRouter()

Database = Annotated[AsyncSession, Depends(get_db)]
FinanceReader = Annotated[
    User,
    Depends(require_analytics_capabilities(AnalyticsCapability.view_finance)),
]
ModuleKey = Annotated[str, Path(pattern=MODULE_KEY_PATTERN)]


def cutover_period(
    period: AnalyticsPeriodKind = Query(AnalyticsPeriodKind.month),
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
) -> AnalyticsPeriod:
    return resolve_period(period, date_from=date_from, date_to=date_to)


Period = Annotated[AnalyticsPeriod, Depends(cutover_period)]


@router.post(
    "/admin/legacy-snapshots/import",
    response_model=LegacySnapshotImportResult,
)
async def import_legacy_snapshots(
    payload: LegacySnapshotImportRequest,
    _admin: AdminUser,
    db: Database,
) -> LegacySnapshotImportResult:
    """Idempotently import up to 1000 immutable legacy JSON snapshots."""

    try:
        return await AnalyticsCutoverService(db).import_legacy_snapshots(
            payload.snapshots
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.get("/legacy-snapshots", response_model=LegacySnapshotList)
async def list_legacy_snapshots(
    _reader: FinanceReader,
    db: Database,
    metric_key: str | None = Query(default=None, pattern=METRIC_KEY_PATTERN),
    scope: str | None = Query(default=None, min_length=1, max_length=64),
    source: str | None = Query(default=None, min_length=1, max_length=64),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> LegacySnapshotList:
    """Read legacy Board/P&L history; available only to admin and DL."""

    return await AnalyticsCutoverService(db).list_snapshots(
        metric_key=metric_key,
        scope=scope,
        source=source,
        limit=limit,
        offset=offset,
    )


@router.put(
    "/admin/cutovers/{module_key}",
    response_model=AnalyticsCutoverRow,
)
async def set_cutover(
    module_key: ModuleKey,
    payload: AnalyticsCutoverUpsert,
    admin: AdminUser,
    db: Database,
) -> AnalyticsCutoverRow:
    """Set an audited cutover at a full Warsaw calendar month boundary."""

    try:
        return await AnalyticsCutoverService(db).set_cutover(
            module_key=module_key,
            payload=payload,
            admin_user_id=admin.id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.get("/cutovers", response_model=AnalyticsCutoverList)
async def list_cutovers(
    _reader: FinanceReader,
    db: Database,
) -> AnalyticsCutoverList:
    return AnalyticsCutoverList(
        cutovers=await AnalyticsCutoverService(db).list_cutovers()
    )


@router.get("/cutovers/{module_key}", response_model=AnalyticsCutoverRow)
async def get_cutover(
    module_key: ModuleKey,
    _reader: FinanceReader,
    db: Database,
) -> AnalyticsCutoverRow:
    cutover = await AnalyticsCutoverService(db).get_cutover(module_key)
    if cutover is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analytics cutover not found",
        )
    return cutover


@router.get(
    "/cutovers/{module_key}/resolve",
    response_model=AnalyticsCutoverResolution,
)
async def resolve_cutover(
    module_key: ModuleKey,
    period: Period,
    _reader: FinanceReader,
    db: Database,
) -> AnalyticsCutoverResolution:
    """Choose one source; crossing requests are rejected instead of blended."""

    try:
        return await AnalyticsCutoverService(db).resolve(
            module_key=module_key,
            period=period,
        )
    except CutoverBoundaryError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Requested period crosses the analytics cutover",
                "module_key": exc.module_key,
                "cutover_at": exc.cutover_at.isoformat(),
                "action": "Request separate pre-cutover and post-cutover periods",
            },
        ) from exc
