"""0326: kolumny przełącznika „prowadzona w NEXUSIE" mają lustro w entrypoincie.

Prod alembic bywa osierocony — `entrypoint.sh` JEST wdrożeniem. Model `Job`
deklaruje te kolumny, więc brak lustra = KAŻDY odczyt ofert na produkcji pada
na `UndefinedColumnError`, a w CI (gdzie działa migracja) wszystko jest zielone.
Test czyta DDL z modułu migracji, nie z listy wpisanej ręcznie.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0326_jobs_managed_in_nexus.py"


def _collapse(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def _migration_module():
    spec = importlib.util.spec_from_file_location("m0322", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _statements() -> list[str]:
    module = _migration_module()
    return [
        module.ADD_MANAGED_IN_NEXUS,
        module.ADD_MANAGED_IN_NEXUS_AT,
        module.ADD_MANAGED_IN_NEXUS_BY,
    ]


def test_migration_chains_after_pending_verification_retired():
    module = _migration_module()
    assert module.revision == "0326_jobs_managed_in_nexus"
    assert module.down_revision == "0325_pending_verification_retired"


def test_every_column_statement_is_mirrored_in_entrypoint():
    entrypoint = _collapse((BACKEND / "entrypoint.sh").read_text())
    for statement in _statements():
        assert _collapse(statement) in entrypoint, statement


def test_statements_are_idempotent_and_cover_the_three_columns():
    statements = [_collapse(s) for s in _statements()]
    assert all("ADD COLUMN IF NOT EXISTS" in s for s in statements)
    joined = " ".join(statements)
    for column in ("managed_in_nexus ", "managed_in_nexus_at ", "managed_in_nexus_by "):
        assert column in joined
    assert "REFERENCES users(id) ON DELETE SET NULL" in joined
