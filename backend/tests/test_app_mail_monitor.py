import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.dialects import postgresql

from app.services.notification_delivery import DeliveryPolicy
from app.tasks import app_mail_monitor as monitor


def _policy(enabled=True):
    return DeliveryPolicy.from_value(
        {
            "enabled": enabled,
            "send_not_before": "2026-09-22T12:00:00+00:00",
            "types": {
                "chat_unread": {
                    "email_enabled": True,
                    "send_not_before": "2026-09-22T12:30:00+00:00",
                }
            },
        }
    )


def _queue(**overrides):
    return {
        "uncertain": 0,
        "pending_retry": 0,
        "oldest_retry_seconds": 0,
        "legacy_suppressed": 4,
        "ready_candidates_upper_bound": 0,
        "scope": "chat_unread",
        **overrides,
    }


def test_alarm_covers_outage_recovery_uncertainty_and_disabled():
    args = dict(
        enabled=True,
        configured=True,
        state={},
        queue={"uncertain": 0, "oldest_retry_seconds": 0},
    )
    assert monitor.verdict(**args) == 0
    assert monitor.verdict(**{**args, "state": {"consecutive_failures": 1}}) == 1
    assert (
        monitor.verdict(
            **{**args, "queue": {"uncertain": 1, "oldest_retry_seconds": 0}}
        )
        == 1
    )
    assert (
        monitor.verdict(
            **{**args, "queue": {"uncertain": 0, "oldest_retry_seconds": 3601}}
        )
        == 1
    )
    assert monitor.verdict(**{**args, "configured": False}) == 1
    assert monitor.verdict(**{**args, "enabled": False, "configured": False}) == 0


async def test_monitor_read_failure_is_not_healthy_and_recovers(monkeypatch, caplog):
    monkeypatch.setattr(monitor.settings, "M365_APP_MAIL_ENABLED", True)
    monkeypatch.setattr(monitor.app_mail, "is_configured", lambda: True)
    monkeypatch.setattr(monitor.mail_circuit, "snapshot", lambda: {})
    monkeypatch.setattr(monitor, "load_policy", AsyncMock(return_value=_policy()))
    session = AsyncMock()
    result = Mock()
    result.mappings.return_value.one.return_value = {
        "uncertain": 0,
        "pending_retry": 0,
        "oldest_retry_seconds": 0,
        "legacy_suppressed": 4,
    }
    session.__aenter__.return_value.execute.side_effect = [
        TimeoutError("private sql"),
        None,
        result,
        Mock(scalar_one=Mock(return_value=7)),
    ]
    monkeypatch.setattr(monitor, "AsyncSessionLocal", lambda: session)
    with caplog.at_level(logging.INFO):
        await monitor.sample_app_mail()
        await monitor.sample_app_mail()
    events = [
        r
        for r in caplog.records
        if getattr(r, "event_kind", None) == "app_mail_monitor"
    ]
    assert [e.alarm for e in events] == [1, 0]
    assert [e.monitor_status for e in events] == ["error", "ok"]
    assert events[-1].ready_candidates_upper_bound == 7
    assert "private sql" not in caplog.text


async def test_policy_pause_is_not_reported_as_provider_recovery(monkeypatch, caplog):
    monkeypatch.setattr(monitor.settings, "M365_APP_MAIL_ENABLED", True)
    monkeypatch.setattr(monitor.app_mail, "is_configured", lambda: True)
    monkeypatch.setattr(
        monitor.mail_circuit,
        "snapshot",
        lambda: {
            "attempts": 1,
            "failures": 1,
            "consecutive_failures": 1,
            "last_failure_code": "http_403",
        },
    )
    monkeypatch.setattr(
        monitor, "load_policy", AsyncMock(return_value=DeliveryPolicy())
    )
    monkeypatch.setattr(
        monitor, "snapshot_queue", AsyncMock(return_value=_queue(uncertain=1))
    )
    monkeypatch.setattr(monitor, "AsyncSessionLocal", lambda: AsyncMock())
    with caplog.at_level(logging.INFO):
        await monitor.sample_app_mail()
    event = next(
        r
        for r in caplog.records
        if getattr(r, "event_kind", None) == "app_mail_monitor"
    )
    assert event.monitor_status == "ok"
    assert event.alarm == 0
    assert event.enabled is False
    assert event.policy_enabled is False
    assert event.delivery_status == "disabled"
    assert event.provider_status == "degraded"
    assert event.uncertain == 1
    assert event.legacy_suppressed == 4


async def test_unreadable_policy_is_an_alarm_not_an_intentional_pause(
    monkeypatch, caplog
):
    monkeypatch.setattr(monitor.settings, "M365_APP_MAIL_ENABLED", False)
    monkeypatch.setattr(monitor, "AsyncSessionLocal", lambda: AsyncMock())
    monkeypatch.setattr(
        monitor, "load_policy", AsyncMock(side_effect=RuntimeError("private policy"))
    )
    with caplog.at_level(logging.WARNING):
        await monitor.sample_app_mail()
    event = next(
        r
        for r in caplog.records
        if getattr(r, "event_kind", None) == "app_mail_monitor"
    )
    assert event.monitor_status == "error"
    assert event.alarm == 1
    assert "private policy" not in caplog.text


@pytest.mark.parametrize("enabled", [False, True])
async def test_backlog_query_and_worker_share_activation_cutoff(enabled):
    db = AsyncMock()
    row = Mock()
    row.mappings.return_value.one.return_value = {
        "uncertain": 0,
        "pending_retry": 0,
        "oldest_retry_seconds": 0,
        "legacy_suppressed": 4,
    }
    db.execute.side_effect = [row, Mock(scalar_one=Mock(return_value=0))]
    policy = _policy(enabled)
    result = await monitor.snapshot_queue(
        db, policy, datetime(2026, 9, 22, 13, tzinfo=timezone.utc)
    )
    assert result == _queue()
    statements = [
        call.args[0].compile(dialect=postgresql.dialect())
        for call in db.execute.call_args_list
    ]
    for statement in statements:
        if enabled:
            assert policy.cutoff_for("chat_unread") in statement.params.values()
            assert "notifications.created_at >=" in str(statement)
        else:
            assert "false" in str(statement).lower()
