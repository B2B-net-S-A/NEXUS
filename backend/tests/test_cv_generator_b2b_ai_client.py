"""CV B2B gateway wrapper tests."""

from types import SimpleNamespace

import pytest

import app.services.cv_generator_b2b.ai_client as ai_client
from app.ai import AIError
from app.services.cv_generator_b2b.ai_client import (
    CVGeneratorAIError,
    CVGeneratorOverloadedError,
    CVGeneratorTruncatedError,
    analyze_with_ai,
)


@pytest.mark.asyncio
async def test_success_uses_cv_b2b_route_and_preserves_context(monkeypatch):
    captured = {}

    async def call(request):  # type: ignore[no-untyped-def]
        captured["request"] = request
        return SimpleNamespace(content='{"ok": true}', model="claude-sonnet-4-6")

    monkeypatch.setattr(ai_client.ai_gateway, "call", call)
    out = await analyze_with_ai(
        "payload",
        "req-1",
        system="sys",
        user_id=7,
        client_id=9,
        candidate_id=11,
    )
    request = captured["request"]
    assert out == '{"ok": true}'
    assert request.feature.value == "cv_b2b"
    assert request.request_id == "req-1"
    assert request.user_id == 7
    assert request.client_id == 9
    assert request.subject_id == 11
    assert request.messages[0] == {"role": "system", "content": "sys"}


@pytest.mark.asyncio
async def test_no_text_raises_clean_error(monkeypatch):
    async def call(_request):  # type: ignore[no-untyped-def]
        return SimpleNamespace(content="", model="claude-sonnet-4-6")

    monkeypatch.setattr(ai_client.ai_gateway, "call", call)
    with pytest.raises(CVGeneratorAIError):
        await analyze_with_ai("payload", "req-empty")


@pytest.mark.asyncio
async def test_truncation_maps_to_dedicated_error(monkeypatch):
    async def call(_request):  # type: ignore[no-untyped-def]
        raise AIError("max_tokens", "truncated")

    monkeypatch.setattr(ai_client.ai_gateway, "call", call)
    with pytest.raises(CVGeneratorTruncatedError):
        await analyze_with_ai("payload", "req-truncated")


@pytest.mark.asyncio
async def test_transient_error_maps_to_retry_actionable_message(monkeypatch):
    async def call(_request):  # type: ignore[no-untyped-def]
        raise AIError("provider_error", "sensitive body", retryable=True)

    monkeypatch.setattr(ai_client.ai_gateway, "call", call)
    with pytest.raises(CVGeneratorOverloadedError) as exc:
        await analyze_with_ai("payload", "req-overload")
    assert "przeciążona" in str(exc.value)
    assert "sensitive body" not in str(exc.value)


@pytest.mark.asyncio
async def test_non_retryable_error_redacts_provider_message(monkeypatch):
    async def call(_request):  # type: ignore[no-untyped-def]
        raise AIError("provider_error", "anna.private@example.com raw CV")

    monkeypatch.setattr(ai_client.ai_gateway, "call", call)
    with pytest.raises(CVGeneratorAIError) as exc:
        await analyze_with_ai("payload", "req-hard")
    assert "anna.private@example.com" not in str(exc.value)
    assert "code=provider_error" in str(exc.value)


@pytest.mark.asyncio
async def test_no_automatic_fallback_is_encoded_in_wrapper(monkeypatch):
    calls = 0

    async def call(_request):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        raise AIError("provider_error", "failed")

    monkeypatch.setattr(ai_client.ai_gateway, "call", call)
    with pytest.raises(CVGeneratorAIError):
        await analyze_with_ai("payload", "req-no-fallback")
    assert calls == 1
