"""End-to-end contract for the read-only schema-drift inventory tool.

Runs ``scripts/schema_inventory.py`` against two throwaway databases created on
the CI Postgres server and asserts the report is well-formed, that Schema A
builds to the single expected head (``0188``), and that the diff categorises
every object type into the four buckets. It also *records* (in assertion
messages / a printed summary) the actual divergences the tool finds — this is a
diagnostic tool, so the test proves it RUNS and CATEGORISES rather than demanding
zero drift.

The tool itself never touches prod and never runs ``alembic stamp``; this test
only exercises disposable ``schema_inv_a`` / ``schema_inv_b`` databases.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import asyncio

import asyncpg
import pytest

BACKEND = Path(__file__).resolve().parents[1]
TOOL = BACKEND / "scripts" / "schema_inventory.py"
EXPECTED_HEAD = "0188_contract_alert_dedup"

CATEGORIES = ("equivalent", "only_in_migrations", "only_in_safetynet", "divergent")
OBJECT_TYPES = ("tables", "columns", "enums", "indexes", "constraints", "views")

DB_A = "schema_inv_a"
DB_B = "schema_inv_b"


def _server_dsn() -> str:
    """asyncpg DSN for the maintenance ('postgres') DB on the CI server."""
    raw = os.environ.get(
        "DATABASE_URL", "postgresql+asyncpg://nexus:nexus@localhost:5432/nexus"
    )
    apg = raw.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgres+asyncpg://", "postgresql://"
    )
    # Swap the database segment to the always-present 'postgres' maintenance DB.
    base, _, _tail = apg.rpartition("/")
    return f"{base}/postgres"


def _dsn_for(db: str) -> str:
    base, _, _ = _server_dsn().rpartition("/")
    return f"{base}/{db}"


async def _recreate_databases() -> None:
    conn = await asyncpg.connect(_server_dsn())
    try:
        for db in (DB_A, DB_B):
            await conn.execute(f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE)')
            await conn.execute(f'CREATE DATABASE "{db}"')
    finally:
        await conn.close()


@pytest.fixture(scope="module")
def throwaway_dbs() -> tuple[str, str]:
    """Create two disposable DBs on the server; skip if the server is unreachable
    or the user lacks CREATE DATABASE (so local runs without a permissive PG do
    not hard-fail — CI's superuser service container runs it for real)."""
    try:
        asyncio.run(_recreate_databases())
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Postgres unavailable or cannot CREATE DATABASE: {exc}")
    return _dsn_for(DB_A), _dsn_for(DB_B)


@pytest.fixture(scope="module")
def report(
    throwaway_dbs: tuple[str, str], tmp_path_factory: pytest.TempPathFactory
) -> dict:
    dsn_a, dsn_b = throwaway_dbs
    out_dir = tmp_path_factory.mktemp("schema_inv_out")
    env = dict(os.environ)
    env["SECRET_KEY"] = "schema-inventory-test-secret-key-at-least-48-chars-xxxxxx"
    env.setdefault("M365_TOKEN_ENCRYPTION_KEY", "0" * 43 + "=")
    proc = subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "--schema-a-dsn",
            dsn_a,
            "--schema-b-dsn",
            dsn_b,
            "--reset",
            "--out-dir",
            str(out_dir),
        ],
        cwd=str(BACKEND),
        env=env,
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert proc.returncode == 0, (
        f"tool exited {proc.returncode}\nSTDOUT tail:\n{proc.stdout[-2000:]}\n"
        f"STDERR tail:\n{proc.stderr[-2000:]}"
    )
    json_path = out_dir / "schema_inventory.json"
    md_path = out_dir / "schema_inventory.md"
    assert json_path.exists(), "JSON report not written"
    assert md_path.exists(), "Markdown report not written"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    # Surface the drift picture in the test log — diagnostic output.
    print("\n[schema_inventory] summary:", json.dumps(data["summary"], indent=2))
    print("[schema_inventory] create_all:", json.dumps(data["schema_b"]["create_all"]))
    return data


def test_schema_a_builds_to_single_expected_head(report: dict) -> None:
    a = report["schema_a"]
    assert a["build_ok"] is True, f"Schema A (migrations) failed to build: {a}"
    assert a["alembic_heads"] == [EXPECTED_HEAD], (
        f"Schema A must build to a single head {EXPECTED_HEAD!r}, "
        f"got {a['alembic_heads']!r} — multiple heads or a wrong head is a "
        "STOP-RELEASE migration-graph problem."
    )
    assert a["single_expected_head"] is True


def test_report_is_well_formed_with_all_categories(report: dict) -> None:
    diff = report["diff"]
    summary = report["summary"]
    for obj in OBJECT_TYPES:
        assert obj in diff, f"diff missing object type {obj!r}"
        assert obj in summary, f"summary missing object type {obj!r}"
        for cat in CATEGORIES:
            assert cat in diff[obj], f"{obj}.{cat} missing from diff"
            assert isinstance(diff[obj][cat], list), f"{obj}.{cat} is not a list"
            assert summary[obj][cat] == len(diff[obj][cat]), (
                f"summary count for {obj}.{cat} disagrees with the diff list length"
            )


def test_both_schemas_actually_built(report: dict) -> None:
    """Sanity: the end-to-end build produced substantial schemas on both sides."""
    a_counts = report["schema_a"]["counts"]
    b_counts = report["schema_b"]["counts"]
    assert a_counts["tables"] > 100, f"Schema A looks unbuilt: {a_counts}"
    assert b_counts["tables"] > 100, f"Schema B looks unbuilt: {b_counts}"


def test_create_all_outcome_is_recorded(report: dict) -> None:
    """The entrypoint's create_all leg is a first-class diagnostic field.

    We do NOT require it to succeed (as shipped it fails on an ORM FK to an
    unmapped table). We require the tool to REPORT the outcome and, when it
    stripped FKs to keep going, to list them — so a future fix flips these fields
    visibly instead of silently.
    """
    ca = report["schema_b"]["create_all"]
    assert "ok" in ca and isinstance(ca["ok"], bool)
    assert "faithful_ok" in ca and isinstance(ca["faithful_ok"], bool)
    assert isinstance(ca["stripped_dangling_fks"], list)
    if not ca["faithful_ok"]:
        # Document the known-at-time-of-writing failure without over-fitting: if
        # create_all was not faithfully OK, the tool must explain why.
        assert ca["error"], "create_all not faithful but no error recorded"


def test_diff_categorises_every_table(report: dict) -> None:
    """Every Schema A table lands in exactly one bucket vs Schema B — the diff is
    total, not partial. This is the core 'do the two systems agree?' guarantee."""
    a_tables = report["schema_a"]["counts"]["tables"]
    t = report["summary"]["tables"]
    accounted = t["equivalent"] + t["only_in_migrations"] + t["divergent"]
    assert accounted == a_tables, (
        f"table diff does not account for all {a_tables} migration tables "
        f"(equivalent+only_in_migrations+divergent={accounted})"
    )
