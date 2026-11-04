"""Explicit, field-level staging promotion. Never a database synchronization.

A versioned, repository-authored recipe registry defines every permitted table,
field, operation and domain hook. The initial built-in covers client descriptions;
other modules require reviewed recipes, never arbitrary imports or dump restores.
Artifacts contain personal/business data and must stay outside repositories.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import stat
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from uuid import UUID
from pathlib import Path
from typing import Any

from sqlalchemy import (
    MetaData,
    Table,
    Text,
    bindparam,
    cast,
    func,
    inspect,
    null,
    select,
    text,
    update,
)
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.services import staging_promotion_recipes as recipes

VERSION = 1
POLICY_VERSION = "reviewed-recipes-v1"
MAX_RECORDS = 100
MAX_BYTES = 2_000_000
PREVIEW_TTL_SECONDS = 900
# Backwards-compatible descriptive alias for callers/tests; actual scope comes
# from each artifact's exact registered recipe identity, not this constant.
CLIENT_GUARDS = {
    "hidden": False,
    "merged_into_client_id": None,
    "archived_at": None,
    "deleted_at": None,
}
RECORD_KEYS = {"recipe", "table", "pk", "fields", "operation"}
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class PromotionError(ValueError):
    """Public errors contain machine codes, never row values or DB exceptions."""


class ConflictError(PromotionError):
    def __init__(self, conflicts: list[dict[str, Any]]):
        self.conflicts = conflicts
        super().__init__("promotion_conflict")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp() -> str:
    return _now().isoformat()


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (ValueError, TypeError) as exc:
        raise PromotionError("invalid_json_value") from exc


def digest(value: dict) -> str:
    """Canonical digest excludes only the artifact's own top-level digest."""
    return hashlib.sha256(
        _canonical({k: v for k, v in value.items() if k != "digest"})
    ).hexdigest()


def _seal(value: dict) -> dict:
    value["digest"] = digest(value)
    return value


def _keys(value: Any, required: set[str], optional: set[str] | None = None) -> None:
    if (
        not isinstance(value, dict)
        or not required <= value.keys()
        or value.keys() - required - (optional or set())
    ):
        raise PromotionError("invalid_artifact_shape")


def _check_artifact(value: dict, kind: str, keys: set[str]) -> None:
    _keys(value, {"version", "policy", "kind", "created_at", "digest"} | keys)
    if (
        value["version"] != VERSION
        or value["policy"] != POLICY_VERSION
        or value["kind"] != kind
    ):
        raise PromotionError("unsupported_artifact")
    if (
        not isinstance(value["digest"], str)
        or not DIGEST_RE.fullmatch(value["digest"])
        or value["digest"] != digest(value)
    ):
        raise PromotionError("artifact_digest_mismatch")
    _parse_time(value["created_at"])


def _parse_time(value: Any) -> datetime:
    try:
        result = datetime.fromisoformat(value)
        if result.tzinfo is None:
            raise ValueError
        return result.astimezone(timezone.utc)
    except (TypeError, ValueError) as exc:
        raise PromotionError("invalid_timestamp") from exc


def _envelope(kind: str, **values: Any) -> dict:
    return {
        "version": VERSION,
        "policy": POLICY_VERSION,
        "kind": kind,
        "created_at": _stamp(),
        **values,
    }


def _recipe(record: dict, *, require_bound: bool = False):
    identity = record.get("recipe")
    if identity is None:
        if require_bound or record.get("table") != "clients":
            raise PromotionError("registered_recipe_required")
        identity = "client-descriptions"
    recipe_id = identity.get("id") if isinstance(identity, dict) else identity
    if not isinstance(recipe_id, str):
        raise PromotionError("registered_recipe_required")
    try:
        recipe = recipes.get_recipe(recipe_id)
        if isinstance(identity, dict):
            recipe.validate_policy(identity)
        elif require_bound:
            raise PromotionError("bound_recipe_identity_required")
    except recipes.RecipeError as exc:
        raise PromotionError("recipe_not_registered_or_policy_changed") from exc
    if record.get("table") != recipe.table or recipe.primary_key != ("id",):
        raise PromotionError("recipe_table_or_primary_key_mismatch")
    return recipe


def list_recipes() -> list[dict]:
    """Safe discoverability: policy declarations only, no database access."""
    return recipes.list_recipes()


