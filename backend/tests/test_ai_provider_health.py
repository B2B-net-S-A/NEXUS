"""Tests for per-provider AI health tracking and call_claude wiring."""

from __future__ import annotations

import pytest

from app.services import claude_client
from app.services.ai_health import (
    provider_status,
    record_provider_call,
    reset_providers_for_tests,
)


@pytest.fixture(autouse=True)
def _clean_providers():
    reset_providers_for_tests()
    yield
    reset_providers_for_tests()


def test_unknown_provider_is_ok():
    assert provider_status("never-seen") == "ok"


def test_three_consecutive_failures_trip_down():
    for _ in range(3):
        record_provider_call("p", 10, failed=True)
    assert provider_status("p") == "down"


def test_success_after_failures_recovers():
    for _ in range(3):
        record_provider_call("p", 10, failed=True)
    record_provider_call("p", 10, failed=False)
    assert provider_status("p") == "ok"


def test_providers_are_isolated():
    for _ in range(3):
        record_provider_call("a", 10, failed=True)
    assert provider_status("a") == "down"
    assert provider_status("b") == "ok"


# ── call_claude wiring ───────────────────────────────────────────────────────


class _FakeErr(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(str(status_code))
        self.status_code = status_code


class _FakeMessage:
    content = [type("Block", (), {"text": "ok"})()]


def _install_client(monkeypatch, side_effects):
    calls = {"n": 0}

    class _Msgs:
        def create(self, **_kwargs):
            i = calls["n"]
            calls["n"] += 1
            effect = side_effects[i]
            if isinstance(effect, Exception):
                raise effect
            return effect

    class _Client:
        def __init__(self, **_kwargs) -> None:
            self.messages = _Msgs()

    monkeypatch.setattr(claude_client.anthropic, "Anthropic", _Client)
    monkeypatch.setattr(claude_client.time, "sleep", lambda *_a, **_k: None)
    return calls


def test_call_claude_success_records_healthy(monkeypatch):
    _install_client(monkeypatch, [_FakeMessage()])
    claude_client.call_claude(
        messages=[{"role": "user", "content": "x"}],
        model="m",
        max_tokens=10,
        api_key="k",
    )
    assert provider_status("claude") == "ok"


def test_call_claude_repeated_failures_trip_claude_down(monkeypatch):
    _install_client(monkeypatch, [_FakeErr(529), _FakeErr(529), _FakeErr(529)])
    for _ in range(3):
        with pytest.raises(_FakeErr):
            claude_client.call_claude(
                messages=[{"role": "user", "content": "x"}],
                model="m",
                max_tokens=10,
                api_key="k",
                max_retries=0,
            )
    assert provider_status("claude") == "down"
