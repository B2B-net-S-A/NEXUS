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
import os
from datetime import date, timedelta
from typing import Iterable, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import Text, cast, select, func
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
    SpendAlertStatus,
    FeatureConfig,
    FeatureConfigUpdate,
    FeatureUsage,
    MasterToggleUpdate,
)
from app.services.ai_models import model_for
from app.services.ai_quota import (
    _current_period_start,
    get_usage_summary_for_period,
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

    # Jeden GROUP BY na całe zużycie okresu zamiast pętli per funkcja (N+1);
    # tokeny podwoiłyby ten koszt. Klucz = wartość enuma (string).
    usage_summary = await get_usage_summary_for_period(db, period_start)

    from app.models.ai_metering import AIOperation, AIProviderCall, AISpendAlert
    from app.models.ai_feature import AIUsageLog
    from app.services.ai_metering import measured_usage

    measured = await measured_usage(db, period_start)
    legacy = set(
        (
            await db.scalars(
                select(cast(AIUsageLog.feature, Text))
                .where(AIUsageLog.period_start == period_start, AIUsageLog.count > 0)
                .distinct()
            )
        ).all()
    )
    missing = dict(
        (
            await db.execute(
                select(AIOperation.feature, func.count())
                .where(
                    AIOperation.period_start == period_start,
                    ~select(AIProviderCall.event_key)
                    .where(AIProviderCall.operation_id == AIOperation.id)
                    .exists(),
                )
                .group_by(AIOperation.feature)
            )
        ).all()
    )
    webhook = bool(os.environ.get("SLACK_WEBHOOK_URL", "").strip())
    from app.tasks.ai_spend_alerts import pending_alert_predicate

    pending = await db.scalar(
        select(func.count())
        .select_from(AISpendAlert)
        .where(pending_alert_predicate(webhook))
    )
    last_delivered = await db.scalar(select(func.max(AISpendAlert.in_app_at)))

    feature_configs: List[FeatureConfig] = []
    feature_usage: List[FeatureUsage] = []

    for feature, enabled, monthly_limit in configs:
        feature_configs.append(
            FeatureConfig(
                feature=feature,
                enabled=enabled,
                monthly_limit=monthly_limit,
                # Efektywny model z rejestru (ai_models) — jedno miejsce prawdy
                # „funkcja → model", to samo, którego używa runtime.
                model=model_for(feature),
                label=FEATURE_LABELS.get(feature, feature.value),
                data_sent_to_ai=FEATURE_DATA_SENT.get(feature, []),
            )
        )

        used, input_tokens, output_tokens = usage_summary.get(feature.value, (0, 0, 0))
        feature_usage.append(
            FeatureUsage(
                feature=feature,
                used=used,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                provider_calls=measured.get(feature.value, {}).get("provider_calls", 0),
                cache_read_tokens=measured.get(feature.value, {}).get(
                    "cache_read_tokens"
                )
                or 0,
                cache_creation_tokens=measured.get(feature.value, {}).get(
                    "cache_creation_tokens"
                )
                or 0,
                estimated_cost_usd=measured.get(feature.value, {}).get(
                    "estimated_cost_usd"
                ),
                unpriced_calls=measured.get(feature.value, {}).get("unpriced_calls", 0),
                legacy_usage_present=feature.value in legacy,
                operations_without_response=missing.get(feature.value, 0),
                limit=monthly_limit,
                period_start=period_start,
                period_end=period_end,
            )
        )

    return AISettingsOut(
        master_enabled=bool(master_enabled),
        features=feature_configs,
        usage=feature_usage,
        spend_alerts=SpendAlertStatus(
            slack_configured=webhook,
            pending_deliveries=pending or 0,
            last_delivered_at=last_delivered,
        ),
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


@router.post("/alerts/test")
async def test_spend_alert(
    admin: AdminUser, db: AsyncSession = Depends(get_db)
) -> dict:
    """Control delivery to the requesting administrator only, never Slack."""
    from uuid import uuid4
    from app.models.ai_metering import AISpendAlert
    from app.services.ai_generation_lease import GenerationBusy, generation_lease
    from app.tasks.ai_spend_alerts import queue_alert, deliver_alerts

    key = f"control:{admin.id}:{uuid4()}"
    try:
        async with generation_lease("ai-spend-alerts"):
            await queue_alert(
                db,
                key,
                "Kontrolny alert zużycia AI. Dostawa powiadomień NEXUS działa.",
                recipient_id=admin.id,
            )
            await db.commit()
            row = await db.scalar(select(AISpendAlert).where(AISpendAlert.key == key))
            await deliver_alerts(db, "", alert_id=row.id)
            await db.refresh(row)
            return {"delivered": row.in_app_at is not None, "alert_id": row.id}
    except GenerationBusy as exc:
        raise HTTPException(
            status_code=409, detail="Trwa dostarczanie alarmów. Ponów za chwilę."
        ) from exc
