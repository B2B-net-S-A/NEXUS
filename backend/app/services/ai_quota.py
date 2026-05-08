"""AI feature quota check + usage counter.

Lifted from `app.models.ai_feature` semantics:
- `AIMasterToggle.enabled = False` → all AI calls blocked.
- `AIFeatureConfig.enabled = False` for a given feature → that feature blocked.
- `AIFeatureConfig.monthly_limit > 0` → check current-month count vs limit.
- `monthly_limit = 0` → unlimited.

Usage: call `await check_and_increment(db, feature, user_id)` at the top of
any AI-touching endpoint. Raises `AIQuotaExceeded` if blocked — the API layer
should catch and convert to HTTP 503.

Atomicity:
- Two reads (master, feature config) + one upsert (usage row).
- Race: if two requests pass the check simultaneously they both increment
  past the limit by 1. Acceptable for our scale (≤200 users) — exact
  enforcement would need SELECT … FOR UPDATE which adds latency. Quota is
  advisory, not security.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_feature import (
    AIFeatureConfig,
    AIFeatureKey,
    AIMasterToggle,
    AIUsageLog,
)

logger = logging.getLogger(__name__)


class AIQuotaExceeded(Exception):
    """Raised when an AI call is blocked by toggle or quota."""

    def __init__(
        self,
        feature: AIFeatureKey,
        reason: str,
        used: int = 0,
        limit: int = 0,
    ):
        super().__init__(f"AI quota for {feature.value} blocked: {reason}")
        self.feature = feature
        self.reason = reason
        self.used = used
        self.limit = limit


@dataclass
class QuotaState:
    used: int
    limit: int
    period_start: date

    @property
    def remaining(self) -> int:
        if self.limit == 0:
            return 2**31 - 1  # effectively unlimited
        return max(0, self.limit - self.used)


def _current_period_start() -> date:
    """First day of the current calendar month, UTC."""
    now = datetime.now(timezone.utc).date()
    return now.replace(day=1)


async def get_master_enabled(db: AsyncSession) -> bool:
    """Read the singleton master toggle. Defaults to True if row missing."""
    result = await db.execute(
        select(AIMasterToggle.enabled).where(AIMasterToggle.id == 1)
    )
    enabled = result.scalar_one_or_none()
    return True if enabled is None else bool(enabled)


async def get_feature_config(
    db: AsyncSession, feature: AIFeatureKey
) -> Optional[AIFeatureConfig]:
    """Look up the per-feature config. Missing row = treat as disabled."""
    result = await db.execute(
        select(AIFeatureConfig).where(AIFeatureConfig.feature == feature)
    )
    return result.scalar_one_or_none()


async def get_usage(
    db: AsyncSession,
    feature: AIFeatureKey,
    user_id: Optional[int],
    period_start: Optional[date] = None,
) -> int:
    """Sum of calls for (feature, user, period). Returns 0 if no row."""
    period = period_start or _current_period_start()
    stmt = select(AIUsageLog.count).where(
        AIUsageLog.feature == feature,
        AIUsageLog.period_start == period,
    )
    if user_id is not None:
        stmt = stmt.where(AIUsageLog.user_id == user_id)
    else:
        stmt = stmt.where(AIUsageLog.user_id.is_(None))

    result = await db.execute(stmt)
    count = result.scalar_one_or_none()
    return count or 0


async def get_total_usage_for_period(
    db: AsyncSession,
    feature: AIFeatureKey,
    period_start: Optional[date] = None,
) -> int:
    """Sum across all users for a given (feature, period). Used by Settings UI."""
    from sqlalchemy import func

    period = period_start or _current_period_start()
    result = await db.execute(
        select(func.coalesce(func.sum(AIUsageLog.count), 0)).where(
            AIUsageLog.feature == feature,
            AIUsageLog.period_start == period,
        )
    )
    return int(result.scalar() or 0)


async def check_and_increment(
    db: AsyncSession,
    feature: AIFeatureKey,
    user_id: Optional[int] = None,
) -> QuotaState:
    """Atomic-ish quota check + increment.

    Raises ``AIQuotaExceeded`` if blocked. Returns post-increment state on
    success. Caller is expected to ``await db.commit()`` if the broader unit
    of work succeeds.
    """
    # 1. Master toggle
    master = await get_master_enabled(db)
    if not master:
        raise AIQuotaExceeded(feature, "Funkcje AI są wyłączone globalnie")

    # 2. Per-feature toggle + limit
    config = await get_feature_config(db, feature)
    if config is None or not config.enabled:
        raise AIQuotaExceeded(feature, "Funkcja AI wyłączona w ustawieniach")

    period = _current_period_start()
    total_used = await get_total_usage_for_period(db, feature, period)

    if config.monthly_limit > 0 and total_used >= config.monthly_limit:
        raise AIQuotaExceeded(
            feature,
            "Miesięczny limit wyczerpany",
            used=total_used,
            limit=config.monthly_limit,
        )

    # 3. Upsert per-user counter for this period.
    now = datetime.now(timezone.utc)
    stmt = (
        pg_insert(AIUsageLog)
        .values(
            feature=feature,
            user_id=user_id,
            period_start=period,
            count=1,
            last_call_at=now,
        )
        .on_conflict_do_update(
            constraint="uq_ai_usage_feature_user_period",
            set_={
                "count": AIUsageLog.count + 1,
                "last_call_at": now,
            },
        )
    )
    await db.execute(stmt)

    return QuotaState(
        used=total_used + 1,
        limit=config.monthly_limit,
        period_start=period,
    )
