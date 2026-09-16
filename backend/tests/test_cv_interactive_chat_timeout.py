"""M12-B05: czat interaktywnego CV ma jawny budżet czasu i czytelny 504."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import anthropic
import httpx
import pytest


def _context():
    from app.services.cv_generator_b2b.interactive_chat import approved_chat_context

    return approved_chat_context(
        SimpleNamespace(language="pl", content_html="<p>Python od 2019.</p>")
    )


async def _ask(monkeypatch, provider):
    from app.services.cv_generator_b2b import interactive_chat as chat

    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-test-key")
    # F5: czat idzie na GPT Luna — sonda pyta o klucz dostawcy modelu.
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-test-key")
    monkeypatch.setattr(chat, "_history", AsyncMock(return_value=[]))
    monkeypatch.setattr(chat, "_persist_exchange", AsyncMock())
    monkeypatch.setattr(chat, "run_in_threadpool", provider)
    return await chat._answer_with_model(
        object(),
        SimpleNamespace(token="synthetic-link"),
        object(),
        "Ile lat Pythona?",
        approved_context=_context(),
    )


async def test_model_call_is_bounded_by_the_chat_budget(monkeypatch):
    from app.services.cv_generator_b2b import interactive_chat as chat

    provider = AsyncMock(
        return_value=SimpleNamespace(content=[SimpleNamespace(text="Od 2019.")])
    )
    assert await _ask(monkeypatch, provider) == "Od 2019."
    kwargs = provider.call_args.kwargs
    assert kwargs["total_timeout"] == chat.CHAT_TIMEOUT_SECONDS
    assert kwargs["timeout"] == chat.CHAT_TIMEOUT_SECONDS
    assert kwargs["max_retries"] == chat.CHAT_MAX_RETRIES
    # Budżet mieści się pod limitem proxy (60 s) — inaczej przeglądarka
    # dostałaby zerwane połączenie zamiast komunikatu.
    assert chat.CHAT_TIMEOUT_SECONDS < 60
    # Model domyślny bez zmian.
    assert kwargs["model"] == chat.CHAT_MODEL


@pytest.mark.parametrize(
    "error",
    [
        "deadline",
        "httpx",
    ],
)
async def test_timeouts_become_chat_timeout(monkeypatch, error):
    from app.services.claude_client import ClaudeDeadlineExceeded
    from app.services.cv_generator_b2b import interactive_chat as chat

    exc = (
        ClaudeDeadlineExceeded("AI response deadline exceeded")
        if error == "deadline"
        else anthropic.APITimeoutError(
            request=httpx.Request("POST", "https://api.invalid/v1/messages")
        )
    )
    with pytest.raises(chat.CvChatTimeout):
        await _ask(monkeypatch, AsyncMock(side_effect=exc))


async def test_other_failures_stay_generic_llm_errors(monkeypatch):
    from app.services.cv_generator_b2b import interactive_chat as chat

    with pytest.raises(chat.CvChatLLMError) as raised:
        await _ask(monkeypatch, AsyncMock(side_effect=RuntimeError("boom")))
    assert not isinstance(raised.value, chat.CvChatTimeout)
    chat._persist_exchange.assert_not_called()


@pytest.mark.parametrize("error,status", [("timeout", 504), ("llm", 502)])
async def test_endpoint_answers_timeout_with_readable_message(
    monkeypatch, error, status
):
    from fastapi import HTTPException, Request, Response

    from app.api import public_share as api
    from app.services.cv_generator_b2b import interactive_chat as chat

    doc = SimpleNamespace(status="ready", mode="upload", render_payload={"name": "X"})
    row = SimpleNamespace(
        token="v2$synthetic", document_version_id=None, generated_document=doc
    )
    monkeypatch.setattr(api, "_load_generated_share", AsyncMock(return_value=row))
    monkeypatch.setattr(api, "_interactive_flags", AsyncMock(return_value=(True, True)))
    exc = chat.CvChatTimeout("slow") if error == "timeout" else chat.CvChatLLMError("x")
    monkeypatch.setattr(chat, "answer_question", AsyncMock(side_effect=exc))
    with pytest.raises(HTTPException) as raised:
        await api.post_public_generated_cv_chat.__wrapped__(
            "synthetic",
            Request({"type": "http", "method": "POST", "path": "/"}),
            api.PublicCvChatRequest(question="Doświadczenie?"),
            Response(),
            object(),
        )
    assert raised.value.status_code == status
    if error == "timeout":
        assert "nie odpowiedział na czas" in raised.value.detail
