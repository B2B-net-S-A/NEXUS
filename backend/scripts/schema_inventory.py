#!/usr/bin/env python3
"""Read-only schema-drift inventory: clean migrations vs. entrypoint safety-net.

P1-DB-01 diagnostic. Prod's alembic bookmark is stuck (``0152``) while the code
head is ``0188``; ``backend/entrypoint.sh`` keeps prod's schema alive through a
huge hand-maintained idempotent DDL safety-net plus ``Base.metadata.create_all``,
swallowing any ``alembic upgrade`` error. The open question this tool answers:
**does the safety-net schema agree with the clean-migration schema, or have the
two drifted into different systems?**

It answers that WITHOUT any production access and WITHOUT writing to any real DB,
by building two throwaway schemas locally and diffing their introspected shape:

  * Schema A  — canonical migrations. A fresh empty DB, then
                ``alembic upgrade heads`` (→ 0188). What the migration ledger
                declares.
  * Schema B  — entrypoint safety-net. A fresh empty DB, then the entrypoint's
                schema-construction path: ``Base.metadata.create_all()`` followed
                by the idempotent DDL the entrypoint runs (``_ENUM_STATEMENTS``,
                ``_COLUMN_STATEMENTS`` incl. its CREATE VIEW blocks,
                ``_DATA_STATEMENTS``, ``_CONSTRAINT_STATEMENTS``,
                ``_INDEX_STATEMENTS``) — parsed live from ``entrypoint.sh`` so the
                tool never drifts from the real boot script.

Both schemas are introspected via ``information_schema`` / ``pg_catalog``
(tables, columns+types+nullability+defaults, PK/FK/unique/check constraints,
indexes, enums, views) and diffed object-by-object into four buckets:
``equivalent | only_in_migrations | only_in_safetynet | divergent``.

Ordering note (deliberate): the boot script runs the safety-net DDL *before*
create_all, because on prod the tables already exist. On a FRESH DB that order
is degenerate — every ``ALTER TABLE`` would hit a missing table and skip, so the
safety-net would contribute nothing. This tool therefore runs create_all FIRST,
then layers the idempotent DDL on top, which is exactly the steady-state prod
picture (ORM tables present, hand-DDL patched over them). See ``--help``.

READ-ONLY, PROD-SAFE — enforced and non-negotiable:
  * NEVER runs ``alembic stamp`` and NEVER mutates any migration bookmark.
  * Writes ONLY to the two throwaway build DSNs (``--schema-a-dsn`` /
    ``--schema-b-dsn``), which the caller declares disposable. It refuses to run
    if those two are equal or collide with ``--compare-dump``.
  * ``--compare-dump`` (the future prod hook) is opened strictly read-only —
    only SELECTs, never a write, never a reset. Do NOT point it at prod today.

Future prod hook (``--compare-dump``): once a prod backup restore is available,
pass its DSN (or a restored ``schema.sql``) and the SAME tool diffs the real prod
schema against Schema A — see ``--help`` for the file-vs-DSN handling.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import asyncpg

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BACKEND_DIR = Path(__file__).resolve().parents[1]
EXPECTED_HEAD = "0188_contract_alert_dedup"

# alembic_version is migration bookkeeping, not part of the domain schema; it
# exists only in Schema A and comparing it would be pure noise.
EXCLUDED_TABLES = frozenset({"alembic_version"})

CATEGORIES = ("equivalent", "only_in_migrations", "only_in_safetynet", "divergent")
OBJECT_TYPES = ("tables", "columns", "enums", "indexes", "constraints", "views")


# ---------------------------------------------------------------------------
# DSN helpers
# ---------------------------------------------------------------------------


def to_asyncpg_dsn(dsn: str) -> str:
    """Normalize any accepted DSN form to what ``asyncpg.connect`` expects."""
    return (
        dsn.replace("postgresql+asyncpg://", "postgresql://")
        .replace("postgres+asyncpg://", "postgresql://")
        .replace("postgresql+psycopg2://", "postgresql://")
    )


def to_sqlalchemy_dsn(dsn: str) -> str:
    """Normalize any accepted DSN form to a SQLAlchemy asyncpg URL."""
    apg = to_asyncpg_dsn(dsn)
    return apg.replace("postgresql://", "postgresql+asyncpg://", 1)


def maintenance_dsn(dsn: str, db: str = "postgres") -> str:
    """Same server, different (maintenance) database — for CREATE/DROP DATABASE."""
    apg = to_asyncpg_dsn(dsn)
    return re.sub(r"/[^/?]+(\?|$)", f"/{db}\\1", apg, count=1)


# ---------------------------------------------------------------------------
# Introspection — read-only
# ---------------------------------------------------------------------------


def _norm(sql: str | None) -> str:
    """Collapse whitespace and drop the ``public.`` qualifier for stable diffs."""
    if sql is None:
        return ""
    s = re.sub(r"\s+", " ", sql).strip()
    s = s.replace("public.", "")
    return s


@dataclass(frozen=True)
class SchemaSnapshot:
    """Structured, comparable snapshot of one Postgres schema (public)."""

    tables: dict[str, dict[str, Any]]
    columns: dict[str, dict[str, Any]]
    enums: dict[str, list[str]]
    indexes: dict[str, dict[str, Any]]
    constraints: dict[str, dict[str, Any]]
    views: dict[str, str]

    def counts(self) -> dict[str, int]:
        return {
            "tables": len(self.tables),
            "columns": len(self.columns),
            "enums": len(self.enums),
            "indexes": len(self.indexes),
            "constraints": len(self.constraints),
            "views": len(self.views),
        }


async def introspect(dsn: str) -> SchemaSnapshot:
    """Read the ``public`` schema of ``dsn`` into a :class:`SchemaSnapshot`.

    Pure SELECTs against ``pg_catalog`` — never writes. Safe against prod.
    """
    conn = await asyncpg.connect(to_asyncpg_dsn(dsn))
    try:
        # Tables (base tables only).
        table_rows = await conn.fetch(
            """
            SELECT c.relname AS name
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind = 'r'
            """
        )
        tables = {r["name"]: {} for r in table_rows if r["name"] not in EXCLUDED_TABLES}

        # Columns.
        col_rows = await conn.fetch(
            """
            SELECT c.relname AS table_name,
                   a.attname AS column_name,
                   format_type(a.atttypid, a.atttypmod) AS data_type,
                   a.attnotnull AS not_null,
                   pg_get_expr(ad.adbin, ad.adrelid) AS default_expr
            FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            LEFT JOIN pg_attrdef ad ON ad.adrelid = a.attrelid AND ad.adnum = a.attnum
            WHERE n.nspname = 'public'
              AND c.relkind = 'r'
              AND a.attnum > 0
              AND NOT a.attisdropped
            """
        )
        columns: dict[str, dict[str, Any]] = {}
        for r in col_rows:
            if r["table_name"] in EXCLUDED_TABLES:
                continue
            key = f"{r['table_name']}.{r['column_name']}"
            columns[key] = {
                "table": r["table_name"],
                "column": r["column_name"],
                "data_type": r["data_type"],
                "nullable": not r["not_null"],
                "default": _norm(r["default_expr"]),
            }

        # Enums (labels in sort order).
        enum_rows = await conn.fetch(
            """
            SELECT t.typname AS name, e.enumlabel AS label
            FROM pg_type t
            JOIN pg_enum e ON e.enumtypid = t.oid
            JOIN pg_namespace n ON n.oid = t.typnamespace
            WHERE n.nspname = 'public'
            ORDER BY t.typname, e.enumsortorder
            """
        )
        enums: dict[str, list[str]] = {}
        for r in enum_rows:
            enums.setdefault(r["name"], []).append(r["label"])

        # Constraints (PK/FK/unique/check).
        con_rows = await conn.fetch(
            """
            SELECT con.conname AS name,
                   c.relname AS table_name,
                   con.contype AS contype,
                   con.conindid AS conindid,
                   pg_get_constraintdef(con.oid) AS def
            FROM pg_constraint con
            JOIN pg_class c ON c.oid = con.conrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public'
            """
        )
        contype_label = {
            "p": "primary_key",
            "f": "foreign_key",
            "u": "unique",
            "c": "check",
        }
        constraints: dict[str, dict[str, Any]] = {}
        constraint_index_oids: set[int] = set()
        for r in con_rows:
            if r["table_name"] in EXCLUDED_TABLES:
                continue
            if r["conindid"]:
                constraint_index_oids.add(r["conindid"])
            # ``pg_constraint.contype`` is the internal ``"char"`` type; asyncpg
            # hands it back as a single byte (e.g. b'p'), so decode before lookup.
            contype = r["contype"]
            if isinstance(contype, (bytes, bytearray)):
                contype = contype.decode("ascii")
            constraints[r["name"]] = {
                "table": r["table_name"],
                "type": contype_label.get(contype, contype),
                "definition": _norm(r["def"]),
            }

        # Indexes — exclude those that merely back a PK/unique constraint (already
        # captured above) so the same object is not double-counted.
        idx_rows = await conn.fetch(
            """
            SELECT ic.oid AS index_oid,
                   ic.relname AS index_name,
                   tc.relname AS table_name,
                   pg_get_indexdef(ic.oid) AS def
            FROM pg_index i
            JOIN pg_class ic ON ic.oid = i.indexrelid
            JOIN pg_class tc ON tc.oid = i.indrelid
            JOIN pg_namespace n ON n.oid = ic.relnamespace
            WHERE n.nspname = 'public'
            """
        )
        indexes: dict[str, dict[str, Any]] = {}
        for r in idx_rows:
            if r["table_name"] in EXCLUDED_TABLES:
                continue
            if r["index_oid"] in constraint_index_oids:
                continue
            indexes[r["index_name"]] = {
                "table": r["table_name"],
                "definition": _norm(r["def"]),
            }

        # Views.
        view_rows = await conn.fetch(
            "SELECT viewname AS name, definition FROM pg_views WHERE schemaname = 'public'"
        )
        views = {r["name"]: _norm(r["definition"]) for r in view_rows}

        return SchemaSnapshot(
            tables=tables,
            columns=columns,
            enums=enums,
            indexes=indexes,
            constraints=constraints,
            views=views,
        )
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Reset (throwaway build DBs only)
# ---------------------------------------------------------------------------


async def reset_public_schema(dsn: str) -> None:
    """Drop & recreate the ``public`` schema to guarantee a fresh build target.

    Only ever called on the two throwaway build DSNs — never on ``--compare-dump``.
    """
    conn = await asyncpg.connect(to_asyncpg_dsn(dsn))
    try:
        await conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
        await conn.execute("CREATE SCHEMA public")
        # Postgres 16 revokes CREATE on public from PUBLIC; re-grant so the build
        # user (and create_all) can populate it.
        await conn.execute("GRANT ALL ON SCHEMA public TO public")
        try:
            user = re.search(r"://([^:/@]+)", to_asyncpg_dsn(dsn))
            if user:
                await conn.execute(f'GRANT ALL ON SCHEMA public TO "{user.group(1)}"')
        except Exception:
            pass
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Schema A — canonical migrations
# ---------------------------------------------------------------------------


@dataclass
class SchemaABuild:
    ok: bool
    heads: list[str] = field(default_factory=list)
    stdout_tail: str = ""
    error: str | None = None


def build_schema_a(dsn: str, backend_dir: Path) -> SchemaABuild:
    """``alembic upgrade heads`` against a fresh ``dsn``. Never stamps."""
    env = dict(os.environ)
    env["DATABASE_URL"] = to_sqlalchemy_dsn(dsn)
    env.setdefault(
        "SECRET_KEY", "schema-inventory-tool-ci-secret-key-min-48-chars-xxxxxx"
    )
    proc = subprocess.run(
        ["alembic", "-c", "alembic/alembic.ini", "upgrade", "heads"],
        cwd=str(backend_dir),
        env=env,
        capture_output=True,
        text=True,
    )
    tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-8:])
    if proc.returncode != 0:
        return SchemaABuild(
            ok=False, stdout_tail=tail, error="alembic upgrade heads failed"
        )
    # Read the resulting head(s) straight from the DB — the ground truth.
    return SchemaABuild(ok=True, stdout_tail=tail)


async def read_alembic_heads(dsn: str) -> list[str]:
    conn = await asyncpg.connect(to_asyncpg_dsn(dsn))
    try:
        rows = await conn.fetch("SELECT version_num FROM alembic_version")
        return sorted(r["version_num"] for r in rows)
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Schema B — entrypoint safety-net path
# ---------------------------------------------------------------------------


@dataclass
class CreateAllResult:
    ok: bool
    faithful_ok: bool
    stripped_dangling_fks: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    tables_created: int = 0


async def build_schema_b_create_all(dsn: str, repair_fks: bool) -> CreateAllResult:
    """Run the entrypoint's ``Base.metadata.create_all`` leg against ``dsn``.

    The app is imported LAZILY and only after ``DATABASE_URL`` points at the
    throwaway B target, because ``app.core.database.engine`` binds to the URL at
    import time. We first try create_all exactly as shipped; if it raises (as it
    does on prod — an ORM FK references a table the models never map, so the
    entrypoint's ``|| echo ... continuing`` silently creates ZERO tables), and
    ``repair_fks`` is on, we strip the unresolvable FK constraints (recording
    each) and retry so a meaningful Schema B can still be built and diffed.
    """
    os.environ["DATABASE_URL"] = to_sqlalchemy_dsn(dsn)
    os.environ.setdefault(
        "SECRET_KEY", "schema-inventory-tool-ci-secret-key-min-48-chars-xxxxxx"
    )
    os.environ.setdefault(
        "M365_TOKEN_ENCRYPTION_KEY",
        "0" * 43 + "=",  # any 32-byte urlsafe-b64 value; unused by create_all
    )

    # Ensure ``app`` is importable no matter how the script was invoked
    # (running ``python scripts/schema_inventory.py`` puts scripts/ — not the
    # backend root — on sys.path[0]).
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))

    import app.models  # noqa: F401  (populates Base.metadata)
    from app.core.database import Base, engine

    md = Base.metadata

    async def _run_create_all() -> int:
        async with engine.begin() as conn:
            await conn.run_sync(md.create_all)
        return len(md.tables)

    stripped: list[dict[str, Any]] = []
    try:
        created = await _run_create_all()
        return CreateAllResult(ok=True, faithful_ok=True, tables_created=created)
    except Exception as exc:  # noqa: BLE001 — faithful reproduction of prod
        faithful_error = f"{type(exc).__name__}: {exc}"

    if not repair_fks:
        return CreateAllResult(ok=False, faithful_ok=False, error=faithful_error)

    # Strip FK constraints whose referred table is not mapped in the ORM.
    # ``Table.foreign_keys`` is a *stored* set (not computed from the columns), so
    # a full removal must discard the ForeignKey from THREE places: the owning
    # column's ``foreign_keys``, the table's stored ``foreign_keys``, and the
    # ForeignKeyConstraint from ``table.constraints``. Missing any one leaves
    # create_all's table sort still tripping over the dangling reference.
    defined = set(md.tables.keys())
    for table in list(md.tables.values()):
        for fkc in list(table.foreign_key_constraints):
            try:
                target = list(fkc.elements)[0].target_fullname.rsplit(".", 1)[0]
            except Exception:  # noqa: BLE001
                continue
            if target not in defined:
                stripped.append(
                    {
                        "table": table.name,
                        "missing_target": target,
                        "columns": [c.name for c in fkc.columns],
                    }
                )
                table.constraints.discard(fkc)
                for fk in list(fkc.elements):
                    if fk.parent is not None:
                        fk.parent.foreign_keys.discard(fk)
                    table.foreign_keys.discard(fk)

    try:
        created = await _run_create_all()
    except Exception as exc:  # noqa: BLE001
        return CreateAllResult(
            ok=False,
            faithful_ok=False,
            stripped_dangling_fks=stripped,
            error=f"even after stripping {len(stripped)} FK(s): {type(exc).__name__}: {exc}",
        )
    finally:
        await engine.dispose()

    return CreateAllResult(
        ok=True,
        faithful_ok=False,
        stripped_dangling_fks=stripped,
        error=faithful_error,
        tables_created=created,
    )


def extract_safetynet_statements(entrypoint: Path) -> dict[str, list[str]]:
    """Parse the safety-net statement lists straight out of ``entrypoint.sh``.

    The entrypoint embeds a ``python - <<'PY' ... PY`` heredoc defining
    ``_ENUM_STATEMENTS`` … ``_INDEX_STATEMENTS`` and an ``async def backfill``
    that applies them. We slice the heredoc up to (not including) ``backfill`` —
    that prefix is just imports + the five list literals — and ``exec`` it to
    recover the lists verbatim. Parsing the source (rather than hardcoding a
    copy) keeps this tool in lockstep with the real boot script.
    """
    text = entrypoint.read_text(encoding="utf-8")
    # The opening line carries a trailing `|| echo ...`, and the closing `PY` sits
    # on its own line — hence `[^\n]*` after the marker and an anchored `^PY$`.
    heredocs = re.findall(r"<<'PY'[^\n]*\n(.*?)\n^PY$", text, re.DOTALL | re.MULTILINE)
    block = next((h for h in heredocs if "_ENUM_STATEMENTS" in h), None)
    if block is None:
        raise RuntimeError("could not locate the safety-net heredoc in entrypoint.sh")
    prefix = block.split("async def backfill", 1)[0]
    ns: dict[str, Any] = {}
    exec(compile(prefix, "<entrypoint-safetynet>", "exec"), ns)  # noqa: S102
    return {
        "enums": list(ns.get("_ENUM_STATEMENTS", [])),
        "columns": list(
            ns.get("_COLUMN_STATEMENTS", [])
        ),  # includes CREATE VIEW blocks
        "data": list(ns.get("_DATA_STATEMENTS", [])),
        "constraints": list(ns.get("_CONSTRAINT_STATEMENTS", [])),
        "indexes": list(ns.get("_INDEX_STATEMENTS", [])),
    }


async def apply_safetynet(
    dsn: str, statements: dict[str, list[str]]
) -> dict[str, dict[str, int]]:
    """Apply the extracted DDL with the entrypoint's exact per-statement skip
    semantics (idempotent; a failure on one statement is recorded, not fatal).

    Runs in autocommit (plain connection, no surrounding transaction) so that
    ``ALTER TYPE ... ADD VALUE`` and ``CREATE INDEX CONCURRENTLY`` behave as they
    do at boot.
    """
    conn = await asyncpg.connect(to_asyncpg_dsn(dsn))
    outcome: dict[str, dict[str, int]] = {}
    try:
        for group in ("enums", "columns", "data", "constraints", "indexes"):
            applied = skipped = 0
            for stmt in statements.get(group, []):
                try:
                    await conn.execute(stmt)
                    applied += 1
                except Exception:  # noqa: BLE001 — mirrors entrypoint's try/except
                    skipped += 1
            outcome[group] = {"applied": applied, "skipped": skipped}
    finally:
        await conn.close()
    return outcome


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------


def _diff_mapping(
    a: dict[str, Any],
    b: dict[str, Any],
    equal: Any,
    detail: Any,
) -> dict[str, list[Any]]:
    """Generic key-based diff into the four buckets."""
    result: dict[str, list[Any]] = {c: [] for c in CATEGORIES}
    for key in sorted(set(a) | set(b)):
        in_a, in_b = key in a, key in b
        if in_a and not in_b:
            result["only_in_migrations"].append(key)
        elif in_b and not in_a:
            result["only_in_safetynet"].append(key)
        elif equal(a[key], b[key]):
            result["equivalent"].append(key)
        else:
            result["divergent"].append({"object": key, **detail(a[key], b[key])})
    return result


def _reconcile_by_definition(
    diff: dict[str, list[Any]],
    a: dict[str, dict[str, Any]],
    b: dict[str, dict[str, Any]],
    def_key: str,
) -> None:
    """Second pass for named objects (indexes/constraints): re-pair leftovers
    whose definitions match modulo their name, reclassifying name-only drift as
    ``divergent`` instead of a misleading only_in_* pair.
    """

    def norm_def(name: str, obj: dict[str, Any]) -> str:
        return obj[def_key].replace(name, "<name>")

    only_mig = {k: norm_def(k, a[k]) for k in diff["only_in_migrations"]}
    only_saf = {k: norm_def(k, b[k]) for k in diff["only_in_safetynet"]}
    saf_by_def: dict[str, str] = {}
    for k, d in only_saf.items():
        saf_by_def.setdefault(d, k)

    matched_mig: set[str] = set()
    matched_saf: set[str] = set()
    for mk, md in only_mig.items():
        sk = saf_by_def.get(md)
        if sk is not None and sk not in matched_saf:
            matched_mig.add(mk)
            matched_saf.add(sk)
            diff["divergent"].append(
                {
                    "object": mk,
                    "kind": "name_only",
                    "migrations_name": mk,
                    "safetynet_name": sk,
                    "definition": a[mk][def_key],
                }
            )
    diff["only_in_migrations"] = [
        k for k in diff["only_in_migrations"] if k not in matched_mig
    ]
    diff["only_in_safetynet"] = [
        k for k in diff["only_in_safetynet"] if k not in matched_saf
    ]


def diff_schemas(
    a: SchemaSnapshot, b: SchemaSnapshot
) -> dict[str, dict[str, list[Any]]]:
    """Full object-by-object diff. Left = migrations (A), right = safety-net (B)."""
    diff: dict[str, dict[str, list[Any]]] = {}

    diff["tables"] = _diff_mapping(
        a.tables, b.tables, lambda x, y: True, lambda x, y: {}
    )

    def col_eq(x: dict[str, Any], y: dict[str, Any]) -> bool:
        return (
            x["data_type"] == y["data_type"]
            and x["nullable"] == y["nullable"]
            and x["default"] == y["default"]
        )

    def col_detail(x: dict[str, Any], y: dict[str, Any]) -> dict[str, Any]:
        fields = {}
        for f in ("data_type", "nullable", "default"):
            if x[f] != y[f]:
                fields[f] = {"migrations": x[f], "safetynet": y[f]}
        return {"differences": fields}

    diff["columns"] = _diff_mapping(a.columns, b.columns, col_eq, col_detail)

    def enum_detail(x: list[str], y: list[str]) -> dict[str, Any]:
        # Label order is semantically meaningful in Postgres (ORDER BY / range
        # comparisons on the enum), so equal *sets* in a different order still
        # count as divergent — spell out which case it is.
        same_set = set(x) == set(y)
        detail: dict[str, Any] = {
            "only_in_migrations_labels": sorted(set(x) - set(y)),
            "only_in_safetynet_labels": sorted(set(y) - set(x)),
            "order_differs": same_set and x != y,
        }
        if same_set and x != y:
            detail["migrations_order"] = x
            detail["safetynet_order"] = y
        return detail

    diff["enums"] = _diff_mapping(a.enums, b.enums, lambda x, y: x == y, enum_detail)

    diff["indexes"] = _diff_mapping(
        a.indexes,
        b.indexes,
        lambda x, y: x["definition"] == y["definition"],
        lambda x, y: {"migrations": x["definition"], "safetynet": y["definition"]},
    )
    _reconcile_by_definition(diff["indexes"], a.indexes, b.indexes, "definition")

    diff["constraints"] = _diff_mapping(
        a.constraints,
        b.constraints,
        lambda x, y: x["type"] == y["type"] and x["definition"] == y["definition"],
        lambda x, y: {
            "migrations": {"type": x["type"], "definition": x["definition"]},
            "safetynet": {"type": y["type"], "definition": y["definition"]},
        },
    )
    _reconcile_by_definition(
        diff["constraints"], a.constraints, b.constraints, "definition"
    )

    diff["views"] = _diff_mapping(
        a.views,
        b.views,
        lambda x, y: x == y,
        lambda x, y: {"migrations": x, "safetynet": y},
    )
    return diff


def summarize(diff: dict[str, dict[str, list[Any]]]) -> dict[str, dict[str, int]]:
    return {
        obj: {cat: len(diff[obj][cat]) for cat in CATEGORIES} for obj in OBJECT_TYPES
    }


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------


def render_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(
        "# Schema drift inventory — clean migrations vs. entrypoint safety-net"
    )
    lines.append("")
    lines.append(f"_Generated: {report['generated_at']} — READ-ONLY, no prod access._")
    lines.append("")

    a = report["schema_a"]
    b = report["schema_b"]
    lines.append("## Build status")
    lines.append("")
    lines.append(
        f"- **Schema A (migrations)**: {'built' if a['build_ok'] else 'FAILED'} — "
        f"heads = `{', '.join(a['alembic_heads']) or 'none'}` "
        f"(expected single head `{report['expected_head']}`: "
        f"{'OK' if a['single_expected_head'] else 'MISMATCH'})."
    )
    ca = b["create_all"]
    lines.append(
        f"- **Schema B (safety-net)**: create_all faithful={ca['faithful_ok']}, "
        f"usable={ca['ok']}, tables_created={ca['tables_created']}."
    )
    if not ca["faithful_ok"]:
        lines.append(
            f"  - :warning: **The entrypoint's `Base.metadata.create_all()` leg is "
            f"non-functional as shipped** — it raises `{ca['error']}`. At boot the "
            f"`|| echo ... continuing` swallows it, so on a genuinely fresh DB "
            f"(new env / DR restore) create_all creates ZERO tables; only the "
            f"migration chain (Schema A) can rebuild the schema."
        )
        for s in ca["stripped_dangling_fks"]:
            lines.append(
                f"  - stripped unresolvable FK to build a diffable Schema B: "
                f"`{s['table']}({', '.join(s['columns'])})` → missing table "
                f"`{s['missing_target']}`."
            )
    sn = b["safetynet_apply"]
    if sn:
        applied = ", ".join(
            f"{g}={v['applied']}/{v['applied'] + v['skipped']}" for g, v in sn.items()
        )
        lines.append(f"  - safety-net DDL applied (applied/total): {applied}.")
    lines.append("")

    lines.append("## Object counts")
    lines.append("")
    lines.append("| object | migrations (A) | safety-net (B) |")
    lines.append("|---|---:|---:|")
    for obj in OBJECT_TYPES:
        lines.append(f"| {obj} | {a['counts'][obj]} | {b['counts'][obj]} |")
    lines.append("")

    lines.append("## Diff summary (A = migrations, B = safety-net)")
    lines.append("")
    lines.append(
        "| object | equivalent | only in migrations | only in safety-net | divergent |"
    )
    lines.append("|---|---:|---:|---:|---:|")
    s = report["summary"]
    for obj in OBJECT_TYPES:
        lines.append(
            f"| {obj} | {s[obj]['equivalent']} | {s[obj]['only_in_migrations']} "
            f"| {s[obj]['only_in_safetynet']} | {s[obj]['divergent']} |"
        )
    lines.append("")

    diff = report["diff"]
    for obj in OBJECT_TYPES:
        blocks = []
        for cat in ("only_in_migrations", "only_in_safetynet", "divergent"):
            items = diff[obj][cat]
            if items:
                blocks.append((cat, items))
        if not blocks:
            continue
        lines.append(f"### {obj}")
        lines.append("")
        for cat, items in blocks:
            lines.append(f"**{cat}** ({len(items)}):")
            lines.append("")
            for item in items[:200]:
                if isinstance(item, str):
                    lines.append(f"- `{item}`")
                else:
                    lines.append(
                        f"- `{item.get('object', '?')}` — "
                        f"{json.dumps({k: v for k, v in item.items() if k != 'object'}, ensure_ascii=False)}"
                    )
            if len(items) > 200:
                lines.append(f"- … and {len(items) - 200} more (see JSON report)")
            lines.append("")

    if report.get("compare_dump"):
        cd = report["compare_dump"]
        lines.append("## Compare-dump (external schema vs. migrations A)")
        lines.append("")
        lines.append(f"Source: `{cd['source']}`")
        lines.append("")
        lines.append(
            "| object | equivalent | only in migrations | only in external | divergent |"
        )
        lines.append("|---|---:|---:|---:|---:|")
        for obj in OBJECT_TYPES:
            cs = cd["summary"][obj]
            lines.append(
                f"| {obj} | {cs['equivalent']} | {cs['only_in_migrations']} "
                f"| {cs['only_in_safetynet']} | {cs['divergent']} |"
            )
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


async def run(args: argparse.Namespace) -> dict[str, Any]:
    backend_dir = Path(args.backend_dir).resolve()
    a_dsn, b_dsn = args.schema_a_dsn, args.schema_b_dsn

    # Read-only / safety guardrails.
    if to_asyncpg_dsn(a_dsn) == to_asyncpg_dsn(b_dsn):
        raise SystemExit(
            "refusing to run: --schema-a-dsn and --schema-b-dsn are the same DB"
        )
    if args.compare_dump and "://" in args.compare_dump:
        cd = to_asyncpg_dsn(args.compare_dump)
        if cd in (to_asyncpg_dsn(a_dsn), to_asyncpg_dsn(b_dsn)):
            raise SystemExit(
                "refusing to run: --compare-dump collides with a throwaway build DSN"
            )

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "expected_head": args.expected_head,
        "read_only": True,
        "ordering_note": "Schema B builds create_all FIRST, then layers safety-net DDL (see module docstring).",
    }

    build = args.build
    do_a = build in ("both", "a")
    do_b = build in ("both", "b")

    # --- Schema A ---------------------------------------------------------
    if do_a:
        if args.reset:
            await reset_public_schema(a_dsn)
        a_build = build_schema_a(a_dsn, backend_dir)
        heads = await read_alembic_heads(a_dsn) if a_build.ok else []
    else:
        a_build = SchemaABuild(ok=True, stdout_tail="(build skipped)")
        heads = await read_alembic_heads(a_dsn)

    # --- Schema B ---------------------------------------------------------
    if do_b:
        if args.reset:
            await reset_public_schema(b_dsn)
        create_all = await build_schema_b_create_all(
            b_dsn, repair_fks=args.repair_dangling_fks
        )
        statements = extract_safetynet_statements(backend_dir / "entrypoint.sh")
        safetynet = await apply_safetynet(b_dsn, statements)
    else:
        create_all = CreateAllResult(ok=True, faithful_ok=True)
        safetynet = {}

    # --- Introspect + diff ------------------------------------------------
    snap_a = await introspect(a_dsn)
    snap_b = await introspect(b_dsn)
    diff = diff_schemas(snap_a, snap_b)

    report["schema_a"] = {
        "build_ok": a_build.ok,
        "alembic_heads": heads,
        "single_expected_head": heads == [args.expected_head],
        "stdout_tail": a_build.stdout_tail,
        "counts": snap_a.counts(),
    }
    report["schema_b"] = {
        "create_all": {
            "ok": create_all.ok,
            "faithful_ok": create_all.faithful_ok,
            "tables_created": create_all.tables_created,
            "stripped_dangling_fks": create_all.stripped_dangling_fks,
            "error": create_all.error,
        },
        "safetynet_apply": safetynet,
        "counts": snap_b.counts(),
    }
    report["summary"] = summarize(diff)
    report["diff"] = diff

    # --- Optional future prod hook: compare an external schema vs. A -------
    if args.compare_dump:
        report["compare_dump"] = await _compare_dump(args.compare_dump, snap_a)

    return report


async def _compare_dump(source: str, snap_a: SchemaSnapshot) -> dict[str, Any]:
    """READ-ONLY diff of an external schema (a live DSN) against Schema A.

    The intended future use: after a prod backup restore exists, pass its DSN and
    this reuses the exact same introspection + diff to quantify prod-vs-canonical
    drift. A ``.sql`` file cannot be introspected directly — restore it into a
    throwaway DB first and pass THAT DSN here. This path NEVER writes.
    """
    if "://" not in source:
        return {
            "source": source,
            "error": (
                "a .sql dump cannot be introspected directly — restore it into a "
                "throwaway database and pass that DSN to --compare-dump instead"
            ),
        }
    snap_ext = await introspect(source)  # SELECT-only
    diff = diff_schemas(snap_a, snap_ext)
    return {
        "source": re.sub(r"://[^@/]+@", "://***@", source),  # redact credentials
        "counts": snap_ext.counts(),
        "summary": summarize(diff),
        "diff": diff,
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="schema_inventory.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    p.add_argument(
        "--schema-a-dsn",
        required=True,
        help="throwaway DB for canonical migrations (WRITTEN TO)",
    )
    p.add_argument(
        "--schema-b-dsn",
        required=True,
        help="throwaway DB for the safety-net path (WRITTEN TO)",
    )
    p.add_argument(
        "--reset",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="drop+recreate the public schema on A and B before building (throwaway only)",
    )
    p.add_argument(
        "--build",
        choices=("both", "a", "b", "none"),
        default="both",
        help="which schemas to build before introspecting (default: both)",
    )
    p.add_argument(
        "--repair-dangling-fks",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "when create_all fails on an ORM FK to an unmapped table, strip that FK "
            "(recording it) and retry so a diffable Schema B can be built"
        ),
    )
    p.add_argument(
        "--compare-dump",
        default=None,
        metavar="DSN|schema.sql",
        help=(
            "FUTURE PROD HOOK (read-only): diff an external schema against Schema A. "
            "Pass a live DSN to introspect it directly; a .sql file must first be "
            "restored into a throwaway DB and its DSN passed here. NEVER point this "
            "at prod today."
        ),
    )
    p.add_argument("--out-dir", default=str(BACKEND_DIR / "scripts" / "out"))
    p.add_argument("--backend-dir", default=str(BACKEND_DIR))
    p.add_argument("--expected-head", default=EXPECTED_HEAD)
    p.add_argument("--json-only", action="store_true", help="write/print only JSON")
    p.add_argument(
        "--markdown-only", action="store_true", help="write/print only Markdown"
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = asyncio.run(run(args))

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "schema_inventory.json"
    md_path = out_dir / "schema_inventory.md"
    markdown = render_markdown(report)

    if not args.markdown_only:
        json_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    if not args.json_only:
        md_path.write_text(markdown, encoding="utf-8")

    # Human summary to stdout.
    if args.json_only:
        print(json.dumps(report["summary"], indent=2, ensure_ascii=False))
    else:
        print(markdown)
    print(f"\n[schema_inventory] wrote {json_path} and {md_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
