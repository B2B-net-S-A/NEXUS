"""Fail-closed audit/apply engine for the Nexus.xlsx August 2026 correction.

The checked-in manifest contains only contract IDs and the five fields that the
ticket permits.  Audit never writes.  Apply locks the complete scope, rebuilds
the plan from live rows, and requires both SHA-256 fingerprints emitted by the
matching audit before executing raw, allowlisted SQL.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today
from app.services.order_types import allowed_order_types


class NexusDataCorrectionError(RuntimeError):
    """Raised when the one-off correction cannot be proved safe."""


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SQL_IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_ALLOWED_CONTRACT_FIELDS = (
    "contract_type",
    "start_date",
    "end_date",
    "client_order_end_date",
    "rate_client",
)
_REQUIRED_CONTRACT_FIELDS = frozenset({"id", "contract_type", "start_date", "end_date"})
_OPTIONAL_CONTRACT_FIELDS = frozenset({"client_order_end_date", "rate_client"})
_CONTRACT_TYPES = frozenset({"b2b", "uop", "uzlecenie"})
_CANONICAL_CLIENTS = (
    (12, "BNP Paribas"),
    (15, "Polkomtel"),
    (18, "BIK"),
    (155, "Wedel"),
)
_CANONICAL_CLIENT_IDS = frozenset(client_id for client_id, _ in _CANONICAL_CLIENTS)
_EXPECTED_ALLOWED_ORDER_TYPES: dict[int, tuple[str, ...]] = {
    12: ("md",),
    15: ("md", "cost"),
    18: ("md",),
    155: ("md", "cost"),
}
_EXPECTED_SOURCE = {
    "data_rows": 471,
    "file": "Nexus.xlsx",
    "purple_client_order_end_date_cells": 34,
    "purple_rate_client_cells": 30,
    "purple_rows": 58,
    "sha256": "5f4c38cba2ac3ba6703e66862ccc20525b400dc50f39455f3adf722ac4be8b7a",
    "sheet": "Kontrakty",
}
_EXPECTED_MANIFEST_TARGETS_SHA256 = (
    "23c27f976a0ff5e7fbd8fb53b5178b92bf3d4dd5edfc3a2da27faf147d8b9cca"
)

# Audit reads pg_catalog and rejects every future/unreviewed FK. Dependencies
# that would be deleted or restrict deletion block the operation. Reviewed
# ``SET NULL`` children may survive only under an exact before/after proof.
# PostgreSQL ``pg_constraint.confdeltype`` values expected for every reviewed
# FK into ``client_orders``.  SET NULL dependencies can be preserved exactly;
# CASCADE dependencies remain hard blockers whenever matching rows exist.
_KNOWN_CLIENT_ORDER_FKS: dict[tuple[str, str], str] = {
    ("client_orders", "predecessor_order_id"): "n",
    ("client_order_group_events", "order_id"): "n",
    ("client_order_invoice_consumptions", "order_id"): "c",
    ("client_order_md_consumptions", "order_id"): "c",
    ("client_order_offboarding_cases", "order_id"): "c",
    ("client_order_offboarding_cases", "target_order_id"): "n",
    ("dl_alerts", "order_id"): "n",
    ("md_consumption_import_rows", "matched_order_id"): "n",
}
_SET_NULL_DELETE_ACTION = "n"
_EXPECTED_CHILD_PRIMARY_KEY = ("id",)
_FILE_EVIDENCE_FIELDS = (
    "filename",
    "file_path",
    "content_type",
    "size_bytes",
    "file_uploaded_by",
    "file_uploaded_at",
)
_LOCK_ID = 2026082901


@dataclass(frozen=True)
class ContractCorrection:
    id: int
    contract_type: str
    start_date: date
    end_date: date | None
    client_order_end_date_present: bool
    client_order_end_date: date | None
    rate_client_present: bool
    rate_client: Decimal | None

    @property
    def targets(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "contract_type": self.contract_type,
            "start_date": self.start_date,
            "end_date": self.end_date,
        }
        if self.client_order_end_date_present:
            result["client_order_end_date"] = self.client_order_end_date
        if self.rate_client_present:
            result["rate_client"] = self.rate_client
        return result


@dataclass(frozen=True)
class NexusDataCorrectionManifest:
    contracts: tuple[ContractCorrection, ...]
    clients: tuple[tuple[int, str], ...]
    source: Mapping[str, Any]
    version: int

    @property
    def contract_ids(self) -> tuple[int, ...]:
        return tuple(item.id for item in self.contracts)

    @property
    def rate_client_contract_ids(self) -> tuple[int, ...]:
        return tuple(item.id for item in self.contracts if item.rate_client_present)


def _manifest_targets_sha256(
    contracts: Sequence[ContractCorrection],
    clients: Sequence[tuple[int, str]],
) -> str:
    """Digest only canonical mutation targets, independent of source metadata."""

    contract_targets: list[dict[str, Any]] = []
    for item in sorted(contracts, key=lambda row: row.id):
        target: dict[str, Any] = {
            "id": item.id,
            "contract_type": item.contract_type,
            "start_date": item.start_date.isoformat(),
            "end_date": item.end_date.isoformat() if item.end_date else None,
        }
        if item.client_order_end_date_present:
            target["client_order_end_date"] = (
                item.client_order_end_date.isoformat()
                if item.client_order_end_date
                else None
            )
        if item.rate_client_present:
            target["rate_client"] = (
                format(item.rate_client, "f") if item.rate_client is not None else None
            )
        contract_targets.append(target)
    payload = {
        "contracts": contract_targets,
        "clients": [
            {"id": client_id, "name": name} for client_id, name in sorted(clients)
        ],
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise NexusDataCorrectionError(f"{label} must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise NexusDataCorrectionError(f"{label} must be a positive integer") from exc
    if parsed <= 0 or str(value).strip() != str(parsed):
        raise NexusDataCorrectionError(f"{label} must be a positive integer")
    return parsed


def _parse_date(value: Any, label: str, *, nullable: bool) -> date | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise NexusDataCorrectionError(f"{label} must be an ISO date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise NexusDataCorrectionError(f"{label} must be an ISO date") from exc
    if parsed.isoformat() != value:
        raise NexusDataCorrectionError(f"{label} must be a canonical ISO date")
    return parsed


def _parse_rate(value: Any, label: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise NexusDataCorrectionError(f"{label} must be a decimal")
    try:
        parsed = Decimal(str(value))
    except InvalidOperation as exc:
        raise NexusDataCorrectionError(f"{label} must be a decimal") from exc
    if not parsed.is_finite() or parsed < 0 or parsed.as_tuple().exponent < -3:
        raise NexusDataCorrectionError(
            f"{label} must be a non-negative decimal with at most 3 places"
        )
    if parsed >= Decimal("1000000000"):
        raise NexusDataCorrectionError(f"{label} exceeds Numeric(12,3)")
    return parsed


def load_nexus_data_correction_manifest(
    path: str | Path,
) -> NexusDataCorrectionManifest:
    """Load and strictly validate the immutable, pseudonymous manifest."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or set(raw) != {
        "version",
        "source",
        "contracts",
        "periodic_order_cleanup",
    }:
        raise NexusDataCorrectionError("manifest top-level scope is invalid")
    if raw["version"] != 1:
        raise NexusDataCorrectionError("manifest version must be 1")

    source = raw["source"]
    if not isinstance(source, dict):
        raise NexusDataCorrectionError("manifest.source must be an object")
    for key, expected in _EXPECTED_SOURCE.items():
        if source.get(key) != expected:
            raise NexusDataCorrectionError(
                f"manifest source invariant changed for {key}"
            )
    if not _SHA256_RE.fullmatch(str(source.get("sha256", ""))):
        raise NexusDataCorrectionError("manifest source.sha256 is invalid")
    if set(source) != set(_EXPECTED_SOURCE):
        raise NexusDataCorrectionError("manifest.source has unexpected fields")

    rows = raw["contracts"]
    if not isinstance(rows, list) or len(rows) != _EXPECTED_SOURCE["data_rows"]:
        raise NexusDataCorrectionError("manifest must contain exactly 471 contracts")
    parsed_rows: list[ContractCorrection] = []
    seen: set[int] = set()
    for index, row in enumerate(rows):
        label = f"contracts[{index}]"
        if not isinstance(row, dict):
            raise NexusDataCorrectionError(f"{label} must be an object")
        keys = set(row)
        if not _REQUIRED_CONTRACT_FIELDS.issubset(keys):
            raise NexusDataCorrectionError(f"{label} misses a required target")
        unexpected = keys - _REQUIRED_CONTRACT_FIELDS - _OPTIONAL_CONTRACT_FIELDS
        if unexpected:
            raise NexusDataCorrectionError(
                f"{label} contains forbidden fields: {sorted(unexpected)}"
            )
        contract_id = _positive_int(row["id"], f"{label}.id")
        if contract_id in seen:
            raise NexusDataCorrectionError(f"contract ID {contract_id} is repeated")
        seen.add(contract_id)
        contract_type = row["contract_type"]
        if contract_type not in _CONTRACT_TYPES:
            raise NexusDataCorrectionError(f"{label}.contract_type is invalid")
        parsed_rows.append(
            ContractCorrection(
                id=contract_id,
                contract_type=str(contract_type),
                start_date=_parse_date(
                    row["start_date"], f"{label}.start_date", nullable=False
                ),
                end_date=_parse_date(
                    row["end_date"], f"{label}.end_date", nullable=True
                ),
                client_order_end_date_present="client_order_end_date" in row,
                client_order_end_date=_parse_date(
                    row.get("client_order_end_date"),
                    f"{label}.client_order_end_date",
                    nullable=True,
                ),
                rate_client_present="rate_client" in row,
                rate_client=(
                    _parse_rate(row["rate_client"], f"{label}.rate_client")
                    if "rate_client" in row
                    else None
                ),
            )
        )

    j_count = sum(item.client_order_end_date_present for item in parsed_rows)
    m_count = sum(item.rate_client_present for item in parsed_rows)
    purple_count = sum(
        item.client_order_end_date_present or item.rate_client_present
        for item in parsed_rows
    )
    if (
        j_count != _EXPECTED_SOURCE["purple_client_order_end_date_cells"]
        or m_count != _EXPECTED_SOURCE["purple_rate_client_cells"]
        or purple_count != _EXPECTED_SOURCE["purple_rows"]
    ):
        raise NexusDataCorrectionError("manifest purple-cell scope is invalid")

    cleanup = raw["periodic_order_cleanup"]
    if not isinstance(cleanup, dict) or set(cleanup) != {"clients"}:
        raise NexusDataCorrectionError("periodic_order_cleanup scope is invalid")
    client_rows = cleanup["clients"]
    if not isinstance(client_rows, list):
        raise NexusDataCorrectionError("periodic cleanup clients must be a list")
    clients: list[tuple[int, str]] = []
    for index, item in enumerate(client_rows):
        if not isinstance(item, dict) or set(item) != {"id", "name"}:
            raise NexusDataCorrectionError(
                f"periodic cleanup client {index} is invalid"
            )
        clients.append(
            (
                _positive_int(item["id"], f"clients[{index}].id"),
                str(item["name"]),
            )
        )
    if tuple(sorted(clients)) != _CANONICAL_CLIENTS:
        raise NexusDataCorrectionError("periodic cleanup client identities changed")
    if (
        _manifest_targets_sha256(parsed_rows, clients)
        != _EXPECTED_MANIFEST_TARGETS_SHA256
    ):
        raise NexusDataCorrectionError("manifest canonical targets digest changed")

    return NexusDataCorrectionManifest(
        contracts=tuple(sorted(parsed_rows, key=lambda item: item.id)),
        clients=tuple(sorted(clients)),
        source=dict(source),
        version=1,
    )


