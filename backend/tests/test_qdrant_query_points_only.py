"""Kod woła Qdranta wyłącznie przez `query_points()`, nigdy przez `search()`.

28.07.2026 `qdrant-client` 1.18.0 usunął `QdrantClient.search()`. Wyjątek na
ścieżce wyszukiwania jest połykany do pustej listy, więc wyszukiwanie
i matching zwracały „brak wyników” przy zielonym `/api/health`, a CI nie ma
Qdranta i niczego nie złapało. 14.11.2026 wszystkie wywołania przeszły na
`query_points()`. Ten test pilnuje, żeby nowe wywołanie `search()` nie wróciło
po cichu: działałoby na dzisiejszej wersji klienta do pierwszego podbicia.

Rozpoznanie po argumentach (`collection_name` / `query_vector`), nie po
nazwie metody: `re.search(...)` i `framework_contract_index.search(...)` to
co innego.
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOTS = ("app", "scripts")
_QDRANT_SEARCH_KWARGS = {"collection_name", "query_vector"}
_REMOVED_METHODS = {"search", "search_batch", "search_groups", "recommend"}


def _old_api_calls(tree: ast.AST) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _REMOVED_METHODS
        and {kw.arg for kw in node.keywords if kw.arg} & _QDRANT_SEARCH_KWARGS
    ]


def test_no_qdrant_search_calls() -> None:
    calls = [
        f"{path.relative_to(BACKEND)}:{node.lineno} .{node.func.attr}("
        for root in ROOTS
        for path in sorted((BACKEND / root).rglob("*.py"))
        for node in _old_api_calls(ast.parse(path.read_text(encoding="utf-8")))
    ]
    assert not calls, (
        "wywołanie Qdranta starym API (usuniętym w qdrant-client 1.18) — użyj "
        "`client.query_points(..., query=wektor, ...).points`:\n" + "\n".join(calls)
    )


def test_detector_sees_old_api() -> None:
    """Kontrola przeciwna: detektor rozpoznaje stare wywołanie, a `re.search` nie."""
    tree = ast.parse(
        "client.search(collection_name='c', query_vector=[0.1], limit=1)\n"
        "re.search(r'x', 'y')\n"
    )
    assert len(_old_api_calls(tree)) == 1
