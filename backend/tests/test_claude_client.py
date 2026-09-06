"""Unit tests for the shared resilient Claude helper (app.services.claude_client).

Covers the retry classification and the timeout/backoff loop without touching the
real Anthropic SDK — the client is monkeypatched and time.sleep is stubbed.
"""

from __future__ import annotations

import pytest

from app.services import claude_client
from app.services.claude_client import call_claude, is_retryable_anthropic_error


class _FakeErr(Exception):
    """Minimal error carrying a status_code (what is_retryable inspects first)."""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"status {status_code}")
        self.status_code = status_code


class _FakeMessage:
    def __init__(self, text: str) -> None:
        self.content = [type("Block", (), {"text": text})()]


def _install_fake_client(monkeypatch, side_effects):
    """Patch anthropic.Anthropic so messages.create yields side_effects in order.

    Each element is either an exception (raised) or a value (returned).
    Returns a dict whose ``n`` counts how many times create() was invoked.
    """
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


@pytest.fixture(autouse=True)
def _declare_provider_calls():
    """Zadeklaruj wywołania AI na czas testów w tym pliku.

    Te testy podmieniają KLIENTA SDK, nie `call_claude` — więc realnie wchodzą
    w `_assert_declared`. Od 0270 CI biegnie z `AI_QUOTA_STRICT=true`, gdzie
    niezadeklarowane wywołanie rzuca `AIQuotaUngated`; bez tej deklaracji test
    padałby na bramce kwot zamiast sprawdzać to, po co istnieje (polityka
    ponowień, łańcuch modeli, telemetria zdrowia).

    Deklaracja, nie wyłączenie STRICT: dzięki temu testy przechodzą tą samą
    ścieżką, którą chodzi produkcja.
    """
    from datetime import date

    from app.models.ai_feature import AIFeatureKey
    from app.services.ai_quota import QuotaState, declared_call

    with declared_call(
        AIFeatureKey.scoring,
        user_id=None,
        state=QuotaState(used=1, limit=0, period_start=date(2026, 9, 1)),
    ):
        yield


def test_is_retryable_classification():
    assert is_retryable_anthropic_error(_FakeErr(429)) is True
    assert is_retryable_anthropic_error(_FakeErr(529)) is True
    assert is_retryable_anthropic_error(_FakeErr(400)) is False
    assert is_retryable_anthropic_error(_FakeErr(404)) is False
    assert is_retryable_anthropic_error(ValueError("bad request")) is False


def test_call_claude_retries_transient_then_succeeds(monkeypatch):
    msg = _FakeMessage("ok")
    calls = _install_fake_client(monkeypatch, [_FakeErr(529), _FakeErr(429), msg])

    result = call_claude(
        messages=[{"role": "user", "content": "x"}],
        model="m",
        max_tokens=10,
        api_key="k",
        max_retries=2,
    )

    assert result is msg
    assert calls["n"] == 3  # two transient failures then success


def test_call_claude_does_not_retry_non_retryable(monkeypatch):
    calls = _install_fake_client(monkeypatch, [_FakeErr(400)])

    with pytest.raises(_FakeErr):
        call_claude(
            messages=[{"role": "user", "content": "x"}],
            model="m",
            max_tokens=10,
            api_key="k",
            max_retries=2,
        )

    assert calls["n"] == 1  # 4xx surfaces immediately, no retry


def test_call_claude_exhausts_retry_budget(monkeypatch):
    calls = _install_fake_client(
        monkeypatch, [_FakeErr(529), _FakeErr(529), _FakeErr(529)]
    )

    with pytest.raises(_FakeErr):
        call_claude(
            messages=[{"role": "user", "content": "x"}],
            model="m",
            max_tokens=10,
            api_key="k",
            max_retries=2,
        )

    assert calls["n"] == 3  # first attempt + 2 retries, then re-raise