def validate_selection(selection: dict, *, require_bound: bool = False) -> list[dict]:
    _keys(selection, {"version", "records"})
    if (
        selection["version"] != VERSION
        or not isinstance(selection["records"], list)
        or not 1 <= len(selection["records"]) <= MAX_RECORDS
    ):
        raise PromotionError("invalid_selection")
    found, records = set(), []
    for item in selection["records"]:
        _keys(item, {"table", "pk", "fields"}, {"operation", "recipe"})
        if not isinstance(item["table"], str):
            raise PromotionError("table_not_allowed")
        recipe = _recipe(item, require_bound=require_bound)
        operation = item.get("operation", "update")
        if operation not in recipe.operations or operation not in {"update", "insert"}:
            raise PromotionError("operation_requires_domain_handler")
        if operation == "insert" and recipe.insert_handler is None:
            raise PromotionError("insert_requires_domain_handler")
        _keys(item["pk"], {"id"})
        pk = item["pk"]["id"]
        if type(pk) is not int or not 0 < pk < 2**63:
            raise PromotionError("invalid_primary_key")
        fields = item["fields"]
        if (
            not isinstance(fields, list)
            or not fields
            or any(not isinstance(f, str) or f not in recipe.fields for f in fields)
        ):
            raise PromotionError("field_not_allowed")
        if operation == "insert" and not {
            f for f, policy in recipe.fields.items() if policy.required_for_insert
        } <= set(fields):
            raise PromotionError("insert_required_fields_missing")
        if len(set(fields)) != len(fields) or (recipe.table, pk) in found:
            raise PromotionError("duplicate_selection")
        found.add((recipe.table, pk))
        records.append(
            {
                "recipe": recipe.policy_id,
                "table": recipe.table,
                "pk": {"id": pk},
                "fields": sorted(fields),
                "operation": operation,
            }
        )
    return sorted(records, key=lambda record: (record["table"], record["pk"]["id"]))


def validate_source_url(url: str | URL) -> URL:
    parsed = make_url(url)
    if parsed.drivername != "postgresql+asyncpg" or not parsed.host or parsed.query:
        raise PromotionError("source_must_be_local_staging")
    try:
        local = (
            parsed.host == "localhost" or ipaddress.ip_address(parsed.host).is_loopback
        )
    except ValueError:
        local = parsed.host == "localhost"
    if not local or not re.fullmatch(
        r"nexus_staging_[a-zA-Z0-9_]+", parsed.database or ""
    ):
        raise PromotionError("source_must_be_local_staging")
    return parsed


def _schema_shape(tables: dict[str, Table]) -> list[dict]:
    """Stable metadata only; never serialize data values or expose schema SQL."""
    result = []
    for name, table in sorted(tables.items()):
        columns = []
        for column in table.columns:
            columns.append(
                {
                    "name": column.name,
                    "type": str(column.type),
                    "enum": list(getattr(column.type, "enums", []) or []),
                    "nullable": column.nullable,
                    "primary_key": column.primary_key,
                    "default": str(getattr(column.server_default, "arg", None))
                    if column.server_default is not None
                    else None,
                    "computed": str(column.computed.sqltext)
                    if column.computed is not None
                    else None,
                }
            )
        constraints = []
        for constraint in table.constraints:
            constraints.append(
                {
                    "kind": type(constraint).__name__,
                    "name": constraint.name,
                    "columns": list(constraint.columns.keys()),
                    "sql": str(getattr(constraint, "sqltext", "")),
                    "foreign_keys": sorted(
                        element.target_fullname
                        for element in getattr(constraint, "elements", [])
                    ),
                    "ondelete": getattr(constraint, "ondelete", None),
                    "onupdate": getattr(constraint, "onupdate", None),
                    "deferrable": getattr(constraint, "deferrable", None),
                    "initially": getattr(constraint, "initially", None),
                }
            )
        indexes = [
            {
                "name": index.name,
                "unique": index.unique,
                "expressions": [str(expression) for expression in index.expressions],
                "dialect_options": {
                    key: str(value)
                    for key, value in sorted(index.dialect_kwargs.items())
                },
            }
            for index in table.indexes
        ]
        result.append(
            {
                "table": name,
                "columns": columns,
                "constraints": sorted(constraints, key=lambda item: _canonical(item)),
                "indexes": sorted(indexes, key=lambda item: _canonical(item)),
            }
        )
    return result


