"""GET /api/admin/schema-drift — read-only report: ORM expectation vs live schema.

Motivation
----------
NEXUS prod carries chronic alembic drift: ``alembic_version`` holds a bookmark
far behind the code's head, and the schema is kept alive by two mechanisms that
each have a blind spot:

- ``Base.metadata.create_all`` creates **missing tables** but silently skips
  tables that already exist — so a migration adding a COLUMN to an EXISTING
  table lands nowhere.
- ``entrypoint.sh``'s hand-maintained ``_COLUMN_STATEMENTS`` safety-net closes
  that gap, but only for columns somebody remembered to add to the list.

The failure mode is quiet and nasty: the deploy goes GREEN, ``/api/health``
stays healthy (it only does ``SELECT 1``), and then the ORM ``SELECT``s a
column Postgres does not have → ``UndefinedColumn`` → a whole module renders
empty. ``/api/health/deep`` catches this for ten probed modules; everything
else is unmonitored.

This endpoint answers the question those mechanisms cannot: *what does the ORM
expect that the database does not actually have?* It is the measurement that
decides whether prod needs migrating forward at all, or whether the safety-net
already covers reality.

Contract
--------
- **Read-only.** Nothing here mutates: no DDL, no DML, no ``create_all``.
- **Zero PII.** Output contains schema identifiers only — table names, column
  names, enum labels, alembic revision ids. No row data is read at any point;
  every query targets ``information_schema`` / ``pg_catalog``.
- Each check has its own timeout; one failing check yields an ``error`` field
  instead of collapsing the whole report.
- ``query_version`` lets successive runs be compared meaningfully.

Auth: same as ``/api/admin/snapshot`` — ``X-Snapshot-Token`` (machine) or an
admin JWT.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import Enum as SAEnum
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_snapshot import _snapshot_auth
from app.core.database import Base, get_db

router = APIRouter()

# Bump on every change to what the checks mean — reports are only comparable
# within one version.
QUERY_VERSION = "drift-v1"

CHECK_TIMEOUT_SECONDS = 20.0

# Tables that legitimately live in the DB without an ORM model. Anything here
# is reported as informational rather than as drift.
_KNOWN_NON_ORM_TABLES = frozenset(
    {
        "alembic_version",
        "spatial_ref_sys",  # PostGIS, if ever enabled
    }
)


async def _actual_tables(db: AsyncSession) -> set[str]:
    rows = (
        await db.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
            )
        )
    ).scalars()
    return set(rows)


async def _actual_columns(db: AsyncSession) -> dict[str, dict[str, dict[str, Any]]]:
    """-> {table: {column: {"nullable": bool, "type": str}}}"""
    rows = (
        await db.execute(
            text(
                "SELECT table_name, column_name, is_nullable, data_type, udt_name "
                "FROM information_schema.columns WHERE table_schema = 'public'"
            )
        )
    ).all()
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for table, column, is_nullable, data_type, udt_name in rows:
        out.setdefault(table, {})[column] = {
            "nullable": is_nullable == "YES",
            "type": data_type,
            "udt": udt_name,
        }
    return out


async def _actual_enums(db: AsyncSession) -> dict[str, set[str]]:
    """-> {enum_type_name: {label, ...}} for every enum in the public schema."""
    rows = (
        await db.execute(
            text(
                "SELECT t.typname, e.enumlabel FROM pg_type t "
                "JOIN pg_enum e ON e.enumtypid = t.oid "
                "JOIN pg_namespace n ON n.oid = t.typnamespace "
                "WHERE n.nspname = 'public'"
            )
        )
    ).all()
    out: dict[str, set[str]] = {}
    for typname, label in rows:
        out.setdefault(typname, set()).add(label)
    return out


def _expected_enums() -> dict[str, set[str]]:
    """Enum types the ORM declares, keyed by their Postgres type name."""
    out: dict[str, set[str]] = {}
    for table in Base.metadata.tables.values():
        for column in table.columns:
            coltype = column.type
            if isinstance(coltype, SAEnum) and coltype.name:
                out.setdefault(coltype.name, set()).update(coltype.enums or [])
    return out


async def _actual_indexes(db: AsyncSession) -> set[tuple[str, str]]:
    """-> {(table, index_name)} for every index in the public schema."""
    rows = (
        await db.execute(
            text(
                "SELECT tablename, indexname FROM pg_indexes WHERE schemaname = 'public'"
            )
        )
    ).all()
    return {(t, i) for t, i in rows}


async def _actual_foreign_keys(db: AsyncSession) -> set[tuple[str, str, str]]:
    """-> {(table, column, referenced_table)}.

    Compared by shape rather than by constraint name: SQLAlchemy and hand-written
    migrations name constraints differently for the same relationship, so
    matching on names would report drift that does not exist.
    """
    rows = (
        await db.execute(
            text("""
                SELECT tc.table_name, kcu.column_name, ccu.table_name AS referenced
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON kcu.constraint_name = tc.constraint_name
                 AND kcu.table_schema = tc.table_schema
                JOIN information_schema.constraint_column_usage ccu
                  ON ccu.constraint_name = tc.constraint_name
                 AND ccu.table_schema = tc.table_schema
                WHERE tc.constraint_type = 'FOREIGN KEY'
                  AND tc.table_schema = 'public'
            """)
        )
    ).all()
    return {(t, c, r) for t, c, r in rows}


def _truncate_identifier(name: str) -> str:
    """Postgres silently truncates identifiers at 63 bytes.

    Without mirroring that, every ORM index whose generated name is longer
    would be reported as missing forever — a permanent false positive that
    would teach people to ignore this report.
    """
    return name[:63]


async def _run_checks(db: AsyncSession) -> dict[str, Any]:
    expected_tables = {
        name for name in Base.metadata.tables if name not in _KNOWN_NON_ORM_TABLES
    }
    actual_tables = await _actual_tables(db)
    actual_columns = await _actual_columns(db)

    missing_tables = sorted(expected_tables - actual_tables)
    extra_tables = sorted(
        actual_tables - set(Base.metadata.tables) - _KNOWN_NON_ORM_TABLES
    )

    # The killer check: table exists in both, but the ORM knows a column the
    # database does not have. This is exactly what create_all cannot fix and
    # what the entrypoint safety-net has to be told about by hand.
    missing_columns: list[dict[str, Any]] = []
    nullability_mismatch: list[dict[str, Any]] = []
    for table_name, table in Base.metadata.tables.items():
        if table_name in missing_tables or table_name not in actual_tables:
            continue  # already reported as a whole-table miss
        live = actual_columns.get(table_name, {})
        for column in table.columns:
            actual = live.get(column.name)
            if actual is None:
                missing_columns.append(
                    {
                        "table": table_name,
                        "column": column.name,
                        "orm_type": str(column.type)[:60],
                        "orm_nullable": bool(column.nullable),
                        # A NOT NULL column missing from the DB is the more
                        # urgent case: adding it later needs a default or a
                        # backfill, so it cannot be auto-healed blindly.
                        "severity": "high" if not column.nullable else "medium",
                    }
                )
                continue
            # ORM insists NOT NULL, database allows NULL → constraint never
            # landed. Rows may already violate the ORM's assumption.
            if not column.nullable and actual["nullable"]:
                nullability_mismatch.append(
                    {
                        "table": table_name,
                        "column": column.name,
                        "orm": "NOT NULL",
                        "db": "NULLABLE",
                    }
                )

    # Enum drift — the trap called out in the entrypoint safety-net notes: a
    # migration adds a label, the safety-net mirrors columns but not enum
    # values, and the first INSERT with the new label fails at runtime.
    expected_enums = _expected_enums()
    actual_enums = await _actual_enums(db)
    missing_enum_types = sorted(set(expected_enums) - set(actual_enums))
    missing_enum_values: list[dict[str, Any]] = []
    for enum_name, labels in expected_enums.items():
        live_labels = actual_enums.get(enum_name)
        if live_labels is None:
            continue  # already reported as a missing type
        absent = sorted(labels - live_labels)
        if absent:
            missing_enum_values.append({"enum": enum_name, "missing": absent})

    # Indexes — a missing one is invisible until it is a performance incident.
    # The performance audit flagged full scans on candidate_stages as P1; an
    # index that a migration declared but never landed looks exactly like that
    # and nothing else in the stack notices.
    actual_indexes = await _actual_indexes(db)
    actual_index_names = {name for _, name in actual_indexes}
    missing_indexes: list[dict[str, Any]] = []
    for table_name, table in Base.metadata.tables.items():
        if table_name not in actual_tables:
            continue
        for index in table.indexes:
            if not index.name:
                continue
            if _truncate_identifier(index.name) not in actual_index_names:
                missing_indexes.append(
                    {
                        "table": table_name,
                        "index": index.name,
                        "columns": [c.name for c in index.columns],
                        "unique": bool(index.unique),
                    }
                )

    # Foreign keys — a missing one is silent integrity loss: orphaned rows
    # accumulate and only surface much later as "impossible" data.
    actual_fks = await _actual_foreign_keys(db)
    missing_foreign_keys: list[dict[str, Any]] = []
    for table_name, table in Base.metadata.tables.items():
        if table_name not in actual_tables:
            continue
        for fk in table.foreign_keys:
            referenced = fk.column.table.name
            local = fk.parent.name
            if (table_name, local, referenced) not in actual_fks:
                missing_foreign_keys.append(
                    {
                        "table": table_name,
                        "column": local,
                        "references": referenced,
                    }
                )

    return {
        "missing_tables": missing_tables,
        "extra_tables": extra_tables,
        "missing_indexes": sorted(
            missing_indexes, key=lambda r: (r["table"], r["index"])
        ),
        "missing_foreign_keys": sorted(
            missing_foreign_keys, key=lambda r: (r["table"], r["column"])
        ),
        "missing_columns": sorted(
            missing_columns,
            key=lambda r: (r["severity"] != "high", r["table"], r["column"]),
        ),
        "nullability_mismatch": sorted(
            nullability_mismatch, key=lambda r: (r["table"], r["column"])
        ),
        "missing_enum_types": missing_enum_types,
        "missing_enum_values": sorted(missing_enum_values, key=lambda r: r["enum"]),
    }


def _alembic_state_from_code() -> dict[str, Any]:
    """Code-side revision graph. Best-effort: never raises."""
    out: dict[str, Any] = {}
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        # __file__ is <backend>/app/api/admin_schema_drift.py and the migration
        # tree lives at <backend>/alembic — three levels up (api → app →
        # backend). The two-level form works in app/main.py, which sits one
        # directory shallower; copying it here silently resolved to
        # <backend>/app/alembic, ScriptDirectory raised CommandError, and the
        # bare except below turned that into a quiet "code_error" field. The
        # endpoint reported no alembic state at all until a test caught it.
        script_location = str(Path(__file__).resolve().parents[2] / "alembic")
        cfg = Config()
        cfg.set_main_option("script_location", script_location)
        script = ScriptDirectory.from_config(cfg)
        heads = list(script.get_heads())
        out["code_heads"] = heads
        out["code_head_count"] = len(heads)
        # `head` (singular) — used by backup-drill.yml — only resolves when
        # there is exactly one tip.
        out["singular_head_resolves"] = len(heads) == 1
        out["revision_count"] = sum(1 for _ in script.walk_revisions())
    except Exception as exc:  # noqa: BLE001 — diagnostic must never raise
        out["code_error"] = type(exc).__name__
        # Recording only the exception class is what let a plain
        # "path doesn't exist" hide as an opaque `CommandError`. This endpoint
        # is admin-gated and emits schema identifiers only, so the message adds
        # no exposure and saves the next debugging session.
        out["code_error_detail"] = str(exc)[:200]
    return out


@router.get("/schema-drift")
async def schema_drift(
    auth_mode: Annotated[str, Depends(_snapshot_auth)],
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Report what the ORM expects that the live database does not have.

    Read-only. Emits schema identifiers only — never row data.
    """
    started = time.monotonic()
    out: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "query_version": QUERY_VERSION,
        "auth_mode": auth_mode,
    }

    try:
        checks = await asyncio.wait_for(_run_checks(db), timeout=CHECK_TIMEOUT_SECONDS)
        out.update(checks)
        out["summary"] = {
            "missing_tables": len(checks["missing_tables"]),
            "missing_columns": len(checks["missing_columns"]),
            "missing_columns_high": sum(
                1 for c in checks["missing_columns"] if c["severity"] == "high"
            ),
            "nullability_mismatch": len(checks["nullability_mismatch"]),
            "missing_enum_types": len(checks["missing_enum_types"]),
            "missing_enum_values": len(checks["missing_enum_values"]),
            "missing_indexes": len(checks["missing_indexes"]),
            "missing_foreign_keys": len(checks["missing_foreign_keys"]),
            "extra_tables": len(checks["extra_tables"]),
        }
        # The headline: is the live schema able to serve the ORM as written?
        out["schema_satisfies_orm"] = not (
            checks["missing_tables"]
            or checks["missing_columns"]
            or checks["missing_enum_types"]
            or checks["missing_enum_values"]
        )
    except asyncio.TimeoutError:
        out["error"] = "timeout"
    except Exception as exc:  # noqa: BLE001 — diagnostic must not 500
        out["error"] = type(exc).__name__

    # Alembic bookkeeping, so one call answers both "is the schema OK" and
    # "is the migration state coherent".
    alembic: dict[str, Any] = _alembic_state_from_code()
    try:
        rows = (
            (await db.execute(text("SELECT version_num FROM alembic_version")))
            .scalars()
            .all()
        )
        alembic["db_versions"] = list(rows)
    except Exception as exc:  # noqa: BLE001
        alembic["db_error"] = type(exc).__name__
    out["alembic"] = alembic

    out["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    return out
