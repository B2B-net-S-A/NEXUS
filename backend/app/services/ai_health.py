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

        if len(tail) >= CONSECUTIVE_FAILURE_THRESHOLD and all(s.failed for s in tail):
            return "down"

        slow_tail = tail[-CONSECUTIVE_SLOW_THRESHOLD:]
        if len(slow_tail) >= CONSECUTIVE_SLOW_THRESHOLD and all(
            s.elapsed_ms >= SLOW_THRESHOLD_MS for s in slow_tail
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


# ── Per-provider trackers ────────────────────────────────────────────────────
# The global _TRACKER above is the legacy "matching pipeline" view (Voyage +
# Qdrant, surfaced as meta.ai_status). These named trackers let individual
# providers (e.g. "claude") report their own recent health independently — used
# by /api/health to show a provider as degraded/down after a run of failures,
# without any of them flipping the app's overall status.

_PROVIDER_TRACKERS: dict[str, _AiHealthTracker] = {}
_PROVIDER_REGISTRY_LOCK = threading.Lock()


def _tracker_for(provider: str) -> _AiHealthTracker:
    with _PROVIDER_REGISTRY_LOCK:
        tracker = _PROVIDER_TRACKERS.get(provider)
        if tracker is None:
            tracker = _AiHealthTracker()
            _PROVIDER_TRACKERS[provider] = tracker
        return tracker


def record_provider_call(provider: str, elapsed_ms: int, failed: bool) -> None:
    """Append one observation to the named provider's rolling window."""
    _tracker_for(provider).record(elapsed_ms, failed)


def provider_status(provider: str) -> AiStatus:
    """Recent health for one provider (``ok`` when it has no samples yet)."""
    with _PROVIDER_REGISTRY_LOCK:
        tracker = _PROVIDER_TRACKERS.get(provider)
    return tracker.status() if tracker is not None else "ok"


def provider_observed(provider: str) -> bool:
    """Whether this provider has reported at least one call in this process.

    ``provider_status`` answers ``ok`` for a provider nobody ever called, which
    is indistinguishable from a provider that is genuinely healthy. That is the
    shape of every false-green outage: the probe reports success because it has
    nothing to report. Callers that surface health to humans must pair the two
    and say "unknown" when this is False, so a dependency that is silently never
    exercised — or wired up wrong — cannot pass as working.
    """
    with _PROVIDER_REGISTRY_LOCK:
        tracker = _PROVIDER_TRACKERS.get(provider)
    if tracker is None:
        return False
    with tracker._lock:  # noqa: SLF001 — same module, deliberate
        return bool(tracker._samples)


def provider_health_label(provider: str) -> str:
    """Health of one provider as the string ``/api/health`` publishes.

    ``unknown`` means "not exercised since this process started" — not a
    failure, but explicitly not a pass either.
    """
    if not provider_observed(provider):
        return "unknown"
    return {"ok": "healthy", "degraded": "degraded", "down": "unhealthy"}[
        provider_status(provider)
    ]


def reset_providers_for_tests() -> None:
    """Test-only: drop all per-provider samples."""
    with _PROVIDER_REGISTRY_LOCK:
        _PROVIDER_TRACKERS.clear()