async def _binding(conn: AsyncConnection, tables: dict[str, Table]) -> str:
    if conn.dialect.name != "postgresql":
        raise PromotionError("postgresql_required")
    row = (
        await conn.execute(
            text(
                "SELECT current_database(), (SELECT oid FROM pg_database WHERE datname = current_database()), current_schema(), inet_server_addr()::text, inet_server_port()"
            )
        )
    ).one()
    schema = row[2]
    has_alembic = await conn.run_sync(
        lambda sync: inspect(sync).has_table("alembic_version", schema=schema)
    )
    heads = []
    if has_alembic:
        bookmark = await conn.run_sync(
            lambda sync: Table(
                "alembic_version", MetaData(), schema=schema, autoload_with=sync
            )
        )
        heads = list(
            (
                await conn.execute(
                    select(bookmark.c.version_num).order_by(bookmark.c.version_num)
                )
            ).scalars()
        )
    url = conn.engine.url
    # Both the actual server/DB/schema and schema/migration state are approved.
    # A migration between preview and apply invalidates the target fingerprint.
    return hashlib.sha256(
        _canonical(
            {
                "endpoint": [
                    url.host,
                    url.port or 5432,
                    url.database,
                    url.username,
                    *row,
                ],
                "schema": _schema_shape(tables),
                "alembic_heads": heads,
            }
        )
    ).hexdigest()


async def _tables(conn: AsyncConnection, names: set[str]) -> dict[str, Table]:
    def reflect(sync):
        schema = sync.scalar(text("SELECT current_schema()"))
        if not schema:
            raise PromotionError("missing_schema")
        metadata = MetaData()
        result = {
            name: Table(name, metadata, schema=schema, autoload_with=sync)
            for name in sorted(names)
        }
        for name, table in result.items():
            if list(table.primary_key.columns.keys()) != ["id"]:
                raise PromotionError("unexpected_primary_key")
        return result

    return await conn.run_sync(reflect)


def _decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise PromotionError("nonfinite_decimal_not_allowed")
    # Decimal.normalize() obeys the process precision context and can round.
    # Formatting preserves every digit, even beyond the default 28-digit context.
    result = format(value, "f")
    if "." in result:
        result = result.rstrip("0").rstrip(".")
    return "0" if result in {"-0", ""} else result


def _json_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PromotionError("duplicate_json_key")
        result[key] = value
    return result


def _exact_json_load(value: str):
    def reject_constant(_):
        raise PromotionError("nonfinite_json_not_allowed")

    try:
        return json.loads(
            value,
            parse_float=Decimal,
            parse_constant=reject_constant,
            object_pairs_hook=_json_pairs,
        )
    except (ValueError, TypeError, RecursionError) as exc:
        raise PromotionError("invalid_exact_json") from exc


def _exact_json_dump(value: Any, depth: int = 0) -> str:
    if depth > 32:
        raise PromotionError("json_nesting_limit")
    if value is recipes.JSON_NULL:
        return "null"
    if value is None or type(value) in {bool, int, str}:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, Decimal):
        return _decimal_text(value)
    if isinstance(value, list):
        return "[" + ",".join(_exact_json_dump(item, depth + 1) for item in value) + "]"
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return (
            "{"
            + ",".join(
                json.dumps(key, ensure_ascii=False)
                + ":"
                + _exact_json_dump(value[key], depth + 1)
                for key in sorted(value)
            )
            + "}"
        )
    raise PromotionError("json_requires_exact_json_safe_values")


def encode_value(policy, value: Any, *, json_from_database: bool = False) -> Any:
    kind = policy.kind
    database_json_document = kind == "json" and json_from_database and value is not None
    if database_json_document:
        value = _exact_json_load(value)
        if value is None:
            value = recipes.JSON_NULL
    try:
        policy.validate(value)
    except recipes.RecipeError as exc:
        raise PromotionError("invalid_recipe_field_value") from exc
    if (value is None and not database_json_document) or kind in {
        "string",
        "integer",
        "boolean",
    }:
        return value
    if kind == "decimal":
        encoded = _decimal_text(value)
    elif kind == "date":
        encoded = value.isoformat()
    elif kind == "datetime":
        encoded = value.astimezone(timezone.utc).isoformat()
    elif kind == "uuid":
        encoded = str(value)
    elif kind == "json":
        encoded = _exact_json_dump(value)
    else:
        raise PromotionError("unsupported_recipe_codec")
    return {"$nexus_type": kind, "value": encoded}


