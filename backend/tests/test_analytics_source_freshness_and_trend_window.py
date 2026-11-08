"""Audyt statystyk 14.09.2026 — A07, A09 (PR 2, obszar G6).

A07: `finance_trend` nie miesza w jednej kolumnie marży kontraktowej (live)
     z wynikiem po pozostałych kosztach (legacy) ani MRR z przychodem
     miesięcznym — osobne pola + ostrzeżenie o zmianie źródła w serii.
A09: `/finance/trend` kotwiczy serię na końcu żądanego okresu — koperta
     `period` i punkty opisują to samo okno.

Dane syntetyczne; lata 2007/2008 celowo spoza zakresu innych testów (baza
testowa jest wspólna dla przebiegu).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import delete

from app.analytics import metrics
from app.core.database import AsyncSessionLocal
from app.models.analytics_snapshot import AnalyticsCutover, AnalyticsMetricSnapshot
from app.services.analytics_snapshots import BOARD_MODULE

pytestmark = pytest.mark.asyncio


# ── A09: seria kotwiczona na końcu okresu ────────────────────────────────────


async def test_finance_trend_series_ends_at_requested_period_end():
    async with AsyncSessionLocal() as db:
        data, _warnings, _flag = await metrics.finance_trend(
            db, months=3, end=date(2007, 6, 30)
        )
    assert [p["month"] for p in data["months"]] == ["2007-04", "2007-05", "2007-06"]
    assert data["window"] == {"from": "2007-04", "to": "2007-06"}


# ── A07: legacy i live pod różnymi polami + ostrzeżenie o zmianie źródła ────


async def test_finance_trend_keeps_legacy_and_live_definitions_apart():
    cutover = date(2008, 5, 1)
    async with AsyncSessionLocal() as db:
        await db.execute(delete(AnalyticsCutover))
        await db.execute(
            delete(AnalyticsMetricSnapshot).where(
                AnalyticsMetricSnapshot.period_label == "2008-04"
            )
        )
        db.add(AnalyticsCutover(module=BOARD_MODULE, cutover_date=cutover))
        db.add(
            AnalyticsMetricSnapshot(
                module=BOARD_MODULE,
                metric="board_monthly",
                period_label="2008-04",
                value={
                    "revenue": "10000",
                    "consultant_costs": "7000",
                    "other_costs": "1000",
                    "active_consultants": 4,
                },
                checksum="0" * 64,
            )
        )
        await db.commit()
    try:
        async with AsyncSessionLocal() as db:
            data, warnings, _flag = await metrics.finance_trend(
                db, months=2, end=date(2008, 5, 31)
            )
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(AnalyticsCutover))
            await db.execute(
                delete(AnalyticsMetricSnapshot).where(
                    AnalyticsMetricSnapshot.period_label == "2008-04"
                )
            )
            await db.commit()

    legacy, live = data["months"]
    assert (legacy["source"], live["source"]) == ("legacy", "live")
    assert legacy["basis"] == "legacy_monthly_report"
    assert live["basis"] == "contracts"

    # Przychód miesięczny legacy NIE udaje MRR.
    assert legacy["mrr"] is None
    assert legacy["monthly_revenue"] == "10000.00"
    assert live["monthly_revenue"] is None
    # Marża = przychód − koszt konsultantów w OBU źródłach (3 000, nie 2 000).
    assert legacy["monthly_margin"] == "3000.00"
    # Wynik po pozostałych kosztach zna tylko legacy.
    assert legacy["result_after_other_costs"] == "2000.00"
    assert live["result_after_other_costs"] is None
    assert Decimal(live["monthly_margin"]) >= 0

    assert any("Seria łączy dwa źródła" in w for w in warnings), warnings
