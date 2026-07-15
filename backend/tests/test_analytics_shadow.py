"""Shadow parity evidence is restart-safe and independent of HTTP traffic."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.analytics.periods import WARSAW
from app.tasks import analytics_shadow


def _legacy_snapshot() -> dict:
    return {
        "candidates": {"total": 10, "active": 8},
        "jobs": {"total": 6, "open": 3},
        "clients": {"total": 4, "active": 2},
        "contracts": {"active": 5, "expiring_soon": 1},
        "pipeline": {"hired_this_month": 2},
    }


def _overview(*, jobs_total: int = 6):
    return SimpleNamespace(
        candidates=SimpleNamespace(total=10, active=8),
        jobs=SimpleNamespace(total=jobs_total, open=3),
        clients=SimpleNamespace(total=4, active=2),
        contracts=SimpleNamespace(active=5, expiring_30_days=1),
        pipeline=SimpleNamespace(placements=2),
    )


class _Session:
    def __init__(self) -> None:
        self.params: list[dict] = []
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def execute(self, _statement, params):
        self.params.append(params)

    async def commit(self):
        self.committed = True


@pytest.mark.asyncio
async def test_shadow_run_persists_one_daily_row_per_metric(monkeypatch) -> None:
    session = _Session()

    async def fake_snapshot(_db):
        return _legacy_snapshot()

    class FakeAnalyticsService:
        def __init__(self, _db):
            pass

        async def overview(self, _period, *, generated_at):
            assert generated_at.tzinfo is not None
            return _overview(jobs_total=7)

    monkeypatch.setattr(analytics_shadow, "AsyncSessionLocal", lambda: session)
    monkeypatch.setattr(analytics_shadow, "compute_kpi_snapshot", fake_snapshot)
    monkeypatch.setattr(analytics_shadow, "AnalyticsV1Service", FakeAnalyticsService)

    counters = await analytics_shadow.run_analytics_shadow_once(
        datetime(2026, 7, 14, 12, 0, tzinfo=WARSAW)
    )

    assert counters == {"identical": 8, "mismatch": 1, "unavailable": 0}
    assert session.committed is True
    assert len(session.params) == 9
    assert {row["observed_on"].isoformat() for row in session.params} == {"2026-07-14"}
    jobs = next(row for row in session.params if row["metric_key"] == "jobs.total")
    assert jobs["legacy_value"] == 6
    assert jobs["analytics_value"] == 7
    assert jobs["absolute_diff"] == 1
    assert jobs["status"] == "mismatch"


@pytest.mark.asyncio
async def test_shadow_loop_exits_cleanly_outside_shadow_mode(monkeypatch) -> None:
    monkeypatch.setattr(analytics_shadow.settings, "ANALYTICS_V1_MODE", "live")
    await analytics_shadow.analytics_shadow_loop()
