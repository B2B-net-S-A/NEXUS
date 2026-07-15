"""Settings → AI panel.

Admin-only endpoints to manage:
- Master AI toggle (kill-switch).
- Per-feature toggle + monthly call limit.
- View current-month usage per feature.

Read access (GET) is restricted to admins to keep usage stats internal.
We don't want regular recruiters to see "AI is at 95%" and start fighting
over capacity.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser
from app.core.database import get_db
from app.models.ai_feature import (
    FEATURE_DATA_SENT,
    FEATURE_LABELS,
    AIFeatureConfig,
    AIFeatureKey,
    AIMasterToggle,
)
from app.schemas.ai_settings import (
    AISettingsPatch,
    AISettingsOut,
    FeatureConfig,
    FeatureConfigUpdate,
    FeatureUsage,
    MasterToggleUpdate,
)
from app.ai.registry import public_registry
from app.models.ai_platform import AICallLedger, AIProviderCompliance, AIRoutingState
from app.services.ai_quota import (
    _current_period_start,
    get_total_usage_for_period,
)

router = APIRouter(prefix="/settings/ai", tags=["ai-settings"])


def _end_of_month(period_start: date) -> date:
    """Last day of the calendar month containing ``period_start``."""
    if period_start.month == 12:
        next_month_start = period_start.replace(year=period_start.year + 1, month=1)
    else:
        next_month_start = period_start.replace(month=period_start.month + 1)
    return next_month_start - timedelta(days=1)


@router.get("", response_model=AISettingsOut)
async def get_ai_settings(
    _: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> AISettingsOut:
    """Return master toggle + per-feature config + current-month usage."""
    master_result = await db.execute(
        select(AIMasterToggle.enabled).where(AIMasterToggle.id == 1)
    )
    master_enabled = master_result.scalar_one_or_none()
    if master_enabled is None:
        master_enabled = True

    cfg_result = await db.execute(
        select(AIFeatureConfig).order_by(AIFeatureConfig.feature)
    )
    configs = list(cfg_result.scalars().all())

    routing = await db.get(AIRoutingState, 1)
    registry_version = routing.registry_version if routing else "v1_current"
    routing_lock_version = routing.lock_version if routing else 1
    compliance_rows = list((await db.scalars(select(AIProviderCompliance))).all())

    period_start = _current_period_start()
    period_end = _end_of_month(period_start)

    feature_configs: List[FeatureConfig] = []
    feature_usage: List[FeatureUsage] = []
    period_datetime = datetime.combine(
        period_start, datetime.min.time(), tzinfo=timezone.utc
    )
    ledger_rows = list(
        (
            await db.execute(
                select(
                    AICallLedger.feature,
                    AICallLedger.cost_usd,
                    AICallLedger.latency_ms,
                    AICallLedger.status,
                ).where(AICallLedger.created_at >= period_datetime)
            )
        ).all()
    )

    for cfg in configs:
        feature_configs.append(
            FeatureConfig(
                feature=cfg.feature,
                enabled=cfg.enabled,
                monthly_limit=cfg.monthly_limit,
                monthly_budget_usd=cfg.monthly_budget_usd,
                label=FEATURE_LABELS.get(cfg.feature, cfg.feature.value),
                data_sent_to_ai=FEATURE_DATA_SENT.get(cfg.feature, []),
            )
        )

        used = await get_total_usage_for_period(db, cfg.feature, period_start)
        attempts = [row for row in ledger_rows if row.feature == cfg.feature.value]
        latencies = sorted(row.latency_ms for row in attempts if row.latency_ms > 0)
        p95_index = max(0, int(len(latencies) * 0.95) - 1)
        errors = sum(1 for row in attempts if row.status == "error")
        error_rate = errors / len(attempts) if attempts else 0.0
        feature_usage.append(
            FeatureUsage(
                feature=cfg.feature,
                used=used,
                limit=cfg.monthly_limit,
                period_start=period_start,
                period_end=period_end,
                cost_usd=sum(
                    (Decimal(row.cost_usd or 0) for row in attempts), Decimal("0")
                ),
                p95_latency_ms=latencies[p95_index] if latencies else 0,
                error_rate=error_rate,
                health="down"
                if error_rate > 0.1
                else "degraded"
                if error_rate > 0.01
                else "ok",
            )
        )

    return AISettingsOut(
        master_enabled=bool(master_enabled),
        features=feature_configs,
        usage=feature_usage,
        active_registry_version=registry_version,
        routing_lock_version=routing_lock_version,
        routes=public_registry(registry_version),
        compliance={
            row.provider: {
                "production_allowed": row.production_allowed,
                "dpa_approved": row.dpa_approved,
                "zdr_approved": row.zdr_approved,
                "subprocessors_reviewed": row.subprocessors_reviewed,
                "transfer_basis": row.transfer_basis,
            }
            for row in compliance_rows
        },
    )


@router.patch("/master", response_model=AISettingsOut)
async def update_master_toggle(
    payload: MasterToggleUpdate,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> AISettingsOut:
    """Flip the global AI kill-switch."""
    result = await db.execute(select(AIMasterToggle).where(AIMasterToggle.id == 1))
    master = result.scalar_one_or_none()
    if master is None:
        master = AIMasterToggle(id=1, enabled=payload.enabled, updated_by=admin.id)
        db.add(master)
    else:
        master.enabled = payload.enabled
        master.updated_by = admin.id

    await db.commit()
    return await get_ai_settings(admin, db)


@router.patch("/features/{feature}", response_model=AISettingsOut)
async def update_feature_config(
    feature: AIFeatureKey,
    payload: FeatureConfigUpdate,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> AISettingsOut:
    """Update enabled/monthly_limit for a single AI feature."""
    result = await db.execute(
        select(AIFeatureConfig).where(AIFeatureConfig.feature == feature)
    )
    cfg = result.scalar_one_or_none()
    if cfg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Feature {feature.value} not configured",
        )

    if payload.enabled is not None:
        cfg.enabled = payload.enabled
    if payload.monthly_limit is not None:
        cfg.monthly_limit = payload.monthly_limit
    if payload.monthly_budget_usd is not None:
        cfg.monthly_budget_usd = payload.monthly_budget_usd
    cfg.updated_by = admin.id

    await db.commit()
    return await get_ai_settings(admin, db)


@router.patch("", response_model=AISettingsOut)
async def patch_ai_settings(
    payload: AISettingsPatch,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> AISettingsOut:
    """Bulk-update only kill-switch, call limits and monthly budgets."""
    if payload.master_enabled is not None:
        master = await db.get(AIMasterToggle, 1)
        if master is None:
            master = AIMasterToggle(
                id=1, enabled=payload.master_enabled, updated_by=admin.id
            )
            db.add(master)
        else:
            master.enabled = payload.master_enabled
            master.updated_by = admin.id
    for item in payload.features:
        cfg = await db.scalar(
            select(AIFeatureConfig).where(AIFeatureConfig.feature == item.feature)
        )
        if cfg is None:
            raise HTTPException(
                status_code=404, detail=f"Feature {item.feature.value} not configured"
            )
        if item.enabled is not None:
            cfg.enabled = item.enabled
        if item.monthly_limit is not None:
            cfg.monthly_limit = item.monthly_limit
        if item.monthly_budget_usd is not None:
            cfg.monthly_budget_usd = item.monthly_budget_usd
        cfg.updated_by = admin.id
    await db.commit()
    return await get_ai_settings(admin, db)
