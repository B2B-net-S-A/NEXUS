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

Pamięć (24.11.2026): zestaw biegnie z ``-n 4 --dist loadgroup`` na runnerze
z 16 GB. Drzewa AST są wspólne w procesie (``share_parsed_trees``), a strażnicy,
którzy je budują, idą na jednego workera (``parses_the_tree``). Na koniec biegu
kontroler wypisuje szczyt RSS każdego workera (``memory_summary``).
"""

from __future__ import annotations

import ast
import inspect
import re
import resource
import sys
from pathlib import Path
from types import CodeType, FunctionType
from typing import Any, Iterable, Iterator

_GUARD_FILE = re.compile(r"guard|golden|^test_.+_contracts?\.py$")
_FILE_HINTS = ("mark.static", "rglob(", "os.walk(")
_DB_FIXTURES = frozenset({"client", "auth_headers", "app_client", "app_auth_headers"})
_DB_NAMES = frozenset({"AsyncSessionLocal", "engine", "get_db", "create_async_engine"})
#: Grupa xdist strażników parsujących drzewo (``parses_the_tree``).
STATIC_TREE_GROUP = "drzewo-ast"


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

    Klucz to sam tekst źródła i tryb, bez ``filename`` i bez rozróżnienia
    argumentu pozycyjnego od nazwanego. Do 24.11.2026 był tu
    ``functools.lru_cache(ast.parse)``: ``ast.parse(text)``,
    ``ast.parse(text, str(path))`` i ``ast.parse(text, filename=str(path))``
    to dla niego trzy klucze, więc worker trzymał trzy kopie drzewa całego
    ``app/`` (po ~1,3 GB) do końca biegu. Przy ``-n 4`` szczyt sięgał 17,6 GB
    na runnerze z 16 GB i runner dostawał „shutdown signal” przy 91–99%.
    """
    parse, walk = ast.parse, ast.walk
    trees: dict[tuple[Any, ...], ast.AST] = {}

    def shared_parse(
        source: Any, filename: Any = "<unknown>", mode: str = "exec", **flags: Any
    ) -> ast.AST:
        key = (source, mode, *sorted(flags.items()))
        try:
            tree = trees.get(key)
        except TypeError:  # niehaszowalne źródło: bez pamięci podręcznej
            return parse(source, filename, mode, **flags)
        if tree is None:
            tree = trees[key] = parse(source, filename, mode, **flags)
        return tree

    def cached_walk(node: ast.AST) -> Iterator[ast.AST]:
        if not isinstance(node, ast.Module):
            return walk(node)
        if not hasattr(node, "_all_nodes"):
            node._all_nodes = list(walk(node))
        return iter(node._all_nodes)

    ast.parse = shared_parse
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


def _item_names(item: Any) -> set[str]:
    function = getattr(item, "function", None)
    if function is None:
        return set()
    return _reachable_names([function, *_fixture_functions(item)], vars(item.module))


def is_static(item: Any) -> bool:
    """Czy test należy do zestawu bez bazy (reguły w opisie modułu)."""
    if item.get_closest_marker("not_static"):
        return False
    if item.get_closest_marker("static"):
        return True
    if getattr(item, "function", None) is None or _DB_FIXTURES & set(item.fixturenames):
        return False
    names = _item_names(item)
    if names & _DB_NAMES:
        return False
    return bool(_GUARD_FILE.search(item.path.name)) or _scans_tree(names)


def parses_the_tree(item: Any) -> bool:
    """Czy test skanuje drzewo i parsuje pliki do AST.

    Taki strażnik trzyma w workerze drzewa całego katalogu: ``app/`` to
    ~1,3 GB, ``tests/`` drugie tyle. Pomiar 24.11.2026 (``-n 4``, 1 567
    testów): osiem takich strażników rozłożonych na cztery workery dawało
    2,2–3,7 GB na workera nawet przy wspólnych drzewach. W jednej grupie
    xdist (``--dist loadgroup``) drzewa są w pamięci raz.
    """
    names = _item_names(item)
    return _scans_tree(names) and "parse" in names


def mark_static_items(
    items: Iterable[Any], marker: Any, tree_marker: Any | None = None
) -> None:
    for item in items:
        if is_static(item):
            item.add_marker(marker)
            if tree_marker is not None and parses_the_tree(item):
                item.add_marker(tree_marker)


#: Runner ``ubuntu-latest`` repo publicznego: 16 GB na system, runner i testy.
RUNNER_MEMORY_GB = 16
#: Próg ostrzeżenia. 23–24.11.2026 runner dostawał „shutdown signal” przy
#: szczycie ~17,6 GB (pomiar na Macu, ``-n 4``); po poprawce szczyt to ~7,8 GB.
MEMORY_WARNING_GB = 11


def peak_rss_bytes() -> int:
    """Szczyt RSS tego procesu; ``ru_maxrss`` jest w KB na Linuksie, w bajtach na macOS."""
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == "darwin" else peak * 1024


def _gb(size: int) -> str:
    return f"{size / 1024**3:.1f}".replace(".", ",")


def memory_summary(peaks: dict[str, int]) -> tuple[str, bool]:
    """Linia raportu i czy suma szczytów workerów przekracza próg ostrzeżenia.

    Suma szczytów zawyża jednoczesne zużycie (szczyty bywają w różnych
    chwilach), więc próg działa z zapasem.
    """
    total = sum(peaks.values())
    parts = " + ".join(f"{name} {_gb(size)}" for name, size in sorted(peaks.items()))
    line = (
        f"Strażnicy repo — szczyt RSS: {parts} = {_gb(total)} GB "
        f"(runner {RUNNER_MEMORY_GB} GB, ostrzeżenie od {MEMORY_WARNING_GB} GB)"
    )
    return line, total > MEMORY_WARNING_GB * 1024**3
