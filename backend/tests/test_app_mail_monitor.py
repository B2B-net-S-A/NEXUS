import logging
from unittest.mock import AsyncMock, Mock

from app.tasks import app_mail_monitor as monitor


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
    session = AsyncMock()
    result = Mock()
    result.mappings.return_value.one.return_value = {
        "uncertain": 0,
        "pending_retry": 0,
        "oldest_retry_seconds": 0,
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