def decode_value(policy, wire: Any) -> Any:
    kind = policy.kind
    if wire is None or kind in {"string", "integer", "boolean"}:
        native = wire
    else:
        _keys(wire, {"$nexus_type", "value"})
        if wire["$nexus_type"] != kind or not isinstance(wire["value"], str):
            raise PromotionError("invalid_typed_wire_value")
        try:
            value = wire["value"]
            if kind == "decimal":
                native = Decimal(value)
            elif kind == "date":
                native = date.fromisoformat(value)
            elif kind == "datetime":
                native = datetime.fromisoformat(value)
            elif kind == "uuid":
                native = UUID(value)
            elif kind == "json":
                native = _exact_json_load(value)
                if native is None:
                    native = recipes.JSON_NULL
            else:
                raise PromotionError("unsupported_recipe_codec")
        except (ValueError, TypeError, InvalidOperation) as exc:
            raise PromotionError("invalid_typed_wire_value") from exc
    if kind == "json" and wire is not None:
        try:
            policy.validate(native)
        except recipes.RecipeError as exc:
            raise PromotionError("invalid_recipe_field_value") from exc
        canonical = {"$nexus_type": "json", "value": _exact_json_dump(native)}
    else:
        canonical = encode_value(policy, native)
    if canonical != wire:
        raise PromotionError("noncanonical_typed_wire_value")
    return native


def _decoded_values(record: dict, values: dict) -> dict:
    recipe = _recipe(record)
    return {
        field: decode_value(recipe.fields[field], wire)
        for field, wire in values.items()
    }


def _values(record: dict, value: Any) -> dict:
    if not isinstance(value, dict) or set(value) != set(record["fields"]):
        raise PromotionError("invalid_field_projection")
    try:
        _recipe(record).validate_values(
            _decoded_values(record, value), for_insert=record["operation"] == "insert"
        )
    except recipes.RecipeError as exc:
        raise PromotionError("invalid_recipe_field_value") from exc
    return value


def _db_values(record: dict, table: Table) -> dict:
    recipe = _recipe(record)
    result = _decoded_values(record, record["desired_after"])
    for field in result:
        if recipe.fields[field].kind == "json":
            wire = record["desired_after"][field]
            # JSONB's default none_as_null=False turns Python None into JSON
            # null. SQL NULL therefore needs an explicit SQL NULL expression.
            result[field] = (
                null()
                if wire is None
                else cast(
                    bindparam(None, wire["value"], type_=Text()), table.c[field].type
                )
            )
    return result


async def _read(
    conn: AsyncConnection, table: Table, record: dict, lock: bool = False
) -> dict | None:
    fields = sorted(set(record["fields"]) | set(_recipe(record).lifecycle))
    if not set(fields) <= set(table.columns.keys()):
        raise PromotionError("missing_promoted_or_lifecycle_column")
    recipe = _recipe(record)
    projections = [
        cast(table.c[field], Text()).label(field)
        if field in recipe.fields and recipe.fields[field].kind == "json"
        else table.c[field]
        for field in fields
    ]
    query = select(*projections).where(table.c.id == record["pk"]["id"])
    if lock:
        query = query.with_for_update()
    row = (await conn.execute(query)).mappings().one_or_none()
    if row is None:
        return None
    result = dict(row)
    for field in record["fields"]:
        policy = recipe.fields[field]
        result[field] = encode_value(
            policy, result[field], json_from_database=policy.kind == "json"
        )
    return result


def _writable(row: dict | None, record: dict) -> bool:
    return row is not None and all(
        row[field] == expected for field, expected in _recipe(record).lifecycle.items()
    )


async def snapshot(conn: AsyncConnection, selection: dict) -> dict:
    """Capture a pre-edit local baseline; no write or implicit DB commit."""
    validate_source_url(conn.engine.url)
    records = validate_selection(selection)
    tables = await _tables(conn, {r["table"] for r in records})
    before = []
    for record in records:
        row = await _read(conn, tables[record["table"]], record)
        if record["operation"] == "insert":
            if row is not None:
                raise PromotionError("insert_source_baseline_requires_absence")
            values = None
        else:
            if not _writable(row, record):
                raise PromotionError("source_record_missing_or_not_writable")
            values = _values(record, {field: row[field] for field in record["fields"]})
        before.append({**record, "expected_before": values})
    return _seal(
        _envelope(
            "baseline", source_binding=await _binding(conn, tables), records=before
        )
    )


