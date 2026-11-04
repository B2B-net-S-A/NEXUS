"""Runda 9 (R9-N9-4, R9-X1-8): importer Traffita nie niesie treści wiersza w błędach.

`repr(IntegrityError)` ma `DETAIL: Key (email)=(…) already exists` — adres
kandydata trafiał do `error_samples` fazy (`/api/admin/traffit/sync/status`,
czytany kluczem `traffit:read`) i do logów. Każdy błąd złapany w importerze
idzie przez `safe_db_error` (klasa + nazwa ograniczenia dla błędów bazy).
"""

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy.exc import IntegrityError

from app.services.traffit.importer import (
    PhaseProgress,
    TraffitImporter,
    safe_db_error,
)

_IMPORTER = (
    Path(__file__).resolve().parents[1] / "app" / "services" / "traffit" / "importer.py"
)


def _exception_names(tree: ast.AST) -> set[str]:
    names = {"pagination_error"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
    return names


def _raw_uses(expr: ast.AST, exc_names: set[str], parents: dict) -> list[int]:
    """Linie, w których zmienna wyjątku trafia do tekstu bez `safe_db_error`."""
    hits: list[int] = []
    for node in ast.walk(expr):
        if not (isinstance(node, ast.Name) and node.id in exc_names):
            continue
        parent = parents.get(node)
        if isinstance(parent, ast.Call) and getattr(parent.func, "id", None) in {
            "safe_db_error",
            "type",
            "needs_session_rollback",
            "isinstance",
        }:
            continue
        if isinstance(parent, ast.Attribute):
            # `type(e).__name__`, `e.orig` itp. — nie tekst wyjątku.
            continue
        hits.append(node.lineno)
    return hits


def test_no_raw_exception_text_in_errors_or_logs():
    tree = ast.parse(_IMPORTER.read_text(encoding="utf-8"))
    parents = {
        child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)
    }
    exc_names = _exception_names(tree)
    offenders: list[int] = []
    for node in ast.walk(tree):
        # f-stringi w całym pliku (także `msg = f"…{e!r}"` przed add_error)
        if isinstance(node, ast.FormattedValue):
            offenders += _raw_uses(node.value, exc_names, parents)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            owner = node.func.value
            if isinstance(owner, ast.Name) and owner.id == "logger":
                for arg in node.args[1:]:
                    offenders += _raw_uses(arg, exc_names, parents)
    assert offenders == [], f"surowy wyjątek w komunikacie: importer.py:{offenders}"


def test_safe_db_error_drops_the_row_detail():
    orig = Exception('duplicate key DETAIL: Key (email)=(jan@firma.pl) exists')
    orig.constraint_name = "ix_candidates_email"
    err = IntegrityError("INSERT …", {"email": "jan@firma.pl"}, orig)
    text = safe_db_error(err)
    assert "jan@firma.pl" not in text
    assert "ix_candidates_email" in text


class _BrokenDb:
    def __init__(self):
        self.rolled_back = False

    async def execute(self, *_a, **_k):
        raise IntegrityError("SELECT …", {}, Exception("DETAIL: (jan@firma.pl)"))

    async def rollback(self):
        self.rolled_back = True


def test_failed_enrich_reindex_intent_rolls_the_session_back():
    """R9-X1-8: bez rollbacku następne zapytanie fazy dostawało PendingRollbackError."""
    db = _BrokenDb()
    importer = TraffitImporter(SimpleNamespace(), db)  # type: ignore[arg-type]
    progress = PhaseProgress(phase="candidates_enrich_names")
    asyncio.run(
        importer._record_enriched_candidate_index_intent(
            progress, after_id=0, last_id=10
        )
    )
    assert db.rolled_back is True
    assert progress.errors == 0
