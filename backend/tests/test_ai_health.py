"""Unit tests for the AI matching circuit breaker.

In-process module — no network, no DB. Each test resets the rolling window
explicitly so the global tracker doesn't leak state across cases.
"""

from __future__ import annotations

import pytest

from app.services.ai_health import (
    CONSECUTIVE_FAILURE_THRESHOLD,
    SLOW_THRESHOLD_MS,
    ai_status,
    record_ai_call,
    reset_for_tests,
)


@pytest.fixture(autouse=True)
def _reset_tracker():
    reset_for_tests()
    yield
    reset_for_tests()


class TestStatusTransitions:
    def test_empty_window_is_ok(self):
        assert ai_status() == "ok"

    def test_single_fast_ok_call_keeps_status_ok(self):
        record_ai_call(elapsed_ms=120, failed=False)
        assert ai_status() == "ok"

    def test_one_failure_alone_is_not_down(self):
        record_ai_call(elapsed_ms=200, failed=True)
        assert ai_status() == "ok"

    def test_three_consecutive_failures_flip_to_down(self):
        for _ in range(CONSECUTIVE_FAILURE_THRESHOLD):
            record_ai_call(elapsed_ms=200, failed=True)
        assert ai_status() == "down"

    def test_three_consecutive_slow_calls_flip_to_degraded(self):
        for _ in range(3):
            record_ai_call(elapsed_ms=SLOW_THRESHOLD_MS + 200, failed=False)
        assert ai_status() == "degraded"

    def test_one_ok_call_after_failures_resets_to_ok(self):
        for _ in range(CONSECUTIVE_FAILURE_THRESHOLD):
            record_ai_call(elapsed_ms=200, failed=True)
        assert ai_status() == "down"
        record_ai_call(elapsed_ms=120, failed=False)
        assert ai_status() == "ok"

    def test_failure_outranks_slow(self):
        # Two slow + one failed call: tail is [slow, slow, failed] — failure
        # streak is only 1, slow streak is broken → status stays ok.
        record_ai_call(elapsed_ms=SLOW_THRESHOLD_MS + 100, failed=False)
        record_ai_call(elapsed_ms=SLOW_THRESHOLD_MS + 100, failed=False)
        record_ai_call(elapsed_ms=200, failed=True)
        assert ai_status() == "ok"

    def test_mixed_slow_and_fast_below_threshold_stays_ok(self):
        record_ai_call(elapsed_ms=SLOW_THRESHOLD_MS + 100, failed=False)
        record_ai_call(elapsed_ms=120, failed=False)
        record_ai_call(elapsed_ms=SLOW_THRESHOLD_MS + 100, failed=False)
        assert ai_status() == "ok"


class TestRollingWindow:
    def test_window_caps_at_10_samples(self):
        # Push 12 ok calls then 3 failures — failures should still flip down.
        for _ in range(12):
            record_ai_call(elapsed_ms=120, failed=False)
        for _ in range(3):
            record_ai_call(elapsed_ms=200, failed=True)
        assert ai_status() == "down"
