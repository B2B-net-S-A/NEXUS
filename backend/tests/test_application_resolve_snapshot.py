"""``resolve(create)`` musi zapisać snapshot CV, tak jak każda inna ścieżka.

Siedem ścieżek tworzących ``CandidateStage`` woła ``create_original_cv_snapshot``
od zawsze. Ósma — przyjęcie kandydata ze zgłoszenia z publicznej aplikacji —
nie wołała, więc wchodził on do pipeline'u bez zapisu, z jakim CV go zgłoszono.
To jest dokładnie ten dokument, który trzeba pokazać klientowi, gdy kandydat
później podmieni plik w profilu.

Test jest strukturalny, bo pilnuje dwóch rzeczy, których test na danych by nie
złapał tak wprost:

1. wywołanie w ogóle istnieje — regresja tutaj jest cicha, funkcja dalej
   działa, tylko snapshot przestaje powstawać;
2. ``await db.flush()`` idzie PRZED snapshotem — bez flusha nowy
   ``CandidateStage`` nie ma jeszcze ``id``, a snapshot kluczuje się właśnie po
   nim.
"""

from __future__ import annotations

import ast
import pathlib

BACKEND = pathlib.Path(__file__).resolve().parents[1]
_ROUTE = "resolve_application_submission"


def _route_node() -> ast.AST:
    tree = ast.parse((BACKEND / "app/api/application_submissions.py").read_text())
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == _ROUTE
        ):
            return node
    raise AssertionError(
        f"{_ROUTE} nie istnieje — jeśli przemianowano, zaktualizuj test"
    )


def _call_linenos(node: ast.AST, name: str) -> list[int]:
    out = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            called = getattr(child.func, "id", None) or getattr(
                child.func, "attr", None
            )
            if called == name:
                out.append(child.lineno)
    return sorted(out)


def test_resolve_create_takes_a_cv_snapshot() -> None:
    node = _route_node()
    assert _call_linenos(node, "create_original_cv_snapshot"), (
        "kandydat przyjęty ze zgłoszenia wchodzi do pipeline'u bez snapshotu CV "
        "— nie da się później pokazać, z jakim dokumentem go zgłoszono"
    )


def test_stage_is_flushed_before_the_snapshot() -> None:
    """Bez ``flush`` nowy ``CandidateStage`` nie ma jeszcze ``id``."""
    node = _route_node()
    snapshots = _call_linenos(node, "create_original_cv_snapshot")
    flushes = _call_linenos(node, "flush")
    assert snapshots and flushes
    assert any(f < snapshots[0] for f in flushes), (
        "create_original_cv_snapshot wykonuje się przed flushem — stage nie ma "
        "jeszcze id, po którym snapshot się kluczuje"
    )


def test_snapshot_helper_is_imported_not_shadowed() -> None:
    """Import na poziomie modułu, nie lokalna atrapa o tej samej nazwie."""
    src = (BACKEND / "app/api/application_submissions.py").read_text()
    assert (
        "from app.services.candidate_stage_cv_service import create_original_cv_snapshot"
        in src
    )
