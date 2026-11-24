"""Reguła markera ``static``: kto trafia do joba „Strażnicy repo”."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests._static_marker import (
    MEMORY_WARNING_GB,
    RUNNER_MEMORY_GB,
    is_static,
    mark_static_items,
    may_hold_static_tests,
    memory_summary,
    parses_the_tree,
    share_parsed_trees,
)

pytestmark = pytest.mark.static

_TESTS = Path(__file__).resolve().parent


def _item(
    function: Any,
    name: str = "test_x_guard.py",
    fixtures: tuple[str, ...] = (),
    markers: tuple[str, ...] = (),
) -> SimpleNamespace:
    added: list[Any] = []
    return SimpleNamespace(
        function=function,
        fixturenames=list(fixtures),
        module=SimpleNamespace(),
        path=Path(name),
        get_closest_marker=lambda mark: mark if mark in markers else None,
        added=added,
        add_marker=added.append,
    )


def _no_database() -> bool:
    return True


def _opens_a_session() -> None:
    from app.core.database import AsyncSessionLocal

    AsyncSessionLocal()


def _through_a_helper() -> None:
    _opens_a_session()


def _scans_the_tree() -> list[Path]:
    return list(Path("app").rglob("*.py"))


def _parse_all(root: str) -> list[ast.AST]:
    return [ast.parse(path.read_text()) for path in Path(root).rglob("*.py")]


def _parses_the_tree() -> list[ast.AST]:
    return _parse_all("app")


def _parses_one_file() -> ast.AST:
    return ast.parse(Path("app/main.py").read_text())


def test_guard_file_without_database_is_static() -> None:
    assert is_static(_item(_no_database))
    assert is_static(_item(_no_database, "test_authz_golden.py"))
    assert is_static(_item(_no_database, "test_route_authz_contract.py"))


def test_contract_as_business_domain_is_not_a_guard_by_name() -> None:
    assert not is_static(_item(_no_database, "test_contracts.py"))
    assert not is_static(_item(_no_database, "test_contract_termination.py"))


@pytest.mark.parametrize("fixture", ["app_client", "client", "app_auth_headers"])
def test_database_fixture_excludes_a_guard(fixture: str) -> None:
    assert not is_static(_item(_no_database, fixtures=(fixture,)))


def test_session_opened_directly_or_through_a_helper_excludes_a_guard() -> None:
    assert not is_static(_item(_opens_a_session))
    assert not is_static(_item(_through_a_helper))


def test_tree_scanner_is_static_whatever_the_file_is_called() -> None:
    assert is_static(_item(_scans_the_tree, "test_candidate_rate_readers.py"))


def test_explicit_markers_override_the_rule() -> None:
    assert is_static(_item(_no_database, "test_stamps.py", markers=("static",)))
    assert not is_static(_item(_no_database, markers=("not_static",)))


@pytest.mark.parametrize(
    "name",
    [
        # Stemple, jedna głowa Alembica, daty przy imporcie, spawn, snapshot v1:
        # to oni wyrzucali PR-y z kolejki (23–24.09, 21.10, 25.10.2026).
        "test_screen_guides_freshness.py",
        "test_orders_procedure_freshness.py",
        "test_contract_order_workflows_migration.py",
        "test_no_import_time_dates.py",
        "test_core_tasks_spawn.py",
        "test_integrations_v1_contract.py",
        "test_section_ceiling_contract.py",
        "test_route_authz_contract.py",
        "test_rate_from_readers_guard.py",
    ],
)
def test_guards_that_ejected_prs_stay_in_the_set(name: str) -> None:
    path = _TESTS / name
    assert path.is_file(), name
    assert may_hold_static_tests(path), name


def test_route_matrix_stays_in_the_sieve() -> None:
    """Macierz to ~200 s na jednym procesie: dzieli ją sito, po trasach."""
    source = (_TESTS / "test_authz_guard_matrix.py").read_text(encoding="utf-8")
    assert "pytestmark = pytest.mark.not_static" in source


def test_one_tree_per_source_however_parse_is_called(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do 24.11.2026 ``lru_cache`` dawał osobne drzewo dla ``ast.parse(text)``,
    ``ast.parse(text, path)`` i ``ast.parse(text, filename=path)``: trzy kopie
    ``app/`` (po ~1,3 GB) w workerze i runner bez pamięci przy 91–99%."""
    monkeypatch.setattr(ast, "parse", ast.parse)
    monkeypatch.setattr(ast, "walk", ast.walk)
    share_parsed_trees()
    source = "value = 1\n"
    tree = ast.parse(source)
    assert ast.parse(source, "app/a.py") is tree
    assert ast.parse(source, filename="app/b.py") is tree
    assert ast.parse(source, mode="exec") is tree
    assert ast.parse(source, type_comments=True) is not tree
    assert ast.parse("value\n", mode="eval") is not ast.parse("value\n")


def test_tree_parsers_are_told_apart_from_other_guards() -> None:
    assert parses_the_tree(_item(_parses_the_tree)), "Przez pomocnika z tests."
    assert not parses_the_tree(_item(_scans_the_tree)), "Skan bez AST."
    assert not parses_the_tree(_item(_parses_one_file)), "Jeden plik, bez skanu."


def test_only_tree_parsers_join_the_shared_worker_group() -> None:
    parser, scanner, plain = (
        _item(_parses_the_tree),
        _item(_scans_the_tree),
        _item(_parses_the_tree),
    )
    mark_static_items([parser, scanner], "static", "drzewo")
    mark_static_items([plain], "static")
    assert parser.added == ["static", "drzewo"]
    assert scanner.added == ["static"]
    assert plain.added == ["static"], "Bez grupy poza biegiem ``-m static``."


def test_group_marker_is_set_before_xdist_reads_it() -> None:
    """xdist dopisuje grupę do id testu we własnym ``pytest_collection_modifyitems``,
    który bez ``tryfirst`` biegnie przed hakiem conftestu: 24.11.2026 strażnicy
    z grupą lądowali wtedy na różnych workerach."""
    tree = ast.parse((_TESTS / "conftest.py").read_text(encoding="utf-8"))
    hook = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "pytest_collection_modifyitems"
    )
    assert any(
        isinstance(decorator, ast.Call)
        and ast.unparse(decorator.func) == "pytest.hookimpl"
        and any(
            keyword.arg == "tryfirst" and ast.literal_eval(keyword.value) is True
            for keyword in decorator.keywords
        )
        for decorator in hook.decorator_list
    )


def test_memory_report_warns_before_the_runner_runs_out() -> None:
    gb = 1024**3
    line, too_high = memory_summary({"gw1": 2 * gb, "gw0": 4 * gb})
    assert "gw0 4,0 + gw1 2,0 = 6,0 GB" in line
    assert not too_high
    assert not memory_summary({"gw0": MEMORY_WARNING_GB * gb})[1]
    assert memory_summary({"gw0": MEMORY_WARNING_GB * gb, "gw1": 1})[1]
    assert MEMORY_WARNING_GB < RUNNER_MEMORY_GB
