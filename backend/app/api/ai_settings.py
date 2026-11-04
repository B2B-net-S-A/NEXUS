"""Settings → AI panel.

Admin-only, read-only report of current-month AI usage and cost per feature,
plus a control delivery of the spend alarm.

NEXUS nie ma limitów AI (decyzja Artura, 17.09.2026): nie ma już głównego
wyłącznika, przełączników per funkcja ani miesięcznych sufitów. Kolumny
`ai_features.enabled` / `monthly_limit` zostają w bazie, ale nic ich nie czyta
jako bramki, a ten moduł nie ma już tras, które by je zapisywały.

Read access (GET) is restricted to admins to keep usage stats internal.
We don't want regular recruiters to see "AI is at 95%" and start fighting
over capacity.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta
from typing import Iterable, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
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
    FeatureUsage,
)
from app.services.ai_models import model_for
from app.services.auto_match_outbox import auto_match_mode as _auto_match_mode
from app.services.ai_quota import (
    _current_period_start,
    get_usage_summary_for_period,
)
from app.core.scheduling import business_today

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


@router.get("/auto-match")
async def get_auto_match_overview(
    _: AdminUser, db: AsyncSession = Depends(get_db)
) -> dict:
    """Podgląd autonomicznego dopasowania CV ↔ rekrutacje (ostatnie 7 dni).

    Liczby decyzji, stan kolejki i ostatnie wpisy dziennika. Bez nazwisk
    i treści CV — identyfikatory prowadzą do profilu i rekrutacji.
    """
    from app.core.config import settings
    from sqlalchemy import text

    since = business_today() - timedelta(days=7)
    decisions = dict(
        (
            await db.execute(
                text(
                    "SELECT decision, count(*) FROM candidate_auto_match_log "
                    "WHERE created_at >= :since GROUP BY decision"
                ),
                {"since": since},
            )
        ).all()
    )
    queue = dict(
        (
            await db.execute(
                text(
                    "SELECT status, count(*) FROM candidate_match_outbox "
                    "WHERE created_at >= :since GROUP BY status"
                ),
                {"since": since},
            )
        ).all()
    )
    recent = [
        dict(row._mapping)
        for row in await db.execute(
            text(
                "SELECT l.candidate_id, l.job_id, j.title AS job_title, l.score, "
                "l.decision, l.reason, l.trigger, l.created_at "
                "FROM candidate_auto_match_log l JOIN jobs j ON j.id = l.job_id "
                "ORDER BY l.created_at DESC LIMIT 25"
            )
        )
    ]
    for row in recent:
        if row["score"] is not None:
            row["score"] = float(row["score"])
    return {
        "enabled": bool(settings.AUTO_MATCH_ENABLED),
        "dry_run": _auto_match_mode() == "dry_run",
        "mode": _auto_match_mode(),
        "min_score": float(settings.AUTO_MATCH_MIN_SCORE),
        "max_jobs_per_candidate": int(settings.AUTO_MATCH_MAX_JOBS_PER_CANDIDATE),
        "max_candidates_per_job": int(settings.AUTO_MATCH_MAX_CANDIDATES_PER_JOB),
        "decisions_7d": decisions,
        "queue_7d": queue,
        "recent": recent,
    }


# ── „Jakość QC” (D6, 13.10.2026) ────────────────────────────────────────────


class QcQualityCheck(BaseModel):
    key: str
    label: str
    blocking: bool
    shown: int
    dismissed_wrong: int
    precision: Optional[float] = None
    reasons: dict[str, int] = {}
    state: Literal["active", "info", "off"]
    auto: Optional[Literal["info"]] = None
    manual: Optional[Literal["active", "info", "off"]] = None


class QcQualityDismissal(BaseModel):
    id: int
    check_key: str
    check_label: str
    label: str
    reason: str
    reason_label: str
    note: Optional[str] = None
    by_name: Optional[str] = None
    at: datetime
    restored: bool
    job_id: int
    candidate_id: int


class QcQualityOut(BaseModel):
    window_days: int
    auto_min_shown: int
    auto_info_below: float
    alert_blocking_below: float
    checks: List[QcQualityCheck]
    recent: List[QcQualityDismissal]


class QcQualityStateIn(BaseModel):
    # None = wróć do automatu.
    state: Optional[Literal["active", "info", "off"]] = None


async def _qc_quality(db: AsyncSession) -> QcQualityOut:
    from app.models.cv_finding_dismissal import CvFindingDismissal
    from app.models.user import User
    from app.services import qc_quality
    from app.services.cv_finding_dismissals import REASONS
    from app.services.cv_qc import BLOCKING_KEYS, LABELS, WARNING_KEYS

    numbers = await qc_quality.report(db)
    states = await qc_quality.load_states(db)
    effective = qc_quality.effective_states(states)
    checks = [
        QcQualityCheck(
            key=key,
            label=LABELS.get(key, key),
            blocking=key in BLOCKING_KEYS,
            shown=numbers[key]["shown"],
            dismissed_wrong=numbers[key]["dismissed_wrong"],
            precision=numbers[key]["precision"],
            reasons=numbers[key]["reasons"],
            state=effective.get(key, "active"),
            auto=(states.get(key) or {}).get("auto"),
            manual=(states.get(key) or {}).get("manual"),
        )
        for key in (*BLOCKING_KEYS, *WARNING_KEYS)
    ]
    rows = (
        await db.execute(
            select(CvFindingDismissal, User.name)
            .outerjoin(User, User.id == CvFindingDismissal.dismissed_by_user_id)
            .where(CvFindingDismissal.source == "qc")
            .order_by(CvFindingDismissal.created_at.desc())
            .limit(30)
        )
    ).all()
    recent = [
        QcQualityDismissal(
            id=row.id,
            check_key=row.check_key,
            check_label=LABELS.get(row.check_key, row.check_key),
            label=row.label,
            reason=row.reason,
            reason_label=REASONS.get(row.reason, (row.reason, False))[0],
            note=row.note,
            by_name=name,
            at=row.created_at,
            restored=row.restored_at is not None,
            job_id=row.job_id,
            candidate_id=row.candidate_id,
        )
        for row, name in rows
    ]
    return QcQualityOut(
        window_days=qc_quality.WINDOW_DAYS,
        auto_min_shown=qc_quality.AUTO_MIN_SHOWN,
        auto_info_below=qc_quality.AUTO_INFO_BELOW,
        alert_blocking_below=qc_quality.ALERT_BLOCKING_BELOW,
        checks=checks,
        recent=recent,
    )


@router.get("/qc-quality", response_model=QcQualityOut)
async def get_qc_quality(
    _: AdminUser, db: AsyncSession = Depends(get_db)
) -> QcQualityOut:
    """Trafność sprawdzeń QC CV z pominięć „To nieprawda” i ich stan (D6)."""
    return await _qc_quality(db)


@router.patch("/qc-quality/{key}", response_model=QcQualityOut)
async def set_qc_check_state(
    key: str,
    payload: QcQualityStateIn,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> QcQualityOut:
    """Ręczny stan uwagi QC: aktywna, informacja, wyłączona albo automat.

    Blokad nie da się wyciszyć (422) — decyzja D6: blokada nigdy nie
    przechodzi w informację sama ani ręcznie z tego panelu.
    """
    from app.services import qc_quality

    try:
        await qc_quality.set_manual(db, key, payload.state, user_id=admin.id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await db.commit()
    return await _qc_quality(db)
