"""Opóźnienie pętli zdarzeń i obciążenie puli połączeń — jedna linia JSON na minutę.

Audyt wydajności 13.09 (F06/F12) i reaudyt 14.09 wymagają pomiaru, zanim ktoś
zmieni rozmiar puli albo doda proces: `http_outcome` mówi, ile trwało żądanie,
ale nie mówi, czy czekało na zajętą pętlę zdarzeń (pełny przegląd bazy, CPU
w pętlach tła), czy na wolne połączenie z puli (20 + 40 na proces). Ta pętla
co ``INTERVAL_SECONDS`` loguje ``runtime_metrics`` (Alloy → Loki):

* ``loop_lag_ms_p99`` / ``loop_lag_ms_max`` — spóźnienie budzika co 0,5 s;
  wartość rosnąca = coś trzyma pętlę zdarzeń i wszystkie żądania czekają;
* ``pool_in_use_max`` — najwięcej jednocześnie wypożyczonych połączeń w oknie
  (liczone zdarzeniami `checkout`/`checkin` puli);
* ``pool_probe_checkout_ms`` — ile trwało wypożyczenie JEDNEGO połączenia na
  koniec okna (nic nie wykonuje). Kilka ms = pula ma zapas; setki ms albo
  ``pool_probe_error`` = żądania czekają w kolejce puli.

Wyłącznie liczby, bez treści zapytań i danych. Awaria pomiaru nigdy nie
przerywa pętli.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 60
LAG_TICK_SECONDS = 0.5
PROBE_TIMEOUT_SECONDS = 10.0


@dataclass
class PoolUsage:
    """Licznik wypożyczonych połączeń z maksimum w bieżącym oknie."""

    in_use: int = 0
    window_max: int = 0

    def checkout(self) -> None:
        self.in_use += 1
        self.window_max = max(self.window_max, self.in_use)

    def checkin(self) -> None:
        self.in_use = max(0, self.in_use - 1)

    def take_window_max(self) -> int:
        peak = self.window_max
        self.window_max = self.in_use
        return peak


@dataclass
class LagWindow:
    samples_ms: list[float] = field(default_factory=list)

    def add(self, lag_ms: float) -> None:
        self.samples_ms.append(max(0.0, lag_ms))

    def take(self) -> dict[str, float | int | None]:
        values = sorted(self.samples_ms)
        self.samples_ms = []
        if not values:
            return {
                "loop_lag_ms_p99": None,
                "loop_lag_ms_max": None,
                "loop_lag_samples": 0,
            }
        p99 = values[min(len(values) - 1, int(round(0.99 * (len(values) - 1))))]
        return {
            "loop_lag_ms_p99": round(p99, 1),
            "loop_lag_ms_max": round(values[-1], 1),
            "loop_lag_samples": len(values),
        }


def attach_pool_usage(engine: AsyncEngine) -> PoolUsage:
    usage = PoolUsage()
    sync_engine = engine.sync_engine
    event.listen(sync_engine, "checkout", lambda *_: usage.checkout())
    event.listen(sync_engine, "checkin", lambda *_: usage.checkin())
    return usage


def pool_snapshot(engine: AsyncEngine) -> dict[str, int | None]:
    pool = engine.sync_engine.pool
    snapshot: dict[str, int | None] = {}
    for key, attr in (
        ("pool_size", "size"),
        ("pool_checked_out", "checkedout"),
        ("pool_overflow", "overflow"),
    ):
        getter = getattr(pool, attr, None)
        try:
            snapshot[key] = int(getter()) if callable(getter) else None
        except Exception:  # noqa: BLE001 — różne implementacje puli
            snapshot[key] = None
    return snapshot


async def probe_checkout(engine: AsyncEngine) -> tuple[float | None, str | None]:
    started = time.monotonic()
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            async with engine.connect():
                pass
    except Exception as exc:  # noqa: BLE001 — pomiar, nie może wywrócić pętli
        return None, type(exc).__name__
    return round((time.monotonic() - started) * 1000, 1), None


async def _measure_lag(window: LagWindow, until: float) -> None:
    loop = asyncio.get_running_loop()
    while loop.time() < until:
        expected = loop.time() + LAG_TICK_SECONDS
        await asyncio.sleep(LAG_TICK_SECONDS)
        window.add((loop.time() - expected) * 1000)


async def runtime_metrics_monitor_loop(engine: AsyncEngine | None = None) -> None:
    if engine is None:
        from app.core.database import engine as default_engine

        engine = default_engine
    usage = attach_pool_usage(engine)
    window = LagWindow()
    loop = asyncio.get_running_loop()
    while True:
        try:
            await _measure_lag(window, loop.time() + INTERVAL_SECONDS)
            probe_ms, probe_error = await probe_checkout(engine)
            logger.info(
                "runtime_metrics",
                extra={
                    "event_kind": "runtime_metrics",
                    "window_seconds": INTERVAL_SECONDS,
                    **window.take(),
                    **pool_snapshot(engine),
                    "pool_in_use_max": usage.take_window_max(),
                    "pool_probe_checkout_ms": probe_ms,
                    "pool_probe_error": probe_error,
                },
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "runtime_metrics failed",
                extra={
                    "event_kind": "runtime_metrics",
                    "failure_kind": type(exc).__name__,
                },
            )
            await asyncio.sleep(INTERVAL_SECONDS)
