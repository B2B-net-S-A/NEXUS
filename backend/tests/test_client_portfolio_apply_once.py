"""Fail-closed startup and deep-health contracts for the client import."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import postgresql

import app.models.skill  # noqa: F401  (register relationship target)
from app.cli import client_portfolio_import as cli
from app.models.client_directory import ClientAlias
from app.services.client_portfolio_import import (
    POSTGRES_LOCK_TIMEOUT,
    SOURCE_SYSTEM,
    _acquire_import_advisory_lock,
    _find_existing_msa,
    _find_existing_scope,
    _lock_import_write_surface,
    _normalized_manifest_sha256,
    _upsert_alias,
    apply_client_portfolio_manifest,
    get_client_portfolio_import_health,
)


class _Session:
    def __init__(self) -> None:
        self.commit = AsyncMock()
        self.rollback = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _AliasSession:
    def __init__(self, existing: ClientAlias | None = None) -> None:
        self.scalar = AsyncMock(return_value=existing)
        self.flush = AsyncMock()
        self.added: list[ClientAlias] = []

    def add(self, alias: ClientAlias) -> None:
        alias.id = 91
        self.added.append(alias)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected_code", "commits", "rollbacks"),
    [
        ("applied", 0, 1, 0),
        ("already_applied", 0, 0, 1),
        ("blocked", 2, 1, 0),
        ("failed", 1, 1, 0),
    ],
)
async def test_apply_once_commits_success_or_durable_failure_audit(
    monkeypatch,
    status: str,
    expected_code: int,
    commits: int,
    rollbacks: int,
) -> None:
    session = _Session()
    monkeypatch.setattr(cli, "AsyncSessionLocal", lambda: session)
    monkeypatch.setattr(
        cli,
        "apply_client_portfolio_manifest",
        AsyncMock(return_value={"status": status}),
    )
    monkeypatch.setattr(cli, "_print", lambda payload: None)

    code = await cli._run(
        dry_run=False,
        apply_once=True,
        rollback_run_id=None,
    )

    assert code == expected_code
    assert session.commit.await_count == commits
    assert session.rollback.await_count == rollbacks


@pytest.mark.asyncio
async def test_import_health_reports_exact_hash_and_count_consistency() -> None:
    manifest = {
        "source": {"sha256": "a" * 64},
        "rows": [
            {"category": "active", "effective_date": "2026-01-01"},
            {"category": "relationship", "effective_date": "2026-02-01"},
            {"category": "inactive"},
        ],
    }
    run = SimpleNamespace(
        id=41,
        applied_at=datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc),
        summary={"normalized_manifest_sha256": _normalized_manifest_sha256(manifest)},
    )
    count_row = SimpleNamespace(
        audit_rows=5,
        imported_manifest_rows=3,
        nexus_only_rows=2,
        unique_clients=4,
        portfolio_scopes=5,
        framework_contracts=2,
        active_rows=1,
        relationship_rows=1,
        inactive_rows=1,
    )
    db = SimpleNamespace(
        scalar=AsyncMock(return_value=run),
        execute=AsyncMock(
            side_effect=[
                SimpleNamespace(one=lambda: count_row),
                SimpleNamespace(scalar_one=lambda: 5),
                SimpleNamespace(scalar_one=lambda: 2),
            ],
        ),
    )

    health = await get_client_portfolio_import_health(db, manifest=manifest)

    assert health == {
        "expected_source_sha256": "a" * 64,
        "expected_manifest_sha256": _normalized_manifest_sha256(manifest),
        "status": "applied",
        "run_id": 41,
        "applied_at": "2026-07-30T12:00:00+00:00",
        "counts": {
            "expected_manifest_rows": 3,
            "expected_framework_contracts": 2,
            "imported_manifest_rows": 3,
            "nexus_only_rows": 2,
            "audit_rows": 5,
            "unique_clients": 4,
            "portfolio_scopes": 5,
            "framework_contracts": 2,
            "live_portfolio_scopes": 5,
            "live_framework_contracts": 2,
            "category_rows": {
                "active": 1,
                "relationship": 1,
                "inactive": 1,
            },
        },
    }


@pytest.mark.asyncio
async def test_import_health_rejects_missing_live_msa() -> None:
    manifest = {
        "source": {"sha256": "d" * 64},
        "rows": [{"category": "active", "effective_date": "2026-01-01"}],
    }
    run = SimpleNamespace(
        id=42,
        applied_at=datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc),
        summary={"normalized_manifest_sha256": _normalized_manifest_sha256(manifest)},
    )
    count_row = SimpleNamespace(
        audit_rows=1,
        imported_manifest_rows=1,
        nexus_only_rows=0,
        unique_clients=1,
        portfolio_scopes=1,
        framework_contracts=1,
        active_rows=1,
        relationship_rows=0,
        inactive_rows=0,
    )
    db = SimpleNamespace(
        scalar=AsyncMock(return_value=run),
        execute=AsyncMock(
            side_effect=[
                SimpleNamespace(one=lambda: count_row),
                SimpleNamespace(scalar_one=lambda: 1),
                SimpleNamespace(scalar_one=lambda: 0),
            ],
        ),
    )

    health = await get_client_portfolio_import_health(db, manifest=manifest)

    assert health["status"] == "inconsistent"
    assert health["counts"]["live_framework_contracts"] == 0


def test_entrypoint_runs_apply_once_before_api_without_fail_open() -> None:
    entrypoint = (Path(__file__).resolve().parents[1] / "entrypoint.sh").read_text(
        encoding="utf-8"
    )
    command = "python -m app.cli.client_portfolio_import --apply-once"
    command_line = next(
        line.strip() for line in entrypoint.splitlines() if command in line
    )

    assert entrypoint.index(command) > entrypoint.index("Running database migrations")
    assert entrypoint.index(command) < entrypoint.index("exec uvicorn app.main:app")
    assert command_line == command


@pytest.mark.asyncio
async def test_apply_once_blocks_changed_reviewed_json_for_same_workbook() -> None:
    manifest = {
        "source": {"sha256": "b" * 64},
        "rows": [],
    }
    applied_run = SimpleNamespace(
        id=73,
        summary={"normalized_manifest_sha256": "c" * 64},
    )
    db = SimpleNamespace(
        bind=None,
        scalar=AsyncMock(return_value=applied_run),
    )

    result = await apply_client_portfolio_manifest(db, manifest=manifest)

    assert result["status"] == "blocked"
    assert result["run_id"] == 73
    assert result["blockers"][0]["code"] == "normalized_manifest_digest_mismatch"


@pytest.mark.asyncio
async def test_postgres_lock_timeout_is_set_before_advisory_lock() -> None:
    db = SimpleNamespace(
        bind=SimpleNamespace(dialect=SimpleNamespace(name="postgresql")),
        execute=AsyncMock(),
    )

    acquired = await _acquire_import_advisory_lock(db)

    assert acquired is True
    assert db.execute.await_count == 2
    timeout_call, advisory_call = db.execute.await_args_list
    assert "set_config('lock_timeout'" in str(timeout_call.args[0])
    assert timeout_call.args[1] == {"timeout": POSTGRES_LOCK_TIMEOUT}
    assert POSTGRES_LOCK_TIMEOUT == "15s"
    assert "pg_advisory_xact_lock" in str(advisory_call.args[0])


@pytest.mark.asyncio
async def test_alias_upsert_records_provenance_and_revives_archived_record() -> None:
    created_session = _AliasSession()

    created_audit = await _upsert_alias(
        created_session,
        client_id=17,
        alias="  Imported Alias  ",
        source_key="active:test:0",
        import_run_id=41,
    )

    assert created_audit is not None
    assert created_audit["before"] is None
    assert created_audit["after"]["id"] == 91
    assert created_audit["after"]["import_run_id"] == 41
    assert created_audit["after"]["archived_at"] is None
    assert created_session.added[0].source_system == SOURCE_SYSTEM

    archived_at = datetime(2026, 7, 30, 8, 0, tzinfo=timezone.utc)
    archived = ClientAlias(
        id=92,
        client_id=17,
        alias="Imported Alias",
        normalized_alias="imported alias",
        source_system=SOURCE_SYSTEM,
        source_key="active:test:0",
        import_run_id=41,
        archived_at=archived_at,
    )
    revived_session = _AliasSession(archived)

    revived_audit = await _upsert_alias(
        revived_session,
        client_id=17,
        alias="Imported Alias",
        source_key="active:test:0",
        import_run_id=42,
    )

    assert revived_audit is not None
    assert revived_audit["before"]["archived_at"] == archived_at.isoformat()
    assert revived_audit["before"]["import_run_id"] == 41
    assert revived_audit["after"]["archived_at"] is None
    assert revived_audit["after"]["import_run_id"] == 42
    assert archived.archived_at is None
    assert archived.import_run_id == 42


@pytest.mark.asyncio
async def test_apply_write_surface_locks_matching_inputs_and_kir_rows() -> None:
    db = SimpleNamespace(execute=AsyncMock())

    await _lock_import_write_surface(
        db,
        kir_client_ids=(24, 32),
        include_candidates=True,
    )

    assert db.execute.await_count == 2
    table_lock, row_lock = db.execute.await_args_list
    lock_sql = str(table_lock.args[0])
    for table in ("clients", "client_aliases", "candidates"):
        assert table in lock_sql
    assert "client_portfolio_scopes" not in lock_sql
    assert "client_framework_contracts" not in lock_sql
    assert "SHARE ROW EXCLUSIVE" in lock_sql
    row_sql = str(row_lock.args[0].compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in row_sql
    assert "WHERE clients.id IN" in row_sql


@pytest.mark.asyncio
async def test_apply_write_surface_skips_candidate_and_row_locks_without_kir() -> None:
    db = SimpleNamespace(execute=AsyncMock())

    await _lock_import_write_surface(db)

    db.execute.assert_awaited_once()
    lock_sql = str(db.execute.await_args.args[0])
    assert "clients" in lock_sql
    assert "client_aliases" in lock_sql
    assert "candidates" not in lock_sql


@pytest.mark.asyncio
async def test_existing_scope_and_msa_are_row_locked_and_archived_scope_is_visible() -> (
    None
):
    db = SimpleNamespace(scalar=AsyncMock(return_value=None))

    await _find_existing_scope(db, "scope-key")
    scope_statement = db.scalar.await_args.args[0]
    scope_sql = str(scope_statement.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in scope_sql
    assert "archived_at IS NULL" not in scope_sql
    assert "ORDER BY" in scope_sql

    db.scalar.reset_mock()
    await _find_existing_msa(db, "msa-key")
    msa_statement = db.scalar.await_args.args[0]
    msa_sql = str(msa_statement.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in msa_sql
