"""R10-V3-3: dopasowanie kandydata po adresie w M365 ma indeks.

Po R9-N10-8 matcher maili i dopasowanie uczestników spotkań porównują
``lower(btrim(email))``. Planer użyje indeksu wyrażeniowego tylko przy
DOKŁADNIE tym samym wyrażeniu — ``trim`` zamiast ``btrim`` albo
``btrim(email, ' \\t\\r\\n')`` to inne wyrażenie i znowu skan tabeli.
Test pilnuje zgodności zapytań, migracji 0391 i lustra w ``entrypoint.sh``.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql

from app.models.candidate import Candidate
from app.services.m365 import matcher, sync

BACKEND = Path(__file__).resolve().parents[1]
EXPR = "lower(btrim(email))"
QUERY_EXPR = "func.lower(func.btrim(Candidate.email))"


def test_migration_and_entrypoint_create_the_same_index() -> None:
    migration = (
        BACKEND / "alembic/versions/0391_auth_candidate_email_lower_index.py"
    ).read_text(encoding="utf-8")
    entrypoint = (BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    assert f"ON candidates ({EXPR})" in migration
    assert "ix_candidates_email_lower_btrim" in migration
    assert (
        '"CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_candidates_email_lower_btrim "\n'
        f'    "ON candidates ({EXPR})",'
    ) in entrypoint


def test_m365_queries_use_the_indexed_expression() -> None:
    for module in (matcher, sync):
        source = inspect.getsource(module)
        assert "func.lower(func.trim(Candidate.email))" not in source
        assert QUERY_EXPR in source


def test_indexed_expression_compiles_to_lower_btrim() -> None:
    stmt = select(Candidate.id).where(
        func.lower(func.btrim(Candidate.email)).in_(["a@example.com"])
    )
    sql = str(
        stmt.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    ).lower()
    assert "lower(btrim(candidates.email))" in sql