def _validate_baseline(baseline: dict) -> list[dict]:
    _check_artifact(baseline, "baseline", {"source_binding", "records"})
    if not isinstance(baseline["records"], list):
        raise PromotionError("invalid_selection")
    selection = {"version": VERSION, "records": []}
    for record in baseline["records"]:
        _keys(record, RECORD_KEYS | {"expected_before"})
        selection["records"].append({key: record[key] for key in RECORD_KEYS})
    records = validate_selection(selection, require_bound=True)
    if selection["records"] != records:
        raise PromotionError("noncanonical_selection")
    for item in baseline["records"]:
        if item["operation"] == "insert":
            if item["expected_before"] is not None:
                raise PromotionError("insert_baseline_must_be_absent")
        else:
            _values(item, item["expected_before"])
    return records


async def package(conn: AsyncConnection, baseline: dict) -> dict:
    """Compare the same local source to baseline; omit unchanged fields/rows."""
    validate_source_url(conn.engine.url)
    records = _validate_baseline(baseline)
    tables = await _tables(conn, {r["table"] for r in records})
    if await _binding(conn, tables) != baseline["source_binding"]:
        raise PromotionError("source_binding_mismatch")
    changes = []
    for record, initial in zip(records, baseline["records"]):
        row = await _read(conn, tables[record["table"]], record)
        if not _writable(row, record):
            raise PromotionError("source_record_missing_or_not_writable")
        fields = (
            record["fields"]
            if record["operation"] == "insert"
            else [
                field
                for field in record["fields"]
                if row[field] != initial["expected_before"][field]
            ]
        )
        if fields:
            operation = {**record, "fields": fields}
            after = _values(operation, {field: row[field] for field in fields})
            changes.append(
                {
                    **operation,
                    "expected_before": None
                    if record["operation"] == "insert"
                    else {field: initial["expected_before"][field] for field in fields},
                    "desired_after": after,
                }
            )
    return _seal(
        _envelope(
            "package",
            baseline_digest=baseline["digest"],
            source_binding=baseline["source_binding"],
            changes=changes,
        )
    )


def validate_package(value: dict) -> list[dict]:
    _check_artifact(value, "package", {"baseline_digest", "source_binding", "changes"})
    if not isinstance(value["changes"], list) or len(value["changes"]) > MAX_RECORDS:
        raise PromotionError("invalid_changes")
    if not value["changes"]:
        return []
    selection = {"version": VERSION, "records": []}
    for change in value["changes"]:
        _keys(change, RECORD_KEYS | {"expected_before", "desired_after"})
        selection["records"].append({key: change[key] for key in RECORD_KEYS})
    records = validate_selection(selection, require_bound=True)
    if selection["records"] != records:
        raise PromotionError("noncanonical_selection")
    for change in value["changes"]:
        after = _values(change, change["desired_after"])
        if change["operation"] == "insert":
            if change["expected_before"] is not None:
                raise PromotionError("insert_baseline_must_be_absent")
        else:
            before = _values(change, change["expected_before"])
            if any(before[field] == after[field] for field in change["fields"]):
                raise PromotionError("unchanged_field_in_package")
    return value["changes"]


def _operation_context(
    change: dict,
    *,
    actor_id: int,
    package_digest: str,
    preview_digest: str = "",
    state: str,
) -> dict:
    return {
        **change,
        "actor_id": actor_id,
        "package_digest": package_digest,
        "preview_digest": preview_digest,
        "state": state,
        "decoded_values": _decoded_values(change, change["desired_after"]),
    }


async def _has_insert_receipt(
    conn: AsyncConnection, change: dict, package_digest: str, table: Table
) -> bool:
    audit_table = await _audit_schema(conn, {change["table"]: table})
    recipe = _recipe(change)
    query = (
        select(audit_table.c.entity_id)
        .where(
            audit_table.c.entity_type == recipe.entity_type,
            audit_table.c.entity_id == change["pk"]["id"],
            audit_table.c.action == "created",
            audit_table.c.details["via"].as_string() == "staging_data_promotion",
            audit_table.c.details["package_digest"].as_string() == package_digest,
            audit_table.c.details["recipe"]["policy_digest"].as_string()
            == recipe.policy_digest,
        )
        .limit(1)
    )
    return (await conn.execute(query)).first() is not None


