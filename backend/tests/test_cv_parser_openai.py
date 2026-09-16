"""Parser CV — dostawca OpenAI (gpt-5.6-luna) przed Claude'em.

Trzy kontrakty:
1. Z `CV_PARSE_PROVIDER=openai` wynik OpenAI wygrywa i jest znakowany
   `_source=openai:...` — czyli po `cv_extracted_data` da się policzyć, co
   sparsował który dostawca.
2. OpenAI zwracające None (brak klucza, HTTP ≠ 200, nie-JSON) NIE psuje
   parsera: hierarchia schodzi na Claude → Ollama → regex jak dotąd.
3. Domyślny provider „claude" w ogóle nie woła OpenAI.

Parsowanie odpowiedzi Responses API testujemy osobno: `output_text` (skrót)
i sklejane bloki `output[].content[].text`.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.services import cv_parser

_CV = "Jan Kowalski\njan@example.com\n+48 600 100 200\nPython, Django, PostgreSQL\n5 lat doświadczenia"


def test_extract_openai_text_prefers_output_text():
    assert cv_parser._extract_openai_text({"output_text": '{"a": 1}'}) == '{"a": 1}'


def test_extract_openai_text_joins_content_blocks():
    payload = {
        "output": [
            {"type": "reasoning", "content": []},
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": '{"first_name": '},
                    {"type": "output_text", "text": '"Jan"}'},
                ],
            },
        ]
    }
    assert cv_parser._extract_openai_text(payload) == '{"first_name": "Jan"}'


@pytest.mark.asyncio
async def test_openai_result_wins_when_provider_is_openai(monkeypatch):
    monkeypatch.setattr(settings, "CV_PARSE_PROVIDER", "openai")

    async def _openai(cv_text, **_k):
        return {
            "first_name": "Jan",
            "last_name": "Kowalski",
            "skills": ["Python"],
            "_source": "openai:cv_enrichment:v6",
        }

    async def _claude(cv_text, **_k):  # pragma: no cover — nie może być wołany
        raise AssertionError("Claude nie powinien być wołany, gdy OpenAI zwrócił wynik")

    monkeypatch.setattr(cv_parser, "_parse_with_openai", _openai)
    monkeypatch.setattr(cv_parser, "_parse_with_claude", _claude)
    parsed = await cv_parser.parse_cv(_CV)
    assert parsed["first_name"] == "Jan"
    assert parsed["_source"].startswith("openai:")
    # Fallback kontaktowy z regexu dokłada e-mail, którego LLM nie zwrócił.
    assert parsed["email"] == "jan@example.com"


@pytest.mark.asyncio
async def test_openai_failure_falls_back_to_claude(monkeypatch):
    monkeypatch.setattr(settings, "CV_PARSE_PROVIDER", "openai")

    async def _openai(cv_text, **_k):
        return None

    async def _claude(cv_text, **_k):
        return {
            "first_name": "Jan",
            "last_name": "Kowalski",
            "_source": "claude:cv_enrichment:v6",
        }

    monkeypatch.setattr(cv_parser, "_parse_with_openai", _openai)
    monkeypatch.setattr(cv_parser, "_parse_with_claude", _claude)
    parsed = await cv_parser.parse_cv(_CV)
    assert parsed["_source"].startswith("claude:")


@pytest.mark.asyncio
async def test_default_provider_never_calls_openai(monkeypatch):
    monkeypatch.setattr(settings, "CV_PARSE_PROVIDER", "claude")
    calls: list[str] = []

    async def _openai(cv_text, **_k):  # pragma: no cover
        calls.append("openai")
        return {"first_name": "X"}

    async def _claude(cv_text, **_k):
        return None

    monkeypatch.setattr(cv_parser, "_parse_with_openai", _openai)
    monkeypatch.setattr(cv_parser, "_parse_with_claude", _claude)
    monkeypatch.setattr(cv_parser, "_parse_with_ollama", _claude)
    parsed = await cv_parser.parse_cv(_CV)
    assert calls == []
    assert parsed["_source"] == "regex"


@pytest.mark.asyncio
async def test_openai_without_key_returns_none(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    assert await cv_parser._parse_with_openai(_CV) is None
