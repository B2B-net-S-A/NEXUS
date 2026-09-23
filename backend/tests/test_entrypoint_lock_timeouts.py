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
from app.services import signature_policy_bootstrap as signature
from app.services.startup_locks import is_lock_timeout

ENTRYPOINT = Path(__file__).resolve().parents[1] / "entrypoint.sh"


def _entrypoint() -> str:
    return ENTRYPOINT.read_text(encoding="utf-8")


def test_signature_policy_is_bounded_and_soft_only_on_a_lock_timeout() -> None:
    """The 0282 repair left the heredoc: its lock handling is tested below.

    The heredoc caught EVERY exception ("start is more important"), so a
    broken migration, a missing table or a bad connection string started the
    container silently without the signature permission. Only a lock timeout
    is soft now; anything else fails the boot, as it did before 09.2026.
    """
    source = _entrypoint()
    assert "PY_SIGNATURE_POLICY" not in source
    lines = [line.strip() for line in source.splitlines()]
    # Exactly the command: no `|| echo` — the policy lives inside the module.
    assert "python -m app.services.signature_policy_bootstrap" in lines
    assert lines.index("python -m app.services.signature_policy_bootstrap") < (
        lines.index("exec uvicorn app.main:app --host 0.0.0.0 --port 8000")
    )
    assert signature.BOOT_LOCK_TIMEOUT == "10s"
    assert signature.MIGRATION.is_file()


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


async def test_signature_policy_ready_on_a_migrated_database(engine):
    async with engine.connect() as connection:
        assert await connection.scalar(text(signature.READY_SQL)) is True


async def test_signature_policy_verified_when_nothing_blocks_it(engine, capsys):
    await signature.main(engine)

    assert "Signature confirmation policy verified" in capsys.readouterr().out


async def test_signature_repair_behind_a_dump_is_a_soft_skip(
    engine, monkeypatch, capsys
):
    """The 0282 DDL waits for ACCESS EXCLUSIVE behind pg_dump's ACCESS SHARE."""
    ready_sql = signature.READY_SQL
    monkeypatch.setattr(signature, "BOOT_LOCK_TIMEOUT", "200ms")
    monkeypatch.setattr(signature, "READY_SQL", "SELECT false")

    await _while_locked(
        engine, "rbac_role_action_permissions", lambda: signature.main(engine)
    )

    out = capsys.readouterr().out
    assert "skipped after a lock timeout" in out
    assert "verified" not in out
    # The timed-out repair rolled back: the policy is exactly as it was.
    async with engine.connect() as connection:
        assert await connection.scalar(text(ready_sql)) is True


async def test_signature_policy_behind_a_concurrent_boot_is_a_soft_skip(
    engine, monkeypatch, capsys
):
    """The lock timeout also bounds the wait for the advisory lock itself."""
    monkeypatch.setattr(signature, "BOOT_LOCK_TIMEOUT", "200ms")

    async with engine.connect() as holder:
        transaction = await holder.begin()
        try:
            await holder.execute(
                text("SELECT pg_advisory_xact_lock(:key)"),
                {"key": signature.POLICY_LOCK},
            )
            await signature.main(engine)
        finally:
            await transaction.rollback()

    assert "skipped after a lock timeout" in capsys.readouterr().out


async def test_signature_policy_other_errors_still_fail_the_boot(engine, monkeypatch):
    """Only a lock timeout is soft: a real fault must stop the start."""
    monkeypatch.setattr(
        signature, "READY_SQL", "SELECT no_such_column FROM rbac_policy_state"
    )

    with pytest.raises(DBAPIError) as error:
        await signature.main(engine)
    assert not is_lock_timeout(error.value)


async def test_signature_policy_missing_migration_still_fails_the_boot(
    engine, monkeypatch
):
    monkeypatch.setattr(signature, "READY_SQL", "SELECT false")
    monkeypatch.setattr(signature, "MIGRATION", signature.MIGRATION.with_name("x.py"))

    with pytest.raises(FileNotFoundError):
        await signature.main(engine)


# ── Audyt 22.09 r2 (DATA-02): mail_delivery_schema ──────────────────────────


def _sync_engine():
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url

    return create_engine(
        make_url(settings.DATABASE_URL).set(drivername="postgresql+psycopg2")
    )


def test_mail_delivery_schema_ready_on_a_migrated_database() -> None:
    from app.services.m365 import mail_delivery_schema as mail

    engine = _sync_engine()
    try:
        with engine.connect() as connection:
            assert connection.execute(text(mail.READY_SQL)).scalar() is True
    finally:
        engine.dispose()


async def test_mail_delivery_schema_complete_runs_no_ddl_behind_a_dump(engine):
    """Kompletny schemat = żadnego ALTER — start nie czeka za pg_dump."""
    from app.services.m365 import mail_delivery_schema as mail

    sync = _sync_engine()
    try:
        result = await _while_locked(engine, "notifications", lambda: _call(mail, sync))
    finally:
        sync.dispose()
    assert result == "complete"


async def test_mail_delivery_schema_incomplete_behind_a_dump_still_fails(
    engine, monkeypatch
):
    from app.services.m365 import mail_delivery_schema as mail

    monkeypatch.setattr(mail, "BOOT_LOCK_TIMEOUT", "200ms")
    monkeypatch.setattr(mail, "READY_SQL", "SELECT false")
    sync = _sync_engine()
    try:
        with pytest.raises(DBAPIError) as error:
            await _while_locked(engine, "notifications", lambda: _call(mail, sync))
    finally:
        sync.dispose()
    assert is_lock_timeout(error.value)


async def test_mail_delivery_schema_timeout_on_a_complete_schema_is_soft(
    engine, monkeypatch
):
    """Wyścig: schemat uzupełniony w międzyczasie — timeout nie zatrzymuje startu."""
    from app.services.m365 import mail_delivery_schema as mail

    ready_sql = mail.READY_SQL
    probe = "__ready_probe__"
    calls = {"n": 0}
    original_text = mail.text

    def _text(sql):
        if sql == probe:
            # Pierwsze sprawdzenie: niekompletny; po timeoucie: kompletny.
            calls["n"] += 1
            return original_text("SELECT false" if calls["n"] == 1 else ready_sql)
        return original_text(sql)

    monkeypatch.setattr(mail, "BOOT_LOCK_TIMEOUT", "200ms")
    monkeypatch.setattr(mail, "READY_SQL", probe)
    monkeypatch.setattr(mail, "text", _text)
    sync = _sync_engine()
    try:
        result = await _while_locked(engine, "notifications", lambda: _call(mail, sync))
    finally:
        sync.dispose()
    assert result == "skipped_lock_timeout"


def test_mail_delivery_ddl_tuple_is_unchanged_for_migration_0332() -> None:
    from app.services.m365 import mail_delivery_schema as mail

    assert len(mail.DDL) == 4
    assert mail.DDL[1].startswith("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS")


async def _call(module, sync_engine):
    return module.main(sync_engine)
