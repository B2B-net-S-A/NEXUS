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
    assert stats == {
        "loop_lag_ms_p99": 98.0,
        "loop_lag_ms_max": 99.0,
        "loop_lag_samples": 101,
    }
    assert window.take()["loop_lag_samples"] == 0


def test_gc_window_times_only_full_collections_and_resets() -> None:
    window = monitor.GcWindow()
    clock = iter([10.0, 11.5, 20.0, 20.25])
    window.clock = lambda: next(clock)
    window.callback("start", {"generation": 1})  # gen1 nie zatrzymuje na sekundy
    window.callback("stop", {"generation": 1})
    for _ in range(2):
        window.callback("start", {"generation": 2})
        window.callback("stop", {"generation": 2})
    assert window.take() == {
        "gc_gen2_count": 2,
        "gc_gen2_ms_sum": 1750.0,
        "gc_gen2_ms_max": 1500.0,
    }
    assert window.take() == {
        "gc_gen2_count": 0,
        "gc_gen2_ms_sum": 0.0,
        "gc_gen2_ms_max": 0.0,
    }


def test_gc_window_ignores_stop_without_start() -> None:
    # Podpięcie w trakcie zbierania: pierwszy „stop” nie ma pary.
    window = monitor.GcWindow()
    window.callback("stop", {"generation": 2})
    assert window.take()["gc_gen2_count"] == 0


def _cpu_window(cpu: list[float], wall: list[float]) -> monitor.CpuWindow:
    cpu_readings, wall_readings = iter(cpu), iter(wall)
    return monitor.CpuWindow(
        cpu_clock=lambda: next(cpu_readings),
        wall_clock=lambda: next(wall_readings),
    )


def test_cpu_window_first_take_has_no_baseline_and_hides_startup_cpu() -> None:
    # Pierwszy odczyt nie ma z czym się porównać; czas CPU importów i startu
    # nie może wejść do pierwszego okna jako „obciążenie”.
    window = _cpu_window([500.0], [1000.0])
    assert window.take() == {"cpu_pct": None}


def test_cpu_window_divides_cpu_delta_by_real_window_and_moves_on() -> None:
    window = _cpu_window([10.0, 40.0, 40.6], [100.0, 160.0, 220.0])
    window.take()
    assert window.take() == {"cpu_pct": 50.0}
    assert window.take() == {"cpu_pct": 1.0}


def test_cpu_window_uses_actual_elapsed_time_not_nominal_interval() -> None:
    # Okno z sondą puli albo po awarii trwa dłużej niż 60 s.
    window = _cpu_window([0.0, 30.0], [0.0, 120.0])
    window.take()
    assert window.take() == {"cpu_pct": 25.0}


def test_cpu_window_counts_all_threads_and_may_exceed_one_core() -> None:
    window = _cpu_window([0.0, 90.0], [0.0, 60.0])
    window.take()
    assert window.take() == {"cpu_pct": 150.0}


def test_cpu_window_reports_none_for_empty_window() -> None:
    window = _cpu_window([1.0, 2.0], [5.0, 5.0])
    window.take()
    assert window.take() == {"cpu_pct": None}


def test_cpu_window_failure_gives_none_and_recovers() -> None:
    readings = iter([0.0, OSError("clock"), 10.0, 40.0])

    def flaky_cpu() -> float:
        value = next(readings)
        if isinstance(value, Exception):
            raise value
        return value

    wall = iter([0.0, 60.0, 120.0, 180.0])
    window = monitor.CpuWindow(cpu_clock=flaky_cpu, wall_clock=lambda: next(wall))
    window.take()
    assert window.take() == {"cpu_pct": None}  # awaria odczytu
    assert window.take() == {"cpu_pct": None}  # brak punktu odniesienia po awarii
    assert window.take() == {"cpu_pct": 50.0}


def test_read_rss_mb_takes_resident_pages_from_statm(tmp_path, monkeypatch) -> None:
    statm = tmp_path / "statm"
    statm.write_text("900000 460800 12000 1 0 300000 0\n", encoding="ascii")
    monkeypatch.setattr(monitor, "STATM_PATH", str(statm))
    monkeypatch.setattr(monitor.os, "sysconf", lambda name: 4096)
    assert monitor.read_rss_mb() == 1800.0


def test_read_rss_mb_is_none_without_proc(tmp_path, monkeypatch) -> None:
    # Laptop: macOS nie ma /proc.
    monkeypatch.setattr(monitor, "STATM_PATH", str(tmp_path / "brak"))
    assert monitor.read_rss_mb() is None


@pytest.mark.parametrize("content", ["", "900000", "900000 x 1\n"])
def test_read_rss_mb_is_none_for_malformed_statm(
    tmp_path, monkeypatch, content
) -> None:
    statm = tmp_path / "statm"
    statm.write_text(content, encoding="ascii")
    monkeypatch.setattr(monitor, "STATM_PATH", str(statm))
    assert monitor.read_rss_mb() is None


