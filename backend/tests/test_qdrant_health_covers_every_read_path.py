"""Każdy ODCZYT z Qdranta ma trafiać do okna zdrowia providera.

`_run_qdrant` istnieje po to, żeby `/api/health` mógł powiedzieć, że padł
Qdrant, a nie Voyage. Trzy ścieżki odczytu wołały jednak `asyncio.to_thread`
wprost, więc ich awarie były dla healthchecku niewidzialne:

  * `similarity_for_candidate_ids` — scoring pipeline'u i badge'y na kanbanie,
  * `search_jobs_semantic`          — dopasowanie odwrotne (CV → oferty),
  * `search_similar_jobs_by_job_id` — podpowiedzi pytań i prep-kit.

Pierwsza z nich obsługuje ruch, który przy padniętym Qdrancie milczy
najgłośniej — a `/api/health` raportował wtedy `qdrant: healthy`, bo widział
wyłącznie ruch z wyszukiwarki. Zdrowie mówiące „ok" w trakcie awarii jest
gorsze niż jego brak: kieruje diagnozę w stronę danych zamiast dostawcy.

Test czyta ŹRÓDŁO, bo broni NIEOBECNOŚCI wzorca. Przejście tych ścieżek
wymagałoby żywego Qdranta, a atrapa i tak nie pokazałaby, czy wywołanie zostało
zaraportowane — dokładnie ten sam powód, dla którego defekt przeżył.
"""

from __future__ import annotations

import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "app" / "services" / "embedding_service.py"

# Funkcje, które NIE czytają z Qdranta — zapis idzie własną ścieżką i celowo
# nie wchodzi do okna odczytów.
_WRITE_PATHS = {"embed_candidate", "delete_candidate_embedding", "embed_job"}


def _to_thread_calls_by_function() -> dict[str, int]:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    found: dict[str, int] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Call):
                continue
            fn = inner.func
            if (
                isinstance(fn, ast.Attribute)
                and fn.attr == "to_thread"
                and isinstance(fn.value, ast.Name)
                and fn.value.id == "asyncio"
            ):
                found[node.name] = found.get(node.name, 0) + 1
    return found


def test_no_read_path_calls_asyncio_to_thread_directly():
    offenders = {
        name: count
        for name, count in _to_thread_calls_by_function().items()
        if name not in _WRITE_PATHS and name != "_run_qdrant"
    }
    assert offenders == {}, (
        "te odczyty omijają okno zdrowia Qdranta — użyj `_run_qdrant`: "
        f"{sorted(offenders)}"
    )


def test_the_three_repaired_read_paths_still_go_through_run_qdrant():
    """Kontrola pozytywna — sam brak `to_thread` przeszedłby też po usunięciu
    wywołania w ogóle."""
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    routed: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Name)
                and inner.func.id == "_run_qdrant"
            ):
                routed.add(node.name)

    for name in (
        "similarity_for_candidate_ids",
        "search_jobs_semantic",
        "search_similar_jobs_by_job_id",
        "search_candidates_semantic",
    ):
        assert name in routed, f"`{name}` musi raportować odczyt do zdrowia Qdranta"
