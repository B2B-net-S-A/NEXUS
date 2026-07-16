"""Backfill snapshotów + resolver legacy/live (plan PR 7).

Backfill przenosi NIEODTWARZALNĄ historię z DynaReportera (miesięczne
raporty Board/P&L — ``dr_board_monthly_report``) do
``analytics_metric_snapshots``:
- idempotentny (unikat module+metric+period+source, konflikt = skip),
- checksum sha256 wartości źródłowych per wiersz,
- raportuje pominięte i wstawione,
- NIGDY nie nadpisuje istniejących snapshotów.

Resolver: dla modułu z wpisem w ``analytics_cutovers`` okresy PRZED
cutoverem czyta ze snapshotów, od cutoveru — live ATS. Bez sumowania obu.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analytics_snapshot import AnalyticsCutover, AnalyticsMetricSnapshot
from app.models.dr_board import DrBoardMonthlyReport

BOARD_MODULE = "finance"
_SOURCE = "dynareporter"


def _checksum(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def backfill_board_snapshots(db: AsyncSession) -> dict[str, int]:
    """Skopiuj miesięczne raporty Board do snapshotów (idempotentnie)."""
    rows = (
        (
            await db.execute(
                select(DrBoardMonthlyReport).order_by(DrBoardMonthlyReport.report_month)
            )
        )
        .scalars()
        .all()
    )
    inserted = 0
    skipped = 0
    for r in rows:
        period_label = r.report_month.isoformat()[:7]
        value = {
            "revenue": str(r.revenue),
            "consultant_costs": str(r.consultant_costs),
            "other_costs": str(r.other_costs),
            "active_consultants": r.active_consultants,
            "placements": r.placements,
            "avg_margin_per_hour": str(r.avg_margin_per_hour),
            "currency": "PLN",
        }
        stmt = (
            pg_insert(AnalyticsMetricSnapshot)
            .values(
                module=BOARD_MODULE,
                metric="board_monthly",
                period_label=period_label,
                value=value,
                source=_SOURCE,
                checksum=_checksum(value),
            )
            .on_conflict_do_nothing(constraint="uq_analytics_snapshot")
        )
        result = await db.execute(stmt)
        if result.rowcount:
            inserted += 1
        else:
            skipped += 1
    await db.commit()
    return {"inserted": inserted, "skipped_existing": skipped, "source_rows": len(rows)}


async def get_cutover(db: AsyncSession, module: str) -> date | None:
    return await db.scalar(
        select(AnalyticsCutover.cutover_date).where(AnalyticsCutover.module == module)
    )


async def snapshot_for_month(
    db: AsyncSession, *, module: str, metric: str, period_label: str
) -> dict[str, Any] | None:
    return await db.scalar(
        select(AnalyticsMetricSnapshot.value).where(
            AnalyticsMetricSnapshot.module == module,
            AnalyticsMetricSnapshot.metric == metric,
            AnalyticsMetricSnapshot.period_label == period_label,
        )
    )


async def resolve_month_source(
    db: AsyncSession, *, module: str, month_start: date
) -> str:
    """'legacy' gdy miesiąc PRZED cutoverem modułu, inaczej 'live'.

    Brak wpisu cutover = wszystko live (stan przed migracją historii).
    """
    cutover = await get_cutover(db, module)
    if cutover is not None and month_start < cutover:
        return "legacy"
    return "live"
