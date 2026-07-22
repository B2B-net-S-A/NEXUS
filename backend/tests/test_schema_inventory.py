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

CATEGORIES = ("equivalent", "only_in_migrations", "only_in_safetynet", "divergent")
OBJECT_TYPES = ("tables", "columns", "enums", "indexes", "constraints", "views")

DB_A = "schema_inv_a"
DB_B = "schema_inv_b"

# Import the tool as a module for the DB-free unit tests of its safety gate.
sys.path.insert(0, str(BACKEND / "scripts"))
import schema_inventory as si  # noqa: E402


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
            # Destructive reset is now opt-in AND requires the exact db name of
            # each disposable build DSN (typo-guard). These are localhost DBs,
            # so assert_safe_to_reset allows them.
            "--reset",
            "--destructive-reset-disposable",
            DB_A,
            "--destructive-reset-disposable",
            DB_B,
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
    # Head-agnostic: the invariant is a SINGLE head (no multi-head branch),
    # not a specific revision id — hardcoding the revision made this test break
    # on every new migration (it was pinned to 0188 while the head advanced to
    # 0190). Assert exactly one head instead.
    assert len(a["alembic_heads"]) == 1, (
        f"Schema A must build to a SINGLE head, got {a['alembic_heads']!r} — "
        "multiple heads is a STOP-RELEASE migration-graph problem."
    )


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


# ---------------------------------------------------------------------------
# Destructive-reset safety gate (F-02) — DB-free unit tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "dsn",
    [
        # Production-looking host marker.
        "postgresql://nexus:nexus@db.dynaminds.pl:5432/nexus",
        "postgresql+asyncpg://u:p@api.nexus.dynaminds.pl:5432/nexus",
        # Non-local host whose db name carries no disposable marker.
        "postgresql://u:p@db.internal:5432/nexus",
        "postgresql://u:p@10.0.0.9:5432/nexus_prod",
    ],
)
def test_assert_safe_to_reset_refuses_production_looking_dsns(dsn: str) -> None:
    """The gate fails closed on any DSN that does not look clearly disposable."""
    with pytest.raises(si.SchemaResetRefused):
        si.assert_safe_to_reset(dsn)


def test_assert_safe_to_reset_refuses_when_environment_is_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ENVIRONMENT=production overrides even a localhost disposable target."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(si.SchemaResetRefused):
        si.assert_safe_to_reset("postgresql://nexus:nexus@localhost:5432/schema_inv_a")


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://nexus:nexus@localhost:5432/schema_inv_a",
        "postgresql://nexus:nexus@127.0.0.1:5432/schema_inv_b",
        "postgresql+asyncpg://u:p@host.docker.internal:5432/anything",
        # Remote host, but a clearly disposable db name → allowed.
        "postgresql://u:p@ci-runner:5432/nexus_test",
    ],
)
def test_assert_safe_to_reset_allows_disposable_targets(
    dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Local hosts (any db name) and disposable db names are allowed."""
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    si.assert_safe_to_reset(dsn)  # must not raise


def _spy_reset(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace ``reset_public_schema`` with a spy; return the list of DSNs it saw."""
    calls: list[str] = []

    async def _fake_reset(dsn: str) -> None:
        calls.append(dsn)

    monkeypatch.setattr(si, "reset_public_schema", _fake_reset)
    return calls


def test_default_invocation_performs_no_drop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No --reset ⇒ reset default is False and no DROP is ever issued."""
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    ns = si.build_parser().parse_args(
        [
            "--schema-a-dsn",
            f"postgresql://u@localhost:5432/{DB_A}",
            "--schema-b-dsn",
            f"postgresql://u@localhost:5432/{DB_B}",
        ]
    )
    assert ns.reset is False, "reset must default to False (non-destructive)"

    calls = _spy_reset(monkeypatch)
    did_reset = asyncio.run(
        si.reset_if_requested(
            f"postgresql://u@localhost:5432/{DB_A}",
            reset=ns.reset,
            confirmations=set(),
        )
    )
    assert did_reset is False
    assert calls == [], "reset_public_schema must not be called without --reset"


def test_destructive_reset_requires_matching_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--reset with a confirmation that does not match the DSN db → no DROP."""
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    calls = _spy_reset(monkeypatch)
    with pytest.raises(SystemExit):
        asyncio.run(
            si.reset_if_requested(
                f"postgresql://u@localhost:5432/{DB_A}",
                reset=True,
                confirmations={"totally-different-name"},
            )
        )
    assert calls == [], "a mismatched confirmation must not trigger a DROP"


def test_destructive_reset_with_matching_confirmation_drops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--reset + exact db-name confirmation on a disposable localhost DB → DROP."""
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    calls = _spy_reset(monkeypatch)
    dsn = f"postgresql://u@localhost:5432/{DB_A}"
    did_reset = asyncio.run(
        si.reset_if_requested(dsn, reset=True, confirmations={DB_A})
    )
    assert did_reset is True
    assert calls == [dsn], "a confirmed, safe reset must call reset_public_schema once"


def test_expected_head_default_is_dynamic_not_hardcoded() -> None:
    """F-01: no stale hardcoded head. The default is dynamic; the derived head is
    computed from the live migration graph (head-agnostic — we do not pin a
    specific revision, only assert the stale ``0188`` pin is gone)."""
    ns = si.build_parser().parse_args(
        [
            "--schema-a-dsn",
            f"postgresql://u@localhost:5432/{DB_A}",
            "--schema-b-dsn",
            f"postgresql://u@localhost:5432/{DB_B}",
        ]
    )
    assert ns.expected_head is None, "expected-head must have no hardcoded default"

    head = si.determine_expected_head(BACKEND)
    if head is None:
        pytest.skip("alembic unavailable or multi-head in this environment")
    assert isinstance(head, str) and head
    assert head != "0188_contract_alert_dedup", (
        "the stale 0188 pin must not be baked back in — the head is dynamic"
    )
