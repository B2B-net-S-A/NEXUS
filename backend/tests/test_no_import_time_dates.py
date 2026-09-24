"""Żaden plik testowy nie liczy daty ani godziny przy imporcie.

16.09.2026 shard CI padł na `test_order_line_roster.py`, choć PR nie dotykał
zamówień: moduł liczył `_TODAY = business_today()` RAZ, przy imporcie, a kod
produkcyjny woła `business_today()` przy każdym wywołaniu. Shard przekroczył
północ warszawską, więc wpis z końcem „dziś" stał się wpisem z końcem „wczoraj".

Pierwsza naprawa (przypinanie zegara Pythona na 23:59 w `conftest`) zamieniła
ten błąd na inny: `now()` Postgresa szło dalej, więc po północy (23.09.2026)
padały testy porównujące czas z Pythona ze znacznikami nadanymi przez bazę.
Zegara bazy przypiąć się nie da — dlatego naprawą jest brak dat z importu,
a ten plik pilnuje, żeby nie wróciły.

Sprawdzane jest wszystko, co Python wykonuje przy imporcie modułu: instrukcje
na poziomie modułu, ciała klas, dekoratory (np. `parametrize`) i domyślne
wartości argumentów. Ciała funkcji i lambd nie — tam data liczy się przy
wywołaniu, czyli tak, jak powinna.
"""

from __future__ import annotations

import ast
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent

#: Funkcje zwracające „teraz" albo „dziś", wołane po nazwie.
_CLOCK_NAMES = frozenset(
    {"business_today", "local_now", "utcnow", "_utcnow", "now_utc", "utc_now"}
)
#: Metody zwracające „teraz" albo „dziś": `date.today()`, `datetime.now(...)`,
#: `datetime.utcnow()`, `pd.Timestamp.now()`…
_CLOCK_ATTRS = frozenset({"today", "now", "utcnow"})


def _is_clock_call(node: ast.Call, local_clock_functions: set[str]) -> bool:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id in _CLOCK_NAMES or func.id in local_clock_functions
    if isinstance(func, ast.Attribute):
        if func.attr in _CLOCK_ATTRS:
            return True
        # `time.time()`
        return (
            func.attr == "time"
            and isinstance(func.value, ast.Name)
            and func.value.id == "time"
        )
    return False


def _walk_expression(node: ast.AST):
    """Jak `ast.walk`, ale bez wchodzenia w ciała lambd (liczą się przy wywołaniu)."""
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        for child in ast.iter_child_nodes(current):
            if isinstance(child, ast.Lambda):
                stack.extend(child.args.defaults)
                stack.extend(d for d in child.args.kw_defaults if d is not None)
                continue
            stack.append(child)


def _import_time_nodes(statements: list[ast.stmt]):
    """Węzły wykonywane przy imporcie: wszystko poza ciałami funkcji."""
    for statement in statements:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in statement.decorator_list:
                yield from _walk_expression(decorator)
            args = statement.args
            for default in [*args.defaults, *args.kw_defaults]:
                if default is not None:
                    yield from _walk_expression(default)
            continue
        if isinstance(statement, ast.ClassDef):
            for expression in [
                *statement.decorator_list,
                *statement.bases,
                *(keyword.value for keyword in statement.keywords),
            ]:
                yield from _walk_expression(expression)
            yield from _import_time_nodes(statement.body)
            continue
        nested_bodies = []
        for field in ("body", "orelse", "finalbody"):
            nested_bodies.extend(getattr(statement, field, None) or [])
        for handler in getattr(statement, "handlers", None) or []:
            nested_bodies.extend(handler.body)
        for case in getattr(statement, "cases", None) or []:
            nested_bodies.extend(case.body)
        if nested_bodies:
            # if/for/while/with/try: wyrażenia nagłówka + ciała rekurencyjnie.
            for field_name, value in ast.iter_fields(statement):
                if field_name in ("body", "orelse", "finalbody", "handlers", "cases"):
                    continue
                for child in value if isinstance(value, list) else [value]:
                    if isinstance(child, ast.AST):
                        yield from _walk_expression(child)
            yield from _import_time_nodes(nested_bodies)
            continue
        yield from _walk_expression(statement)


