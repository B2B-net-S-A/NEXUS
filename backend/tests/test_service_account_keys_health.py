"""Runda 9 (R9-N9-9): sonda wygasania kluczy kont serwisowych w `/api/health`."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.services.service_account_health import (
    EXPIRY_WARNING_DAYS,
    service_account_keys_verdict,
)

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)


def test_no_active_accounts_is_unconfigured():
    assert service_account_keys_verdict([], now=NOW) == "unconfigured"


def test_all_keys_valid_for_long_is_healthy():
    assert (
        service_account_keys_verdict(
            [NOW + timedelta(days=60), NOW + timedelta(days=EXPIRY_WARNING_DAYS + 1)],
            now=NOW,
        )
        == "healthy"
    )


def test_key_expiring_within_warning_window_degrades():
    assert (
        service_account_keys_verdict(
            [NOW + timedelta(days=60), NOW + timedelta(days=3)], now=NOW
        )
        == "degraded"
    )


def test_account_without_valid_key_degrades():
    assert (
        service_account_keys_verdict([NOW + timedelta(days=60), None], now=NOW)
        == "degraded"
    )


def test_probe_is_wired_and_never_unhealthy():
    src = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text()
    start = src.index('checks["service_account_keys"]')
    block = src[start : src.index("# Qdrant", start)]
    assert "service_account_keys_verdict" in block
    assert '"unhealthy"' not in block
