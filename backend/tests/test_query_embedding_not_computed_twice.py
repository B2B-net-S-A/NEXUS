"""Jeden request nie może embedować tego samego zapytania dwa razy.

`retrieve_candidate_pool` w trybie hybrydowym pyta o embedding DWA razy dla
tego samego tekstu: raz w nodze gęstej (`search_candidates_semantic` przez
`hybrid_candidates`), drugi raz w dosypce kosinusów
(`similarity_for_candidate_ids`). Ścieżka wielo-zapytaniowa robi to samo.

Cache postgresowy tego nie łapał, bo obsługuje wyłącznie `input_type="document"`
— zapytanie rekrutera bywa unikalne i wiersz per literówka nie miałby sensu.
Dopóki `HYBRID_POOL_ENABLED` było wyłączone, płaciliśmy za to tylko w teorii.
Po włączeniu to podwójne wywołanie Voyage'a i podwójna latencja na KAŻDEJ
ofercie — a oferty liczą się w tysiącach przy nocnym digeście.

Stąd cache W PROCESIE, krótkotrwały: te dwa wywołania dzieli ułamek sekundy.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clean_query_cache():
    from app.services.embedding_service import reset_query_embedding_cache

    reset_query_embedding_cache()
    yield
    reset_query_embedding_cache()


@pytest.mark.asyncio
async def test_same_query_hits_voyage_once(monkeypatch):
    """Drugie pytanie o TEN SAM tekst nie schodzi do dostawcy."""
    from app.services import embedding_service as es

    calls: list[str] = []

    async def fake_voyage(text, *, input_type="document"):
        calls.append(text)
        return [0.5] * es.VECTOR_SIZE

    monkeypatch.setattr(es, "_voyage_embed", fake_voyage)
    monkeypatch.setattr(es.settings, "VOYAGE_API_KEY", "test-key")

    first = await es.generate_embedding("senior python", input_type="query")
    second = await es.generate_embedding("senior python", input_type="query")

    assert first == second
    assert len(calls) == 1, f"zapytanie poszło do Voyage'a {len(calls)} razy"


@pytest.mark.asyncio
async def test_different_queries_are_not_confused(monkeypatch):
    """Kontrola negatywna — cache nie może oddawać cudzego wektora.

    Bez tego testu „naprawa" zwracająca zawsze pierwszy embedding przechodzi
    na zielono, a każde kolejne wyszukiwanie w procesie dostaje wynik
    poprzedniego. To byłaby cicha katastrofa: wyniki wyglądają sensownie,
    tylko dotyczą innego zapytania.
    """
    from app.services import embedding_service as es

    calls: list[str] = []

    async def fake_voyage(text, *, input_type="document"):
        calls.append(text)
        return [float(len(text))] * es.VECTOR_SIZE

    monkeypatch.setattr(es, "_voyage_embed", fake_voyage)
    monkeypatch.setattr(es.settings, "VOYAGE_API_KEY", "test-key")

    a = await es.generate_embedding("java", input_type="query")
    b = await es.generate_embedding("scala developer", input_type="query")

    assert a != b
    assert calls == ["java", "scala developer"]


@pytest.mark.asyncio
async def test_documents_do_not_bleed_into_the_query_cache(monkeypatch):
    """Dokument NIE może zostać złapany przez cache ZAPYTAŃ.

    `use_cache=False` wyłącza obie ścieżki cache'u, więc ten test nie dowodzi
    niczego o cache'u postgresowym — dowodzi, że nowy cache w procesie nie
    łapie tego, czego łapać nie powinien. Gdyby łapał, indeksowanie 55 tys.
    kandydatów zapychałoby pamięć procesu wektorami, których nikt nie odczyta
    drugi raz w tym samym biegu.
    """
    from app.services import embedding_service as es

    calls: list[str] = []

    async def fake_voyage(text, *, input_type="document"):
        calls.append(text)
        return [0.25] * es.VECTOR_SIZE

    monkeypatch.setattr(es, "_voyage_embed", fake_voyage)
    monkeypatch.setattr(es.settings, "VOYAGE_API_KEY", "test-key")

    await es.generate_embedding("CV kandydata", input_type="document", use_cache=False)
    await es.generate_embedding("CV kandydata", input_type="document", use_cache=False)

    assert len(calls) == 2, (
        "dokument z `use_cache=False` musi iść do dostawcy za każdym razem"
    )


@pytest.mark.asyncio
async def test_ollama_vector_is_never_cached_under_the_voyage_key(monkeypatch):
    """Wektor z Ollamy ma te same 1024 wymiary, ale INNĄ przestrzeń.

    Zapisany pod kluczem modelu Voyage'a zatruwałby kosinusy tak samo cicho jak
    w cache'u postgresowym (AI-P0-03) — tyle że w pamięci procesu, więc jeszcze
    trudniej byłoby to zauważyć. Ten test zamraża warunek `from_voyage`.
    """
    from app.services import embedding_service as es

    ollama_calls: list[str] = []

    async def no_voyage(text, *, input_type="document"):
        return None

    async def fake_ollama(text):
        ollama_calls.append(text)
        return [0.1] * es.VECTOR_SIZE

    monkeypatch.setattr(es, "_voyage_embed", no_voyage)
    monkeypatch.setattr(es, "_ollama_embed", fake_ollama)
    # Brak klucza Voyage = tryb offline, w którym fallback na Ollamę jest legalny.
    monkeypatch.setattr(es.settings, "VOYAGE_API_KEY", "")

    await es.generate_embedding("senior python", input_type="query")
    await es.generate_embedding("senior python", input_type="query")

    assert len(ollama_calls) == 2, (
        "wektor z Ollamy nie może wylądować w cache'u pod kluczem Voyage'a"
    )