@pytest.mark.skipif(
    not Path(monitor.STATM_PATH).exists(), reason="system bez /proc (laptop)"
)
def test_read_rss_mb_reads_this_process_on_linux() -> None:
    assert (monitor.read_rss_mb() or 0) > 1


@pytest.mark.asyncio
async def test_loop_logs_cpu_and_rss_with_existing_fields(monkeypatch, caplog) -> None:
    windows = 0

    async def fake_measure(_window, _until) -> None:
        nonlocal windows
        windows += 1
        if windows == 3:
            raise asyncio.CancelledError

    async def fake_probe(_engine):
        return 1.5, None

    monkeypatch.setattr(monitor, "_measure_lag", fake_measure)
    monkeypatch.setattr(monitor, "probe_checkout", fake_probe)
    monkeypatch.setattr(monitor, "attach_pool_usage", lambda _: monitor.PoolUsage())
    monkeypatch.setattr(monitor, "pool_snapshot", lambda _: {})
    monkeypatch.setattr(monitor.gc, "callbacks", [])
    monkeypatch.setattr(monitor, "read_rss_mb", lambda: 1234.5)

    with caplog.at_level("INFO", logger=monitor.logger.name):
        with pytest.raises(asyncio.CancelledError):
            await monitor.runtime_metrics_monitor_loop(engine=object())

    lines = [r for r in caplog.records if r.getMessage() == "runtime_metrics"]
    assert len(lines) == 2
    assert lines[0].cpu_pct is None
    assert isinstance(lines[1].cpu_pct, float)
    assert [r.rss_mb for r in lines] == [1234.5, 1234.5]
    assert lines[1].pool_probe_checkout_ms == 1.5


@pytest.mark.asyncio
async def test_loop_keeps_logging_when_rss_is_unavailable(monkeypatch, caplog) -> None:
    calls = 0

    async def fake_measure(_window, _until) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise asyncio.CancelledError

    async def fake_probe(_engine):
        return 1.0, None

    monkeypatch.setattr(monitor, "_measure_lag", fake_measure)
    monkeypatch.setattr(monitor, "probe_checkout", fake_probe)
    monkeypatch.setattr(monitor, "attach_pool_usage", lambda _: monitor.PoolUsage())
    monkeypatch.setattr(monitor, "pool_snapshot", lambda _: {})
    monkeypatch.setattr(monitor.gc, "callbacks", [])
    monkeypatch.setattr(monitor, "STATM_PATH", "/nie/ma/takiego/pliku")

    with caplog.at_level("INFO", logger=monitor.logger.name):
        with pytest.raises(asyncio.CancelledError):
            await monitor.runtime_metrics_monitor_loop(engine=object())

    lines = [r for r in caplog.records if r.getMessage() == "runtime_metrics"]
    assert len(lines) == 1 and lines[0].rss_mb is None
    assert not [r for r in caplog.records if r.getMessage() == "runtime_metrics failed"]


def test_freeze_startup_heap_collects_first_and_then_freezes(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(monitor.gc, "collect", lambda: calls.append("collect") or 0)
    monkeypatch.setattr(monitor.gc, "freeze", lambda: calls.append("freeze"))
    monitor.freeze_startup_heap()
    assert calls == ["collect", "freeze"]


def test_lifespan_freezes_heap_before_background_tasks() -> None:
    source = (BACKEND / "app" / "main.py").read_text("utf-8")
    assert source.index("freeze_startup_heap()") < source.index(
        "def _start_background_tasks()"
    )


def test_pool_snapshot_reads_queue_pool_counters_and_tolerates_other_pools() -> None:
    engine = SimpleNamespace(
        sync_engine=SimpleNamespace(
            pool=SimpleNamespace(
                size=lambda: 20, checkedout=lambda: 7, overflow=lambda: -13
            )
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
async def test_probe_checkout_reports_error_class_instead_of_raising(
    monkeypatch,
) -> None:
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
    assert (
        '"runtime_metrics": asyncio.create_task(runtime_metrics_monitor_loop())' in main
    )


def test_connect_args_name_the_application_only_for_asyncpg() -> None:
    from app.core.database import _connect_args

    assert _connect_args("postgresql+asyncpg://u:p@h/db") == {
        "server_settings": {"application_name": "nexus-backend", "jit": "off"}
    }
    assert _connect_args("sqlite+aiosqlite:///:memory:") == {}


def test_engine_keeps_forty_warm_connections() -> None:
    # Przy puli 20 + 40 produkcja otwierała ~95 połączeń na minutę (27.10.2026):
    # połączenia ponad `pool_size` są zamykane zaraz po oddaniu.
    from app.core.database import engine

    assert engine.pool.size() == 40
    assert engine.pool._max_overflow == 20
