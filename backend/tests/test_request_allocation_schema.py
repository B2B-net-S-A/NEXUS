"""Automat przydziału requestów (0371): lustro DDL w entrypoint.sh i rejestracje.

Prod alembic bywa osierocony — entrypoint JEST wdrożeniem schematu, więc
kolumny, tabela, indeksy i wartości enumów muszą być w nim 1:1 z jednym
źródłem (`app/services/request_allocation_schema.py`).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.services.job_column_ownership import NEXUS_OWNED
from app.services.request_allocation_schema import (
    COLUMN_STATEMENTS,
    ENUM_STATEMENTS,
)

ROOT = Path(__file__).resolve().parents[1]


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text)


@pytest.mark.unit
def test_every_ddl_statement_is_mirrored_in_entrypoint() -> None:
    entry = _squash((ROOT / "entrypoint.sh").read_text())
    for statement in COLUMN_STATEMENTS + ENUM_STATEMENTS:
        assert _squash(statement) in entry, statement.splitlines()[0]


@pytest.mark.unit
def test_migration_reads_the_single_source() -> None:
    migration = (ROOT / "alembic/versions/0371_request_allocation.py").read_text()
    assert "COLUMN_STATEMENTS" in migration
    assert "sync_statements" in migration


@pytest.mark.unit
def test_data_block_runs_after_the_schema_in_entrypoint() -> None:
    entry = (ROOT / "entrypoint.sh").read_text()
    columns_applied = entry.index("_COLUMN_STATEMENTS = [")
    data_block = entry.index('startup_phase "competence-categories-four"')
    assert data_block > columns_applied


@pytest.mark.unit
def test_work_state_is_never_written_by_the_traffit_sync() -> None:
    assert {"work_state", "work_state_changed_at", "work_state_changed_by"} <= (
        NEXUS_OWNED
    )


@pytest.mark.unit
def test_assignments_table_is_probed_by_deep_health() -> None:
    main = (ROOT / "app/main.py").read_text()
    assert '("job_work_assignments", JobWorkAssignment)' in main
