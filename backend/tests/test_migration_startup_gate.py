"""Negative regression tests for Alembic-only, fail-closed startup."""

from __future__ import annotations

import ast
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(0o755)


def _fake_path(tmp_path: Path, *, gate_exit: int = 0, alembic_exit: int = 0) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "id",
        "#!/bin/sh\nif [ \"${1:-}\" = '-u' ]; then echo 10001; else echo appuser; fi\n",
    )
    _write_executable(
        bin_dir / "python",
        "#!/bin/sh\n"
        "if [ \"${1:-}\" = '-m' ] && "
        "[ \"${2:-}\" = 'scripts.assert_migration_head' ]; then "
        f"exit {gate_exit}; fi\n"
        "exit 0\n",
    )
    _write_executable(bin_dir / "sleep", "#!/bin/sh\nexit 0\n")
    _write_executable(bin_dir / "alembic", f"#!/bin/sh\nexit {alembic_exit}\n")
    _write_executable(
        bin_dir / "uvicorn",
        '#!/bin/sh\n: > "${UVICORN_MARKER:?}"\nexit 0\n',
    )
    return bin_dir


def _entrypoint_env(tmp_path: Path, fake_path: Path) -> tuple[dict[str, str], Path]:
    marker = tmp_path / "uvicorn-started"
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_path}:{env['PATH']}",
            "NEXUS_APP_ROOT": str(BACKEND_ROOT),
            "NEXUS_MIGRATION_GATE_ATTEMPTS": "1",
            "NEXUS_ENABLE_DEMO_SEED": "false",
            "UVICORN_MARKER": str(marker),
        }
    )
    return env, marker


def test_application_startup_sources_have_no_schema_mutator() -> None:
    python_startup_sources = [
        BACKEND_ROOT / "app" / "main.py",
        BACKEND_ROOT / "seed.py",
        BACKEND_ROOT / "seed_v4.py",
        BACKEND_ROOT / "seed_v5.py",
        BACKEND_ROOT / "seed_v6_pipeline.py",
    ]
    for path in python_startup_sources:
        tree = ast.parse(path.read_text(), filename=str(path))
        forbidden = [
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and node.attr in {"create_all", "drop_all"}
        ]
        assert forbidden == [], f"{path} contains schema mutator(s): {forbidden}"

    entrypoint = (BACKEND_ROOT / "entrypoint.sh").read_text().upper()
    assert "ALEMBIC -C" not in entrypoint
    assert "UPGRADE HEAD" not in entrypoint
    for token in (
        "CREATE TABLE",
        "ALTER TABLE",
        "DROP TABLE",
        "CREATE TYPE",
        "ALTER TYPE",
    ):
        assert token not in entrypoint

    main_source = (BACKEND_ROOT / "app" / "main.py").read_text()
    gate = main_source.index("await require_current_migration_head()")
    first_startup_side_effect = main_source.index(
        "await asyncio.to_thread(init_qdrant_collection)", gate
    )
    assert gate < first_startup_side_effect


def test_migration_command_is_exactly_upgrade_head() -> None:
    script = (BACKEND_ROOT / "migrate.sh").read_text()
    assert "upgrade heads" not in script
    assert "||" not in script
    assert "continue" not in script.lower()
    assert script.rstrip().endswith("exec alembic -c alembic/alembic.ini upgrade head")


def test_migration_failure_prevents_serving(tmp_path: Path) -> None:
    fake_path = _fake_path(tmp_path, gate_exit=0, alembic_exit=23)
    env, marker = _entrypoint_env(tmp_path, fake_path)

    result = subprocess.run(
        ["sh", str(BACKEND_ROOT / "entrypoint.sh"), "migrate"],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    assert result.returncode == 23
    assert not marker.exists()


def test_stale_or_failed_migration_gate_prevents_uvicorn(tmp_path: Path) -> None:
    fake_path = _fake_path(tmp_path, gate_exit=1)
    env, marker = _entrypoint_env(tmp_path, fake_path)

    result = subprocess.run(
        ["sh", str(BACKEND_ROOT / "entrypoint.sh"), "serve"],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    assert result.returncode == 70
    assert "refusing to serve" in result.stderr
    assert not marker.exists()


@pytest.mark.asyncio
async def test_fastapi_lifespan_fails_before_side_effects(monkeypatch) -> None:
    from app.main import app, lifespan

    qdrant_called = False

    async def _migration_failure() -> None:
        raise RuntimeError("synthetic migration failure")

    def _qdrant_side_effect() -> None:
        nonlocal qdrant_called
        qdrant_called = True

    monkeypatch.setattr("app.main.require_current_migration_head", _migration_failure)
    monkeypatch.setattr(
        "app.services.embedding_service.init_qdrant_collection",
        _qdrant_side_effect,
    )

    with pytest.raises(RuntimeError, match="synthetic migration failure"):
        async with lifespan(app):
            pass

    assert qdrant_called is False


def test_compose_migration_job_is_required_before_backend() -> None:
    compose = (REPO_ROOT / "docker-compose.yml").read_text()
    migration_service = compose[
        compose.index("  migrate:\n") : compose.index("  backend:\n")
    ]
    backend_service = compose[
        compose.index("  backend:\n") : compose.index("  frontend:\n")
    ]

    assert 'command: ["migrate"]' in migration_service
    assert 'restart: "no"' in migration_service
    assert (
        "      migrate:\n        condition: service_completed_successfully"
        in backend_service
    )


def test_revision_gate_queries_are_read_only() -> None:
    source = (BACKEND_ROOT / "app" / "core" / "migration_gate.py").read_text()
    tree = ast.parse(source)
    sql_literals = [
        node.value.upper()
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and "ALEMBIC_VERSION" in node.value.upper()
    ]
    assert sql_literals
    assert all(value.lstrip().startswith("SELECT") for value in sql_literals)
