"""In-memory circuit breaker for the AI matching pipeline.

Tracks recent calls to Voyage embeddings + Qdrant retrieval and exposes a
simple ``ok | degraded | down`` status the API surfaces in
``meta.ai_status``. The frontend consumes that to decide whether to nudge
the user toward manual search.

Design choices:

* **In-process, single instance.** The deployment runs one FastAPI process
  per Hetzner CAX21 box; cross-process consensus isn't worth the
  Redis/lock complexity here. Each replica has its own view.
* **Rolling window of 10 calls per endpoint.** Enough to absorb a single
  flaky call without flipping the banner, small enough to recover quickly
  after the dependency stabilizes.
* **Reset on first OK.** A clean call after a degraded streak returns
  status to ``ok``; we don't require N consecutive successes.

Thresholds match ``.claude/plans/zaplanuj-wszystko-teraz-pamietaj-wondrous-moon.md``:
3 consecutive failures → ``down``; 3 consecutive >5s p95 → ``degraded``.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Literal

AiStatus = Literal["ok", "degraded", "down"]

WINDOW_SIZE = 10
SLOW_THRESHOLD_MS = 5000
CONSECUTIVE_FAILURE_THRESHOLD = 3
CONSECUTIVE_SLOW_THRESHOLD = 3


@dataclass
class CallSample:
    elapsed_ms: int
    failed: bool


class _AiHealthTracker:
    """Thread-safe rolling window of recent AI matching calls.

    Public surface: :meth:`record`, :meth:`status`, :meth:`reset` (testing).
    """

    def __init__(self) -> None:
        self._samples: Deque[CallSample] = deque(maxlen=WINDOW_SIZE)
        self._lock = threading.Lock()

    def record(self, elapsed_ms: int, failed: bool) -> None:
        with self._lock:
            self._samples.append(CallSample(elapsed_ms=elapsed_ms, failed=failed))

    def reset(self) -> None:
        with self._lock:
            self._samples.clear()

    def status(self) -> AiStatus:
        with self._lock:
            if not self._samples:
                return "ok"
            tail = list(self._samples)[-CONSECUTIVE_FAILURE_THRESHOLD:]

        if (
            len(tail) >= CONSECUTIVE_FAILURE_THRESHOLD
            and all(s.failed for s in tail)
        ):
            return "down"

        slow_tail = tail[-CONSECUTIVE_SLOW_THRESHOLD:]
        if (
            len(slow_tail) >= CONSECUTIVE_SLOW_THRESHOLD
            and all(s.elapsed_ms >= SLOW_THRESHOLD_MS for s in slow_tail)
        ):
            return "degraded"

        return "ok"


_TRACKER = _AiHealthTracker()


def record_ai_call(elapsed_ms: int, failed: bool) -> None:
    """Append one observation to the rolling window."""
    _TRACKER.record(elapsed_ms, failed)


def ai_status() -> AiStatus:
    """Return current health status across the most recent calls."""
    return _TRACKER.status()


def reset_for_tests() -> None:
    """Test-only: drop all samples so each test starts on a clean slate."""
    _TRACKER.reset()


class AiCallTimer:
    """Context manager: times the wrapped block and records an observation.

    Usage::

        with AiCallTimer() as t:
            await voyage.embed(text)
        # t.failed defaults to False; set True on caught exceptions.
    """

    def __init__(self) -> None:
        self.failed = False
        self._t0 = 0.0
        self.elapsed_ms = 0

    def __enter__(self) -> "AiCallTimer":
        self._t0 = time.monotonic()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.elapsed_ms = int((time.monotonic() - self._t0) * 1000)
        if exc is not None:
            self.failed = True
        record_ai_call(self.elapsed_ms, self.failed)
