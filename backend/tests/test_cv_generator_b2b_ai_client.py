"""Unit tests for the CV Generator B2B AI client resilience layer.

Covers the 2026-06-23 fix for the production "Claude call failed: Error code
529 - overloaded_error" failure: model fallback chain, retry-then-fallback
cascade, the clean user-facing overload message, and the no-fallback-on-4xx
guard so a misconfigured model surfaces instead of being silently masked.
"""

from __future__ import annotations

import pytest

import app.services.cv_generator_b2b.ai_client as ai_client
from app.services.cv_generator_b2b.ai_client import (
    CVGeneratorAIError,
    CVGeneratorOverloadedError,
    CVGeneratorTruncatedError,
    analyze_with_ai,
)


# ── Fakes ───────────────────────────────────────────────────────────────────


class _FakeUsage:
    input_tokens = 100
    output_tokens = 200
    cache_read_input_tokens = 0


class _FakeBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeMessage:
    def __init__(self, text: str, stop_reason: str = "end_turn") -> None:
        self.content = [_FakeBlock(text)]
        self.stop_reason = stop_reason
        self.usage = _FakeUsage()


class _FakeStatusError(Exception):
    """Mimics an anthropic API error carrying a status_code (e.g. 529/400)."""

    def __init__(self, status_code: int, err_type: str) -> None:
        super().__init__(f"Error code: {status_code} - {err_type}")
        self.status_code = status_code
        self.body = {"error": {"type": err_type}}