def _local_clock_functions(tree: ast.Module) -> set[str]:
    """Funkcje modułu, które (także pośrednio) wołają zegar.

    Bez tego `_TODAY = _today()` na poziomie modułu przeszłoby przez sito,
    choć to dokładnie ten sam błąd schowany o jedno wywołanie głębiej.
    """
    functions = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    found: set[str] = set()
    changed = True
    while changed:
        changed = False
        for name, function in functions.items():
            if name in found:
                continue
            if any(
                isinstance(node, ast.Call) and _is_clock_call(node, found)
                for node in ast.walk(function)
            ):
                found.add(name)
                changed = True
    return found


def find_import_time_dates(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    local_clock = _local_clock_functions(tree)
    hits = {
        (node.lineno, ast.unparse(node))
        for node in _import_time_nodes(tree.body)
        if isinstance(node, ast.Call) and _is_clock_call(node, local_clock)
    }
    return sorted(hits)


def _test_python_files() -> list[Path]:
    return sorted(
        path for path in TESTS_ROOT.rglob("*.py") if "__pycache__" not in path.parts
    )


def test_no_date_or_time_is_computed_at_import():
    offenders = [
        f"{path.relative_to(TESTS_ROOT.parent)}:{line}: {call}"
        for path in _test_python_files()
        for line, call in find_import_time_dates(path)
    ]
    assert not offenders, (
        "Data albo godzina liczona przy imporcie modułu testowego — po "
        "przekroczeniu północy w trakcie biegu CI taka stała wskazuje wczoraj, "
        "a kod produkcyjny już dziś. Policz ją wewnątrz testu albo w funkcji "
        "(np. `business_today()` w teście; w `parametrize` podaj przesunięcie "
        "w dniach, a datę policz w teście):\n  " + "\n  ".join(offenders)
    )


# ── Sito samo w sobie: musi łapać znane kształty i nie łapać poprawnych ──────


def _scan_source(tmp_path: Path, source: str) -> list[tuple[int, str]]:
    path = tmp_path / "test_sample.py"
    path.write_text(source, encoding="utf-8")
    return find_import_time_dates(path)


def test_scanner_catches_import_time_shapes(tmp_path):
    source = "\n".join(
        [
            "import time",
            "from datetime import date, datetime, timezone",
            "import pytest",
            "_TODAY = business_today()",
            "NOW: datetime = datetime.now(timezone.utc)",
            "_MONTH = local_now().strftime('%Y-%m')",
            "_STAMP = int(time.time())",
            "class Seed:",
            "    DAY = date.today()",
            "@pytest.mark.parametrize('d', [datetime.utcnow()])",
            "def test_a(d, when=business_today()):",
            "    pass",
            "def _today():",
            "    return business_today()",
            "_ALIAS = _today()",
            "if True:",
            "    _LATER = local_now()",
        ]
    )
    lines = [line for line, _ in _scan_source(tmp_path, source)]
    assert lines == [4, 5, 6, 7, 9, 10, 11, 15, 17]


def test_scanner_ignores_call_time_dates(tmp_path):
    source = "\n".join(
        [
            "from datetime import datetime, timezone",
            "import pytest",
            "def _today():",
            "    return business_today()",
            "_FACTORY = lambda: datetime.now(timezone.utc)",
            "@pytest.mark.parametrize('offset', [0, -1])",
            "def test_b(offset):",
            "    assert _today() == business_today()",
            "class TestC:",
            "    def test_d(self):",
            "        return local_now()",
        ]
    )
    assert _scan_source(tmp_path, source) == []