async def _inspect_state(
    conn: AsyncConnection,
    changes: list[dict],
    tables: dict[str, Table],
    lock: bool = False,
    *,
    actor_id: int,
    package_digest: str,
    preview_digest: str = "",
) -> tuple[list[dict], list[dict]]:
    states, conflicts = [], []
    for index, change in enumerate(changes):
        recipe = _recipe(change)
        table = tables[change["table"]]
        row = await _read(conn, table, change, lock)
        state, reason = "conflict", "missing_or_not_writable"
        if change["operation"] == "insert" and row is None:
            state, reason = "ready", None
        elif _writable(row, change):
            actual = {field: row[field] for field in change["fields"]}
            if change["operation"] == "insert":
                if actual == change["desired_after"] and await _has_insert_receipt(
                    conn, change, package_digest, table
                ):
                    state, reason = "already_applied", None
                else:
                    reason = "insert_primary_key_exists"
            elif actual == change["desired_after"]:
                state, reason = "already_applied", None
            elif actual == change["expected_before"]:
                state, reason = "ready", None
            else:
                reason = "field_conflict"
        if state != "conflict":
            context = _operation_context(
                change,
                actor_id=actor_id,
                package_digest=package_digest,
                preview_digest=preview_digest,
                state=state,
            )
            try:
                if lock:
                    await recipe.run_hook("validate_domain", conn, context)
                else:
                    # CLI preview is DB-enforced READ ONLY; repository-authored
                    # validators must only inspect state, never mutate it.
                    await recipe.validate_domain(conn, context)
            except Exception:
                state, reason = "conflict", "recipe_domain_precondition_failed"
        if state == "conflict":
            conflicts.append({"operation_index": index, "code": reason})
        states.append(
            {
                "operation_index": index,
                "state": state,
                "projection_digest": hashlib.sha256(
                    _canonical(
                        {field: row[field] for field in change["fields"]}
                        if row is not None
                        else None
                    )
                ).hexdigest(),
            }
        )
    return states, conflicts


async def _actor(conn: AsyncConnection, actor_id: int, lock: bool = False) -> None:
    if type(actor_id) is not int or not 0 < actor_id < 2**31:
        raise PromotionError("explicit_admin_actor_required")

    def reflect(sync):
        schema = sync.scalar(text("SELECT current_schema()"))
        return Table("users", MetaData(), schema=schema, autoload_with=sync)

    users = await conn.run_sync(reflect)
    if not {"id", "roles", "is_active"} <= set(users.columns.keys()):
        raise PromotionError("missing_actor_schema")
    query = select(users.c.roles, users.c.is_active).where(users.c.id == actor_id)
    if lock:
        query = query.with_for_update(read=True)
    row = (await conn.execute(query)).mappings().one_or_none()
    if (
        row is None
        or row["is_active"] is not True
        or not isinstance(row["roles"], list)
        or "admin" not in row["roles"]
    ):
        raise PromotionError("explicit_active_admin_actor_required")


def _recipe_bindings(changes: list[dict]) -> list[dict]:
    bindings = {change["recipe"]["id"]: change["recipe"] for change in changes}
    return [bindings[key] for key in sorted(bindings)]


async def preview(conn: AsyncConnection, change_package: dict, actor_id: int) -> dict:
    changes = validate_package(change_package)
    await _actor(conn, actor_id)
    tables = await _tables(conn, {r["table"] for r in changes})
    states, conflicts = await _inspect_state(
        conn,
        changes,
        tables,
        actor_id=actor_id,
        package_digest=change_package["digest"],
    )
    return _seal(
        _envelope(
            "preview",
            actor_id=actor_id,
            package_digest=change_package["digest"],
            target_binding=await _binding(conn, tables),
            recipes=_recipe_bindings(changes),
            expires_at=(_now() + timedelta(seconds=PREVIEW_TTL_SECONDS)).isoformat(),
            states=states,
            conflicts=conflicts,
        )
    )


