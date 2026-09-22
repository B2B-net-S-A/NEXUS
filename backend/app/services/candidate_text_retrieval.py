"""Retrieval tekstowy `q` wspólny dla listy i wyszukiwarki kandydatów.

Tryb semantyczny (BM25 + Voyage + RRF + reranker, `hybrid_search`) był do
22.09.2026 wyłącznie w `POST /api/search/candidates`. Po połączeniu ekranów
„Kandydaci" korzysta z niego także `GET /api/candidates` (v2, jawne
`text_mode`). Rozmiar puli i samo wywołanie retrievalu są tutaj, żeby oba
silniki oglądały TĘ SAMĄ pulę — kopia pokrętła rozjechałaby się przy
pierwszej zmianie.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Ile osób ogląda tryb semantyczny na jedno zapytanie. To jest SUFIT WYNIKU,
# nie tylko szczegół retrievalu: `total` w trybie hybrydowym nigdy nie przekroczy
# tej liczby, bo zbiór wynikowy jest przecięciem puli z filtrami. Zmiana tej
# wartości zmienia więc to, co rekruter widzi jako „liczbę wyników" — i koszt
# rerankera Voyage, który dostaje CAŁĄ pulę przy KAŻDYM żądaniu strony.
#
# Ten koszt jest większy, niż sugeruje konfiguracja: komentarz przy
# `RERANKER_ENABLED` budżetuje „~595 ms p95", ale docstring `reranker_service`
# mówi, że ta liczba dotyczy ~50 dokumentów. Przy 200 wysyłamy czterokrotność
# tego budżetu, do 200 pełnych wierszy ORM i do 800 KB tekstu — i płacimy to
# ponownie przy każdej zmianie strony, bo endpoint jest BEZSTANOWY. Dawny
# komentarz przy wywołaniu twierdził, że zapas 200 „oszczędza odpytywanie
# orchestratora przy zmianie strony"; nie oszczędza — nie ma czego zapamiętać
# między żądaniami.
#
# Czy 200 wygrywa ze 100, wie wyłącznie pomiar (`scripts/eval_matching.py`),
# a nie ten komentarz. Dlatego wartość jest teraz POKRĘTŁEM, nie stałą wbitą
# w kod: da się ją przestawić zmienną środowiskową i zmierzyć obie, bez deployu.
HYBRID_POOL_DEFAULT = 200


def hybrid_pool_size() -> int:
    from app.core.config import settings  # noqa: PLC0415

    # Wartość bezsensowna (0, ujemna, `None`) wraca do DOMYŚLNEJ, nie do 1.
    # Pierwsza wersja robiła `max(1, raw or 200)`, co dawało dwa różne
    # zachowania dla dwóch równie bezsensownych wejść: `0` → 200 (bo `or`
    # zwierał się przed `max`), a `-5` → 1. Pula równa 1 nie jest zresztą
    # sensowniejsza od zera — wyszukiwarka oglądałaby jedną osobę i wyglądałoby
    # to jak pusta baza, czyli ta sama pomyłka, przed którą broni
    # `search_degraded`.
    raw = getattr(settings, "SEARCH_HYBRID_POOL_SIZE", HYBRID_POOL_DEFAULT)
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return HYBRID_POOL_DEFAULT
    return parsed if parsed > 0 else HYBRID_POOL_DEFAULT


@dataclass(frozen=True)
class SemanticPool:
    """Wynik retrievalu semantycznego dla `q`.

    ``ids`` — kolejność retrievalu (RRF / reranker), najlepszy pierwszy.
    ``degraded`` — noga gęsta (Qdrant / Voyage) padła, wynik to sam BM25.
    ``cap_reached`` — pula osiągnęła sufit, więc wyników może być więcej,
    niż pokazujemy.
    """

    ids: list[int]
    degraded: bool
    cap_reached: bool
    pool_size: int


async def semantic_pool(db: Any, q_text: str) -> SemanticPool:
    """Pula kandydatów dla `q` w trybie semantycznym — to samo wywołanie co
    wyszukiwarka (`advanced_candidate_search`)."""
    from app.services.hybrid_search import hybrid_candidates  # noqa: PLC0415

    pool_size = hybrid_pool_size()
    hybrid = await hybrid_candidates(
        db,
        q_text,
        pool=pool_size,
        final_top_k=pool_size,
        use_rerank=None,
    )
    ids = [cid for cid, _ in hybrid.pairs]
    return SemanticPool(
        ids=ids,
        degraded=bool(hybrid.degraded),
        cap_reached=len(ids) >= pool_size,
        pool_size=pool_size,
    )
