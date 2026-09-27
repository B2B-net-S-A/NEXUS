"""Runda 10 (R10-N12-2): ``alembic upgrade`` przy starcie ma limity czekania.

Bez ``lock_timeout`` migracja z DDL wdrożona w trakcie nocnego ``pg_dump``
czekała na ACCESS EXCLUSIVE do końca zrzutu (stary kontener już stał).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.services import startup_locks

ENV_PY = Path(__file__).resolve().parents[1] / "alembic" / "env.py"


class _Conn:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def execute(self, statement, params=None):
        self.calls.append(("execute", (str(statement), params)))

    def commit(self):
        self.calls.append(("commit", None))


def test_limits_are_session_level_and_committed_before_alembic_transaction():
    conn = _Conn()
    limits = startup_locks.apply_migration_session_limits(conn)
    assert limits == {
        "lock_timeout": startup_locks.BOOT_LOCK_TIMEOUT,
        "statement_timeout": startup_locks.ALEMBIC_STATEMENT_TIMEOUT,
    }
    executed = [c[1] for c in conn.calls if c[0] == "execute"]
    assert all("set_config(:name, :value, false)" in sql for sql, _ in executed)
    assert {p["name"]: p["value"] for _, p in executed} == limits
    # Otwarta transakcja po SELECT oznaczałaby, że alembic nie zatwierdzi
    # migracji (begin_transaction uznaje ją za cudzą).
    assert conn.calls[-1] == ("commit", None)


def test_env_override_accepts_only_postgres_durations(monkeypatch):
    monkeypatch.setenv("ALEMBIC_STATEMENT_TIMEOUT", "45min")
    monkeypatch.setenv("ALEMBIC_LOCK_TIMEOUT", "30s'; DROP TABLE users; --")
    limits = startup_locks.apply_migration_session_limits(_Conn())
    assert limits["statement_timeout"] == "45min"
    assert limits["lock_timeout"] == startup_locks.BOOT_LOCK_TIMEOUT


def _do_run_migrations() -> ast.FunctionDef:
    tree = ast.parse(ENV_PY.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "do_run_migrations":
            return node
    pytest.fail("alembic/env.py nie ma do_run_migrations")


def test_env_py_applies_limits_before_configuring_migrations():
    lines: dict[str, int] = {}
    for node in ast.walk(_do_run_migrations()):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", "")
            lines.setdefault(name, node.lineno)
    assert "apply_migration_session_limits" in lines
    assert lines["apply_migration_session_limits"] < lines["configure"]
