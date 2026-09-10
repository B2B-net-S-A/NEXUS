"""Boot-time schema repairs wait for a lock at most `BOOT_LOCK_TIMEOUT` (09.2026).

`entrypoint.sh` runs under `set -e` and re-applies idempotent DDL on every
start; `ADD COLUMN IF NOT EXISTS` requests ACCESS EXCLUSIVE even when there is
nothing to add. Behind the nightly pg_dump (ACCESS SHARE on every table) the
boot hung without end, and the queued request stalled every reader of the
table in the container still serving traffic. With a bare limit the start
would crash-loop for the whole dump instead — so a lock timeout is fatal only
when the schema really is incomplete.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.services import allocation_schema_bootstrap as allocation
from app.services import cv_schema_bootstrap as cv_schema
from app.services.startup_locks import is_lock_timeout

ENTRYPOINT = Path(__file__).resolve().parents[1] / "entrypoint.sh"


def _entrypoint() -> str:
    return ENTRYPOINT.read_text(encoding="utf-8")


def test_signature_policy_block_is_bounded_and_soft() -> None:
    source = _entrypoint()
    assert "python - <<'PY_SIGNATURE_POLICY'\n" in source
    block = source.split("python - <<'PY_SIGNATURE_POLICY'", 1)[1].split(
        "\nPY_SIGNATURE_POLICY", 1
    )[0]
    compile(block, "signature-policy-entrypoint", "exec")
    assert "SET LOCAL lock_timeout = '10s'" in block
    # Soft: the failure is caught inside the block, the process exits 0.
    assert "except Exception" in block
    assert block.index("SET LOCAL lock_timeout") < block.index("pg_advisory_xact_lock")


def test_allocation_and_cv_repairs_run_as_fail_hard_modules() -> None:
    lines = [line.strip() for line in _entrypoint().splitlines()]
    for command in (
        "python -m app.services.allocation_schema_bootstrap",
        "python -m app.services.cv_schema_bootstrap",
    ):
        # Exactly the command: no `|| echo`, a truly incomplete schema must
        # still stop the start — the lock policy lives inside the module.
        assert command in lines, command
    assert "PY_ALLOCATION" not in _entrypoint()
    assert lines.index("python -m app.services.allocation_schema_bootstrap") < (
        lines.index("exec uvicorn app.main:app --host 0.0.0.0 --port 8000")
    )


def test_allocation_lock_is_the_runtime_allocation_lock() -> None:
    from app.services.recruitment_allocation import ALLOCATION_LOCK

    assert allocation.ALLOCATION_LOCK == ALLOCATION_LOCK
    assert allocation.MIGRATION.is_file()


def test_lock_timeout_is_recognised_by_sqlstate_only() -> None:
    wrapped = DBAPIError("ALTER TABLE", {}, SimpleNamespace(sqlstate="55P03"))
    other = DBAPIError("ALTER TABLE", {}, SimpleNamespace(sqlstate="42P01"))

    assert is_lock_timeout(wrapped)
    assert not is_lock_timeout(other)
    assert not is_lock_timeout(RuntimeError("55P03"))


# ── Real PostgreSQL ──────────────────────────────────────────────────────────


@pytest.fixture
async def engine():
    engine = create_async_engine(settings.DATABASE_URL)
    try:
        yield engine
    finally:
        await engine.dispose()


async def _while_locked(engine, table: str, action):
    """Run ``action`` while another session holds ACCESS SHARE, like pg_dump."""
    async with engine.connect() as holder:
        transaction = await holder.begin()
        try:
            await holder.execute(text(f"LOCK TABLE {table} IN ACCESS SHARE MODE"))
            return await action()
        finally:
            await transaction.rollback()


async def test_allocation_ready_sql_holds_on_a_migrated_database(engine):
    async with engine.connect() as connection:
        assert await connection.scalar(text(allocation.READY_SQL)) is True


async def test_allocation_repair_runs_when_nothing_blocks_it(engine, capsys):
    await allocation.main(engine)

    assert "schema verified" in capsys.readouterr().out


async def test_allocation_lock_timeout_on_a_complete_schema_does_not_stop_boot(
    engine, monkeypatch, capsys
):
    monkeypatch.setattr(allocation, "BOOT_LOCK_TIMEOUT", "200ms")

    await _while_locked(engine, "calendar_events", lambda: allocation.main(engine))

    assert "repair skipped after a lock timeout" in capsys.readouterr().out


async def test_allocation_lock_timeout_on_a_missing_schema_still_fails(
    engine, monkeypatch
):
    monkeypatch.setattr(allocation, "BOOT_LOCK_TIMEOUT", "200ms")
    monkeypatch.setattr(allocation, "READY_SQL", "SELECT false")

    with pytest.raises(DBAPIError) as error:
        await _while_locked(engine, "calendar_events", lambda: allocation.main(engine))
    assert is_lock_timeout(error.value)


async def test_cv_schema_ready_on_a_migrated_database(engine):
    async with engine.connect() as connection:
        assert await connection.run_sync(cv_schema.cv_schema_ready) is True


async def test_cv_repair_lock_timeout_on_a_complete_schema_does_not_stop_boot(
    engine, monkeypatch, capsys
):
    monkeypatch.setattr(cv_schema, "BOOT_LOCK_TIMEOUT", "200ms")

    await _while_locked(
        engine, "cv_generated_documents", lambda: cv_schema.main(engine)
    )

    assert "repair skipped after a lock timeout" in capsys.readouterr().out


async def test_cv_repair_lock_timeout_on_an_incomplete_schema_still_fails(
    engine, monkeypatch
):
    monkeypatch.setattr(cv_schema, "BOOT_LOCK_TIMEOUT", "200ms")
    monkeypatch.setattr(cv_schema, "cv_schema_ready", lambda connection: False)

    with pytest.raises(DBAPIError):
        await _while_locked(
            engine, "cv_generated_documents", lambda: cv_schema.main(engine)
        )
