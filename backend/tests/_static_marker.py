"""Marker ``static``: strażnicy repo, którzy nie potrzebują bazy.

Job „Strażnicy repo” na każdym PR-ze i krok kolejki w ``ci-gate.yml`` biegną
``pytest -m static`` bez Postgresa. Marker nadaje się przy kolekcji, więc nowy
strażnik wchodzi do zestawu bez dopisywania go do listy. Do 08.11.2026 była to
ręczna lista ``_ALWAYS`` w ``select_pr_tests.py``: sito widziało 19 strażników,
reszta padała dopiero w grupie kolejki i wywracała PR-y za sobą.

Test jest ``static``, gdy nie używa bazy i spełnia jedno z trzech:

* plik ma w nazwie ``guard`` albo ``golden`` lub kończy się na ``_contract(s).py``;
  ``test_contract_*.py`` to domena „umowa”, a nie kontrakt kodu, więc odpada;
* test (wprost albo przez pomocnika z ``tests``) skanuje drzewo: ``rglob``, ``os.walk``;
* test albo plik ma ``pytest.mark.static``.

``pytest.mark.not_static`` wyjmuje test z zestawu: za długi na ten job albo
sięga do bazy przez kod aplikacji, czego analiza tutaj nie zobaczy.
"""

from __future__ import annotations

import ast
import functools
import inspect
import re
from pathlib import Path
from types import CodeType, FunctionType
from typing import Any, Iterable, Iterator

_GUARD_FILE = re.compile(r"guard|golden|^test_.+_contracts?\.py$")
_FILE_HINTS = ("mark.static", "rglob(", "os.walk(")
_DB_FIXTURES = frozenset({"client", "auth_headers", "app_client", "app_auth_headers"})
_DB_NAMES = frozenset({"AsyncSessionLocal", "engine", "get_db", "create_async_engine"})


def _scans_tree(names: set[str]) -> bool:
    return "rglob" in names or {"os", "walk"} <= names


def only_static_requested(config: Any) -> bool:
    if config is None:
        return False
    return (config.getoption("markexpr", "") or "").strip() == "static"


def share_parsed_trees() -> None:
    """W biegu ``-m static`` każdy strażnik parsuje całe ``app/`` osobno.

    Pomiar 08.11.2026: ``compile`` i ``ast.walk`` to ponad 80% czasu strażnika, a
    job trwał 5:15 (pytest 3:54) przy celu 3 min. Drzewa współdzielimy w obrębie
    procesu; poza tym biegiem zostają zwykłe funkcje z ``ast``.
    """
    walk = ast.walk

    def cached_walk(node: ast.AST) -> Iterator[ast.AST]:
        if not isinstance(node, ast.Module):
            return walk(node)
        if not hasattr(node, "_all_nodes"):
            node._all_nodes = list(walk(node))
        return iter(node._all_nodes)

    ast.parse = functools.lru_cache(maxsize=None)(ast.parse)
    ast.walk = cached_walk


def may_hold_static_tests(path: Path) -> bool:
    """Tani odsiew przed kolekcją: import 2200 plików to ~40 s na runnerze."""
    if _GUARD_FILE.search(path.name):
        return True
    text = path.read_text(encoding="utf-8", errors="ignore")
    return any(hint in text for hint in _FILE_HINTS)


def _code_objects(code: CodeType) -> Iterator[CodeType]:
    yield code
    for const in code.co_consts:
        if isinstance(const, CodeType):
            yield from _code_objects(const)


def _reachable_names(roots: Iterable[Any], module_globals: dict[str, Any]) -> set[str]:
    """Nazwy użyte przez funkcje ``roots`` i pomocników z modułów ``tests``."""
    names: set[str] = set()
    seen: set[CodeType] = set()
    stack = [inspect.unwrap(root) for root in roots]
    while stack:
        func = stack.pop()
        code = getattr(func, "__code__", None)
        if code is None or code in seen:
            continue
        seen.add(code)
        scope = getattr(func, "__globals__", module_globals)
        for part in _code_objects(code):
            names.update(part.co_names)
            for name in part.co_names:
                helper = scope.get(name)
                if isinstance(helper, FunctionType) and helper.__module__.startswith(
                    "tests"
                ):
                    stack.append(inspect.unwrap(helper))
    return names


def _fixture_functions(item: Any) -> list[Any]:
    """Fixture'y z pliku testu. Te z conftestu są autouse dla wszystkich i bazy
    nie otwierają; bazę wnoszą tylko ``_DB_FIXTURES``."""
    info = getattr(item, "_fixtureinfo", None)
    defs = getattr(info, "name2fixturedefs", None) or {}
    return [
        chain[-1].func
        for chain in defs.values()
        if chain and chain[-1].func.__module__ != "tests.conftest"
    ]


def is_static(item: Any) -> bool:
    """Czy test należy do zestawu bez bazy (reguły w opisie modułu)."""
    if item.get_closest_marker("not_static"):
        return False
    if item.get_closest_marker("static"):
        return True
    function = getattr(item, "function", None)
    if function is None or _DB_FIXTURES & set(item.fixturenames):
        return False
    module_globals = vars(item.module)
    names = _reachable_names([function, *_fixture_functions(item)], module_globals)
    if names & _DB_NAMES:
        return False
    return bool(_GUARD_FILE.search(item.path.name)) or _scans_tree(names)


def mark_static_items(items: Iterable[Any], marker: Any) -> None:
    for item in items:
        if is_static(item):
            item.add_marker(marker)