def _stable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _stable(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_stable(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if hasattr(value, "value"):
        return _stable(value.value)
    return value


def plan_fingerprint(payload: Mapping[str, Any]) -> str:
    """Hash every live input needed to authorize this exact mutation set."""
    body = {
        key: value
        for key, value in payload.items()
        if key
        not in {
            "mode",
            "ok",
            "fingerprint",
            "approval_fingerprint",
            "generated_at",
        }
    }
    encoded = json.dumps(
        _stable(body), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def approval_fingerprint(plan_sha256: str) -> str:
    """Bind approval to the exact plan and the sole allowed operation."""
    if not _SHA256_RE.fullmatch(plan_sha256):
        raise NexusDataCorrectionError("approval requires a valid plan fingerprint")
    payload = {
        "operation": "nexus_orders_contracts_correction_2026_08",
        "plan_fingerprint": plan_sha256,
        "contract_fields": list(_ALLOWED_CONTRACT_FIELDS),
        "periodic_order_clients": [item[0] for item in _CANONICAL_CLIENTS],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _database_equal(field: str, before: Any, after: Any) -> bool:
    if field in {"start_date", "end_date", "client_order_end_date"}:
        return (
            _parse_date(str(before), field, nullable=True)
            if before is not None
            else None
        ) == after
    if field == "rate_client":
        return (Decimal(str(before)) if before is not None else None) == after
    return str(before) == str(after)


def build_contract_deltas(
    rows: Mapping[int, Mapping[str, Any]],
    manifest: NexusDataCorrectionManifest,
) -> list[dict[str, Any]]:
    """Return exact allowlisted differences; absent optional keys stay untouched."""
    result: list[dict[str, Any]] = []
    for target in manifest.contracts:
        current = rows.get(target.id)
        if current is None:
            continue
        changes: list[dict[str, Any]] = []
        for field, after in target.targets.items():
            before = current.get(field)
            if not _database_equal(field, before, after):
                changes.append({"field": field, "before": before, "after": after})
        if changes:
            result.append({"contract_id": target.id, "changes": changes})
    return result


def _schedule_effective_from(row: Mapping[str, Any]) -> date:
    value = row.get("effective_from")
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        parsed = _parse_date(value, "schedule.effective_from", nullable=False)
        assert parsed is not None
        return parsed
    raise NexusDataCorrectionError("schedule.effective_from must be a date")


def select_effective_client_rate_schedule_rows(
    rows: Sequence[Mapping[str, Any]], audit_date: date
) -> dict[int, dict[str, Any]]:
    """Select the exact row read by ``Contract._resolve_scheduled_rate``.

    Database relationship order is ``effective_from, id``.  Therefore the
    resolver's last-insertion tie break is the highest row ID: newest past
    step wins; if all steps are future-dated, the earliest future date and
    highest ID on that date wins.
    """

    grouped: dict[int, list[dict[str, Any]]] = {}
    seen_row_ids: set[int] = set()
    for raw_row in rows:
        row = dict(raw_row)
        row_id = _positive_int(row.get("id"), "schedule row ID")
        contract_id = _positive_int(row.get("contract_id"), "schedule contract ID")
        if row_id in seen_row_ids:
            raise NexusDataCorrectionError(
                f"client-rate schedule row ID {row_id} is repeated"
            )
        seen_row_ids.add(row_id)
        _schedule_effective_from(row)
        # ``rate`` is NOT NULL in PostgreSQL, but validate the live boundary
        # before it can participate in a fingerprint or mismatch decision.
        _parse_rate(row.get("rate"), "schedule.rate")
        grouped.setdefault(contract_id, []).append(row)

    selected: dict[int, dict[str, Any]] = {}
    for contract_id, entries in grouped.items():
        past = [row for row in entries if _schedule_effective_from(row) <= audit_date]
        if past:
            chosen = max(
                past,
                key=lambda row: (
                    _schedule_effective_from(row),
                    int(row["id"]),
                ),
            )
        else:
            earliest = min(_schedule_effective_from(row) for row in entries)
            chosen = max(
                (row for row in entries if _schedule_effective_from(row) == earliest),
                key=lambda row: int(row["id"]),
            )
        selected[contract_id] = chosen
    return selected


async def _fetch_contracts(
    db: AsyncSession, ids: Sequence[int], *, lock: bool
) -> dict[int, dict[str, Any]]:
    suffix = " FOR UPDATE OF c" if lock else ""
    rows = (
        (
            await db.execute(
                text(
                    "SELECT to_jsonb(c) AS row FROM contracts c "
                    f"WHERE c.id = ANY(:ids) ORDER BY c.id{suffix}"
                ),
                {"ids": list(ids)},
            )
        )
        .mappings()
        .all()
    )
    return {int(item["row"]["id"]): dict(item["row"]) for item in rows}


async def _fetch_clients(
    db: AsyncSession, ids: Sequence[int], *, lock: bool
) -> list[dict[str, Any]]:
    suffix = " FOR UPDATE OF c" if lock else ""
    return [
        dict(row)
        for row in (
            (
                await db.execute(
                    text(
                        "SELECT c.id, c.name FROM clients c "
                        f"WHERE c.id = ANY(:ids) ORDER BY c.id{suffix}"
                    ),
                    {"ids": list(ids)},
                )
            )
            .mappings()
            .all()
        )
    ]


async def _fetch_rate_schedule_rows(
    db: AsyncSession, ids: Sequence[int], *, lock: bool
) -> list[dict[str, Any]]:
    if not ids:
        return []
    suffix = " FOR UPDATE OF r" if lock else ""
    return [
        {
            **dict(item["row"]),
            # JSONB numbers decode as floats.  Keep the two decision fields in
            # their native asyncpg types so a financial equality/fingerprint
            # never depends on an IEEE-754 round trip.
            "rate": item["rate"],
            "effective_from": item["effective_from"],
        }
        for item in (
            (
                await db.execute(
                    text(
                        "SELECT to_jsonb(r) AS row, r.rate, r.effective_from "
                        "FROM contract_client_rates r "
                        "WHERE r.contract_id = ANY(:ids) "
                        f"ORDER BY r.contract_id, r.effective_from, r.id{suffix}"
                    ),
                    {"ids": list(ids)},
                )
            )
            .mappings()
            .all()
        )
    ]


async def _client_order_fk_catalog(db: AsyncSession) -> list[dict[str, Any]]:
    """Inventory every non-system FK into the resolved ``client_orders``.

    The child schema and primary-key columns are part of the fingerprint.  A
    relation is queried dynamically only after all interpolated identifiers
    have passed the strict lowercase PostgreSQL identifier allowlist below.
    """

    rows = (
        (
            await db.execute(
                text(
                    "SELECT child_ns.nspname AS schema_name, "
                    "child.relname AS table_name, a.attname AS column_name, "
                    "parent_ns.nspname AS target_schema, "
                    "parent_a.attname AS target_column_name, "
                    "con.conname AS constraint_name, "
                    "array_length(con.conkey, 1) AS column_count, "
                    "con.confdeltype::text AS delete_action, "
                    "COALESCE(pk_info.primary_key_columns, ARRAY[]::name[]) "
                    "AS primary_key_columns FROM pg_constraint con "
                    "JOIN pg_class child ON child.oid = con.conrelid "
                    "JOIN pg_namespace child_ns ON child_ns.oid = child.relnamespace "
                    "JOIN pg_class parent ON parent.oid = con.confrelid "
                    "JOIN pg_namespace parent_ns ON parent_ns.oid = parent.relnamespace "
                    "JOIN LATERAL unnest(con.conkey) WITH ORDINALITY ck(attnum, ord) "
                    "ON TRUE JOIN LATERAL unnest(con.confkey) WITH ORDINALITY "
                    "fk(attnum, ord) ON fk.ord = ck.ord "
                    "JOIN pg_attribute a ON a.attrelid = child.oid "
                    "AND a.attnum = ck.attnum LEFT JOIN LATERAL ("
                    "SELECT array_agg(pk_attr.attname ORDER BY pk_key.ord) "
                    "AS primary_key_columns FROM pg_constraint pk "
                    "JOIN LATERAL unnest(pk.conkey) WITH ORDINALITY "
                    "pk_key(attnum, ord) ON TRUE "
                    "JOIN pg_attribute pk_attr ON pk_attr.attrelid = child.oid "
                    "AND pk_attr.attnum = pk_key.attnum "
                    "WHERE pk.contype = 'p' AND pk.conrelid = child.oid"
                    ") pk_info ON TRUE JOIN pg_attribute parent_a "
                    "ON parent_a.attrelid = parent.oid "
                    "AND parent_a.attnum = fk.attnum WHERE con.contype = 'f' "
                    "AND con.confrelid = 'client_orders'::regclass "
                    "AND child_ns.nspname <> 'information_schema' "
                    "AND child_ns.nspname !~ '^pg_' "
                    "ORDER BY child_ns.nspname, child.relname, con.conname, ck.ord"
                )
            )
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def _catalog_fk_issue(fk: Mapping[str, Any]) -> str | None:
    """Return why a catalog row must block, or ``None`` when reviewed/safe."""

    identifiers = [
        fk.get("schema_name"),
        fk.get("table_name"),
        fk.get("column_name"),
        fk.get("target_schema"),
        fk.get("target_column_name"),
    ]
    primary_key_columns = tuple(str(item) for item in fk.get("primary_key_columns", []))
    identifiers.extend(primary_key_columns)
    if any(not _SQL_IDENTIFIER_RE.fullmatch(str(item or "")) for item in identifiers):
        return "unsafe_identifier"
    if str(fk["schema_name"]) != str(fk["target_schema"]):
        return "foreign_schema"
    if int(fk.get("column_count") or 0) != 1:
        return "composite_foreign_key"
    if str(fk.get("target_column_name")) != "id":
        return "unexpected_target_column"
    if primary_key_columns != _EXPECTED_CHILD_PRIMARY_KEY:
        return "unexpected_primary_key"
    key = (str(fk["table_name"]), str(fk["column_name"]))
    expected_action = _KNOWN_CLIENT_ORDER_FKS.get(key)
    if expected_action is None:
        return "unknown_foreign_key"
    if str(fk.get("delete_action")) != expected_action:
        return "unexpected_delete_action"
    return None


def _qualified_identifier(*parts: str) -> str:
    """Quote an already allowlisted identifier path, failing closed otherwise."""

    if not parts or any(not _SQL_IDENTIFIER_RE.fullmatch(part) for part in parts):
        raise NexusDataCorrectionError("unsafe SQL identifier in FK inventory")
    return ".".join(f'"{part}"' for part in parts)


async def _fetch_standalone_orders(
    db: AsyncSession, client_ids: Sequence[int], *, lock: bool
) -> list[dict[str, Any]]:
    """Fetch the complete standalone before-state for the four pinned clients."""

    suffix = " FOR UPDATE OF o" if lock else ""
    rows = (
        (
            await db.execute(
                text(
                    "SELECT to_jsonb(o) AS row FROM client_orders o "
                    "WHERE o.client_id = ANY(:client_ids) "
                    "AND o.order_group_id IS NULL "
                    f"ORDER BY o.id{suffix}"
                ),
                {"client_ids": list(client_ids)},
            )
        )
        .mappings()
        .all()
    )
    return [dict(item["row"]) for item in rows]


async def _fetch_client_order_groups(
    db: AsyncSession, client_ids: Sequence[int], *, lock: bool
) -> list[dict[str, Any]]:
    """Fetch every group needed to prove the pinned type policy."""

    suffix = " FOR UPDATE OF g" if lock else ""
    rows = (
        (
            await db.execute(
                text(
                    "SELECT to_jsonb(g) AS row FROM client_order_groups g "
                    "WHERE g.client_id = ANY(:client_ids) "
                    f"ORDER BY g.id{suffix}"
                ),
                {"client_ids": list(client_ids)},
            )
        )
        .mappings()
        .all()
    )
    return [dict(item["row"]) for item in rows]


def _order_type_policy_inventory(
    standalone_orders: Sequence[Mapping[str, Any]],
    order_groups: Sequence[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Classify exact deletions, preserved legacy NULLs, and policy violations.

    A raw standalone ``NULL`` is never a deletion signal.  The shared runtime
    policy interprets it as legacy MD for the four pinned clients.  A legacy
    group keeps the established ``is_cost_based`` discriminator.  Only an
    explicit standalone ``periodic`` is in the destructive scope.
    """

    periodic_orders: list[dict[str, Any]] = []
    legacy_null_orders: list[dict[str, Any]] = []
    disallowed_orders: list[dict[str, Any]] = []
    disallowed_groups: list[dict[str, Any]] = []

    for raw_row in standalone_orders:
        row = dict(raw_row)
        client_id = int(row["client_id"])
        if client_id not in _CANONICAL_CLIENT_IDS:
            raise NexusDataCorrectionError(
                f"standalone order {row['id']} escaped the canonical client scope"
            )
        raw_type = row.get("order_type")
        if raw_type == "periodic":
            periodic_orders.append(row)
            continue
        if raw_type is None:
            legacy_null_orders.append(row)
            effective_type = _EXPECTED_ALLOWED_ORDER_TYPES[client_id][0]
        else:
            effective_type = str(raw_type)
        allowed = set(_EXPECTED_ALLOWED_ORDER_TYPES[client_id])
        if effective_type not in allowed:
            disallowed_orders.append(
                {
                    "order_id": int(row["id"]),
                    "client_id": client_id,
                    "effective_type": effective_type,
                }
            )

    for raw_row in order_groups:
        row = dict(raw_row)
        client_id = int(row["client_id"])
        if client_id not in _CANONICAL_CLIENT_IDS:
            raise NexusDataCorrectionError(
                f"order group {row['id']} escaped the canonical client scope"
            )
        raw_type = row.get("order_type")
        effective_type = (
            str(raw_type)
            if raw_type is not None
            else ("cost" if bool(row.get("is_cost_based")) else "md")
        )
        allowed = set(_EXPECTED_ALLOWED_ORDER_TYPES[client_id])
        if effective_type not in allowed:
            disallowed_groups.append(
                {
                    "group_id": int(row["id"]),
                    "client_id": client_id,
                    "effective_type": effective_type,
                }
            )

    return {
        "periodic_orders": periodic_orders,
        "legacy_null_orders": legacy_null_orders,
        "disallowed_orders": disallowed_orders,
        "disallowed_groups": disallowed_groups,
    }


def _runtime_order_type_policy_drift() -> list[dict[str, Any]]:
    """Prove that the runtime writer policy matches this destructive audit."""

    result: list[dict[str, Any]] = []
    for client_id, expected in sorted(_EXPECTED_ALLOWED_ORDER_TYPES.items()):
        actual = tuple(item.value for item in allowed_order_types(client_id))
        if actual != expected:
            result.append({"client_id": client_id})
    return result


async def _dependency_inventory(
    db: AsyncSession,
    catalog: Sequence[Mapping[str, Any]],
    order_ids: Sequence[int],
    *,
    lock: bool,
) -> dict[str, dict[str, Any]]:
    """Fingerprint full before-state for every reviewed matching child row."""

    if not order_ids:
        return {}
    inventory: dict[str, dict[str, Any]] = {}
    for fk in catalog:
        if _catalog_fk_issue(fk) is not None:
            continue
        schema = str(fk["schema_name"])
        table = str(fk["table_name"])
        column = str(fk["column_name"])
        primary_key_columns = tuple(
            str(item) for item in fk.get("primary_key_columns", [])
        )
        qualified_table = _qualified_identifier(schema, table)
        qualified_column = _qualified_identifier(column)
        qualified_pk = _qualified_identifier(primary_key_columns[0])
        suffix = " FOR UPDATE OF child" if lock else ""
        rows = (
            (
                await db.execute(
                    text(
                        f"SELECT to_jsonb(child) AS row FROM {qualified_table} child "
                        f"WHERE child.{qualified_column} = ANY(:ids) "
                        f"ORDER BY child.{qualified_pk}{suffix}"
                    ),
                    {"ids": list(order_ids)},
                )
            )
            .mappings()
            .all()
        )
        if rows:
            key = f"{schema}.{table}.{column}"
            inventory[key] = {
                "schema_name": schema,
                "table_name": table,
                "column_name": column,
                "delete_action": str(fk["delete_action"]),
                "primary_key_columns": list(primary_key_columns),
                "rows": [dict(item["row"]) for item in rows],
            }
    return inventory


def _split_deletion_dependencies(
    inventory: Mapping[str, Mapping[str, Any]],
    deletion_ids: Sequence[int],
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
]:
    """Separate surviving SET NULL, also-deleted SET NULL, and blockers."""

    deletion_set = set(deletion_ids)
    set_null: dict[str, dict[str, Any]] = {}
    set_null_deleted: dict[str, dict[str, Any]] = {}
    blocking: dict[str, dict[str, Any]] = {}
    for key, raw_entry in inventory.items():
        entry = dict(raw_entry)
        rows = [dict(row) for row in entry.get("rows", [])]
        allowed_rows: list[dict[str, Any]] = []
        deleted_rows: list[dict[str, Any]] = []
        blocked_rows: list[dict[str, Any]] = []
        for row in rows:
            # A self-referencing child that is itself in the DELETE set cannot
            # satisfy the required "same PK survives with FK NULL" invariant.
            child_deleted = (
                entry.get("table_name") == "client_orders"
                and int(row["id"]) in deletion_set
            )
            if entry.get("delete_action") == _SET_NULL_DELETE_ACTION:
                if child_deleted:
                    deleted_rows.append(row)
                else:
                    allowed_rows.append(row)
            else:
                blocked_rows.append(row)
        if allowed_rows:
            set_null[key] = {**entry, "rows": allowed_rows}
        if deleted_rows:
            set_null_deleted[key] = {**entry, "rows": deleted_rows}
        if blocked_rows:
            blocking[key] = {**entry, "rows": blocked_rows}
    return set_null, set_null_deleted, blocking


def _dependency_row_ids(
    inventory: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[int, list[int]]]:
    """Pseudonymous projection used by blockers and the CI artifact."""

    result: dict[str, dict[int, list[int]]] = {}
    for key, entry in inventory.items():
        column = str(entry["column_name"])
        primary_key_columns = tuple(
            str(item) for item in entry.get("primary_key_columns", [])
        )
        if primary_key_columns != _EXPECTED_CHILD_PRIMARY_KEY:
            raise NexusDataCorrectionError("dependency inventory primary key drifted")
        per_order: dict[int, list[int]] = {}
        for row in entry.get("rows", []):
            per_order.setdefault(int(row[column]), []).append(int(row["id"]))
        result[str(key)] = per_order
    return result


def _dependency_count(inventory: Mapping[str, Mapping[str, Any]]) -> int:
    return sum(len(entry.get("rows", [])) for entry in inventory.values())


def _blocker(code: str, **context: Any) -> dict[str, Any]:
    return {"code": code, **context}


async def build_nexus_data_correction_plan(
    db: AsyncSession,
    manifest: NexusDataCorrectionManifest,
    *,
    lock: bool = False,
) -> dict[str, Any]:
    """Build a deterministic plan.  With ``lock=False`` this is read-only."""
    audit_date = business_today()
    contract_ids = list(manifest.contract_ids)
    client_ids = [item[0] for item in manifest.clients]
    contracts = await _fetch_contracts(db, contract_ids, lock=lock)
    clients = await _fetch_clients(db, client_ids, lock=lock)
    schedules = await _fetch_rate_schedule_rows(
        db, manifest.rate_client_contract_ids, lock=lock
    )
    catalog = await _client_order_fk_catalog(db)
    standalone_orders = await _fetch_standalone_orders(db, client_ids, lock=lock)
    order_groups = await _fetch_client_order_groups(db, client_ids, lock=lock)
    type_inventory = _order_type_policy_inventory(standalone_orders, order_groups)
    orders = type_inventory["periodic_orders"]
    legacy_null_orders = type_inventory["legacy_null_orders"]
    order_ids = [int(row["id"]) for row in orders]
    dependency_inventory = await _dependency_inventory(
        db, catalog, order_ids, lock=lock
    )
    (
        set_null_dependencies,
        set_null_deleted_dependencies,
        blocking_dependencies,
    ) = _split_deletion_dependencies(dependency_inventory, order_ids)
    legacy_null_dependencies = await _dependency_inventory(
        db,
        catalog,
        [int(row["id"]) for row in legacy_null_orders],
        lock=lock,
    )

    blockers: list[dict[str, Any]] = []
    blockers.extend(
        _blocker("order_type_runtime_policy_drift", **item)
        for item in _runtime_order_type_policy_drift()
    )
    missing_contract_ids = sorted(set(contract_ids) - set(contracts))
    if missing_contract_ids:
        blockers.append(
            _blocker("missing_contracts", contract_ids=missing_contract_ids)
        )

    actual_clients = {int(row["id"]): str(row["name"]) for row in clients}
    for client_id, expected_name in manifest.clients:
        if client_id not in actual_clients:
            blockers.append(_blocker("missing_client", client_id=client_id))
        elif actual_clients[client_id] != expected_name:
            blockers.append(_blocker("wrong_client_identity", client_id=client_id))

    unknown_fks = []
    for item in catalog:
        issue = _catalog_fk_issue(item)
        if issue is None:
            continue
        unknown_fks.append(
            {
                "schema": str(item.get("schema_name", "")),
                "table": str(item.get("table_name", "")),
                "column": str(item.get("column_name", "")),
                "issue": issue,
            }
        )
    if unknown_fks:
        blockers.append(_blocker("unknown_client_order_foreign_keys", fks=unknown_fks))

    blocking_dependency_ids = _dependency_row_ids(blocking_dependencies)
    if blocking_dependency_ids:
        blockers.append(
            _blocker("client_order_dependencies", dependencies=blocking_dependency_ids)
        )
    blockers.extend(
        _blocker("disallowed_client_order_type", **item)
        for item in type_inventory["disallowed_orders"]
    )
    blockers.extend(
        _blocker("disallowed_client_order_group_type", **item)
        for item in type_inventory["disallowed_groups"]
    )

    file_order_ids = sorted(
        int(row["id"])
        for row in orders
        if any(row.get(field) is not None for field in _FILE_EVIDENCE_FIELDS)
    )
    if file_order_ids:
        blockers.append(
            _blocker("client_order_file_evidence", order_ids=file_order_ids)
        )

    schedule_targets = {
        item.id: item.rate_client
        for item in manifest.contracts
        if item.rate_client_present
    }
    selected_schedule_rows = select_effective_client_rate_schedule_rows(
        schedules, audit_date
    )
    unexpected_schedule_contracts = sorted(
        set(selected_schedule_rows) - set(schedule_targets)
    )
    if unexpected_schedule_contracts:
        raise NexusDataCorrectionError(
            "client-rate schedule escaped purple-M scope: "
            + ", ".join(str(item) for item in unexpected_schedule_contracts)
        )
    for contract_id, row in sorted(selected_schedule_rows.items()):
        if not _database_equal(
            "rate_client", row.get("rate"), schedule_targets[contract_id]
        ):
            blockers.append(
                _blocker(
                    "target_client_rate_schedule_mismatch",
                    contract_id=contract_id,
                    row_id=int(row["id"]),
                )
            )

    deltas = build_contract_deltas(contracts, manifest)
    field_counts = {
        field: sum(
            change["field"] == field
            for update in deltas
            for change in update["changes"]
        )
        for field in _ALLOWED_CONTRACT_FIELDS
    }
    plan: dict[str, Any] = {
        "mode": "audit",
        "ok": not blockers,
        "business_date": audit_date,
        "manifest": {
            "version": manifest.version,
            "source_sha256": manifest.source["sha256"],
            "contract_ids": contract_ids,
            "contract_targets": [
                {"id": item.id, **item.targets} for item in manifest.contracts
            ],
            "clients": [
                {"id": client_id, "name": name} for client_id, name in manifest.clients
            ],
        },
        "live_state": {
            "contract_rows": [contracts[key] for key in sorted(contracts)],
            "client_rows": clients,
            "client_rate_schedule_rows": schedules,
            "standalone_order_rows": standalone_orders,
            "periodic_order_rows": orders,
            "legacy_null_order_rows": legacy_null_orders,
            "client_order_group_rows": order_groups,
            "client_order_foreign_keys": list(catalog),
            # Full rows stay only in the ephemeral container report and bind
            # approval to the exact child PK/before-state. CI gets counts/IDs.
            "set_null_dependency_rows": set_null_dependencies,
            "set_null_deleted_dependency_rows": set_null_deleted_dependencies,
            "blocking_dependency_rows": blocking_dependencies,
            "legacy_null_dependency_rows": legacy_null_dependencies,
            "dependency_row_ids": blocking_dependency_ids,
            "set_null_dependency_row_ids": _dependency_row_ids(set_null_dependencies),
            "set_null_deleted_dependency_row_ids": _dependency_row_ids(
                set_null_deleted_dependencies
            ),
            "legacy_null_dependency_row_ids": _dependency_row_ids(
                legacy_null_dependencies
            ),
        },
        "contract_updates": deltas,
        "client_order_deletions": [
            {"order_id": int(row["id"]), "client_id": int(row["client_id"])}
            for row in orders
        ],
        "blockers": blockers,
        "summary": {
            "manifest_contracts": len(manifest.contracts),
            "contracts_found": len(contracts),
            "contracts_with_changes": len(deltas),
            "contract_field_changes": field_counts,
            "periodic_orders_to_delete": len(orders),
            "legacy_null_orders_preserved": len(legacy_null_orders),
            "disallowed_standalone_order_types": len(
                type_inventory["disallowed_orders"]
            ),
            "disallowed_group_order_types": len(type_inventory["disallowed_groups"]),
            "dependency_rows": _dependency_count(blocking_dependencies),
            "set_null_dependency_rows": _dependency_count(set_null_dependencies),
            "set_null_deleted_dependency_rows": _dependency_count(
                set_null_deleted_dependencies
            ),
            "legacy_null_dependency_rows": _dependency_count(legacy_null_dependencies),
            "blockers": len(blockers),
        },
    }
    plan["fingerprint"] = plan_fingerprint(plan)
    plan["approval_fingerprint"] = approval_fingerprint(plan["fingerprint"])
    return plan


def _contract_non_target_snapshot(
    row: Mapping[str, Any], target_fields: Sequence[str]
) -> dict[str, Any]:
    return {
        key: _stable(value)
        for key, value in sorted(row.items())
        if key not in target_fields
    }


def _expected_standalone_after_order_delete(
    plan: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Apply the sole approved SET NULL side effect to the expected snapshot."""

    deleted_ids = {int(item["order_id"]) for item in plan["client_order_deletions"]}
    expected = [
        dict(row)
        for row in plan["live_state"]["standalone_order_rows"]
        if int(row["id"]) not in deleted_ids
    ]
    by_id = {int(row["id"]): row for row in expected}
    for entry in (
        plan.get("live_state", {}).get("set_null_dependency_rows", {}).values()
    ):
        if entry.get("table_name") != "client_orders":
            continue
        column = str(entry["column_name"])
        for child in entry.get("rows", []):
            survivor = by_id.get(int(child["id"]))
            if survivor is not None:
                survivor[column] = None
    return expected


async def _apply_contract_updates(
    db: AsyncSession, updates: Sequence[Mapping[str, Any]]
) -> int:
    changed = 0
    for update in updates:
        contract_id = _positive_int(update["contract_id"], "contract update ID")
        changes = list(update["changes"])
        fields = [str(item["field"]) for item in changes]
        if len(fields) != len(set(fields)) or any(
            field not in _ALLOWED_CONTRACT_FIELDS for field in fields
        ):
            raise NexusDataCorrectionError("unsafe contract update scope")
        casts = {
            "contract_type": "contracttype",
            "start_date": "date",
            "end_date": "date",
            "client_order_end_date": "date",
            "rate_client": "numeric(12,3)",
        }
        assignments = ", ".join(
            f"{field} = CAST(:v_{field} AS {casts[field]})" for field in fields
        )
        params = {f"v_{item['field']}": item["after"] for item in changes}
        params["contract_id"] = contract_id
        result = await db.execute(
            text(f"UPDATE contracts SET {assignments} WHERE id = :contract_id"),
            params,
        )
        if int(result.rowcount or 0) != 1:
            raise NexusDataCorrectionError(
                f"contract {contract_id} update cardinality changed"
            )
        changed += 1
    return changed


async def _assert_set_null_dependency_postconditions(
    db: AsyncSession,
    inventory: Mapping[str, Mapping[str, Any]],
) -> None:
    """Prove each approved child survived and only its FK became ``NULL``."""

    for entry in inventory.values():
        schema = str(entry.get("schema_name", ""))
        table = str(entry.get("table_name", ""))
        column = str(entry.get("column_name", ""))
        primary_key_columns = tuple(
            str(item) for item in entry.get("primary_key_columns", [])
        )
        if (
            entry.get("delete_action") != _SET_NULL_DELETE_ACTION
            or primary_key_columns != _EXPECTED_CHILD_PRIMARY_KEY
        ):
            raise NexusDataCorrectionError("unsafe SET NULL postcondition scope")
        qualified_table = _qualified_identifier(schema, table)
        _qualified_identifier(column)
        qualified_pk = _qualified_identifier(primary_key_columns[0])
        before_rows = [dict(row) for row in entry.get("rows", [])]
        primary_keys = [int(row["id"]) for row in before_rows]
        if len(primary_keys) != len(set(primary_keys)):
            raise NexusDataCorrectionError("duplicate dependency primary key")
        after_rows = (
            (
                await db.execute(
                    text(
                        f"SELECT to_jsonb(child) AS row FROM {qualified_table} child "
                        f"WHERE child.{qualified_pk} = ANY(:ids) "
                        f"ORDER BY child.{qualified_pk}"
                    ),
                    {"ids": primary_keys},
                )
            )
            .mappings()
            .all()
        )
        after_by_id = {int(item["row"]["id"]): dict(item["row"]) for item in after_rows}
        if sorted(after_by_id) != sorted(primary_keys):
            raise NexusDataCorrectionError(
                f"SET NULL dependency preservation failed for {table}.{column}"
            )
        for before in before_rows:
            expected = dict(before)
            expected[column] = None
            if _stable(after_by_id[int(before["id"])]) != _stable(expected):
                raise NexusDataCorrectionError(
                    f"SET NULL dependency state changed for {table}.{column}"
                )


async def _assert_deleted_dependency_postconditions(
    db: AsyncSession,
    inventory: Mapping[str, Mapping[str, Any]],
) -> None:
    """Prove each self-referencing child in the delete set no longer exists."""

    for entry in inventory.values():
        schema = str(entry.get("schema_name", ""))
        table = str(entry.get("table_name", ""))
        column = str(entry.get("column_name", ""))
        primary_key_columns = tuple(
            str(item) for item in entry.get("primary_key_columns", [])
        )
        if (
            table != "client_orders"
            or column != "predecessor_order_id"
            or entry.get("delete_action") != _SET_NULL_DELETE_ACTION
            or primary_key_columns != _EXPECTED_CHILD_PRIMARY_KEY
        ):
            raise NexusDataCorrectionError("unsafe deleted dependency scope")
        qualified_table = _qualified_identifier(schema, table)
        qualified_pk = _qualified_identifier(primary_key_columns[0])
        primary_keys = [int(row["id"]) for row in entry.get("rows", [])]
        if len(primary_keys) != len(set(primary_keys)):
            raise NexusDataCorrectionError("duplicate deleted dependency primary key")
        remaining = await db.scalar(
            text(
                f"SELECT count(*) FROM {qualified_table} child "
                f"WHERE child.{qualified_pk} = ANY(:ids)"
            ),
            {"ids": primary_keys},
        )
        if int(remaining or 0) != 0:
            raise NexusDataCorrectionError(
                "deleted self-FK dependency preservation failed"
            )


async def _assert_postconditions(
    db: AsyncSession,
    manifest: NexusDataCorrectionManifest,
    plan: Mapping[str, Any],
) -> None:
    after = await _fetch_contracts(db, manifest.contract_ids, lock=False)
    if sorted(after) != list(manifest.contract_ids):
        raise NexusDataCorrectionError("contract postcondition cardinality failed")
    before = {int(row["id"]): row for row in plan["live_state"]["contract_rows"]}
    before_schedules = [
        dict(row)
        for row in plan.get("live_state", {}).get("client_rate_schedule_rows", [])
    ]
    schedule_contract_ids = {int(row["contract_id"]) for row in before_schedules}
    for target in manifest.contracts:
        current = after[target.id]
        for field, expected in target.targets.items():
            if not _database_equal(field, current.get(field), expected):
                raise NexusDataCorrectionError(
                    f"contract {target.id} target postcondition failed for {field}"
                )
        target_fields = tuple(target.targets)
        if _contract_non_target_snapshot(before[target.id], target_fields) != (
            _contract_non_target_snapshot(current, target_fields)
        ):
            raise NexusDataCorrectionError(
                f"contract {target.id} non-target fields changed"
            )

    client_ids = [item[0] for item in manifest.clients]
    standalone_after = await _fetch_standalone_orders(db, client_ids, lock=False)
    order_groups_after = await _fetch_client_order_groups(db, client_ids, lock=False)
    expected_standalone = _expected_standalone_after_order_delete(plan)
    if _stable(standalone_after) != _stable(expected_standalone):
        raise NexusDataCorrectionError(
            "standalone order preservation postcondition failed"
        )
    if _stable(order_groups_after) != _stable(
        plan["live_state"]["client_order_group_rows"]
    ):
        raise NexusDataCorrectionError("client order group preservation failed")

    type_inventory = _order_type_policy_inventory(standalone_after, order_groups_after)
    if type_inventory["periodic_orders"]:
        raise NexusDataCorrectionError("periodic order deletion postcondition failed")
    if type_inventory["disallowed_orders"] or type_inventory["disallowed_groups"]:
        raise NexusDataCorrectionError("pinned client order-type policy failed")

    await _assert_set_null_dependency_postconditions(
        db,
        plan.get("live_state", {}).get("set_null_dependency_rows", {}),
    )
    await _assert_deleted_dependency_postconditions(
        db,
        plan.get("live_state", {}).get("set_null_deleted_dependency_rows", {}),
    )

    clients = await _fetch_clients(db, client_ids, lock=False)
    actual_clients = {int(row["id"]): str(row["name"]) for row in clients}
    if actual_clients != dict(manifest.clients):
        raise NexusDataCorrectionError("canonical client identity drifted")

    schedules_after = await _fetch_rate_schedule_rows(
        db, manifest.rate_client_contract_ids, lock=False
    )
    if _stable(schedules_after) != _stable(before_schedules):
        raise NexusDataCorrectionError(
            "client-rate schedule preservation postcondition failed"
        )

    if schedule_contract_ids:
        business_date = _parse_date(
            str(plan.get("business_date")), "plan.business_date", nullable=False
        )
        assert business_date is not None
        selected_after = select_effective_client_rate_schedule_rows(
            schedules_after, business_date
        )
        target_by_id = {
            item.id: item.rate_client
            for item in manifest.contracts
            if item.rate_client_present
        }
        for contract_id in schedule_contract_ids:
            selected = selected_after.get(contract_id)
            if selected is None or not _database_equal(
                "rate_client", selected.get("rate"), target_by_id[contract_id]
            ):
                raise NexusDataCorrectionError(
                    f"contract {contract_id} effective client-rate postcondition failed"
                )


async def apply_nexus_data_correction_plan(
    db: AsyncSession,
    manifest: NexusDataCorrectionManifest,
    *,
    expected_fingerprint: str,
    expected_approval_fingerprint: str,
) -> dict[str, Any]:
    """Lock, re-audit, update five fields, and delete exact periodic IDs."""
    if not _SHA256_RE.fullmatch(expected_fingerprint):
        raise NexusDataCorrectionError(
            "apply requires a 64-character lowercase plan fingerprint"
        )
    calculated_approval = approval_fingerprint(expected_fingerprint)
    if calculated_approval != expected_approval_fingerprint:
        raise NexusDataCorrectionError("approval fingerprint does not match plan")

    # This must be the first statement in the apply transaction.
    await db.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
    acquired = await db.scalar(
        text("SELECT pg_try_advisory_xact_lock(:lock_id)"), {"lock_id": _LOCK_ID}
    )
    if acquired is not True:
        raise NexusDataCorrectionError("another Nexus data correction is running")
    await db.execute(text("SET LOCAL lock_timeout = '5s'"))
    target_schema = await db.scalar(
        text(
            "SELECT n.nspname FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.oid = 'client_orders'::regclass"
        )
    )
    if not isinstance(target_schema, str) or not _SQL_IDENTIFIER_RE.fullmatch(
        target_schema
    ):
        raise NexusDataCorrectionError("client_orders schema cannot be qualified")
    # Bind every subsequent unqualified model/raw-SQL relation and custom type
    # to the same schema as the tables locked below.  Listing ``pg_temp`` last
    # prevents its usual implicit precedence from shadowing an application
    # relation during the destructive transaction.
    await db.execute(
        text(
            "SET LOCAL search_path TO pg_catalog, "
            f"{_qualified_identifier(target_schema)}, pg_temp"
        )
    )
    lock_tables = sorted(
        {
            "clients",
            "contracts",
            "contract_client_rates",
            "client_order_groups",
            "client_orders",
        }
        | {table for table, _ in _KNOWN_CLIENT_ORDER_FKS}
    )
    qualified_lock_tables = [
        _qualified_identifier(target_schema, table) for table in lock_tables
    ]
    await db.execute(
        text(
            "LOCK TABLE "
            + ", ".join(qualified_lock_tables)
            + " IN SHARE ROW EXCLUSIVE MODE"
        )
    )

    plan = await build_nexus_data_correction_plan(db, manifest, lock=True)
    if plan["fingerprint"] != expected_fingerprint:
        raise NexusDataCorrectionError(
            "plan drift: expected fingerprint does not match locked live state"
        )
    if plan["approval_fingerprint"] != expected_approval_fingerprint:
        raise NexusDataCorrectionError("locked approval fingerprint drifted")
    if plan["blockers"]:
        raise NexusDataCorrectionError("locked plan contains blockers")

    updated_count = await _apply_contract_updates(db, plan["contract_updates"])
    deletion_ids = [int(item["order_id"]) for item in plan["client_order_deletions"]]
    if deletion_ids:
        result = await db.execute(
            text(
                "DELETE FROM client_orders WHERE id = ANY(:ids) "
                "AND client_id = ANY(:client_ids) AND order_group_id IS NULL "
                "AND order_type = 'periodic'"
            ),
            {
                "ids": deletion_ids,
                "client_ids": [item[0] for item in manifest.clients],
            },
        )
        if int(result.rowcount or 0) != len(deletion_ids):
            raise NexusDataCorrectionError("client order delete cardinality drifted")

    await _assert_postconditions(db, manifest, plan)
    return {
        **plan,
        "mode": "apply",
        "ok": True,
        "applied": {
            "contract_ids": [
                int(item["contract_id"]) for item in plan["contract_updates"]
            ],
            "client_order_ids": deletion_ids,
            "contracts_updated": updated_count,
            "client_orders_deleted": len(deletion_ids),
        },
    }


def redact_nexus_data_correction_report(
    report: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the stable CI contract without PII or financial/file values."""
    summary = dict(_stable(report.get("summary", {})))
    if report.get("approval_fingerprint") is not None:
        summary["approval_fingerprint"] = report["approval_fingerprint"]
    redacted: dict[str, Any] = {
        "mode": report.get("mode"),
        "ok": bool(report.get("ok")),
        "fingerprint": report.get("fingerprint"),
        "summary": summary,
    }
    redacted["contracts"] = [
        {
            "id": int(item["contract_id"]),
            "changed_fields": sorted(
                str(change["field"]) for change in item["changes"]
            ),
        }
        for item in report.get("contract_updates", [])
    ]
    live_state = report.get("live_state", {})

    def dependency_counts_for(state_key: str) -> dict[int, dict[str, int]]:
        result: dict[int, dict[str, int]] = {}
        for key, per_order in live_state.get(state_key, {}).items():
            for raw_order_id, row_ids in per_order.items():
                order_id = int(raw_order_id)
                result.setdefault(order_id, {})[str(key)] = len(row_ids)
        return result

    dependency_counts = dependency_counts_for("dependency_row_ids")
    set_null_dependency_counts = dependency_counts_for("set_null_dependency_row_ids")
    set_null_deleted_dependency_counts = dependency_counts_for(
        "set_null_deleted_dependency_row_ids"
    )
    redacted["orders"] = [
        {
            "id": int(row["id"]),
            "client_id": int(row["client_id"]),
            "status": str(row["status"]),
            "dependency_counts": dependency_counts.get(int(row["id"]), {}),
            "set_null_dependency_counts": set_null_dependency_counts.get(
                int(row["id"]), {}
            ),
            "set_null_deleted_dependency_counts": (
                set_null_deleted_dependency_counts.get(int(row["id"]), {})
            ),
            "has_file": any(
                row.get(field) is not None for field in _FILE_EVIDENCE_FIELDS
            ),
        }
        for row in live_state.get("periodic_order_rows", [])
    ]
    legacy_null_dependency_counts = dependency_counts_for(
        "legacy_null_dependency_row_ids"
    )
    redacted["legacy_null_orders"] = [
        {
            "id": int(row["id"]),
            "client_id": int(row["client_id"]),
            "status": str(row["status"]),
            "dependency_counts": legacy_null_dependency_counts.get(int(row["id"]), {}),
            "has_file": any(
                row.get(field) is not None for field in _FILE_EVIDENCE_FIELDS
            ),
        }
        for row in live_state.get("legacy_null_order_rows", [])
    ]

    simple_blockers: list[dict[str, Any]] = []
    for item in report.get("blockers", []):
        code = str(item.get("code"))
        if code == "missing_contracts":
            simple_blockers.extend(
                {"code": code, "contract_id": int(contract_id)}
                for contract_id in item.get("contract_ids", [])
            )
        elif code in {
            "missing_client",
            "wrong_client_identity",
            "order_type_runtime_policy_drift",
        }:
            simple_blockers.append({"code": code, "client_id": int(item["client_id"])})
        elif code == "unknown_client_order_foreign_keys":
            simple_blockers.extend(
                {
                    "code": code,
                    "schema": str(fk.get("schema", "")),
                    "table": str(fk["table"]),
                    "column": str(fk["column"]),
                    "issue": str(fk.get("issue", "unknown_foreign_key")),
                }
                for fk in item.get("fks", [])
            )
        elif code == "target_client_rate_schedule_mismatch":
            simple_blockers.append(
                {"code": code, "contract_id": int(item["contract_id"])}
            )
        elif code == "client_order_dependencies":
            for key, per_order in item.get("dependencies", {}).items():
                schema, table, column = str(key).split(".", 2)
                simple_blockers.extend(
                    {
                        "code": code,
                        "order_id": int(order_id),
                        "schema": schema,
                        "table": table,
                        "column": column,
                    }
                    for order_id in per_order
                )
        elif code == "client_order_file_evidence":
            simple_blockers.extend(
                {"code": code, "order_id": int(order_id)}
                for order_id in item.get("order_ids", [])
            )
        elif code == "disallowed_client_order_type":
            simple_blockers.append(
                {
                    "code": code,
                    "order_id": int(item["order_id"]),
                    "client_id": int(item["client_id"]),
                    "effective_type": str(item["effective_type"]),
                }
            )
        elif code == "disallowed_client_order_group_type":
            simple_blockers.append(
                {
                    "code": code,
                    "group_id": int(item["group_id"]),
                    "client_id": int(item["client_id"]),
                    "effective_type": str(item["effective_type"]),
                }
            )
        else:
            simple_blockers.append({"code": code})
    redacted["blockers"] = simple_blockers
    return redacted
