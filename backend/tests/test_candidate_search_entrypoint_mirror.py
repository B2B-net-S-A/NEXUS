"""Migracje 0281/0282/0305 i ich lustro w ``entrypoint.sh`` muszą się zgadzać.

Prod alembic bywa osierocony — safety-net w ``entrypoint.sh`` jest realnym
wdrożeniem. Model ``Job`` deklaruje ``matching_requirements`` i
``requirements_reviewed`` (0282), więc brak tych kolumn wywala KAŻDY odczyt
ofert; indeksy 0281/0305 bez lustra po prostu nigdy nie powstają.

Obie strony czytane ze źródeł (AST, bez wykonania). Świadomie NIE importujemy
heredocu jako modułu — ``test_entrypoint_ddl_guards.py`` robi to i podmienia
``sys.modules["asyncpg"]`` atrapą, co zatruwa testy z bazą w tej samej sesji.
"""

from __future__ import annotations

import ast
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
_ENTRYPOINT = _BACKEND / "entrypoint.sh"
_VERSIONS = _BACKEND / "alembic" / "versions"


def _shape(text: str) -> str:
    return " ".join(text.split())


def _heredoc_source() -> str:
    lines = _ENTRYPOINT.read_text(encoding="utf-8").split("\n")
    start = next(
        i + 1
        for i, line in enumerate(lines)
        if line.startswith("python - <<'PY'") and "column backfill" in line
    )
    end = start
    while lines[end] != "PY":
        end += 1
    return "\n".join(lines[start:end])


def _entrypoint_list(name: str) -> set[str]:
    tree = ast.parse(_heredoc_source())
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == name
            and isinstance(node.value, ast.List)
        ):
            values = set()
            for element in node.value.elts:
                try:
                    value = ast.literal_eval(element)
                except (ValueError, TypeError):
                    continue
                if isinstance(value, str):
                    values.add(_shape(value))
            return values
    raise AssertionError(f"entrypoint.sh: brak listy {name}")


def _migration_executes(filename: str) -> list[str]:
    """Every literal ``op.execute(...)`` inside ``upgrade()``, nested blocks too."""
    tree = ast.parse((_VERSIONS / filename).read_text(encoding="utf-8"))
    upgrade = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "upgrade"
    )
    statements = []
    for node in ast.walk(upgrade):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "execute"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "op"
            and node.args
        ):
            statements.append(_shape(ast.literal_eval(node.args[0])))
    return statements


def test_index_migrations_0281_and_0305_are_mirrored_verbatim():
    mirrored = _entrypoint_list("_INDEX_STATEMENTS")
    for migration in (
        "0281_candidate_skill_audit_index.py",
        "0305_candidate_search_retention_indexes.py",
    ):
        statements = _migration_executes(migration)
        assert statements, f"{migration}: brak CREATE INDEX w upgrade()"
        missing = [s for s in statements if s not in mirrored]
        assert not missing, f"entrypoint.sh nie ma lustra {migration}: {missing}"


def test_0282_job_columns_are_mirrored_with_the_migration_types():
    columns = _entrypoint_list("_COLUMN_STATEMENTS")
    # 0282: JSONB NULL bez domyślnej; BOOLEAN NOT NULL z domyślnym false.
    assert (
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS matching_requirements JSONB NULL"
        in columns
    )
    assert (
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS requirements_reviewed "
        "BOOLEAN NOT NULL DEFAULT false" in columns
    )
    migration = (_VERSIONS / "0282_shared_candidate_search.py").read_text(
        encoding="utf-8"
    )
    assert 'sa.Column("matching_requirements", postgresql.JSONB())' in migration
    assert "server_default=sa.false()" in migration


def test_model_declares_the_0305_indexes_for_create_all():
    """`create_all` in the entrypoint builds fresh tables from the model."""
    from app.models.candidate_search_run import (
        CandidateSearchResult,
        CandidateSearchRun,
    )

    run_indexes = {i.name for i in CandidateSearchRun.__table__.indexes}
    result_indexes = {i.name for i in CandidateSearchResult.__table__.indexes}
    assert "ix_candidate_search_runs_completed_at" in run_indexes
    assert "ix_candidate_search_results_candidate_id" in result_indexes
