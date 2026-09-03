"""C-12: fallback Ollama tylko przy JAWNIE ustawionym OLLAMA_BASE_URL.

Usługi nie ma w compose prod. Niepusty default ("http://localhost:11434")
sprawiał, że guard `if not host: return None` w trzech konsumentach nigdy nie
chronił — każda awaria Claude'a/Voyage dokładała nieudane HTTP na localhost.
"""

import pytest

from app.core.config import Settings


def test_ollama_base_url_defaults_to_empty():
    """Default klasy jest PUSTY (env-niezależnie) — brak Ollamy bez konfiguracji."""
    assert Settings.model_fields["OLLAMA_BASE_URL"].default == ""


@pytest.mark.asyncio
async def test_cv_parser_skips_ollama_when_unset(monkeypatch):
    from app.core.config import settings
    from app.services import cv_parser

    monkeypatch.setattr(settings, "OLLAMA_BASE_URL", "")
    monkeypatch.delattr(settings, "OLLAMA_HOST", raising=False)

    called = {"http": False}

    class _Boom:
        def __init__(self, *_a, **_k):
            called["http"] = True

    # Gdyby guard nie zadziałał, _parse_with_ollama zbudowałby klienta HTTP.
    monkeypatch.setattr("httpx.AsyncClient", _Boom)

    result = await cv_parser._parse_with_ollama("jakiś tekst CV")
    assert result is None
    assert called["http"] is False, "próba HTTP na Ollamę mimo pustego OLLAMA_BASE_URL"


@pytest.mark.asyncio
async def test_embedding_service_skips_ollama_when_unset(monkeypatch):
    from app.core.config import settings
    from app.services import embedding_service

    monkeypatch.setattr(settings, "OLLAMA_BASE_URL", "")
    monkeypatch.delattr(settings, "OLLAMA_HOST", raising=False)

    called = {"http": False}

    class _Boom:
        def __init__(self, *_a, **_k):
            called["http"] = True

    monkeypatch.setattr("httpx.AsyncClient", _Boom)

    result = await embedding_service._ollama_embed("tekst")
    assert result is None
    assert called["http"] is False
