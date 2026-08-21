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

import logging
from datetime import date, timedelta
from typing import Iterable, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import Text, cast, select
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
    AISettingsOut,
    FeatureConfig,
    FeatureConfigUpdate,
    FeatureUsage,
    MasterToggleUpdate,
)
from app.services.ai_quota import (
    _current_period_start,
    get_total_usage_for_period,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings/ai", tags=["ai-settings"])


def _end_of_month(period_start: date) -> date:
    """Last day of the calendar month containing ``period_start``."""
    if period_start.month == 12:
        next_month_start = period_start.replace(year=period_start.year + 1, month=1)
    else:
        next_month_start = period_start.replace(month=period_start.month + 1)
    return next_month_start - timedelta(days=1)


def resolve_feature_rows(
    rows: Iterable[tuple[object, object, object]],
) -> tuple[List[tuple[AIFeatureKey, bool, int]], List[str]]:
    """Rozdziel wiersze `ai_features` na znane funkcje i osierocone klucze.

    Wyniesione z handlera, żeby dało się to sprawdzić bez bazy: to jedyne
    miejsce, które decyduje, czy wiersz po usuniętej funkcji wywróci panel,
    czy zostanie pominięty.
    """
    known: List[tuple[AIFeatureKey, bool, int]] = []
    stale: List[str] = []
    for raw_feature, enabled, monthly_limit in rows:
        try:
            key = AIFeatureKey(str(raw_feature))
        except ValueError:
            stale.append(str(raw_feature))
            continue
        known.append((key, bool(enabled), int(monthly_limit or 0)))
    return known, stale


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

    # Kolumna `feature` czytana jako TEKST, a nie przez pythonowy `Enum(AIFeatureKey)`.
    # Prod trzyma w `ai_features` wiersze po funkcjach przemianowanych i usuniętych
    # (`embeddings`, `matching`, `reranking`, …). SQLAlchemy hydratuje kolumnę enumem
    # przy ODCZYCIE, więc jeden taki wiersz rzucał `LookupError` na całym `select()`
    # i zwracał 500 z JEDYNEGO w produkcie panelu, w którym da się ustawić miesięczny
    # limit i przełączyć główny kill-switch AI — a front tłumaczył to adminowi jako
    # brak uprawnień, więc przestawał szukać. Dokładnie ta sama poprawka co w sondzie
    # `/api/health.checks.ai_features` (main.py). ORDER BY zostaje na kolumnie enuma:
    # sortuje Postgres po stronie serwera, nic tam nie jest hydratowane.
    cfg_result = await db.execute(
        select(
            cast(AIFeatureConfig.feature, Text),
            AIFeatureConfig.enabled,
            AIFeatureConfig.monthly_limit,
        ).order_by(AIFeatureConfig.feature)
    )

    configs, stale = resolve_feature_rows(cfg_result.all())

    if stale:
        # Osierocone wiersze pomijamy, ale nie po cichu: dopóki nie posprząta ich
        # migracja danych, to jedyny ślad, że w `ai_features` siedzi konfiguracja
        # funkcji, których już nie ma.
        logger.warning(
            "[ai-settings] pominięto %d osieroconych wierszy ai_features "
            "(nie są elementami AIFeatureKey): %s",
            len(stale),
            ",".join(sorted(stale)),
        )

    period_start = _current_period_start()
    period_end = _end_of_month(period_start)

    feature_configs: List[FeatureConfig] = []
    feature_usage: List[FeatureUsage] = []

    for feature, enabled, monthly_limit in configs:
        feature_configs.append(
            FeatureConfig(
                feature=feature,
                enabled=enabled,
                monthly_limit=monthly_limit,
                label=FEATURE_LABELS.get(feature, feature.value),
                data_sent_to_ai=FEATURE_DATA_SENT.get(feature, []),
            )
        )

        used = await get_total_usage_for_period(db, feature, period_start)
        feature_usage.append(
            FeatureUsage(
                feature=feature,
                used=used,
                limit=monthly_limit,
                period_start=period_start,
                period_end=period_end,
            )
        )

    return AISettingsOut(
        master_enabled=bool(master_enabled),
        features=feature_configs,
        usage=feature_usage,
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
    cfg.updated_by = admin.id

    await db.commit()
    return await get_ai_settings(admin, db)
