"""Etap B2: DDL z ``entrypoint.sh`` pominięty przez limit zamka jest widoczny.

Przy rolling update stary kontener obsługuje ruch, gdy nowy wykonuje siatkę
DDL, więc ``lock_timeout`` realnie odpuszcza instrukcje. Pominięcie ma trafić
do ``checks.migrations`` i Sentry, a nie zostać linią w logu kontenera.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.services import migration_health as mh
from app.services.startup_locks import (
    SKIPPED_DDL_FILE_ENV,
    read_skipped_ddl,
    record_skipped_ddl,
)

ENTRYPOINT = Path(__file__).resolve().parents[1] / "entrypoint.sh"
HEALTHY_STATE = {"db_versions": ["a"], "code_heads": ["a"], "orphaned": []}


class _PgError(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__("DETAIL: Key (email)=(jan@example.com) already exists")
        self.sqlstate = sqlstate


class _Wrapped(Exception):
    def __init__(self, orig: Exception) -> None:
        super().__init__("wrapper")
        self.orig = orig


@pytest.fixture
def skips_file(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "skips.jsonl"
    monkeypatch.setenv(SKIPPED_DDL_FILE_ENV, str(path))
    return path


def test_lock_statement_timeout_and_deadlock_are_recorded(skips_file: Path) -> None:
    record_skipped_ddl("ALTER TABLE candidates\n   ADD COLUMN x int", _PgError("55P03"))
    record_skipped_ddl("CREATE INDEX CONCURRENTLY ix", _Wrapped(_PgError("57014")))
    record_skipped_ddl("priority work: fk", _PgError("40P01"))
    assert read_skipped_ddl() == [
        {"step": "ALTER TABLE candidates ADD COLUMN x int", "sqlstate": "55P03"},
        {"step": "CREATE INDEX CONCURRENTLY ix", "sqlstate": "57014"},
        {"step": "priority work: fk", "sqlstate": "40P01"},
    ]
    # Treść błędu (DETAIL z danymi) nie trafia do pliku.
    assert "example.com" not in skips_file.read_text()


def test_other_errors_are_idempotent_noise_not_skips(skips_file: Path) -> None:
    record_skipped_ddl("CREATE TYPE x", _PgError("42710"))  # duplicate_object
    record_skipped_ddl("ALTER TABLE y", RuntimeError("boom"))
    assert read_skipped_ddl() == []
    assert not skips_file.exists()


def test_missing_or_broken_file_means_no_skips(skips_file: Path) -> None:
    assert read_skipped_ddl() == []
    skips_file.write_text('not json\n{"step": "ok", "sqlstate": "55P03"}\n')
    assert read_skipped_ddl() == [{"step": "ok", "sqlstate": "55P03"}]


def test_skips_turn_healthy_into_degraded_and_keep_worse_verdicts() -> None:
    skips = [{"step": "ALTER TABLE x", "sqlstate": "55P03"}]
    assert mh.migrations_verdict(HEALTHY_STATE, None, []) == "healthy"
    assert mh.migrations_verdict(HEALTHY_STATE, None, skips).startswith(
        "degraded: 1 startup DDL step(s) skipped"
    )
    drift = {"db_versions": ["a"], "code_heads": ["b"], "orphaned": []}
    verdict = mh.migrations_verdict(drift, None, skips)
    assert verdict.startswith("unhealthy: db a != heads b; 1 startup DDL")


def test_startup_message_lists_steps_and_caps_length() -> None:
    assert mh.skipped_ddl_message([]) is None
    skips = [{"step": f"step {i}", "sqlstate": "55P03"} for i in range(12)]
    message = mh.skipped_ddl_message(skips)
    assert "step 0 [55P03]" in message and "step 9 [55P03]" in message
    assert "step 10" not in message and "(+2 more)" in message


def test_entrypoint_resets_the_file_before_any_ddl() -> None:
    text = ENTRYPOINT.read_text(encoding="utf-8")
    reset = text.index('rm -f "$STARTUP_DDL_SKIPS_FILE"')
    assert reset < text.index("alembic -c alembic/alembic.ini upgrade heads")
    assert text.index("export STARTUP_DDL_SKIPS_FILE") < reset


def test_every_backfill_skip_is_recorded() -> None:
    """Każda instrukcja siatki, która „skip”-uje, zapisuje też pominięcie."""
    text = ENTRYPOINT.read_text(encoding="utf-8")
    skips = list(re.finditer(r'print\(f"backfill (\w+) skip: .*\n(.*)\n', text))
    assert {m.group(1) for m in skips} >= {
        "enum",
        "column",
        "data",
        "constraint",
        "index",
    }
    for match in skips:
        assert "record_skipped_ddl(stmt, e)" in match.group(2), match.group(1)
