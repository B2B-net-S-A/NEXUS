"""DEP-02 (audyt 14.09.2026): nieudana migracja widoczna w runtime.

Dwie połowy mechanizmu:

* ``entrypoint.sh`` zapisuje wynik ``alembic upgrade heads`` do pliku statusu
  i NIE przerywa startu (exit 1 = pętla restartów bez rolling update);
* ``app.services.migration_health`` zamienia plik + rewizje na
  ``checks.migrations`` i jednorazowy ``logger.error`` przy starcie.

Blok entrypointu jest WYKONYWANY z podstawionym ``alembic`` — nie tylko
czytany — bo pułapka ``set -e`` + ``PIPESTATUS`` jest w zachowaniu powłoki.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from app.services import migration_health as mh

_ENTRYPOINT = Path(__file__).parents[1] / "entrypoint.sh"


# ── werdykt ────────────────────────────────────────────────────────────────


def _state(db: list[str], heads: list[str], orphaned: list[str] | None = None) -> dict:
    return {"db_versions": db, "code_heads": heads, "orphaned": orphaned or []}


@pytest.mark.parametrize(
    ("state", "startup", "expected"),
    [
        (_state(["0310"], ["0310"]), {"ok": True, "exit_code": 0}, "healthy"),
        (_state(["0310"], ["0310"]), None, "healthy"),
        (
            _state(["0310"], ["0310"]),
            {"ok": False, "exit_code": 1},
            "degraded: alembic upgrade failed at startup (exit 1), revisions match",
        ),
        (
            _state(["0309"], ["0310"]),
            {"ok": False, "exit_code": 1},
            "unhealthy: db 0309 != heads 0310",
        ),
        (
            {"db_versions": [], "db_error": "OSError"},
            {"ok": False, "exit_code": 1},
            "unhealthy: alembic upgrade failed at startup (exit 1)",
        ),
        (_state(["0309"], ["0310"]), None, "unhealthy: db 0309 != heads 0310"),
        (_state(["x"], ["0310"], ["x"]), None, "unhealthy: orphaned revisions x"),
        (
            {"db_versions": [], "db_error": "OSError", "code_heads": ["0310"]},
            None,
            "unknown",
        ),
        (_state([], ["0310"]), None, "unknown"),
    ],
)
def test_migrations_verdict(state: dict, startup: dict | None, expected: str) -> None:
    assert mh.migrations_verdict(state, startup) == expected


def test_startup_failure_message_redacts_credentials_and_is_silent_on_success() -> None:
    assert mh.startup_failure_message({"ok": True, "exit_code": 0}) is None
    assert mh.startup_failure_message(None) is None
    msg = mh.startup_failure_message(
        {
            "ok": False,
            "exit_code": 2,
            "tail": "connect postgresql+asyncpg://nexus:s3cr3t@postgres:5432/nexus failed",
        }
    )
    assert msg is not None and "exit 2" in msg
    assert "s3cr3t" not in msg
    assert "nexus:***@postgres" in msg


def test_read_startup_status_tolerates_missing_or_garbage(tmp_path: Path) -> None:
    assert mh.read_startup_status(tmp_path / "missing.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    assert mh.read_startup_status(bad) is None
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"ok": False, "exit_code": 1}), encoding="utf-8")
    assert mh.read_startup_status(good) == {"ok": False, "exit_code": 1}


def test_code_revisions_reads_real_graph() -> None:
    heads, known = mh.code_revisions()
    assert heads and set(heads) <= known


# ── entrypoint ─────────────────────────────────────────────────────────────


def _alembic_block() -> str:
    text = _ENTRYPOINT.read_text(encoding="utf-8")
    start = text.index('ALEMBIC_STATUS_FILE="${ALEMBIC_STATUS_FILE:-')
    end = (
        text.index("\nfi\n", text.index('if [ "$ALEMBIC_RC" -ne 0 ]; then', start)) + 4
    )
    return text[start:end]


def test_entrypoint_alembic_block_never_exits() -> None:
    block = _alembic_block()
    assert not re.search(r"^\s*exit\b", block, re.MULTILINE), (
        "Nieudany alembic NIE może zatrzymać startu — brak rolling update w Coolify "
        "oznacza pętlę restartów (deploy #702)."
    )
    assert "PIPESTATUS[0]" in block


@pytest.mark.parametrize("rc", [0, 3])
def test_entrypoint_alembic_block_writes_status_and_continues(
    tmp_path: Path, rc: int
) -> None:
    fake = tmp_path / "bin"
    fake.mkdir()
    alembic = fake / "alembic"
    alembic.write_text(f"#!/bin/sh\necho 'migration output line'\nexit {rc}\n")
    alembic.chmod(0o755)
    python = fake / "python"
    python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    python.chmod(0o755)
    status = tmp_path / "status.json"
    script = "set -e\n" + _alembic_block() + '\necho "AFTER_BLOCK"\n'
    result = subprocess.run(
        ["bash", "-c", script],
        env={
            "PATH": f"{fake}{os.pathsep}{os.environ['PATH']}",
            "ALEMBIC_STATUS_FILE": str(status),
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "AFTER_BLOCK" in result.stdout
    data = json.loads(status.read_text(encoding="utf-8"))
    assert data["ok"] is (rc == 0)
    assert data["exit_code"] == rc
    if rc:
        assert "migration output line" in data["tail"]
        assert "ERROR: alembic upgrade heads failed" in result.stdout
