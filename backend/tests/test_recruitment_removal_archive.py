"""Korekcyjne usunięcie rekrutacji nie może kasować dowodu przebiegu procesu.

``DELETE /api/candidates/{id}/recruitments/{job_id}`` jest operacją korekcyjną
("dodano nie tego kandydata / nie na tę ofertę") i fizycznie kasuje WSZYSTKIE
``CandidateStage`` pary, a kaskadą snapshoty CV, share-tokeny i zaplanowane
maile odrzucenia. Po niej nie dało się odtworzyć, przez jakie etapy kandydat
przeszedł ani kto go przesuwał — zostawało zbiorcze ``Activity`` bez treści
decyzji.

Usuwanie zostaje (to jest cel tej trasy i UX się nie zmienia), ale wiersze są
najpierw archiwizowane. Ten test pilnuje, że archiwizacja NIE zniknie:
regresja tutaj jest cicha — funkcja dalej działa, tylko dowód przestaje
powstawać, i nikt tego nie zauważy do pierwszego sporu z klientem.

Test strukturalny (AST), bo sprawdza kolejność i obecność kroku, nie efekt na
danych: zapis MUSI iść przed ``delete()``, inaczej archiwizuje pustkę.
"""

from __future__ import annotations

import ast
import pathlib

BACKEND = pathlib.Path(__file__).resolve().parents[1]
_ROUTE = "remove_candidate_from_recruitment"


def _route_node() -> ast.AST:
    tree = ast.parse((BACKEND / "app/api/candidates.py").read_text())
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == _ROUTE
        ):
            return node
    raise AssertionError(f"{_ROUTE} nie istnieje w app/api/candidates.py")


def _first_lineno(node: ast.AST, predicate) -> int | None:
    hits = [
        child.lineno
        for child in ast.walk(node)
        if isinstance(child, ast.Call) and predicate(child)
    ]
    return min(hits) if hits else None


def _is_archive_call(call: ast.Call) -> bool:
    for sub in ast.walk(call):
        name = getattr(sub, "id", None) or getattr(sub, "attr", None)
        if name == "CandidateStageRemoval":
            return True
    return False


def _is_delete_boundary_call(call: ast.Call) -> bool:
    """Granica usunięcia historii — bezpośrednia albo przez command service.

    Po centralizacji writerów endpoint nie może już wykonywać
    ``delete(CandidateStage)`` samodzielnie. Deleguje operację do
    ``delete_voided_stage_history``; wywołanie tej komendy jest więc momentem,
    przed którym archiwum musi być utworzone. Obsługa bezpośredniego
    ``delete(CandidateStage)`` zostaje dla czytelnego błędu regresji, gdyby
    ktoś ponownie wprowadził legacy writer do endpointu.
    """
    name = getattr(call.func, "id", None) or getattr(call.func, "attr", None)
    if name == "delete_voided_stage_history":
        return True
    if name != "delete":
        return False
    return any(
        (getattr(arg, "id", None) or getattr(arg, "attr", None)) == "CandidateStage"
        for arg in call.args
    )


def test_removal_is_archived() -> None:
    node = _route_node()
    assert _first_lineno(node, _is_archive_call) is not None, (
        "usunięcie rekrutacji przestało archiwizować etapy — kasujemy jedyny "
        "dowód, przez jakie etapy kandydat przeszedł i kto go przesuwał"
    )


def test_archive_happens_before_the_delete() -> None:
    """Kolejność jest całą istotą — po ``delete()`` nie ma czego zapisać."""
    node = _route_node()
    archived_at = _first_lineno(node, _is_archive_call)
    deleted_at = _first_lineno(node, _is_delete_boundary_call)
    assert archived_at is not None and deleted_at is not None
    assert archived_at < deleted_at, (
        "archiwizacja wykonuje się PO skasowaniu wierszy — zapisze pustkę"
    )


def test_archive_table_is_mirrored_in_entrypoint() -> None:
    """Produkcyjny alembic_version jest osierocony.

    Migracja sama z siebie nie założy tabeli na prodzie — ``entrypoint.sh``
    lustruje DDL przy każdym starcie. Bez lustra pierwsze wywołanie DELETE
    wywala się na brakującej tabeli, a jedynym „wyjściem" byłby powrót do
    kasowania bez śladu.
    """
    entrypoint = (BACKEND / "entrypoint.sh").read_text()
    assert "CREATE TABLE IF NOT EXISTS candidate_stage_removals" in entrypoint, (
        "brak lustra DDL w entrypoint.sh — tabela nie powstanie na produkcji"
    )


def test_archive_has_no_cascade_to_candidates_or_jobs() -> None:
    """Archiwum ma przeżyć skasowanie kandydata albo oferty.

    FK z kaskadą zabrałby dokładnie ten dowód, dla którego tabela istnieje —
    a kasowanie kandydata jest właśnie tym momentem, w którym ktoś zapyta,
    co się z nim działo.
    """
    model = (BACKEND / "app/models/candidate_stage_removal.py").read_text()
    assert 'ForeignKey("candidates.id"' not in model
    assert 'ForeignKey("jobs.id"' not in model