def _install_fake_client(monkeypatch, plan):
    """Patch the Anthropic constructor with a fake driven by ``plan``.

    ``plan`` maps a model name to a zero-arg callable invoked on each
    ``messages.create`` call — it returns a ``_FakeMessage`` or raises. The
    list of models actually called (in order) is returned for assertions.
    """
    calls: list[str] = []

    class _FakeMessages:
        def create(self, *, model, max_tokens, messages, **kwargs):
            calls.append(model)
            return plan[model]()

    class _FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            self.messages = _FakeMessages()

    monkeypatch.setattr(ai_client.anthropic, "Anthropic", _FakeClient)
    # No real sleeping during backoff.
    monkeypatch.setattr(ai_client.time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    return calls


# ── _models() chain ──────────────────────────────────────────────────────────


def test_default_model_chain(monkeypatch):
    monkeypatch.delenv("CV_B2B_MODEL", raising=False)
    monkeypatch.delenv("CV_B2B_FALLBACK_MODELS", raising=False)
    assert ai_client._models() == ["claude-sonnet-5", "claude-opus-4-8"]


def test_model_chain_respects_env_and_dedups(monkeypatch):
    monkeypatch.setenv("CV_B2B_MODEL", "claude-opus-4-8")
    # Duplicate of primary + a real fallback — primary must win and dedup.
    monkeypatch.setenv("CV_B2B_FALLBACK_MODELS", "claude-opus-4-8, claude-haiku-4-5")
    assert ai_client._models() == ["claude-opus-4-8", "claude-haiku-4-5"]


def test_empty_fallback_env_yields_single_model(monkeypatch):
    monkeypatch.setenv("CV_B2B_MODEL", "claude-sonnet-5")
    monkeypatch.setenv("CV_B2B_FALLBACK_MODELS", "")
    assert ai_client._models() == ["claude-sonnet-5"]


# ── analyze_with_ai behaviour ────────────────────────────────────────────────


def test_success_on_primary_no_fallback(monkeypatch):
    monkeypatch.delenv("CV_B2B_MODEL", raising=False)
    monkeypatch.delenv("CV_B2B_FALLBACK_MODELS", raising=False)
    calls = _install_fake_client(
        monkeypatch,
        {
            "claude-sonnet-5": lambda: _FakeMessage('{"ok": true}'),
            "claude-opus-4-8": lambda: _FakeMessage("should-not-be-called"),
        },
    )

    out = analyze_with_ai("payload", "req-1", system="sys")

    assert out == '{"ok": true}'
    assert calls == ["claude-sonnet-5"]  # fallback never touched


def test_falls_back_to_second_model_on_overload(monkeypatch):
    monkeypatch.delenv("CV_B2B_MODEL", raising=False)
    monkeypatch.delenv("CV_B2B_FALLBACK_MODELS", raising=False)
    monkeypatch.setenv("CV_B2B_MAX_RETRIES", "1")

    def overloaded():
        raise _FakeStatusError(529, "overloaded_error")

    calls = _install_fake_client(
        monkeypatch,
        {
            "claude-sonnet-5": overloaded,
            "claude-opus-4-8": lambda: _FakeMessage('{"from": "opus"}'),
        },
    )

    out = analyze_with_ai("payload", "req-2")

    assert out == '{"from": "opus"}'
    # Primary retried (max_retries=1 → 2 attempts) then opus succeeded once.
    assert calls == ["claude-sonnet-5", "claude-sonnet-5", "claude-opus-4-8"]


def test_all_models_overloaded_raises_clean_message(monkeypatch):
    monkeypatch.delenv("CV_B2B_MODEL", raising=False)
    monkeypatch.delenv("CV_B2B_FALLBACK_MODELS", raising=False)
    monkeypatch.setenv("CV_B2B_MAX_RETRIES", "0")

    def overloaded():
        raise _FakeStatusError(529, "overloaded_error")

    _install_fake_client(
        monkeypatch,
        {
            "claude-sonnet-5": overloaded,
            "claude-opus-4-8": overloaded,
        },
    )

    with pytest.raises(CVGeneratorOverloadedError) as exc:
        analyze_with_ai("payload", "req-3")

    msg = str(exc.value)
    assert "przeciążona" in msg
    # The raw API dict must NOT leak into the user-facing message.
    assert "overloaded_error" not in msg
    assert "529" not in msg


def test_overload_then_non_retryable_fallback_still_overloaded(monkeypatch):
    # Primary 529 (retryable) → fallback raises a non-retryable 4xx. The
    # recoverable condition still holds (a later retry could hit the recovered
    # primary), so the clean overload message must win over the fallback's 4xx.
    monkeypatch.delenv("CV_B2B_MODEL", raising=False)
    monkeypatch.delenv("CV_B2B_FALLBACK_MODELS", raising=False)
    monkeypatch.setenv("CV_B2B_MAX_RETRIES", "0")

    def overloaded():
        raise _FakeStatusError(529, "overloaded_error")

    def bad_request():
        raise _FakeStatusError(400, "invalid_request_error")

    calls = _install_fake_client(
        monkeypatch,
        {
            "claude-sonnet-5": overloaded,
            "claude-opus-4-8": bad_request,
        },
    )

    with pytest.raises(CVGeneratorOverloadedError):
        analyze_with_ai("payload", "req-overload-then-4xx")

    assert calls == ["claude-sonnet-5", "claude-opus-4-8"]


def test_empty_model_chain_raises_without_calling_claude(monkeypatch):
    monkeypatch.setenv("CV_B2B_MODEL", "")
    monkeypatch.setenv("CV_B2B_FALLBACK_MODELS", "")
    calls = _install_fake_client(
        monkeypatch,
        {"claude-sonnet-5": lambda: _FakeMessage("unreached")},
    )

    with pytest.raises(CVGeneratorAIError) as exc:
        analyze_with_ai("payload", "req-empty-chain")

    # Config error surfaced up front; no Claude call attempted.
    assert not isinstance(exc.value, CVGeneratorOverloadedError)
    assert calls == []


def test_garbage_max_retries_env_does_not_crash(monkeypatch):
    # An empty/garbage numeric override must fall back to the default instead of
    # raising ValueError → bare 500.
    monkeypatch.delenv("CV_B2B_MODEL", raising=False)
    monkeypatch.delenv("CV_B2B_FALLBACK_MODELS", raising=False)
    monkeypatch.setenv("CV_B2B_MAX_RETRIES", "")
    monkeypatch.setenv("CV_B2B_MAX_TOKENS", "not-a-number")
    _install_fake_client(
        monkeypatch,
        {"claude-sonnet-5": lambda: _FakeMessage('{"ok": 1}')},
    )

    assert analyze_with_ai("payload", "req-garbage-env") == '{"ok": 1}'


def test_non_retryable_4xx_does_not_fall_back(monkeypatch):
    monkeypatch.delenv("CV_B2B_MODEL", raising=False)
    monkeypatch.delenv("CV_B2B_FALLBACK_MODELS", raising=False)
    monkeypatch.setenv("CV_B2B_MAX_RETRIES", "2")

    def bad_request():
        raise _FakeStatusError(400, "invalid_request_error")

    calls = _install_fake_client(
        monkeypatch,
        {
            "claude-sonnet-5": bad_request,
            "claude-opus-4-8": lambda: _FakeMessage("unreached"),
        },
    )

    with pytest.raises(CVGeneratorAIError) as exc:
        analyze_with_ai("payload", "req-4")

    # Not an overload — surfaced as a plain AI error, fallback never attempted,
    # and no pointless retries on a deterministic 4xx.
    assert not isinstance(exc.value, CVGeneratorOverloadedError)
    assert calls == ["claude-sonnet-5"]


def test_truncation_raises_immediately_without_fallback(monkeypatch):
    monkeypatch.delenv("CV_B2B_MODEL", raising=False)
    monkeypatch.delenv("CV_B2B_FALLBACK_MODELS", raising=False)
    calls = _install_fake_client(
        monkeypatch,
        {
            "claude-sonnet-5": lambda: _FakeMessage("{...", stop_reason="max_tokens"),
            "claude-opus-4-8": lambda: _FakeMessage("unreached"),
        },
    )

    with pytest.raises(CVGeneratorTruncatedError):
        analyze_with_ai("payload", "req-5")

    # Truncation is a content-length issue — identical on any model, so no
    # fallback is attempted.
    assert calls == ["claude-sonnet-5"]


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # Also neutralise the settings fallback so no real key leaks in.
    monkeypatch.setattr(ai_client, "_api_key", lambda: None)
    with pytest.raises(CVGeneratorAIError):
        analyze_with_ai("payload", "req-6")


# ── content-block extraction (Claude 5 thinking-block resilience) ─────────────


class _FakeThinkingBlock:
    """A non-text block (e.g. a thinking block) — no ``.text`` attribute."""

    def __init__(self, thinking: str) -> None:
        self.thinking = thinking


class _MultiBlockMessage:
    def __init__(self, blocks, stop_reason: str = "end_turn") -> None:
        self.content = list(blocks)
        self.stop_reason = stop_reason
        self.usage = _FakeUsage()


def test_extracts_text_when_thinking_block_leads(monkeypatch):
    # Claude 5 can return a thinking block as content[0]; the JSON lives in a
    # later text block. Reading content[0].text would yield "" → a misleading
    # "invalid JSON (char 0)" failure downstream. The client must skip the
    # thinking block and return the text block's payload.
    monkeypatch.delenv("CV_B2B_MODEL", raising=False)
    monkeypatch.delenv("CV_B2B_FALLBACK_MODELS", raising=False)
    _install_fake_client(
        monkeypatch,
        {
            "claude-sonnet-5": lambda: _MultiBlockMessage(
                [_FakeThinkingBlock("reasoning..."), _FakeBlock('{"ok": true}')]
            ),
        },
    )

    assert analyze_with_ai("payload", "req-thinking") == '{"ok": true}'


def test_no_text_block_raises_clean_error(monkeypatch):
    # A response with only non-text blocks must raise a clean AI error instead
    # of returning "" (which fails JSON parsing at char 0 downstream).
    monkeypatch.delenv("CV_B2B_MODEL", raising=False)
    monkeypatch.setenv("CV_B2B_FALLBACK_MODELS", "")  # single model, no fallback
    monkeypatch.setenv("CV_B2B_MAX_RETRIES", "0")
    _install_fake_client(
        monkeypatch,
        {
            "claude-sonnet-5": lambda: _MultiBlockMessage(
                [_FakeThinkingBlock("only thinking, no answer")]
            ),
        },
    )

    with pytest.raises(CVGeneratorAIError):
        analyze_with_ai("payload", "req-no-text")
