"""0437: `candidates.source_created_at` i indeks „w bazie od” mają lustro w entrypoincie.

Alembic na produkcji bywa osierocony — wtedy wdrożeniem schematu jest
`entrypoint.sh`. Indeks musi mieć TO SAMO wyrażenie co sortowanie listy
(`candidate_added_date.added_to_base_sql`), inaczej planista go nie użyje.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from sqlalchemy.dialects import postgresql

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0437_candidate_source_created_at.py"

COLUMN_DDL = "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS source_created_at TIMESTAMPTZ"
INDEX_EXPR = "(LEAST(created_at, source_created_at)) DESC, id DESC"


def _flat(value: str) -> str:
    return re.sub(r"\s+", " ", value)


def _migration_module():
    spec = importlib.util.spec_from_file_location("m0436", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_migration_revision_chain() -> None:
    module = _migration_module()
    assert module.revision == MIGRATION.stem
    assert module.down_revision


def test_migration_and_entrypoint_carry_the_same_ddl() -> None:
    migration = _flat(MIGRATION.read_text(encoding="utf-8"))
    entrypoint = _flat((BACKEND / "entrypoint.sh").read_text(encoding="utf-8"))
    assert COLUMN_DDL in migration
    assert COLUMN_DDL in entrypoint
    assert INDEX_EXPR in migration
    assert (
        '"CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_candidates_added_to_base_id " '
        f'"ON candidates ({INDEX_EXPR})"'
    ) in entrypoint


def test_model_has_the_column() -> None:
    from app.models.candidate import Candidate

    column = Candidate.__table__.columns["source_created_at"]
    assert column.nullable
    assert column.type.timezone


def test_sort_expression_matches_the_index() -> None:
    from app.models.candidate import Candidate
    from app.services.candidate_added_date import added_to_base_sql

    compiled = str(
        added_to_base_sql(Candidate).compile(dialect=postgresql.dialect())
    )
    assert compiled == "least(candidates.created_at, candidates.source_created_at)"
