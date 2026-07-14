"""Small in-process circuit breaker keyed by provider/model."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class _State:
    failures: int = 0
    opened_at: float | None = None
    last_success_at: float | None = None


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 3, cooldown_seconds: int = 60) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._states: dict[str, _State] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        with self._lock:
            state = self._states.setdefault(key, _State())
            if state.opened_at is None:
                return True
            if time.monotonic() - state.opened_at >= self.cooldown_seconds:
                state.opened_at = None
                state.failures = 0
                return True
            return False

    def success(self, key: str) -> None:
        with self._lock:
            state = self._states.setdefault(key, _State())
            state.failures = 0
            state.opened_at = None
            state.last_success_at = time.time()

    def failure(self, key: str) -> None:
        with self._lock:
            state = self._states.setdefault(key, _State())
            state.failures += 1
            if state.failures >= self.failure_threshold:
                state.opened_at = time.monotonic()

    def snapshot(self) -> dict[str, dict[str, int | float | bool | None]]:
        with self._lock:
            return {
                key: {
                    "failures": state.failures,
                    "open": state.opened_at is not None,
                    "last_success_at": state.last_success_at,
                }
                for key, state in self._states.items()
            }


circuit_breaker = CircuitBreaker()
