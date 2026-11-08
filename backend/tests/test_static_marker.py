"""Reguła markera ``static``: kto trafia do joba „Strażnicy repo”."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests._static_marker import is_static, may_hold_static_tests

pytestmark = pytest.mark.static

_TESTS = Path(__file__).resolve().parent


def _item(
    function: Any,
    name: str = "test_x_guard.py",
    fixtures: tuple[str, ...] = (),
    markers: tuple[str, ...] = (),
) -> SimpleNamespace:
    return SimpleNamespace(
        function=function,
        fixturenames=list(fixtures),
        module=SimpleNamespace(),
        path=Path(name),
        get_closest_marker=lambda mark: mark if mark in markers else None,
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
