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

import contextvars
import logging
from contextlib import asynccontextmanager
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

    # 2. Per-feature toggle + limit.
    #
    # A MISSING row means "enabled, no ceiling" — fail-open, matching
    # `AIFeatureConfig.enabled`'s own default. This module used to fail-closed
    # while `match_justification_service._gate_and_count` failed open on the
    # same question, so whether an unseeded feature worked depended on which of
    # two copies of this logic the request happened to reach. That second copy
    # is gone; this is the one behaviour.
    #
    # Fail-open has a real cost, and on prod it is not hypothetical — but the
    # missing half is NOT the row. All 11 `AIFeatureKey` rows exist there and
    # every one of them still carries the column default `monthly_limit = 0`,
    # which this module documents as "no ceiling". So the branch below can
    # never fire for any feature, and seeding more rows would change nothing:
    # only a positive number does, and picking it is an admin decision
    # (Ustawienia → AI writes `monthly_limit` straight into this column).
    # `/api/health.checks.ai_features` therefore lists every key WITHOUT a
    # positive ceiling — a missing row and a row at 0 alike — as a spend
    # warning, not an outage.
    config = await get_feature_config(db, feature)
    if config is not None and not config.enabled:
        raise AIQuotaExceeded(feature, "Funkcja AI wyłączona w ustawieniach")

    limit = config.monthly_limit if config is not None else 0
    period = _current_period_start()
    total_used = await get_total_usage_for_period(db, feature, period)

    if limit > 0 and total_used >= limit:
        raise AIQuotaExceeded(
            feature,
            "Miesięczny limit wyczerpany",
            used=total_used,
            limit=limit,
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
        limit=limit,
        period_start=period,
    )


# ── Provider-boundary gate ───────────────────────────────────────────────────
#
# A decorator on the route was the obvious design and would not have worked:
# three of the five paths that reach Claude without a quota check are not
# routes at all — `fireflies_sync` is a background loop, CV enrichment is a
# `BackgroundTask`, and `enrich_from_call` sits in a CloudTalk webhook. A
# route decorator never touches any of them, which is precisely how they came
# to be ungated while every handler looked correctly wrapped.
#
# So the gate stands at the provider boundary instead: `call_claude` is the one
# place nearly all traffic funnels through, and it can ask "was this call
# declared?" regardless of what kind of caller made it.

_AI_CALL_CONTEXT: contextvars.ContextVar[Optional["AiCallContext"]] = (
    contextvars.ContextVar("ai_call_context", default=None)
)


@dataclass(frozen=True)
class AiCallContext:
    feature: AIFeatureKey
    user_id: Optional[int]
    state: QuotaState


class AIQuotaUngated(RuntimeError):
    """An LLM call was made outside `async with ai_feature(...)`."""


@asynccontextmanager
async def ai_feature(
    db: AsyncSession,
    feature: AIFeatureKey,
    *,
    user_id: Optional[int] = None,
):
    """Charge the quota and mark the surrounding block as a declared AI call.

    Charge-before-spend on purpose: the increment happens before the provider
    is called, so a call that reaches the API and then fails cannot come back
    for a free retry.

    That intent only survives if the caller commits. The increment lives in the
    caller's session, so a handler that lets the exception propagate — or wraps
    this in `async with db.begin()` — rolls the charge back with everything
    else, and the failed call ends up free after all. This matches the previous
    `_gate_and_count` behaviour and is not a regression, but do not read the
    paragraph above as a guarantee: to actually charge a failed call, the caller
    has to commit the increment on the error path itself.

    The context propagates into `run_in_threadpool` — `anyio.to_thread.run_sync`
    copies the contextvars — so the synchronous `call_claude` sees it.
    """
    # Nested declarations of the SAME feature do not charge twice. A handler
    # may declare the call and then hand off to a service that declares it
    # again — one user action is one unit, and making the count depend on how
    # deep the call stack happens to be would be a quota that drifts with
    # refactors rather than with usage.
    active = _AI_CALL_CONTEXT.get()
    if active is not None and active.feature == feature:
        yield active.state
        return

    state = await check_and_increment(db, feature, user_id=user_id)
    token = _AI_CALL_CONTEXT.set(
        AiCallContext(feature=feature, user_id=user_id, state=state)
    )
    try:
        yield state
    finally:
        _AI_CALL_CONTEXT.reset(token)


def current_ai_call() -> Optional[AiCallContext]:
    """The declared AI call in scope, if any."""
    return _AI_CALL_CONTEXT.get()
