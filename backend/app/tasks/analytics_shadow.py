"""Traffic-independent Analytics v1 shadow comparison loop.

The loop runs only in ``ANALYTICS_V1_MODE=shadow``. It compares the legacy
dashboard adapter with the canonical v1 overview without changing either HTTP
response, then persists one evidence row per Warsaw day and metric. Repeated
runs update the same daily row, making the job restart-safe and cheap.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from decimal import Decimal

from sqlalchemy import text

from app.analytics.periods import AnalyticsPeriodKind, WARSAW, resolve_period
from app.analytics.schemas import METRIC_VERSION
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.services.analytics_v1 import AnalyticsV1Service
from app.services.dashboard_metrics import compute_kpi_snapshot


logger = logging.getLogger(__name__)


_UPSERT = text(
    """
    INSERT INTO analytics_shadow_comparisons (
      observed_on, module_key, metric_key, metric_version,
      period_start, period_end, legacy_value, analytics_value,
      absolute_diff, status, details
    ) VALUES (
      :observed_on, :module_key, :metric_key, :metric_version,
      :period_start, :period_end, :legacy_value, :analytics_value,
      :absolute_diff, :status, CAST(:details AS jsonb)
    )
    ON CONFLICT (observed_on, module_key, metric_key, metric_version)
    DO UPDATE SET
      period_start = EXCLUDED.period_start,
      period_end = EXCLUDED.period_end,
      legacy_value = EXCLUDED.legacy_value,
      analytics_value = EXCLUDED.analytics_value,
      absolute_diff = EXCLUDED.absolute_diff,
      status = EXCLUDED.status,
      details = EXCLUDED.details,
      last_observed_at = now()
    """
)


def _flatten_legacy(snapshot: dict) -> dict[str, Decimal]:
    return {
        "candidates.total": Decimal(snapshot["candidates"]["total"]),
        "candidates.active": Decimal(snapshot["candidates"]["active"]),
        "jobs.total": Decimal(snapshot["jobs"]["total"]),
        "jobs.open": Decimal(snapshot["jobs"]["open"]),
        "clients.total": Decimal(snapshot["clients"]["total"]),
        "clients.active": Decimal(snapshot["clients"]["active"]),
        "contracts.active": Decimal(snapshot["contracts"]["active"]),
        "contracts.expiring_30_days": Decimal(snapshot["contracts"]["expiring_soon"]),
        "placements.period": Decimal(snapshot["pipeline"]["hired_this_month"]),
    }


def _flatten_v1(overview) -> dict[str, Decimal]:
    return {
        "candidates.total": Decimal(overview.candidates.total),
        "candidates.active": Decimal(overview.candidates.active),
        "jobs.total": Decimal(overview.jobs.total),
        "jobs.open": Decimal(overview.jobs.open),
        "clients.total": Decimal(overview.clients.total),
        "clients.active": Decimal(overview.clients.active),
        "contracts.active": Decimal(overview.contracts.active),
        "contracts.expiring_30_days": Decimal(overview.contracts.expiring_30_days),
        "placements.period": Decimal(overview.pipeline.placements),
    }


async def run_analytics_shadow_once(now: datetime | None = None) -> dict[str, int]:
    """Compute and persist one restart-safe Warsaw-day comparison batch."""

    generated_at = (now or datetime.now(WARSAW)).astimezone(WARSAW)
    period = resolve_period(AnalyticsPeriodKind.month, now=generated_at)
    async with AsyncSessionLocal() as db:
        legacy = _flatten_legacy(await compute_kpi_snapshot(db))
        canonical = _flatten_v1(
            await AnalyticsV1Service(db).overview(
                period,
                generated_at=generated_at,
            )
        )
        counters = {"identical": 0, "mismatch": 0, "unavailable": 0}
        metric_keys = sorted(set(legacy) | set(canonical))
        for metric_key in metric_keys:
            legacy_value = legacy.get(metric_key)
            analytics_value = canonical.get(metric_key)
            if legacy_value is None or analytics_value is None:
                status = "unavailable"
                absolute_diff = None
            else:
                absolute_diff = abs(analytics_value - legacy_value)
                status = "identical" if absolute_diff == 0 else "mismatch"
            counters[status] += 1
            await db.execute(
                _UPSERT,
                {
                    "observed_on": generated_at.date(),
                    "module_key": "overview",
                    "metric_key": metric_key,
                    "metric_version": METRIC_VERSION,
                    "period_start": period.start,
                    "period_end": period.end,
                    "legacy_value": legacy_value,
                    "analytics_value": analytics_value,
                    "absolute_diff": absolute_diff,
                    "status": status,
                    "details": json.dumps(
                        {
                            "timezone": period.timezone,
                            "legacy_source": "/api/dashboard/stats",
                            "analytics_source": "/api/analytics/v1/overview",
                        },
                        separators=(",", ":"),
                    ),
                },
            )
        await db.commit()
    logger.info("analytics shadow comparison completed: %s", counters)
    return counters


async def analytics_shadow_loop() -> None:
    """Run immediately in shadow mode, then at a clamped configured interval."""

    if settings.ANALYTICS_V1_MODE != "shadow":
        logger.info(
            "analytics_shadow_loop disabled (mode=%s)",
            settings.ANALYTICS_V1_MODE,
        )
        return
    interval = max(300, settings.ANALYTICS_SHADOW_INTERVAL_SECONDS)
    logger.info("analytics_shadow_loop started (interval=%ss)", interval)
    while True:
        try:
            await run_analytics_shadow_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("analytics shadow comparison failed: %s", exc)
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            break
    logger.info("analytics_shadow_loop stopped")


__all__ = ["analytics_shadow_loop", "run_analytics_shadow_once"]
