"""Lustro DDL 0390 w ``entrypoint.sh`` (runda 9, R9-N7-12).

Prod alembic bywa osierocony — entrypoint JEST wdrożeniem. Brak tabeli =
każde ``DELETE /api/candidates/{id}`` kończy się 500.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re

BACKEND = pathlib.Path(__file__).resolve().parents[1]


def _migration():
    path = BACKEND / "alembic" / "versions" / "0390_cand_retained_candidate_files.py"
    spec = importlib.util.spec_from_file_location("m0390", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _flat(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def test_entrypoint_mirrors_every_0390_statement() -> None:
    entrypoint = _flat((BACKEND / "entrypoint.sh").read_text())
    for statement in _migration().DDL_STATEMENTS:
        assert _flat(statement) in entrypoint, statement[:80]


def test_model_matches_migration_columns() -> None:
    from app.models.retained_candidate_file import RetainedCandidateFile

    ddl = _migration().CREATE_RETAINED_CANDIDATE_FILES
    for column in RetainedCandidateFile.__table__.columns:
        assert re.search(rf"\b{column.name}\b", ddl), column.name


def test_downgrade_refuses_when_rows_exist() -> None:
    assert "FROM retained_candidate_files" in _migration().REFUSE_WITH_ROWS
