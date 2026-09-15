"""`runtime_metrics`: pomiar pętli zdarzeń i puli, który nie może zakłamać ani przerwać pracy.

Liczby z tej pętli mają rozstrzygać, czy zmieniać pulę połączeń albo liczbę
procesów (audyt F06/F12) — dlatego sprawdzamy arytmetykę okna i to, że awaria
pomiaru daje wartość „brak”, a nie wyjątek.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.tasks import runtime_metrics_monitor as monitor

BACKEND = Path(__file__).resolve().parents[1]


def test_pool_usage_tracks_window_peak_and_resets_to_current() -> None:
    usage = monitor.PoolUsage()
    for _ in range(5):
        usage.checkout()
    for _ in range(3):
        usage.checkin()
    assert usage.take_window_max() == 5
    # Nowe okno startuje od bieżącego wypożyczenia, nie od zera.
    assert usage.take_window_max() == 2


def test_pool_usage_never_goes_negative_when_attached_mid_flight() -> None:
    usage = monitor.PoolUsage()
    usage.checkin()  # połączenie wypożyczone przed podpięciem listenera
    assert usage.in_use == 0


def test_lag_window_reports_p99_max_and_resets() -> None:
    window = monitor.LagWindow()
    for value in list(range(100)) + [-3]:
        window.add(float(value))
    stats = window.take()
    assert stats == {"loop_lag_ms_p99": 98.0, "loop_lag_ms_max": 99.0, "loop_lag_samples": 101}
    assert window.take()["loop_lag_samples"] == 0


def test_pool_snapshot_reads_queue_pool_counters_and_tolerates_other_pools() -> None:
    engine = SimpleNamespace(
        sync_engine=SimpleNamespace(
            pool=SimpleNamespace(size=lambda: 20, checkedout=lambda: 7, overflow=lambda: -13)
        )
    )
    assert monitor.pool_snapshot(engine) == {
        "pool_size": 20,
        "pool_checked_out": 7,
        "pool_overflow": -13,
    }
    bare = SimpleNamespace(sync_engine=SimpleNamespace(pool=object()))
    assert monitor.pool_snapshot(bare) == {
        "pool_size": None,
        "pool_checked_out": None,
        "pool_overflow": None,
    }


@pytest.mark.asyncio
async def test_probe_checkout_reports_error_class_instead_of_raising(monkeypatch) -> None:
    class _Broken:
        @asynccontextmanager
        async def connect(self):
            raise ConnectionRefusedError("db down")
            yield  # pragma: no cover

    ms, error = await monitor.probe_checkout(_Broken())
    assert ms is None and error == "ConnectionRefusedError"

    class _Saturated:
        @asynccontextmanager
        async def connect(self):
            await asyncio.sleep(5)
            yield

    monkeypatch.setattr(monitor, "PROBE_TIMEOUT_SECONDS", 0.01)
    ms, error = await monitor.probe_checkout(_Saturated())
    assert ms is None and error == "TimeoutError"


@pytest.mark.asyncio
async def test_probe_checkout_measures_milliseconds() -> None:
    class _Fast:
        @asynccontextmanager
        async def connect(self):
            yield

    ms, error = await monitor.probe_checkout(_Fast())
    assert error is None and ms is not None and ms >= 0


def test_loop_is_registered_in_lifespan() -> None:
    main = (BACKEND / "app/main.py").read_text(encoding="utf-8")
    assert '"runtime_metrics": asyncio.create_task(runtime_metrics_monitor_loop())' in main


def test_connect_args_name_the_application_only_for_asyncpg() -> None:
    from app.core.database import _connect_args

    assert _connect_args("postgresql+asyncpg://u:p@h/db") == {
        "server_settings": {"application_name": "nexus-backend"}
    }
    assert _connect_args("sqlite+aiosqlite:///:memory:") == {}
