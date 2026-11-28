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
        "uncertain_recent": 0,
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
        queue={"uncertain": 0, "uncertain_recent": 0, "oldest_retry_seconds": 0},
    )
    assert monitor.verdict(**args) == 0
    assert monitor.verdict(**{**args, "state": {"consecutive_failures": 1}}) == 1
    assert (
        monitor.verdict(
            **{
                **args,
                "queue": {
                    "uncertain": 1,
                    "uncertain_recent": 1,
                    "oldest_retry_seconds": 0,
                },
            }
        )
        == 1
    )
    # Runda 7 (R7-N5-4): stary niepewny wynik nie trzyma alarmu na zawsze.
    assert (
        monitor.verdict(
            **{
                **args,
                "queue": {
                    "uncertain": 1,
                    "uncertain_recent": 0,
                    "oldest_retry_seconds": 0,
                },
            }
        )
        == 0
    )
    assert (
        monitor.verdict(
            **{
                **args,
                "queue": {
                    "uncertain": 0,
                    "uncertain_recent": 0,
                    "oldest_retry_seconds": 3601,
                },
            }
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
        "uncertain_recent": 0,
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


class _QueryCanceled(Exception):
    """Jak asyncpg po `statement_timeout`: SQLSTATE 57014."""

    sqlstate = "57014"


def _queue_row():
    result = Mock()
    result.mappings.return_value.one.return_value = {
        k: v
        for k, v in _queue().items()
        if k not in ("scope", "ready_candidates_upper_bound")
    }
    return result


def _monitor_with_session(monkeypatch, execute_side_effect):
    monkeypatch.setattr(monitor.settings, "M365_APP_MAIL_ENABLED", True)
    monkeypatch.setattr(monitor.app_mail, "is_configured", lambda: True)
    monkeypatch.setattr(monitor.mail_circuit, "snapshot", lambda: {})
    monkeypatch.setattr(monitor, "load_policy", AsyncMock(return_value=_policy()))
    monkeypatch.setattr(monitor, "STATEMENT_TIMEOUT_RETRY_SECONDS", 0)
    session = AsyncMock()
    session.__aenter__.return_value.execute.side_effect = execute_side_effect
    monkeypatch.setattr(monitor, "AsyncSessionLocal", lambda: session)


def _monitor_events(caplog):
    return [
        r
        for r in caplog.records
        if getattr(r, "event_kind", None) == "app_mail_monitor"
    ]


async def test_single_statement_timeout_after_restart_is_retried_not_alarmed(
    monkeypatch, caplog
):
    """28.11.2026: pierwszy przebieg po wdrożeniu trafił na zimną bazę
    (Postgres wstał 90 s wcześniej), zapytanie przekroczyło 2 s i monitor dał
    `alarm=1` — Grafana wysłała mail o awarii maili, które działały."""
    _monitor_with_session(
        monkeypatch,
        [
            None,  # SET LOCAL statement_timeout
            _QueryCanceled("private sql"),
            None,
            _queue_row(),
            Mock(scalar_one=Mock(return_value=0)),
        ],
    )
    with caplog.at_level(logging.INFO):
        await monitor.sample_app_mail()
    events = _monitor_events(caplog)
    assert [(e.monitor_status, e.alarm) for e in events] == [("ok", 0)]
    assert "private sql" not in caplog.text


async def test_repeated_statement_timeout_is_still_an_alarm(monkeypatch, caplog):
    _monitor_with_session(
        monkeypatch,
        [None, _QueryCanceled("private sql"), None, _QueryCanceled("private sql")],
    )
    with caplog.at_level(logging.INFO):
        await monitor.sample_app_mail()
    events = _monitor_events(caplog)
    assert [(e.monitor_status, e.alarm) for e in events] == [("error", 1)]
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
        "uncertain_recent": 0,
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


async def test_uncertain_alarm_counts_only_recent_rows():
    """Runda 7 (R7-N5-4): licznik alarmu ma okno czasu."""
    db = AsyncMock()
    row = Mock()
    row.mappings.return_value.one.return_value = {
        k: v for k, v in _queue().items() if k != "scope"
    }
    db.execute.side_effect = [row, Mock(scalar_one=Mock(return_value=0))]
    now = datetime(2026, 9, 22, 13, tzinfo=timezone.utc)
    await monitor.snapshot_queue(db, _policy(), now)
    sql = str(
        db.execute.call_args_list[0].args[0].compile(dialect=postgresql.dialect())
    )
    assert (
        "coalesce(notifications.email_send_started_at, notifications.created_at)" in sql
    )
    assert "AS uncertain_recent" in sql
