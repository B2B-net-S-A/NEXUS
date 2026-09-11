"""CV generator retries: 3 by default again, all inside the shared time budget.

#1476 lowered the default to 1 together with adding `CV_B2B_TOTAL_TIMEOUT`.
The budget — not the retry count — is what bounds a stage: `call_claude` never
starts an attempt after the deadline and refuses a backoff that would cross
it. With a single retry a short burst of 529s failed the generation while
minutes of budget were left.
"""

from __future__ import annotations

from unittest.mock import Mock

from app.services.cv_generator_b2b import provider
from tests.test_cv_generator_provider import (  # noqa: F401 — autouse fixture
    _declare_provider_calls,
    _FakeErr,
    _FakeMessage,
    _install,
)


def test_default_retries_run_inside_the_total_budget(monkeypatch):
    monkeypatch.delenv("CV_B2B_MAX_RETRIES", raising=False)
    monkeypatch.delenv("CV_B2B_TOTAL_TIMEOUT", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    call = Mock(return_value="{}")
    monkeypatch.setattr(provider, "call_claude_text", call)

    provider.analyze_with_ai("dane", "req-retries")

    kwargs = call.call_args.kwargs
    assert kwargs["max_retries"] == 3
    assert kwargs["total_timeout"] == 300.0
    assert kwargs["stream_response"] is True


def test_three_overloads_are_survived_on_the_primary_model(monkeypatch):
    monkeypatch.delenv("CV_B2B_MAX_RETRIES", raising=False)
    monkeypatch.setenv("CV_B2B_MODEL", "model-a")
    monkeypatch.setenv("CV_B2B_FALLBACK_MODELS", "")
    seen = _install(
        monkeypatch,
        [_FakeErr(529), _FakeErr(529), _FakeErr(529), _FakeMessage("{}")],
    )

    assert provider.analyze_with_ai("dane", "req-overload") == "{}"
    assert [c["model"] for c in seen] == ["model-a"] * 4


def test_an_explicit_env_value_still_wins(monkeypatch):
    monkeypatch.setenv("CV_B2B_MAX_RETRIES", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    call = Mock(return_value="{}")
    monkeypatch.setattr(provider, "call_claude_text", call)

    provider.analyze_with_ai("dane", "req-env")

    assert call.call_args.kwargs["max_retries"] == 1