async def _audit(
    conn: AsyncConnection,
    table: Table,
    change: dict,
    package_digest: str,
    preview_digest: str,
    actor_id: int,
) -> None:
    await conn.execute(
        table.insert().values(
            entity_type=_recipe(change).entity_type,
            entity_id=change["pk"]["id"],
            action="created" if change["operation"] == "insert" else "updated",
            user_id=actor_id,
            external_source="manual",
            details={
                "fields": change["fields"],
                "recipe": change["recipe"],
                "via": "staging_data_promotion",
                "package_digest": package_digest,
                "preview_digest": preview_digest,
            },
        )
    )


async def _audit_schema(conn: AsyncConnection, tables: dict[str, Table]) -> Table:
    audit_table = await conn.run_sync(
        lambda sync: Table(
            "activities",
            MetaData(),
            schema=next(iter(tables.values())).schema,
            autoload_with=sync,
        )
    )
    required = {
        "entity_type",
        "entity_id",
        "action",
        "user_id",
        "external_source",
        "details",
    }
    if not required <= set(audit_table.columns.keys()):
        raise PromotionError("missing_audit_schema")
    return audit_table


async def apply(
    conn: AsyncConnection,
    change_package: dict,
    preview_artifact: dict,
    approved_digest: str,
    actor_id: int,
) -> dict:
    """Own one transaction: lock, validate every row, write and audit, or rollback.

    Callers must pass an idle connection. Preview expiration is mandatory even
    for retries; a fresh preview can be generated without changing the package.
    """
    changes = validate_package(change_package)
    _check_artifact(
        preview_artifact,
        "preview",
        {
            "actor_id",
            "recipes",
            "package_digest",
            "target_binding",
            "expires_at",
            "states",
            "conflicts",
        },
    )
    if preview_artifact["recipes"] != _recipe_bindings(changes):
        raise PromotionError("preview_recipe_policy_mismatch")
    if actor_id != preview_artifact["actor_id"]:
        raise PromotionError("preview_actor_mismatch")
    if (
        approved_digest != preview_artifact["digest"]
        or preview_artifact["package_digest"] != change_package["digest"]
    ):
        raise PromotionError("approval_digest_mismatch")
    if not isinstance(approved_digest, str) or not DIGEST_RE.fullmatch(approved_digest):
        raise PromotionError("approval_digest_mismatch")
    now = _now()
    created = _parse_time(preview_artifact["created_at"])
    expires = _parse_time(preview_artifact["expires_at"])
    if (
        created > now + timedelta(seconds=5)
        or expires <= now
        or expires > created + timedelta(seconds=PREVIEW_TTL_SECONDS + 1)
    ):
        raise PromotionError("preview_expired_or_invalid")
    if preview_artifact["conflicts"]:
        raise ConflictError(preview_artifact["conflicts"])
    if conn.in_transaction():
        raise PromotionError("apply_requires_idle_connection")
    try:
        async with conn.begin():
            await conn.execute(text("SET LOCAL lock_timeout = '5s'"))
            await conn.execute(text("SET LOCAL statement_timeout = '30s'"))
            # Global promotion lock serializes independent packages. Row locks
            # protect against ordinary application updates until commit.
            await conn.execute(text("SELECT pg_advisory_xact_lock(1398034512, 1)"))
            await _actor(conn, actor_id, lock=True)
            tables = await _tables(conn, {r["table"] for r in changes})
            if await _binding(conn, tables) != preview_artifact["target_binding"]:
                raise PromotionError("target_binding_mismatch")
            states, conflicts = await _inspect_state(
                conn,
                changes,
                tables,
                lock=True,
                actor_id=actor_id,
                package_digest=change_package["digest"],
                preview_digest=approved_digest,
            )
            if conflicts:
                raise ConflictError(conflicts)
            # Re-reflect after acquiring row/relation locks: DDL that completed
            # while locks were awaited must invalidate the approved preview.
            tables = await _tables(conn, {r["table"] for r in changes})
            if await _binding(conn, tables) != preview_artifact["target_binding"]:
                raise PromotionError("target_binding_mismatch")
            all_done = all(s["state"] == "already_applied" for s in states)
            if not all_done and states != preview_artifact["states"]:
                raise PromotionError("preview_stale")
            # Approval must still be fresh after waiting for advisory/user/row
            # locks; checking only before those waits can authorize an expired plan.
            if _now() >= expires:
                raise PromotionError("preview_expired_or_invalid")
            todo = [
                change
                for change, state in zip(changes, states)
                if state["state"] == "ready"
            ]
            if todo:
                # Mandatory audit schema is validated before any business write.
                audit_table = await _audit_schema(conn, tables)
                for change in todo:
                    if _now() >= expires:
                        raise PromotionError("preview_expired_or_invalid")
                    table = tables[change["table"]]
                    recipe = _recipe(change)
                    context = _operation_context(
                        change,
                        actor_id=actor_id,
                        package_digest=change_package["digest"],
                        preview_digest=approved_digest,
                        state="ready",
                    )
                    try:
                        await recipe.run_hook("before_apply", conn, context)
                        if _now() >= expires:
                            raise PromotionError("preview_expired_or_invalid")
                        if change["operation"] == "insert":
                            # Creation is never a generic raw INSERT. A reviewed
                            # handler owns defaults, FK relations and domain state.
                            if recipe.insert_handler is None:
                                raise PromotionError("insert_requires_domain_handler")
                            await recipe.insert_handler(conn, table, context)
                            if not conn.in_transaction():
                                raise PromotionError("recipe_hook_changed_transaction")
                        else:
                            values = _db_values(change, table)
                            if "updated_at" in table.c:
                                values["updated_at"] = func.now()
                            await conn.execute(
                                update(table)
                                .where(table.c.id == change["pk"]["id"])
                                .values(**values)
                            )
                        await recipe.run_hook("after_apply", conn, context)
                    except recipes.RecipeError as exc:
                        raise PromotionError("recipe_domain_hook_failed") from exc
                    # A hook cannot silently broaden the desired result or leave
                    # a newly created record retired/hidden/incomplete.
                    after = await _read(conn, table, change, lock=True)
                    if (
                        not _writable(after, change)
                        or {field: after[field] for field in change["fields"]}
                        != change["desired_after"]
                    ):
                        raise PromotionError("recipe_postapply_projection_mismatch")
                    await _audit(
                        conn,
                        audit_table,
                        change,
                        change_package["digest"],
                        approved_digest,
                        actor_id,
                    )
                if _now() >= expires:
                    raise PromotionError("preview_expired_or_invalid")
            return {
                "digest": approved_digest,
                "applied": len(todo),
                "already_applied": len(changes) - len(todo),
            }
    except SQLAlchemyError as exc:
        # DB errors can contain PII even with hide_parameters=True (PG DETAIL).
        raise PromotionError("database_constraint_or_execution_failed") from exc


