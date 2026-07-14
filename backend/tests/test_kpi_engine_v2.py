"""KPI Coach v2 reads canonical ATS entities, never UserActivity counters."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.models.user import UserRole
from app.services import kpi_engine
from app.services.kpi_catalog import KPI_CATALOG
from app.services.kpi_coach_service import _try_emit
from app.models.kpi_nudge_log import KpiNudgeType
from app.services.kpi_engine import KpiResult
from app.services.kpi_catalog import KpiPeriod


class ScalarSession:
    def __init__(self, value: int = 0):
        self.value = value
        self.calls: list[tuple[object, object | None]] = []

    async def scalar(self, statement, params=None):
        self.calls.append((statement, params))
        return self.value


@pytest.mark.asyncio
async def test_power_calling_counts_only_completed_calls_with_started_at() -> None:
    db = ScalarSession(7)
    value = await kpi_engine.count_canonical_kpi_in_window(
        db,  # type: ignore[arg-type]
        kpi_id="daily_activity_count",
        user_id=42,
        since=datetime.fromisoformat("2026-07-14T00:00:00+02:00"),
        until=datetime.fromisoformat("2026-07-15T00:00:00+02:00"),
    )

    sql = str(db.calls[0][0])
    assert value == 7
    assert "status = 'completed'" in sql
    assert "coalesce(started_at, created_at)" in sql
    assert "user_activities" not in sql


@pytest.mark.asyncio
async def test_verifications_use_first_milestone_and_credit_attribution() -> None:
    db = ScalarSession(4)
    await kpi_engine.count_canonical_kpi_in_window(
        db,  # type: ignore[arg-type]
        kpi_id="weekly_screenings",
        user_id=9,
        since=datetime.fromisoformat("2026-07-14T00:00:00+02:00"),
        until=datetime.fromisoformat("2026-07-15T00:00:00+02:00"),
    )

    sql = str(db.calls[0][0])
    assert "analytics_first_candidate_milestones" in sql
    assert "credited_user_id" in sql
    assert "stage = 'verified'" in sql


@pytest.mark.asyncio
async def test_unconfigured_cloudtalk_is_hidden_not_reported_as_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_resolve_target(*_args, **_kwargs) -> int:
        return 15

    counted: list[str] = []

    async def fake_count(*_args, kpi_id: str, **_kwargs) -> int:
        counted.append(kpi_id)
        return 2

    monkeypatch.setattr(kpi_engine, "resolve_target", fake_resolve_target)
    monkeypatch.setattr(kpi_engine, "count_canonical_kpi_in_window", fake_count)
    monkeypatch.setattr(settings, "CLOUDTALK_ENABLED", False)
    user = SimpleNamespace(id=5, role=UserRole.recruiter)

    results = await kpi_engine.evaluate_user_kpis(
        object(),  # type: ignore[arg-type]
        user=user,  # type: ignore[arg-type]
        now=datetime.fromisoformat("2026-07-14T12:00:00+02:00"),
    )

    calls = next(item for item in results if item.kpi_id == "daily_activity_count")
    assert calls.target == 0
    assert calls.current == 0
    assert "daily_activity_count" not in counted


def test_catalog_keeps_calls_and_verifications_as_separate_daily_kpis() -> None:
    by_id = {item.kpi_id: item for item in KPI_CATALOG}
    assert by_id["daily_activity_count"].default_targets[UserRole.recruiter] == 15
    assert by_id["weekly_screenings"].period.value == "day"
    assert by_id["weekly_screenings"].default_targets[UserRole.recruiter] == 4


@pytest.mark.asyncio
async def test_nudge_dry_run_has_no_database_or_websocket_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DryRunSession:
        async def scalar(self, *_args, **_kwargs):
            return None

        def add(self, *_args, **_kwargs):  # pragma: no cover - failure guard
            raise AssertionError("dry-run must not write")

    async def fail_websocket(*_args, **_kwargs):  # pragma: no cover - guard
        raise AssertionError("dry-run must not publish websocket events")

    monkeypatch.setattr(
        "app.services.kpi_coach_service.ws_manager.notify_user", fail_websocket
    )
    result = await _try_emit(
        DryRunSession(),  # type: ignore[arg-type]
        user=SimpleNamespace(
            id=11,
            name="Test Recruiter",
            email="recruiter@example.com",
        ),  # type: ignore[arg-type]
        kpi_result=KpiResult(
            kpi_id="daily_activity_count",
            period=KpiPeriod.day,
            title_pl="Zakończone rozmowy dziś",
            description_pl="",
            target=15,
            current=15,
            progress_pct=100.0,
            state="hit",
            deadline_hours_left=4.0,
        ),
        nudge_type=KpiNudgeType.praise_hit,
        now=datetime.fromisoformat("2026-07-14T12:00:00+02:00"),
        dry_run=True,
    )

    assert result is True
