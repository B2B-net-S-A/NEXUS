"""Restart-safety contracts for the Priority Work health/alert worker."""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy.dialects import postgresql

from app.models.recruitment_priority import PriorityAlertSeverity
from app.tasks import priority_work


def test_worker_freshness_uses_three_intervals_with_three_minute_floor() -> None:
    now = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
    assert priority_work.worker_is_fresh(
        now - timedelta(seconds=179),
        now=now,
        interval_seconds=30,
    )
    assert priority_work.worker_is_fresh(
        now - timedelta(seconds=180),
        now=now,
        interval_seconds=30,
    )
    assert not priority_work.worker_is_fresh(
        now - timedelta(seconds=181),
        now=now,
        interval_seconds=30,
    )
    assert priority_work.worker_is_fresh(
        now - timedelta(seconds=900),
        now=now,
        interval_seconds=300,
    )


def test_missing_heartbeat_is_never_fresh() -> None:
    assert priority_work.worker_is_fresh(None) is False


def test_worker_interval_is_clamped_to_one_minute(monkeypatch) -> None:
    monkeypatch.setattr(
        priority_work.settings,
        "RECRUITMENT_PRIORITY_WORKER_INTERVAL_SECONDS",
        1,
    )
    assert priority_work._worker_interval_seconds() == 60


async def test_alert_upsert_uses_persisted_unique_dedupe_and_counter() -> None:
    db = SimpleNamespace(execute=AsyncMock())
    await priority_work._upsert_alert(
        db,
        dedupe_key="plan-overdue:17",
        kind="plan_overdue",
        severity=PriorityAlertSeverity.warning,
        payload={"plan_id": 17},
    )

    statement = db.execute.await_args.args[0]
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": False},
        )
    ).lower()
    assert "insert into recruitment_priority_alerts" in sql
    assert "on conflict (dedupe_key) do update" in sql
    assert "occurrence_count = (recruitment_priority_alerts.occurrence_count +" in sql
    assert "resolved_at = " in sql


def test_worker_loop_has_no_process_local_dedupe_container() -> None:
    source = inspect.getsource(priority_work)
    assert "_sent_alerts" not in source
    assert "_seen_alerts" not in source
    assert "on_conflict_do_update" in source
    assert "RecruitmentPriorityAlert.dedupe_key" in source


def test_inactive_process_owner_is_reported_as_unowned_carry_over() -> None:
    source = inspect.getsource(priority_work.run_priority_work_sweep)
    assert ".outerjoin(User, User.id == RecruitmentProcess.owner_user_id)" in source
    assert "User.is_active.is_(False)" in source
