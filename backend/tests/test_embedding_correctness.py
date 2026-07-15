"""Focused unit tests for AI matching correctness hotfixes (plan PR3).

Covers:
  * AI-P0-02 — reverse search (`search_jobs_semantic`) must embed the query
    with ``input_type="query"``, never as a document.
  * AI-P0-03 — an Ollama fallback vector must never be written to the Voyage
    embedding cache (same 1024 dims, different semantic space).

All tests are host-native: Voyage, Ollama, Qdrant and the DB cache are
monkeypatched, so nothing touches the network or Postgres.
"""

from __future__ import annotations

import pytest

from app.services import embedding_service


@pytest.mark.asyncio
async def test_search_jobs_semantic_embeds_query_as_query(monkeypatch):
    """Reverse job search must request an ``input_type="query"`` embedding."""
    captured: dict[str, object] = {}

    async def _spy_embed(text, *, input_type="document", use_cache=True):
        captured["input_type"] = input_type
        # Returning None short-circuits before Qdrant, so no vector DB needed.
        return None

    monkeypatch.setattr(embedding_service, "generate_embedding", _spy_embed)

    result = await embedding_service.search_jobs_semantic("python fastapi senior")

    assert result == []
    assert captured["input_type"] == "query"


@pytest.mark.asyncio
async def test_ollama_fallback_is_not_cached_as_voyage(monkeypatch):
    """When Voyage fails and Ollama answers, the vector must NOT be cached."""
    store_calls: list[tuple] = []

    async def _voyage_none(_text, *, input_type="document"):
        return None

    async def _ollama_vec(_text):
        return [0.5] * embedding_service.VECTOR_SIZE

    async def _cache_get(*_a, **_kw):
        return None

    async def _cache_store(*args, **kwargs):
        store_calls.append((args, kwargs))

    monkeypatch.setattr(embedding_service, "_voyage_embed", _voyage_none)
    monkeypatch.setattr(embedding_service, "_ollama_embed", _ollama_vec)
    monkeypatch.setattr("app.services.embedding_cache.get", _cache_get)
    monkeypatch.setattr("app.services.embedding_cache.store", _cache_store)

    emb = await embedding_service.generate_embedding(
        "some candidate document", input_type="document"
    )

    assert emb == [0.5] * embedding_service.VECTOR_SIZE
    assert store_calls == [], "Ollama fallback must never poison the Voyage cache"


@pytest.mark.asyncio
async def test_voyage_result_is_cached(monkeypatch):
    """A genuine Voyage document embedding is still cached (no regression)."""
    store_calls: list[tuple] = []

    async def _voyage_vec(_text, *, input_type="document"):
        return [0.1] * embedding_service.VECTOR_SIZE

    async def _cache_get(*_a, **_kw):
        return None

    async def _cache_store(*args, **kwargs):
        store_calls.append((args, kwargs))

    monkeypatch.setattr(embedding_service, "_voyage_embed", _voyage_vec)
    monkeypatch.setattr("app.services.embedding_cache.get", _cache_get)
    monkeypatch.setattr("app.services.embedding_cache.store", _cache_store)

    emb = await embedding_service.generate_embedding(
        "some candidate document", input_type="document"
    )

    assert emb == [0.1] * embedding_service.VECTOR_SIZE
    assert len(store_calls) == 1