def _artifact_path(path: str | Path) -> Path:
    raw = Path(path).expanduser()
    if ".." in raw.parts:
        raise PromotionError("artifact_parent_traversal_not_allowed")
    absolute = raw if raw.is_absolute() else Path.cwd() / raw
    if any(part.is_symlink() for part in (absolute, *absolute.parents)):
        raise PromotionError("artifact_symlink_not_allowed")
    candidate = absolute.resolve()
    if any(
        (parent / ".git").exists() for parent in (candidate.parent, *candidate.parents)
    ):
        raise PromotionError("artifacts_must_be_outside_repository")
    try:
        parent_stat = candidate.parent.stat()
    except OSError as exc:
        raise PromotionError("artifact_parent_unavailable") from exc
    if parent_stat.st_uid != os.getuid() or parent_stat.st_mode & 0o022:
        raise PromotionError("artifact_parent_must_be_owned_and_not_writable_by_others")
    return candidate


def write_artifact(path: str | Path, artifact: dict) -> None:
    candidate = _artifact_path(path)
    payload = _canonical(artifact) + b"\n"
    if len(payload) > MAX_BYTES:
        raise PromotionError("artifact_too_large")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(candidate, flags, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise PromotionError("artifact_write_failed_use_new_path") from exc


def read_artifact(path: str | Path) -> dict:
    candidate = _artifact_path(path)
    try:
        fd = os.open(candidate, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as stream:
            mode = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(mode.st_mode)
                or stat.S_IMODE(mode.st_mode) != 0o600
                or mode.st_uid != os.getuid()
            ):
                raise PromotionError("artifact_must_be_owned_regular_file_mode_0600")
            payload = stream.read(MAX_BYTES + 1)
        if len(payload) > MAX_BYTES:
            raise PromotionError("artifact_too_large")
        result = json.loads(payload, object_pairs_hook=_json_pairs)
        if not isinstance(result, dict):
            raise PromotionError("invalid_json_object")
        return result
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PromotionError("artifact_read_failed") from exc
