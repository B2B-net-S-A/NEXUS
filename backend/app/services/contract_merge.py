"""Fail-closed planning and execution of the August 2026 contract cleanup.

The public entry points are :func:`build_contract_merge_plan` (read-only) and
:func:`apply_contract_merge_plan` (one database transaction).  The apply path
never trusts an earlier report: it locks every scoped ``contracts`` row,
rebuilds the plan from live data and requires the caller's exact SHA-256
fingerprint before changing anything.

The module intentionally uses SQL for the one-off operation.  That makes the
catalog/FK checks explicit and avoids ORM cascades silently deleting evidence
when a duplicate contract is physically removed.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today


class ContractMergeError(RuntimeError):
    """Raised when a merge cannot be proved safe."""


@dataclass(frozen=True)
class ExplicitDelete:
    keep_id: int
    delete_id: int
    expected_keep_status: str
    expected_delete_status: str
    expected_keep_client_id: int | None = None
    expected_delete_client_id: int | None = None
    expected_keep_client_name: str | None = None
    expected_delete_client_name: str | None = None


@dataclass(frozen=True)
class ContractMergeManifest:
    same_client_groups: tuple[tuple[int, ...], ...]
    different_client_noop_groups: tuple[tuple[int, ...], ...] = ()
    explicit_deletes: tuple[ExplicitDelete, ...] = ()
    source_file_sha256: str | None = None
    expected: Mapping[str, int] | None = None

    @property
    def all_ids(self) -> tuple[int, ...]:
        ids = {item for group in self.same_client_groups for item in group}
        ids.update(
            item for group in self.different_client_noop_groups for item in group
        )
        for pair in self.explicit_deletes:
            ids.add(pair.keep_id)
            ids.add(pair.delete_id)
        return tuple(sorted(ids))


@dataclass(frozen=True)
class CurrentOrderResolution:
    """Current purchase-order resolution shared by merge and API projections."""

    order: Any | None
    overlapping_orders: tuple[Any, ...]

    @property
    def needs_manual_verification(self) -> bool:
        return bool(self.overlapping_orders)


def resolve_current_client_order(
    orders: Iterable[Any], *, today: date | None = None
) -> CurrentOrderResolution:
    """Resolve the one active order covering the Warsaw business date.

    ``paused``/``draft`` orders are deliberately not current.  Zero matches is
    a valid "no current PO" result; more than one is never guessed and is
    returned as a manual-overlap condition.
    """
    boundary = today or business_today()
    current = [
        order
        for order in orders
        if _enum_text(_value(order, "status")) == "active"
        and _value(order, "start_date") is not None
        and _date_value(_value(order, "start_date")) <= boundary
        and (
            _value(order, "end_date") is None
            or _date_value(_value(order, "end_date")) >= boundary
        )
    ]
    current.sort(
        key=lambda order: (
            _date_value(_value(order, "start_date"))
            if _value(order, "start_date") is not None
            else date.min,
            int(_value(order, "id") or 0),
        )
    )
    if len(current) == 1:
        return CurrentOrderResolution(order=current[0], overlapping_orders=())
    if len(current) > 1:
        return CurrentOrderResolution(order=None, overlapping_orders=tuple(current))
    return CurrentOrderResolution(order=None, overlapping_orders=())


def _enum_text(value: Any) -> str:
    return str(getattr(value, "value", value))


def _value(row: Any, field: str) -> Any:
    if isinstance(row, Mapping):
        return row.get(field)
    return getattr(row, field)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]*$")

# Every *real* FK to contracts that the application owns today.  Audit reads
# the live PostgreSQL catalog and blocks when a future table is not in this
# list, so a schema addition cannot turn into an unnoticed CASCADE delete.
_KNOWN_CONTRACT_FKS = {
    ("b2b_contract_details", "contract_id"),
    ("b2b_generated_contracts", "contract_id"),
    ("calls", "contract_id"),
    ("client_orders", "contract_id"),
    ("contract_amendments", "contract_id"),
    ("contract_candidate_rates", "contract_id"),
    ("contract_client_rates", "contract_id"),
    ("contract_documents", "contract_id"),
    ("contract_equipment", "contract_id"),
    ("contract_framework_rates", "contract_id"),
    ("contract_onboarding_items", "contract_id"),
    ("document_signatures", "contract_id"),
    ("invoices", "contract_id"),
    ("notes", "contract_id"),
}

# Only these scalar fields are eligible for additive (empty <- populated)
# enrichment.  New columns remain untouched until deliberately reviewed.
_MERGEABLE_FIELDS = (
    "candidate_subject_ref",
    "job_id",
    "start_date",
    "end_date",
    "contract_type",
    "documents",
    "client_pm_name",
    "client_pm_email",
    "client_pm_contact_id",
    "work_mode",
    "line_manager",
    "office_location",
    "team_name",
    "project_name",
    "handover_notes",
    "termination_reason",
    "termination_lessons",
    "terminated_at",
    "target_rate_min",
    "target_rate_max",
    "project_code",
    "prolongation_status",
    "engagement_model",
    "hours_pool_total",
    "hours_pool_consumed",
    "order_consumption",
    "order_consumption_unit",
    "draft_content_html",
    "draft_template_id",
    "draft_updated_at",
    "draft_updated_by",
)

# ``to_jsonb(contracts)`` is deliberately fingerprinted, but a newly added
# column must first be classified here before the cleanup can run.  This keeps
# a production schema rollout from silently adding data that the merge neither
# preserves nor consciously ignores.
_CONTRACT_IDENTITY_FIELDS = {"id", "candidate_id", "client_id"}
_CONTRACT_RATE_CACHE_FIELDS = {
    "rate_candidate",
    "rate_client",
    "framework_rate",
    "rate_unit",
    "currency",
    "billing_hours_per_month",
    "margin",
}
_CONTRACT_LIFECYCLE_FIELDS = {"status", "voided_at", "voided_by"}
_CONTRACT_DERIVED_FIELDS = {"client_order_end_date"}
_CONTRACT_AUDIT_FIELDS = {"created_at", "updated_at"}
_CLASSIFIED_CONTRACT_FIELDS = (
    set(_MERGEABLE_FIELDS)
    | _CONTRACT_IDENTITY_FIELDS
    | _CONTRACT_RATE_CACHE_FIELDS
    | _CONTRACT_LIFECYCLE_FIELDS
    | _CONTRACT_DERIVED_FIELDS
    | _CONTRACT_AUDIT_FIELDS
)

_STATUS_RANK = {
    "active": 6,
    "ending": 5,
    "ready_for_signature": 4,
    "draft": 3,
    "ended": 2,
    "void": 1,
}

_V1_EXPECTED_COUNTS = {
    "duplicate_candidate_groups": 74,
    "same_client_groups": 69,
    "same_client_records": 139,
    "same_client_redundant_records": 70,
    "different_client_groups": 5,
    "source_rate_conflict_groups": 3,
}


def load_contract_merge_manifest(path: str | Path) -> ContractMergeManifest:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ContractMergeError("manifest must be a JSON object")
    groups_raw = raw.get("same_client_groups")
    if not isinstance(groups_raw, list) or not groups_raw:
        raise ContractMergeError("manifest.same_client_groups must be a non-empty list")

    groups: list[tuple[int, ...]] = []
    seen: set[int] = set()
    for index, value in enumerate(groups_raw):
        # Accept either the compact [1, 2] representation or {contract_ids: []}.
        ids_raw = value.get("contract_ids") if isinstance(value, dict) else value
        if not isinstance(ids_raw, list) or len(ids_raw) < 2:
            raise ContractMergeError(f"same_client_groups[{index}] needs >=2 IDs")
        ids = tuple(
            sorted(_positive_int(v, f"same_client_groups[{index}]") for v in ids_raw)
        )
        if len(ids) != len(set(ids)):
            raise ContractMergeError(f"same_client_groups[{index}] repeats an ID")
        overlap = seen.intersection(ids)
        if overlap:
            raise ContractMergeError(
                f"contract IDs occur in multiple groups: {sorted(overlap)}"
            )
        seen.update(ids)
        groups.append(ids)

    noop_groups: list[tuple[int, ...]] = []
    noop_raw = raw.get("different_client_noop_groups", [])
    if not isinstance(noop_raw, list):
        raise ContractMergeError("manifest.different_client_noop_groups must be a list")
    for index, value in enumerate(noop_raw):
        ids_raw = value.get("contract_ids") if isinstance(value, dict) else value
        if not isinstance(ids_raw, list) or len(ids_raw) != 2:
            raise ContractMergeError(
                f"different_client_noop_groups[{index}] needs exactly 2 IDs"
            )
        ids = tuple(
            sorted(
                _positive_int(v, f"different_client_noop_groups[{index}]")
                for v in ids_raw
            )
        )
        if len(ids) != len(set(ids)):
            raise ContractMergeError(
                f"different_client_noop_groups[{index}] repeats an ID"
            )
        overlap = seen.intersection(ids)
        if overlap:
            raise ContractMergeError(
                f"contract IDs occur in multiple operations: {sorted(overlap)}"
            )
        seen.update(ids)
        noop_groups.append(ids)

    explicit: list[ExplicitDelete] = []
    explicit_raw = raw.get("explicit_deletes", [])
    if not isinstance(explicit_raw, list):
        raise ContractMergeError("manifest.explicit_deletes must be a list")
    for index, value in enumerate(explicit_raw):
        if not isinstance(value, dict):
            raise ContractMergeError(f"explicit_deletes[{index}] must be an object")
        keep = _positive_int(
            value.get("keep_contract_id", value.get("keep_id", value.get("keep"))),
            "keep_contract_id",
        )
        delete = _positive_int(
            value.get(
                "delete_contract_id", value.get("delete_id", value.get("delete"))
            ),
            "delete_contract_id",
        )
        if keep == delete:
            raise ContractMergeError("explicit delete keep_id equals delete_id")
        overlap = seen.intersection((keep, delete))
        if overlap:
            raise ContractMergeError(
                f"contract IDs occur in multiple operations: {sorted(overlap)}"
            )
        seen.update((keep, delete))
        keep_status = value.get("expected_keep_status")
        delete_status = value.get("expected_delete_status")
        keep_client_id = value.get("expected_keep_client_id")
        delete_client_id = value.get("expected_delete_client_id")
        keep_client_name = value.get("expected_keep_client_name")
        delete_client_name = value.get("expected_delete_client_name")
        if not isinstance(keep_status, str) or not keep_status:
            raise ContractMergeError(
                f"explicit_deletes[{index}] needs expected_keep_status"
            )
        if not isinstance(delete_status, str) or not delete_status:
            raise ContractMergeError(
                f"explicit_deletes[{index}] needs expected_delete_status"
            )
        if keep_client_id is not None:
            keep_client_id = _positive_int(
                keep_client_id, f"explicit_deletes[{index}].expected_keep_client_id"
            )
        if delete_client_id is not None:
            delete_client_id = _positive_int(
                delete_client_id,
                f"explicit_deletes[{index}].expected_delete_client_id",
            )
        if keep_client_id is None and not isinstance(keep_client_name, str):
            raise ContractMergeError(
                f"explicit_deletes[{index}] must pin the keep client"
            )
        if delete_client_id is None and not isinstance(delete_client_name, str):
            raise ContractMergeError(
                f"explicit_deletes[{index}] must pin the delete client"
            )
        explicit.append(
            ExplicitDelete(
                keep,
                delete,
                keep_status,
                delete_status,
                keep_client_id,
                delete_client_id,
                keep_client_name,
                delete_client_name,
            )
        )

    source = raw.get("source", {})
    if not isinstance(source, dict):
        raise ContractMergeError("manifest.source must be an object")
    source_hash = raw.get("source_file_sha256") or source.get("sha256")
    if source_hash is not None and not _SHA256_RE.fullmatch(str(source_hash)):
        raise ContractMergeError(
            "source_file_sha256 must be 64 lowercase hex characters"
        )
    expected_raw = raw.get("expected", {})
    if not isinstance(expected_raw, dict) or any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in expected_raw.values()
    ):
        raise ContractMergeError(
            "manifest.expected values must be non-negative integers"
        )
    actual_counts = {
        "duplicate_candidate_groups": len(groups) + len(noop_groups) + len(explicit),
        "same_client_groups": len(groups),
        "same_client_records": sum(len(group) for group in groups),
        "same_client_redundant_records": sum(len(group) - 1 for group in groups),
        "different_client_groups": len(noop_groups) + len(explicit),
    }
    for key, actual in actual_counts.items():
        if key in expected_raw and expected_raw[key] != actual:
            raise ContractMergeError(
                f"manifest expected.{key}={expected_raw[key]} but content has {actual}"
            )
    if raw.get("schema_version") == 1:
        missing_expected = sorted(set(_V1_EXPECTED_COUNTS) - set(expected_raw))
        if missing_expected:
            raise ContractMergeError(
                f"schema v1 manifest misses expected counts: {missing_expected}"
            )
        unexpected = {
            key: expected_raw[key]
            for key, expected in _V1_EXPECTED_COUNTS.items()
            if expected_raw[key] != expected
        }
        if unexpected:
            raise ContractMergeError(
                f"schema v1 source invariants changed unexpectedly: {unexpected}"
            )
    return ContractMergeManifest(
        same_client_groups=tuple(groups),
        different_client_noop_groups=tuple(noop_groups),
        explicit_deletes=tuple(explicit),
        source_file_sha256=source_hash,
        expected=dict(expected_raw),
    )


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise ContractMergeError(f"{label} must be a positive integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ContractMergeError(f"{label} must be a positive integer") from exc
    if result <= 0 or str(value).strip() != str(result):
        raise ContractMergeError(f"{label} must be a positive integer")
    return result


def parse_rate_source_map(value: str | None) -> dict[int, int]:
    """Parse ``group=source,group=source`` without accepting arbitrary text."""
    if value is None or not value.strip():
        return {}
    result: dict[int, int] = {}
    for chunk in value.split(","):
        if not re.fullmatch(r"[1-9][0-9]*=[1-9][0-9]*", chunk):
            raise ContractMergeError("rate sources must use group=source comma syntax")
        group_raw, source_raw = chunk.split("=", 1)
        group, source = int(group_raw), int(source_raw)
        if group in result:
            raise ContractMergeError(f"duplicate rate decision for group {group}")
        result[group] = source
    return result


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _stable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(k): _stable(v)
            for k, v in sorted(value.items(), key=lambda x: str(x[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_stable(v) for v in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if hasattr(value, "value"):
        return _stable(value.value)
    return value


def plan_fingerprint(payload: Mapping[str, Any]) -> str:
    """Fingerprint the actionable plan, excluding presentation/runtime fields."""
    body = {
        k: v
        for k, v in payload.items()
        if k not in {"fingerprint", "mode", "ok", "generated_at"}
    }
    encoded = json.dumps(
        _stable(body), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def approval_fingerprint(
    plan_sha256: str,
    candidate_rate_sources: Mapping[int, int] | None = None,
    client_rate_sources: Mapping[int, int] | None = None,
) -> str:
    """Bind a human approval to the exact plan *and* normalized decisions."""
    if not _SHA256_RE.fullmatch(plan_sha256):
        raise ContractMergeError("approval requires a valid plan fingerprint")

    def normalized(value: Mapping[int, int] | None) -> list[list[int]]:
        result: list[list[int]] = []
        for raw_group, raw_source in (value or {}).items():
            group = _positive_int(raw_group, "rate decision group")
            source = _positive_int(raw_source, "rate decision source")
            result.append([group, source])
        return sorted(result)

    payload = {
        "plan_fingerprint": plan_sha256,
        "candidate_rate_sources": normalized(candidate_rate_sources),
        "client_rate_sources": normalized(client_rate_sources),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def redact_contract_merge_report(report: Mapping[str, Any]) -> dict[str, Any]:
    """Return an operationally useful report with no PII or financial values.

    The full report is intentionally kept inside the production container.  A
    CI artifact may carry this projection because it contains only database
    identifiers, counts, blocker codes and conflicting *field names*.
    """
    raw_summary = dict(report.get("summary", {}))
    raw_summary.setdefault(
        "delete_count",
        raw_summary.get("contracts_to_delete", raw_summary.get("contracts_deleted", 0)),
    )
    raw_summary.setdefault(
        "unchanged_count",
        raw_summary.get(
            "unchanged_sequential_groups",
            raw_summary.get("sequential_groups_verified_unchanged", 0),
        ),
    )
    redacted: dict[str, Any] = {
        "mode": report.get("mode"),
        "ok": bool(report.get("ok")),
        "fingerprint": report.get("fingerprint"),
        "business_date": report.get("business_date"),
        "summary": _stable(raw_summary),
    }
    if "error" in report:
        # Exception text can contain live values.  Preserve only the stable
        # machine-facing type; the workflow gets the detailed reason from its
        # exit status and a local operator can inspect the ephemeral full file.
        redacted["error_type"] = report.get("error_type", "ContractMergeError")
    if "global_blockers" in report:
        redacted["global_blocker_codes"] = [
            str(item.get("code")) for item in report.get("global_blockers", [])
        ]
    groups: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    for group in report.get("groups", []):
        blocker_codes = [str(item.get("code")) for item in group.get("blockers", [])]
        field_conflicts = [
            str(item.get("field")) for item in group.get("field_conflicts", [])
        ]
        item = {
            "action": group.get("operation"),
            "operation": group.get("operation"),
            "group_key": group.get("group_key"),
            "contract_ids": list(group.get("contract_ids", [])),
            "delete_ids": list(group.get("delete_ids", [])),
            "blocker_codes": blocker_codes,
            "field_conflicts": field_conflicts,
            "rate_conflicts": {
                "candidate": bool(group.get("candidate_rates", {}).get("conflict")),
                "client": bool(group.get("client_rates", {}).get("conflict")),
            },
        }
        if group.get("survivor_id") is not None:
            item["survivor_id"] = group.get("survivor_id")
        groups.append(item)
        if blocker_codes or field_conflicts:
            blockers.append(
                {
                    "group_key": group.get("group_key"),
                    "contract_ids": list(group.get("contract_ids", [])),
                    "codes": blocker_codes,
                    "fields": field_conflicts,
                }
            )
    if groups:
        redacted["groups"] = groups
    if blockers:
        redacted["blockers"] = blockers
    if "applied" in report:
        redacted["applied"] = [
            {
                "group_key": item.get("group_key"),
                "operation": item.get("operation"),
                "survivor_id": item.get("survivor_id"),
                "deleted_ids": list(item.get("deleted_ids", [])),
                "reparented_counts": _stable(item.get("reparented", {})),
                "candidate_rate_source_contract_id": item.get("rate_decisions", {}).get(
                    "candidate_rate_source_contract_id"
                ),
                "client_rate_source_contract_id": item.get("rate_decisions", {}).get(
                    "client_rate_source_contract_id"
                ),
            }
            for item in report.get("applied", [])
        ]
    return redacted


def choose_survivor(
    contracts: Sequence[Mapping[str, Any]], evidence: Mapping[int, Mapping[str, int]]
) -> int:
    """Choose a deterministic survivor from current-order/legal/completeness evidence."""
    if not contracts:
        raise ContractMergeError("cannot choose survivor from an empty group")

    def score(row: Mapping[str, Any]) -> tuple[int, int, int, int, int, int, int]:
        cid = int(row["id"])
        proof = evidence.get(cid, {})
        completeness = sum(not _is_empty(row.get(field)) for field in _MERGEABLE_FIELDS)
        status = _enum_text(row.get("status"))
        return (
            1 if status in {"active", "ending"} else 0,
            int(proof.get("completed_signatures", 0)),
            int(proof.get("signed_generated_contracts", 0)),
            1 if proof.get("current_orders", 0) else 0,
            int(proof.get("documents", 0)),
            completeness + _STATUS_RANK.get(status, 0),
            -cid,
        )

    return int(max(contracts, key=score)["id"])


def merge_field_plan(
    contracts: Sequence[Mapping[str, Any]], survivor_id: int
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    survivor = next(row for row in contracts if int(row["id"]) == survivor_id)
    updates: dict[str, Any] = {}
    conflicts: list[dict[str, Any]] = []
    for field in _MERGEABLE_FIELDS:
        populated = [
            (int(row["id"]), row.get(field))
            for row in contracts
            if not _is_empty(row.get(field))
        ]
        distinct: dict[str, list[int]] = {}
        values: dict[str, Any] = {}
        for cid, value in populated:
            key = json.dumps(
                _stable(value),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            distinct.setdefault(key, []).append(cid)
            values[key] = value
        if field in {"start_date", "end_date"} and populated:
            resolved = (
                min(_date_value(value) for _, value in populated)
                if field == "start_date"
                else max(_date_value(value) for _, value in populated)
            )
            current = survivor.get(field)
            if current is None or _date_value(current) != resolved:
                updates[field] = resolved
        elif len(distinct) > 1:
            conflicts.append(
                {
                    "field": field,
                    "values": [
                        {"contract_ids": ids, "value": _stable(values[key])}
                        for key, ids in sorted(distinct.items())
                    ],
                }
            )
        elif _is_empty(survivor.get(field)) and populated:
            updates[field] = populated[0][1]
    return updates, conflicts


def _rate_snapshot(
    contract: Mapping[str, Any],
    schedule: Sequence[Mapping[str, Any]],
    kind: str,
    today: date,
) -> dict[str, Any]:
    chosen = _resolved_schedule_step(schedule, today)
    raw_field = {
        "candidate": "rate_candidate",
        "client": "rate_client",
        "framework": "framework_rate",
    }[kind]
    value = chosen.get("rate") if chosen is not None else contract.get(raw_field)
    return {
        "contract_id": int(contract["id"]),
        "rate": _stable(value),
        "source": "schedule" if chosen is not None else "cache",
        "schedule_id": int(chosen["id"]) if chosen is not None else None,
        "rate_unit": _stable(contract.get("rate_unit")),
        "currency": contract.get("currency"),
        "billing_hours_per_month": contract.get("billing_hours_per_month"),
    }


def _resolved_schedule_step(
    schedule: Sequence[Mapping[str, Any]], on: date
) -> Mapping[str, Any] | None:
    """Mirror ``Contract._resolve_scheduled_rate`` for SQL-loaded rows."""
    if not schedule:
        return None
    past = [row for row in schedule if _date_value(row["effective_from"]) <= on]
    if past:
        return max(
            past,
            key=lambda row: (_date_value(row["effective_from"]), int(row["id"])),
        )
    earliest = min(_date_value(row["effective_from"]) for row in schedule)
    return max(
        (row for row in schedule if _date_value(row["effective_from"]) == earliest),
        key=lambda row: int(row["id"]),
    )


def _date_value(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _metadata_key(snapshot: Mapping[str, Any]) -> tuple[Any, Any, Any]:
    return (
        snapshot.get("rate_unit"),
        snapshot.get("currency"),
        snapshot.get("billing_hours_per_month"),
    )


def _rate_value_key(snapshot: Mapping[str, Any]) -> Decimal | None:
    value = snapshot.get("rate")
    return Decimal(str(value)) if value is not None else None


def _rate_plan(snapshots: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    filled = [dict(item) for item in snapshots if _rate_value_key(item) is not None]
    distinct_rates = {_rate_value_key(item) for item in filled}
    distinct_metadata = {_metadata_key(item) for item in snapshots}
    return {
        "snapshots": [_stable(item) for item in snapshots],
        "conflict": len(distinct_rates) > 1 or len(distinct_metadata) > 1,
        "metadata_conflict": len(distinct_metadata) > 1,
        "available_source_contract_ids": sorted(
            int(item["contract_id"]) for item in filled
        ),
        "single_source_contract_id": int(filled[0]["contract_id"])
        if filled and len(distinct_rates) <= 1 and len(distinct_metadata) <= 1
        else None,
    }


def _rate_timeline_plan(
    contracts: Sequence[Mapping[str, Any]],
    schedule: Sequence[Mapping[str, Any]],
    kind: str,
    today: date,
) -> dict[str, Any]:
    """Compare complete effective trajectories at every possible boundary."""
    boundaries = sorted(
        {today} | {_date_value(row["effective_from"]) for row in schedule}
    )
    trajectories: dict[int, list[dict[str, Any]]] = {}
    snapshots_at_today: list[dict[str, Any]] = []
    for contract in contracts:
        contract_id = int(contract["id"])
        own_schedule = [
            row for row in schedule if int(row["contract_id"]) == contract_id
        ]
        trajectory = [
            _rate_snapshot(contract, own_schedule, kind, boundary)
            | {"effective_from": boundary.isoformat()}
            for boundary in boundaries
        ]
        trajectories[contract_id] = trajectory
        snapshots_at_today.append(_rate_snapshot(contract, own_schedule, kind, today))

    divergence: list[dict[str, Any]] = []
    for index, boundary in enumerate(boundaries):
        snapshots = [trajectory[index] for trajectory in trajectories.values()]
        nonempty = {_rate_value_key(item) for item in snapshots}
        nonempty.discard(None)
        if len(nonempty) > 1:
            divergence.append(
                {
                    "effective_from": boundary.isoformat(),
                    "contract_ids": sorted(trajectories),
                }
            )
    distinct_metadata = {_metadata_key(item) for item in snapshots_at_today}
    filled_sources = sorted(
        contract_id
        for contract_id, trajectory in trajectories.items()
        if any(_rate_value_key(item) is not None for item in trajectory)
    )
    conflict = bool(divergence) or len(distinct_metadata) > 1
    available = filled_sources or sorted(trajectories)
    return {
        "snapshots": [_stable(item) for item in snapshots_at_today],
        "boundaries": [item.isoformat() for item in boundaries],
        "trajectories": {
            str(contract_id): [_stable(item) for item in trajectory]
            for contract_id, trajectory in sorted(trajectories.items())
        },
        "timeline_divergence": divergence,
        "metadata_conflict": len(distinct_metadata) > 1,
        "conflict": conflict,
        "available_source_contract_ids": available,
        "single_source_contract_id": available[0]
        if available and not conflict
        else None,
    }


def _same_day_schedule_conflicts(
    schedule: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    by_day: dict[tuple[int, str], dict[str, list[int]]] = {}
    for row in schedule:
        day = _date_value(row["effective_from"]).isoformat()
        raw_rate = row.get("rate")
        rate = (
            format(Decimal(str(raw_rate)).normalize(), "f")
            if raw_rate is not None
            else "null"
        )
        key = (int(row["contract_id"]), day)
        by_day.setdefault(key, {}).setdefault(rate, []).append(int(row["id"]))
    return [
        {
            "effective_from": day,
            "contract_id": contract_id,
            "steps": [
                {"rate": rate, "schedule_ids": sorted(ids)}
                for rate, ids in sorted(rates.items())
            ],
        }
        for (contract_id, day), rates in sorted(by_day.items())
        if len(rates) > 1
    ]


async def _fetch_contracts(
    db: AsyncSession, ids: Sequence[int], lock: bool
) -> dict[int, dict[str, Any]]:
    suffix = " FOR UPDATE OF c" if lock else ""
    rows = (
        (
            await db.execute(
                text(
                    f"SELECT c.id, to_jsonb(c) AS payload FROM contracts c WHERE c.id = ANY(:ids) ORDER BY c.id{suffix}"
                ),
                {"ids": list(ids)},
            )
        )
        .mappings()
        .all()
    )
    return {int(row["id"]): dict(row["payload"]) for row in rows}


async def _fetch_rows(
    db: AsyncSession, table: str, ids: Sequence[int]
) -> list[dict[str, Any]]:
    if not _IDENT_RE.fullmatch(table):  # pragma: no cover - constants only
        raise ContractMergeError("unsafe table identifier")
    rows = (
        (
            await db.execute(
                text(
                    f"SELECT to_jsonb(t) AS payload FROM {table} t WHERE t.contract_id = ANY(:ids) ORDER BY t.id"
                ),
                {"ids": list(ids)},
            )
        )
        .mappings()
        .all()
    )
    return [dict(row["payload"]) for row in rows]


async def _contract_fk_catalog(db: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        (
            await db.execute(
                text(
                    """
                SELECT con.conname,
                       child.relname AS table_name,
                       att.attname AS column_name,
                       array_length(con.conkey, 1) AS column_count,
                       con.confdeltype,
                       (SELECT count(*)
                          FROM pg_index pi
                          CROSS JOIN LATERAL unnest(pi.indkey) AS key(attnum)
                         WHERE pi.indrelid = child.oid AND pi.indisprimary
                       ) AS pk_column_count,
                       (SELECT pa.attname
                          FROM pg_index pi
                          CROSS JOIN LATERAL unnest(pi.indkey) AS key(attnum)
                          JOIN pg_attribute pa
                            ON pa.attrelid = child.oid AND pa.attnum = key.attnum
                         WHERE pi.indrelid = child.oid AND pi.indisprimary
                         ORDER BY pa.attnum LIMIT 1
                       ) AS pk_column_name
                FROM pg_constraint con
                JOIN pg_class parent ON parent.oid = con.confrelid
                JOIN pg_class child ON child.oid = con.conrelid
                JOIN pg_namespace ns ON ns.oid = child.relnamespace
                LEFT JOIN pg_attribute att
                  ON att.attrelid = child.oid AND att.attnum = con.conkey[1]
                WHERE con.contype = 'f'
                  AND ns.nspname = 'public'
                  AND parent.oid = 'contracts'::regclass
                ORDER BY child.relname, con.conname
                """
                )
            )
        )
        .mappings()
        .all()
    )
    return [_stable(dict(row)) for row in rows]


async def _child_inventory(
    db: AsyncSession, catalog: Sequence[Mapping[str, Any]], ids: Sequence[int]
) -> dict[int, dict[str, list[int]]]:
    tables = sorted(
        str(fk["table_name"])
        for fk in catalog
        if int(fk["column_count"]) == 1 and int(fk.get("pk_column_count") or 0) == 1
    )
    result = {int(cid): {table: [] for table in tables} for cid in ids}
    for fk in catalog:
        if int(fk["column_count"]) != 1 or int(fk.get("pk_column_count") or 0) != 1:
            continue
        table_name, column_name = str(fk["table_name"]), str(fk["column_name"])
        pk_column = str(fk["pk_column_name"])
        if not all(
            _IDENT_RE.fullmatch(value) for value in (table_name, column_name, pk_column)
        ):
            raise ContractMergeError("unsafe FK identifier returned by catalog")
        rows = (
            (
                await db.execute(
                    text(
                        f"SELECT {column_name} AS contract_id, {pk_column} AS child_id "
                        f"FROM {table_name} WHERE {column_name} = ANY(:ids) "
                        f"ORDER BY {column_name}, {pk_column}"
                    ),
                    {"ids": list(ids)},
                )
            )
            .mappings()
            .all()
        )
        for row in rows:
            result[int(row["contract_id"])][table_name].append(int(row["child_id"]))
    return result


def _child_counts_from_inventory(
    inventory: Mapping[int, Mapping[str, Sequence[int]]],
) -> dict[int, dict[str, int]]:
    return {
        int(contract_id): {
            table: len(child_ids) for table, child_ids in sorted(tables.items())
        }
        for contract_id, tables in inventory.items()
    }


async def _child_content_hashes(
    db: AsyncSession, catalog: Sequence[Mapping[str, Any]], ids: Sequence[int]
) -> dict[int, dict[str, str]]:
    result = {int(contract_id): {} for contract_id in ids}
    for fk in catalog:
        if int(fk["column_count"]) != 1 or int(fk.get("pk_column_count") or 0) != 1:
            continue
        table, column = str(fk["table_name"]), str(fk["column_name"])
        pk_column = str(fk["pk_column_name"])
        if not all(_IDENT_RE.fullmatch(value) for value in (table, column, pk_column)):
            raise ContractMergeError("unsafe FK identifier returned by catalog")
        rows = (
            (
                await db.execute(
                    text(
                        f"SELECT {column} AS contract_id, to_jsonb(t) AS payload "
                        f"FROM {table} t WHERE {column} = ANY(:ids) "
                        f"ORDER BY {column}, {pk_column}"
                    ),
                    {"ids": list(ids)},
                )
            )
            .mappings()
            .all()
        )
        grouped = {int(contract_id): [] for contract_id in ids}
        for row in rows:
            grouped[int(row["contract_id"])].append(dict(row["payload"]))
        for contract_id, payloads in grouped.items():
            encoded = json.dumps(
                _stable(payloads),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            result[contract_id][table] = hashlib.sha256(
                encoded.encode("utf-8")
            ).hexdigest()
    return result


async def _lock_child_rows(
    db: AsyncSession, catalog: Sequence[Mapping[str, Any]], ids: Sequence[int]
) -> None:
    for fk in catalog:
        table, column = str(fk["table_name"]), str(fk["column_name"])
        pk_column = str(fk.get("pk_column_name") or "")
        if (
            int(fk["column_count"]) != 1
            or int(fk.get("pk_column_count") or 0) != 1
            or (table, column) not in _KNOWN_CONTRACT_FKS
            or not _IDENT_RE.fullmatch(pk_column)
        ):
            continue
        await db.execute(
            text(
                f"SELECT {pk_column} FROM {table} "
                f"WHERE {column} = ANY(:ids) ORDER BY {pk_column} FOR UPDATE"
            ),
            {"ids": list(ids)},
        )


def _notification_link_regex(ids: Sequence[int]) -> str:
    alternatives = "|".join(str(int(value)) for value in sorted(set(ids)))
    if not alternatives:
        return r"a\A"
    return (
        rf"/contracts/({alternatives})($|[/?#])"
        rf"|(^|[?&])contract=({alternatives})($|[&#])"
    )


def _link_mentions_contract(link: str, contract_id: int) -> bool:
    return bool(re.search(_notification_link_regex([contract_id]), link))


def _replace_contract_link(link: str, loser_id: int, survivor_id: int) -> str:
    result = re.sub(
        rf"(/contracts/){loser_id}(?=$|[/?#])",
        rf"\g<1>{survivor_id}",
        link,
    )
    return re.sub(
        rf"(^|[?&])(contract=){loser_id}(?=$|[&#])",
        rf"\g<1>\g<2>{survivor_id}",
        result,
    )


async def _polymorphic_inventory(
    db: AsyncSession, ids: Sequence[int]
) -> dict[int, dict[str, Any]]:
    result = {
        int(contract_id): {
            "activities": [],
            "notifications": [],
            "notification_link_refs": [],
            "alert_dedup": [],
        }
        for contract_id in ids
    }
    payloads: dict[int, dict[str, list[dict[str, Any]]]] = {
        int(contract_id): {
            "activities": [],
            "notifications": [],
            "notification_link_refs": [],
            "alert_dedup": [],
        }
        for contract_id in ids
    }
    for table, type_column, id_column in (
        ("activities", "entity_type", "entity_id"),
        ("notifications", "related_entity_type", "related_entity_id"),
    ):
        rows = (
            (
                await db.execute(
                    text(
                        f"SELECT id, {id_column} AS contract_id, to_jsonb(t) AS payload "
                        f"FROM {table} t "
                        f"WHERE {type_column} = 'contract' "
                        f"AND {id_column} = ANY(:ids) ORDER BY id"
                    ),
                    {"ids": list(ids)},
                )
            )
            .mappings()
            .all()
        )
        for row in rows:
            contract_id = int(row["contract_id"])
            result[contract_id][table].append(int(row["id"]))
            payloads[contract_id][table].append(dict(row["payload"]))
    linked_notifications = (
        (
            await db.execute(
                text(
                    "SELECT id, link, to_jsonb(n) AS payload FROM notifications n "
                    "WHERE link IS NOT NULL AND link ~ :pattern ORDER BY id"
                ),
                {"pattern": _notification_link_regex(ids)},
            )
        )
        .mappings()
        .all()
    )
    for row in linked_notifications:
        link = str(row["link"])
        for contract_id in ids:
            if _link_mentions_contract(link, int(contract_id)):
                result[int(contract_id)]["notification_link_refs"].append(
                    int(row["id"])
                )
                payloads[int(contract_id)]["notification_link_refs"].append(
                    dict(row["payload"])
                )
    for contract_id in ids:
        rows = (
            (
                await db.execute(
                    text(
                        "SELECT id, dedup_key, created_at FROM contract_alert_dedup "
                        "WHERE dedup_key LIKE :ending OR dedup_key LIKE :client_order "
                        "ORDER BY id"
                    ),
                    {
                        "ending": f"ending:%:{contract_id}:%",
                        "client_order": f"client_order:{contract_id}:%",
                    },
                )
            )
            .mappings()
            .all()
        )
        result[int(contract_id)]["alert_dedup"] = [int(row["id"]) for row in rows]
        payloads[int(contract_id)]["alert_dedup"] = [dict(row) for row in rows]
    for contract_id in ids:
        for label in (
            "activities",
            "notifications",
            "notification_link_refs",
            "alert_dedup",
        ):
            encoded = json.dumps(
                _stable(payloads[int(contract_id)][label]),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            result[int(contract_id)][f"{label}_sha256"] = hashlib.sha256(
                encoded.encode("utf-8")
            ).hexdigest()
    return result


async def _lock_polymorphic_rows(db: AsyncSession, ids: Sequence[int]) -> None:
    await db.execute(
        text(
            "SELECT id FROM activities WHERE entity_type = 'contract' "
            "AND entity_id = ANY(:ids) ORDER BY id FOR UPDATE"
        ),
        {"ids": list(ids)},
    )
    await db.execute(
        text(
            "SELECT id FROM notifications WHERE related_entity_type = 'contract' "
            "AND related_entity_id = ANY(:ids) ORDER BY id FOR UPDATE"
        ),
        {"ids": list(ids)},
    )
    await db.execute(
        text(
            "SELECT id FROM notifications WHERE link IS NOT NULL "
            "AND link ~ :pattern ORDER BY id FOR UPDATE"
        ),
        {"pattern": _notification_link_regex(ids)},
    )


async def _evidence(
    db: AsyncSession, ids: Sequence[int], today: date
) -> dict[int, dict[str, int]]:
    result = {
        int(cid): {
            "current_orders": 0,
            "completed_signatures": 0,
            "signed_generated_contracts": 0,
            "documents": 0,
        }
        for cid in ids
    }
    queries = (
        (
            "current_orders",
            "SELECT contract_id, count(*) n FROM client_orders WHERE contract_id = ANY(:ids) "
            "AND status = 'active' AND start_date IS NOT NULL AND start_date <= :today "
            "AND (end_date IS NULL OR end_date >= :today) GROUP BY contract_id",
        ),
        (
            "completed_signatures",
            "SELECT contract_id, count(*) n FROM document_signatures WHERE contract_id = ANY(:ids) "
            "AND status = 'completed' GROUP BY contract_id",
        ),
        (
            "signed_generated_contracts",
            "SELECT contract_id, count(*) n FROM b2b_generated_contracts WHERE contract_id = ANY(:ids) "
            "AND (signed_at IS NOT NULL OR signature_status = 'signed_both') GROUP BY contract_id",
        ),
        (
            "documents",
            "SELECT contract_id, count(*) n FROM contract_documents WHERE contract_id = ANY(:ids) GROUP BY contract_id",
        ),
    )
    for label, sql in queries:
        rows = (
            (await db.execute(text(sql), {"ids": list(ids), "today": today}))
            .mappings()
            .all()
        )
        for row in rows:
            result[int(row["contract_id"])][label] = int(row["n"])
    return result


async def _names(db: AsyncSession, ids: Sequence[int]) -> dict[int, dict[str, Any]]:
    rows = (
        (
            await db.execute(
                text(
                    """
                SELECT c.id,
                       concat_ws(' ', nullif(btrim(ca.name), ''), nullif(btrim(ca.lastname), '')) AS candidate,
                       COALESCE(NULLIF(btrim(cl.display_name), ''), NULLIF(btrim(cl.name), '')) AS client
                FROM contracts c
                LEFT JOIN candidates ca ON ca.id = c.candidate_id
                JOIN clients cl ON cl.id = c.client_id
                WHERE c.id = ANY(:ids)
                """
                ),
                {"ids": list(ids)},
            )
        )
        .mappings()
        .all()
    )
    return {
        int(row["id"]): {"candidate": row["candidate"], "client": row["client"]}
        for row in rows
    }


async def _notification_collisions(
    db: AsyncSession, loser_ids: Sequence[int], survivor_id: int
) -> list[dict[str, Any]]:
    rows = (
        (
            await db.execute(
                text(
                    """
                WITH projected AS (
                    SELECT user_id, notification_type,
                           date_trunc('day', created_at AT TIME ZONE 'Europe/Warsaw')::date AS local_day,
                           CASE
                               WHEN related_entity_type = 'contract'
                                AND related_entity_id = ANY(:losers)
                               THEN :survivor
                               ELSE related_entity_id
                           END AS projected_entity_id,
                           (related_entity_type = 'contract'
                            AND related_entity_id = ANY(:losers)) AS is_moved
                    FROM notifications
                    WHERE (related_entity_type = 'contract' AND related_entity_id = ANY(:losers))
                       OR related_entity_id = :survivor
                )
                SELECT user_id, notification_type::text AS notification_type,
                       local_day, count(*) AS count
                FROM projected
                GROUP BY user_id, notification_type, local_day, projected_entity_id
                HAVING count(*) > 1 AND bool_or(is_moved)
                ORDER BY user_id, notification_type, local_day
                """
                ),
                {"losers": list(loser_ids), "survivor": survivor_id},
            )
        )
        .mappings()
        .all()
    )
    return [_stable(dict(row)) for row in rows]


async def _document_collisions(
    db: AsyncSession, ids: Sequence[int]
) -> list[dict[str, Any]]:
    rows = (
        (
            await db.execute(
                text(
                    """
                SELECT source_order_group_id, array_agg(id ORDER BY id) AS document_ids
                FROM contract_documents
                WHERE contract_id = ANY(:ids) AND source_order_group_id IS NOT NULL
                GROUP BY source_order_group_id HAVING count(*) > 1
                ORDER BY source_order_group_id
                """
                ),
                {"ids": list(ids)},
            )
        )
        .mappings()
        .all()
    )
    return [_stable(dict(row)) for row in rows]


def _project_alert_dedup_key(key: str, loser_id: int, survivor_id: int) -> str:
    parts = key.split(":")
    if len(parts) >= 4 and parts[0] == "ending" and parts[2] == str(loser_id):
        parts[2] = str(survivor_id)
    elif len(parts) >= 3 and parts[0] == "client_order" and parts[1] == str(loser_id):
        parts[1] = str(survivor_id)
    return ":".join(parts)


def _historical_reference_counts(inventory: Mapping[str, Any]) -> dict[str, int]:
    return {
        label: len(inventory.get(label, []))
        for label in (
            "activities",
            "notifications",
            "notification_link_refs",
            "alert_dedup",
        )
        if inventory.get(label)
    }


def _explicit_historical_reference_blocker(
    inventory: Mapping[str, Any],
) -> dict[str, Any] | None:
    references = _historical_reference_counts(inventory)
    return (
        {
            "code": "explicit_delete_has_historical_references",
            "references": references,
        }
        if references
        else None
    )


async def _unscoped_contract_ids(
    db: AsyncSession,
    candidate_id: int,
    client_id: int,
    scoped_ids: Sequence[int],
) -> list[int]:
    rows = (
        (
            await db.execute(
                text(
                    "SELECT id FROM contracts WHERE candidate_id = :candidate_id "
                    "AND client_id = :client_id AND NOT (id = ANY(:ids)) ORDER BY id"
                ),
                {
                    "candidate_id": candidate_id,
                    "client_id": client_id,
                    "ids": list(scoped_ids),
                },
            )
        )
        .scalars()
        .all()
    )
    return [int(value) for value in rows]


async def build_contract_merge_plan(
    db: AsyncSession,
    manifest: ContractMergeManifest,
    *,
    lock: bool = False,
    today: date | None = None,
) -> dict[str, Any]:
    """Build a complete read-only plan (row locks are optional, no writes)."""
    boundary = today or business_today()
    ids = manifest.all_ids
    contracts = await _fetch_contracts(db, ids, lock)
    names = await _names(db, ids)
    catalog = await _contract_fk_catalog(db)
    if lock:
        # Parent rows were locked above.  The table locks close non-FK writers
        # (polymorphic references/dedup keys), while ordered row locks make the
        # locked snapshot deterministic and deadlock-resistant.
        await db.execute(
            text(
                "LOCK TABLE activities, notifications, contract_alert_dedup "
                "IN SHARE ROW EXCLUSIVE MODE"
            )
        )
        await _lock_child_rows(db, catalog, ids)
        await _lock_polymorphic_rows(db, ids)
    catalog_shape = {
        (str(row["table_name"]), str(row["column_name"]))
        for row in catalog
        if int(row["column_count"]) == 1
    }
    catalog_problem = [row for row in catalog if int(row["column_count"]) != 1]
    catalog_pk_problem = [
        row for row in catalog if int(row.get("pk_column_count") or 0) != 1
    ]
    unknown_fks = sorted(catalog_shape - _KNOWN_CONTRACT_FKS)
    missing_expected_fks = sorted(_KNOWN_CONTRACT_FKS - catalog_shape)
    child_inventory = await _child_inventory(db, catalog, ids)
    child_hashes = await _child_content_hashes(db, catalog, ids)
    child_counts = _child_counts_from_inventory(child_inventory)
    evidence = await _evidence(db, ids, boundary)
    candidate_schedule = await _fetch_rows(db, "contract_candidate_rates", ids)
    client_schedule = await _fetch_rows(db, "contract_client_rates", ids)
    framework_schedule = await _fetch_rows(db, "contract_framework_rates", ids)
    all_orders = await _fetch_rows(db, "client_orders", ids)
    polymorphic_inventory = await _polymorphic_inventory(db, ids)

    global_blockers: list[dict[str, Any]] = []
    if unknown_fks or catalog_problem or catalog_pk_problem:
        global_blockers.append(
            {
                "code": "unknown_contract_foreign_keys",
                "unknown": unknown_fks,
                "multi_column": catalog_problem,
                "unsupported_primary_keys": catalog_pk_problem,
            }
        )
    if missing_expected_fks:
        global_blockers.append(
            {
                "code": "missing_expected_contract_foreign_keys",
                "missing": [list(item) for item in missing_expected_fks],
            }
        )
    unclassified = sorted(
        {field for row in contracts.values() for field in row}
        - _CLASSIFIED_CONTRACT_FIELDS
    )
    if unclassified:
        global_blockers.append(
            {"code": "unclassified_contract_columns", "fields": unclassified}
        )

    groups: list[dict[str, Any]] = []
    for group_ids in manifest.same_client_groups:
        rows = [contracts[cid] for cid in group_ids if cid in contracts]
        blockers: list[dict[str, Any]] = []
        missing = sorted(set(group_ids) - contracts.keys())
        if missing:
            blockers.append({"code": "missing_contracts", "contract_ids": missing})
        candidates = sorted(
            {row.get("candidate_id") for row in rows}, key=lambda v: (v is None, str(v))
        )
        clients = sorted({row.get("client_id") for row in rows})
        if len(candidates) != 1 or candidates == [None]:
            blockers.append(
                {"code": "candidate_identity_mismatch", "candidate_ids": candidates}
            )
        if len(clients) != 1:
            blockers.append({"code": "client_identity_mismatch", "client_ids": clients})
        if len(candidates) == 1 and candidates[0] is not None and len(clients) == 1:
            outside = await _unscoped_contract_ids(
                db, int(candidates[0]), int(clients[0]), group_ids
            )
            if outside:
                blockers.append(
                    {
                        "code": "unscoped_duplicate_contract",
                        "contract_ids": outside,
                    }
                )
        if any(_enum_text(row.get("status")) == "void" for row in rows):
            blockers.append({"code": "void_contract_in_merge_group"})
        lifecycle_values = {
            field: sorted(
                {
                    json.dumps(_stable(row.get(field)), sort_keys=True)
                    for row in rows
                    if not _is_empty(row.get(field))
                }
            )
            for field in ("voided_at", "voided_by")
        }
        if any(lifecycle_values.values()):
            blockers.append(
                {
                    "code": "contract_lifecycle_metadata_present",
                    "fields": [
                        field for field, values in lifecycle_values.items() if values
                    ],
                }
            )

        group_orders = [
            order for order in all_orders if int(order["contract_id"]) in group_ids
        ]
        active_missing_start = [
            order
            for order in group_orders
            if _enum_text(order.get("status")) == "active"
            and order.get("start_date") is None
            and (
                order.get("end_date") is None
                or _date_value(order["end_date"]) >= boundary
            )
        ]
        if active_missing_start:
            blockers.append(
                {
                    "code": "active_order_missing_start_date",
                    "order_ids": sorted(
                        int(order["id"]) for order in active_missing_start
                    ),
                }
            )
        if len(clients) == 1:
            mismatched_orders = [
                order
                for order in group_orders
                if int(order["client_id"]) != int(clients[0])
            ]
            if mismatched_orders:
                blockers.append(
                    {
                        "code": "client_order_client_mismatch",
                        "order_ids": sorted(
                            int(order["id"]) for order in mismatched_orders
                        ),
                    }
                )
        by_order_group: dict[int, list[int]] = {}
        for order in group_orders:
            if order.get("order_group_id") is not None:
                by_order_group.setdefault(int(order["order_group_id"]), []).append(
                    int(order["id"])
                )
        duplicate_order_groups = {
            str(group_id): sorted(order_ids)
            for group_id, order_ids in by_order_group.items()
            if len(order_ids) > 1
        }
        if duplicate_order_groups:
            blockers.append(
                {
                    "code": "duplicate_client_order_group_lines",
                    "order_groups": duplicate_order_groups,
                }
            )

        order_resolution = resolve_current_client_order(group_orders, today=boundary)
        current_orders = (
            list(order_resolution.overlapping_orders)
            if order_resolution.needs_manual_verification
            else (
                [order_resolution.order] if order_resolution.order is not None else []
            )
        )
        if order_resolution.needs_manual_verification:
            blockers.append(
                {
                    "code": "overlapping_current_orders",
                    "orders": [
                        {
                            k: _stable(order.get(k))
                            for k in (
                                "id",
                                "contract_id",
                                "status",
                                "start_date",
                                "end_date",
                                "rate_client",
                                "currency",
                            )
                        }
                        for order in current_orders
                    ],
                }
            )
        elif order_resolution.order is None and any(
            _enum_text(row.get("status")) in {"active", "ending"} for row in rows
        ):
            blockers.append({"code": "live_contract_has_no_current_order"})

        survivor_id = choose_survivor(rows, evidence) if rows else min(group_ids)
        field_updates, field_conflicts = (
            merge_field_plan(rows, survivor_id) if rows else ({}, [])
        )
        if field_conflicts:
            blockers.append(
                {
                    "code": "contract_field_conflicts",
                    "fields": sorted(item["field"] for item in field_conflicts),
                }
            )
        if order_resolution.order is not None:
            field_updates["client_order_end_date"] = order_resolution.order.get(
                "end_date"
            )

        cand_rows = [
            row for row in candidate_schedule if int(row["contract_id"]) in group_ids
        ]
        cli_rows = [
            row for row in client_schedule if int(row["contract_id"]) in group_ids
        ]
        candidate_rates = _rate_timeline_plan(rows, cand_rows, "candidate", boundary)
        client_rates = _rate_timeline_plan(rows, cli_rows, "client", boundary)
        if candidate_rates["conflict"]:
            blockers.append(
                {"code": "candidate_rate_conflict", "requires_decision": True}
            )
        if client_rates["conflict"]:
            blockers.append({"code": "client_rate_conflict", "requires_decision": True})
        candidate_schedule_conflicts = _same_day_schedule_conflicts(cand_rows)
        if candidate_schedule_conflicts:
            blockers.append(
                {
                    "code": "candidate_rate_schedule_same_day_conflict",
                    "items": candidate_schedule_conflicts,
                }
            )
        client_schedule_conflicts = _same_day_schedule_conflicts(cli_rows)
        if client_schedule_conflicts:
            blockers.append(
                {
                    "code": "client_rate_schedule_same_day_conflict",
                    "items": client_schedule_conflicts,
                }
            )
        framework_rows = [
            row for row in framework_schedule if int(row["contract_id"]) in group_ids
        ]
        framework_rates = _rate_timeline_plan(
            rows, framework_rows, "framework", boundary
        )
        if framework_rates["conflict"]:
            blockers.append({"code": "framework_rate_conflict"})
        framework_schedule_conflicts = _same_day_schedule_conflicts(framework_rows)
        if framework_schedule_conflicts:
            blockers.append(
                {
                    "code": "framework_rate_schedule_same_day_conflict",
                    "items": framework_schedule_conflicts,
                }
            )

        b2b_count = sum(
            child_counts.get(cid, {}).get("b2b_contract_details", 0)
            for cid in group_ids
        )
        if b2b_count > 1:
            blockers.append(
                {"code": "multiple_b2b_contract_details", "count": b2b_count}
            )
        doc_collisions = await _document_collisions(db, group_ids)
        if doc_collisions:
            blockers.append(
                {"code": "contract_document_unique_collision", "items": doc_collisions}
            )
        notif_collisions = await _notification_collisions(
            db,
            [cid for cid in group_ids if cid != survivor_id],
            survivor_id,
        )
        if notif_collisions:
            blockers.append(
                {"code": "notification_unique_collision", "items": notif_collisions}
            )
        group_key = min(group_ids)
        groups.append(
            {
                "operation": "merge_same_client",
                "group_key": group_key,
                "contract_ids": list(group_ids),
                "survivor_id": survivor_id,
                "delete_ids": [cid for cid in group_ids if cid != survivor_id],
                "candidate": names.get(survivor_id, {}).get("candidate"),
                "client": names.get(survivor_id, {}).get("client"),
                "contract_rows": [_stable(row) for row in rows],
                "current_orders": [_stable(row) for row in current_orders],
                "field_updates": _stable(field_updates),
                "field_conflicts": field_conflicts,
                "candidate_rates": candidate_rates,
                "client_rates": client_rates,
                "framework_rates": framework_rates,
                "rate_schedules": {
                    "candidate": [_stable(row) for row in cand_rows],
                    "client": [_stable(row) for row in cli_rows],
                    "framework": [_stable(row) for row in framework_rows],
                },
                "children": {str(cid): child_counts.get(cid, {}) for cid in group_ids},
                "child_row_ids": {
                    str(cid): child_inventory.get(cid, {}) for cid in group_ids
                },
                "child_row_hashes": {
                    str(cid): child_hashes.get(cid, {}) for cid in group_ids
                },
                "polymorphic_row_ids": {
                    str(cid): polymorphic_inventory.get(cid, {}) for cid in group_ids
                },
                "blockers": blockers,
            }
        )

    for group_ids in manifest.different_client_noop_groups:
        rows = [contracts[cid] for cid in group_ids if cid in contracts]
        blockers: list[dict[str, Any]] = []
        missing = sorted(set(group_ids) - contracts.keys())
        if missing:
            blockers.append({"code": "missing_contracts", "contract_ids": missing})
        candidates = {row.get("candidate_id") for row in rows}
        clients = {row.get("client_id") for row in rows}
        if len(candidates) != 1 or None in candidates:
            blockers.append(
                {
                    "code": "candidate_identity_mismatch",
                    "candidate_ids": sorted(
                        candidates, key=lambda value: (value is None, str(value))
                    ),
                }
            )
        if len(clients) != 2:
            blockers.append(
                {"code": "noop_clients_not_distinct", "client_ids": sorted(clients)}
            )
        noop_order_client_mismatches = [
            int(order["id"])
            for order in all_orders
            if int(order["contract_id"]) in group_ids
            and int(order["client_id"])
            != int(contracts[int(order["contract_id"])]["client_id"])
        ]
        if noop_order_client_mismatches:
            blockers.append(
                {
                    "code": "client_order_client_mismatch",
                    "order_ids": sorted(noop_order_client_mismatches),
                }
            )

        ended_rows = [row for row in rows if _enum_text(row.get("status")) == "ended"]
        live_rows = [
            row for row in rows if _enum_text(row.get("status")) in {"active", "ending"}
        ]
        if len(ended_rows) != 1 or len(live_rows) != 1:
            blockers.append(
                {
                    "code": "noop_not_sequential_status_pattern",
                    "statuses": {
                        str(row["id"]): _enum_text(row.get("status")) for row in rows
                    },
                }
            )

        periods: dict[str, dict[str, Any]] = {}
        if len(ended_rows) == 1:
            ended = ended_rows[0]
            ended_orders = [
                order
                for order in all_orders
                if int(order["contract_id"]) == int(ended["id"])
                and order.get("start_date") is not None
                and order.get("end_date") is not None
                and (
                    _enum_text(order.get("status")) == "completed"
                    or (
                        _enum_text(order.get("status")) == "active"
                        and _date_value(order["end_date"]) < boundary
                    )
                )
            ]
            ended_orders.sort(
                key=lambda order: (
                    _date_value(order["end_date"]),
                    _date_value(order["start_date"]),
                    int(order["id"]),
                )
            )
            if not ended_orders:
                blockers.append({"code": "noop_ended_contract_has_no_eligible_order"})
            else:
                latest_end = _date_value(ended_orders[-1]["end_date"])
                latest = [
                    order
                    for order in ended_orders
                    if _date_value(order["end_date"]) == latest_end
                ]
                if len(latest) != 1:
                    blockers.append(
                        {
                            "code": "noop_ended_order_period_ambiguous",
                            "order_ids": sorted(int(order["id"]) for order in latest),
                        }
                    )
                else:
                    ended_period_source = latest[0]
                    periods["ended"] = {
                        "contract_id": int(ended["id"]),
                        "start_date": _stable(ended_period_source.get("start_date")),
                        "end_date": _stable(ended_period_source.get("end_date")),
                        "order_id": int(ended_period_source["id"]),
                        "order_status": _enum_text(ended_period_source.get("status")),
                    }
        if len(live_rows) == 1:
            live = live_rows[0]
            live_orders = [
                order
                for order in all_orders
                if int(order["contract_id"]) == int(live["id"])
            ]
            missing_start = [
                int(order["id"])
                for order in live_orders
                if _enum_text(order.get("status")) == "active"
                and order.get("start_date") is None
            ]
            if missing_start:
                blockers.append(
                    {
                        "code": "active_order_missing_start_date",
                        "order_ids": sorted(missing_start),
                    }
                )
            live_resolution = resolve_current_client_order(live_orders, today=boundary)
            if live_resolution.needs_manual_verification:
                blockers.append(
                    {
                        "code": "overlapping_current_orders",
                        "order_ids": sorted(
                            int(order["id"])
                            for order in live_resolution.overlapping_orders
                        ),
                    }
                )
            elif live_resolution.order is None:
                blockers.append({"code": "noop_live_contract_has_no_current_order"})
            else:
                periods["live"] = {
                    "contract_id": int(live["id"]),
                    "start_date": _stable(live_resolution.order.get("start_date")),
                    "end_date": _stable(live_resolution.order.get("end_date")),
                    "order_id": int(live_resolution.order["id"]),
                }
        if "ended" in periods and "live" in periods:
            ended_end = periods["ended"].get("end_date")
            live_start = periods["live"].get("start_date")
            if (
                ended_end is None
                or live_start is None
                or _date_value(ended_end) >= _date_value(live_start)
            ):
                blockers.append(
                    {
                        "code": "noop_periods_overlap_or_are_incomplete",
                        "periods": periods,
                    }
                )
        representative = int(rows[0]["id"]) if rows else min(group_ids)
        groups.append(
            {
                "operation": "sequential_history_noop",
                "group_key": min(group_ids),
                "contract_ids": list(group_ids),
                "survivor_id": None,
                "delete_ids": [],
                "candidate": names.get(representative, {}).get("candidate"),
                "clients": [names.get(cid, {}).get("client") for cid in group_ids],
                "contract_rows": [_stable(row) for row in rows],
                "periods": periods,
                "child_row_ids": {
                    str(cid): child_inventory.get(cid, {}) for cid in group_ids
                },
                "child_row_hashes": {
                    str(cid): child_hashes.get(cid, {}) for cid in group_ids
                },
                "polymorphic_row_ids": {
                    str(cid): polymorphic_inventory.get(cid, {}) for cid in group_ids
                },
                "blockers": blockers,
            }
        )

    for pair in manifest.explicit_deletes:
        pair_ids = (pair.keep_id, pair.delete_id)
        blockers: list[dict[str, Any]] = []
        missing = sorted(set(pair_ids) - contracts.keys())
        if missing:
            blockers.append({"code": "missing_contracts", "contract_ids": missing})
        pair_rows = [contracts[cid] for cid in pair_ids if cid in contracts]
        pair_candidates = {row.get("candidate_id") for row in pair_rows}
        pair_clients = {row.get("client_id") for row in pair_rows}
        if len(pair_candidates) != 1 or None in pair_candidates:
            blockers.append(
                {
                    "code": "explicit_delete_candidate_mismatch",
                    "candidate_ids": sorted(
                        pair_candidates, key=lambda value: (value is None, str(value))
                    ),
                }
            )
        if len(pair_clients) != 2:
            blockers.append(
                {
                    "code": "explicit_delete_clients_not_distinct",
                    "client_ids": sorted(pair_clients),
                }
            )
        if pair.keep_id in contracts:
            keep = contracts[pair.keep_id]
            if (
                pair.expected_keep_client_id is not None
                and int(keep["client_id"]) != pair.expected_keep_client_id
            ):
                blockers.append({"code": "explicit_keep_client_snapshot_drift"})
            if _enum_text(keep.get("status")) != pair.expected_keep_status:
                blockers.append({"code": "explicit_keep_status_snapshot_drift"})
            if (
                pair.expected_keep_client_name is not None
                and names.get(pair.keep_id, {}).get("client")
                != pair.expected_keep_client_name
            ):
                blockers.append({"code": "explicit_keep_client_snapshot_drift"})
        if pair.delete_id in contracts:
            delete = contracts[pair.delete_id]
            if (
                pair.expected_delete_client_id is not None
                and int(delete["client_id"]) != pair.expected_delete_client_id
            ):
                blockers.append({"code": "explicit_delete_client_snapshot_drift"})
            if _enum_text(delete.get("status")) != pair.expected_delete_status:
                blockers.append({"code": "explicit_delete_status_snapshot_drift"})
            if (
                pair.expected_delete_client_name is not None
                and names.get(pair.delete_id, {}).get("client")
                != pair.expected_delete_client_name
            ):
                blockers.append({"code": "explicit_delete_client_snapshot_drift"})
        delete_children = child_counts.get(pair.delete_id, {})
        protected = {table: count for table, count in delete_children.items() if count}
        if protected:
            blockers.append(
                {"code": "explicit_delete_has_children", "children": protected}
            )
        historical_blocker = _explicit_historical_reference_blocker(
            polymorphic_inventory.get(pair.delete_id, {})
        )
        if historical_blocker:
            blockers.append(historical_blocker)
        groups.append(
            {
                "operation": "explicit_delete_wrong_project",
                "group_key": min(pair_ids),
                "contract_ids": list(pair_ids),
                "survivor_id": pair.keep_id,
                "delete_ids": [pair.delete_id],
                "candidate": names.get(pair.keep_id, {}).get("candidate"),
                "client": names.get(pair.keep_id, {}).get("client"),
                "deleted_client": names.get(pair.delete_id, {}).get("client"),
                "contract_rows": [
                    _stable(contracts[cid]) for cid in pair_ids if cid in contracts
                ],
                "children": {str(cid): child_counts.get(cid, {}) for cid in pair_ids},
                "child_row_ids": {
                    str(cid): child_inventory.get(cid, {}) for cid in pair_ids
                },
                "child_row_hashes": {
                    str(cid): child_hashes.get(cid, {}) for cid in pair_ids
                },
                "polymorphic_row_ids": {
                    str(cid): polymorphic_inventory.get(cid, {}) for cid in pair_ids
                },
                "blockers": blockers,
            }
        )

    blocking_count = len(global_blockers) + sum(
        len(group["blockers"]) for group in groups
    )
    plan: dict[str, Any] = {
        "mode": "audit",
        "ok": True,
        "generated_at": datetime.now().astimezone().isoformat(),
        "business_date": boundary.isoformat(),
        "manifest": {
            "source_file_sha256": manifest.source_file_sha256,
            "expected": _stable(manifest.expected or {}),
            "same_client_group_count": len(manifest.same_client_groups),
            "different_client_noop_count": len(manifest.different_client_noop_groups),
            "explicit_delete_count": len(manifest.explicit_deletes),
            "contract_ids": list(ids),
        },
        "schema": {
            "contract_foreign_keys": catalog,
            "missing_expected_foreign_keys": [
                list(item) for item in missing_expected_fks
            ],
            "contract_column_classification": {
                "mergeable": sorted(_MERGEABLE_FIELDS),
                "identity": sorted(_CONTRACT_IDENTITY_FIELDS),
                "rate_cache": sorted(_CONTRACT_RATE_CACHE_FIELDS),
                "lifecycle": sorted(_CONTRACT_LIFECYCLE_FIELDS),
                "order_derived": sorted(_CONTRACT_DERIVED_FIELDS),
                "audit_timestamps": sorted(_CONTRACT_AUDIT_FIELDS),
            },
        },
        "summary": {
            "groups": len(groups),
            "same_client_groups": len(manifest.same_client_groups),
            "unchanged_sequential_groups": len(manifest.different_client_noop_groups),
            "explicit_deletes": len(manifest.explicit_deletes),
            "contracts_to_delete": sum(len(group["delete_ids"]) for group in groups),
            "blocking_issues": blocking_count,
            "rate_conflict_groups": sum(
                1
                for group in groups
                if group["operation"] == "merge_same_client"
                and (
                    group["candidate_rates"]["conflict"]
                    or group["client_rates"]["conflict"]
                )
            ),
        },
        "global_blockers": global_blockers,
        "groups": groups,
    }
    plan["fingerprint"] = plan_fingerprint(plan)
    return plan


def _validate_decision(
    group: Mapping[str, Any], kind: str, decisions: Mapping[int, int]
) -> int | None:
    rate_plan = group[f"{kind}_rates"]
    key = int(group["group_key"])
    if not rate_plan["conflict"]:
        if key in decisions:
            source = int(decisions[key])
            if source not in rate_plan["available_source_contract_ids"]:
                raise ContractMergeError(
                    f"invalid {kind} rate source {source} for group {key}"
                )
            return source
        return rate_plan["single_source_contract_id"]
    if key not in decisions:
        raise ContractMergeError(f"missing {kind} rate decision for group {key}")
    source = int(decisions[key])
    if source not in rate_plan["available_source_contract_ids"]:
        raise ContractMergeError(f"invalid {kind} rate source {source} for group {key}")
    return source


async def _update_contract_fields(
    db: AsyncSession, contract_id: int, updates: Mapping[str, Any]
) -> None:
    if not updates:
        return
    bad = set(updates) - (set(_MERGEABLE_FIELDS) | {"client_order_end_date"})
    if bad:
        raise ContractMergeError(f"unsafe contract fields in plan: {sorted(bad)}")
    assignments = ", ".join(
        f"{field} = CAST(:v_{field} AS jsonb)"
        if field == "documents"
        else f"{field} = :v_{field}"
        for field in updates
    )
    params = {
        f"v_{field}": _database_value(field, value) for field, value in updates.items()
    }
    params["contract_id"] = contract_id
    await db.execute(
        text(
            f"UPDATE contracts SET {assignments}, updated_at = NOW() WHERE id = :contract_id"
        ),
        params,
    )


def _database_value(field: str, value: Any) -> Any:
    if value is None:
        return None
    if field == "documents":
        return json.dumps(_stable(value), ensure_ascii=False, sort_keys=True)
    if field in {
        "start_date",
        "end_date",
        "terminated_at",
        "client_order_end_date",
    }:
        return _date_value(value)
    if field in {"draft_updated_at"}:
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if field in {
        "framework_rate",
        "target_rate_min",
        "target_rate_max",
        "order_consumption",
        "rate_candidate",
        "rate_client",
    }:
        return Decimal(str(value))
    return value


async def _reparent_fks(
    db: AsyncSession,
    catalog: Sequence[Mapping[str, Any]],
    loser_ids: Sequence[int],
    survivor_id: int,
) -> dict[str, int]:
    moved: dict[str, int] = {}
    for fk in catalog:
        table, column = str(fk["table_name"]), str(fk["column_name"])
        if int(fk["column_count"]) != 1 or (table, column) not in _KNOWN_CONTRACT_FKS:
            raise ContractMergeError(f"refusing unknown contract FK {table}.{column}")
        result = await db.execute(
            text(
                f"UPDATE {table} SET {column} = :survivor WHERE {column} = ANY(:losers)"
            ),
            {"survivor": survivor_id, "losers": list(loser_ids)},
        )
        moved[table] = int(result.rowcount or 0)
    return moved


async def _repoint_polymorphic(
    db: AsyncSession, loser_ids: Sequence[int], survivor_id: int
) -> dict[str, int]:
    activity = await db.execute(
        text(
            "UPDATE activities SET entity_id = :survivor WHERE entity_type = 'contract' AND entity_id = ANY(:losers)"
        ),
        {"survivor": survivor_id, "losers": list(loser_ids)},
    )
    notifications = await db.execute(
        text(
            "UPDATE notifications SET related_entity_id = :survivor "
            "WHERE related_entity_type = 'contract' "
            "AND related_entity_id = ANY(:losers)"
        ),
        {"survivor": survivor_id, "losers": list(loser_ids)},
    )
    link_rows = (
        (
            await db.execute(
                text(
                    "SELECT id, link FROM notifications WHERE link IS NOT NULL "
                    "AND link ~ :pattern ORDER BY id"
                ),
                {"pattern": _notification_link_regex(loser_ids)},
            )
        )
        .mappings()
        .all()
    )
    link_count = 0
    for row in link_rows:
        old_link = str(row["link"])
        new_link = old_link
        for loser_id in sorted(int(value) for value in loser_ids):
            new_link = _replace_contract_link(new_link, loser_id, survivor_id)
        if new_link == old_link:
            continue
        updated = await db.execute(
            text(
                "UPDATE notifications SET link = :new_link "
                "WHERE id = :row_id AND link = :old_link"
            ),
            {
                "new_link": new_link,
                "row_id": int(row["id"]),
                "old_link": old_link,
            },
        )
        if int(updated.rowcount or 0) != 1:
            raise ContractMergeError("notification link drifted while locked")
        link_count += 1
    return {
        "activities": int(activity.rowcount or 0),
        "notifications": int(notifications.rowcount or 0),
        "notification_links": link_count,
    }


async def _alias_alert_dedup(
    db: AsyncSession, loser_ids: Sequence[int], survivor_id: int
) -> int:
    inserted = 0
    rows = (
        (
            await db.execute(
                text("SELECT id, dedup_key FROM contract_alert_dedup ORDER BY id")
            )
        )
        .mappings()
        .all()
    )
    for row in rows:
        key = str(row["dedup_key"])
        projected = key
        for loser_id in loser_ids:
            projected = _project_alert_dedup_key(key, int(loser_id), survivor_id)
            if projected != key:
                break
        if projected == key:
            continue
        result = await db.execute(
            text(
                "INSERT INTO contract_alert_dedup (dedup_key, created_at) "
                "VALUES (:dedup_key, NOW()) ON CONFLICT (dedup_key) DO NOTHING"
            ),
            {"dedup_key": projected},
        )
        inserted += int(result.rowcount or 0)
        original = await db.scalar(
            text("SELECT dedup_key FROM contract_alert_dedup WHERE id = :row_id"),
            {"row_id": int(row["id"])},
        )
        alias_exists = await db.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM contract_alert_dedup "
                "WHERE dedup_key = :dedup_key)"
            ),
            {"dedup_key": projected},
        )
        if original != key or alias_exists is not True:
            raise ContractMergeError("contract alert dedup alias postcondition failed")
    return inserted


def _snapshot_for_source(
    group: Mapping[str, Any],
    decisions: Mapping[str, Any],
    moved: Mapping[str, int],
    changed_fields: Iterable[str],
) -> dict[str, Any]:
    # Activity details are exposed by a broad operational endpoint.  Keep a
    # strict allowlist of IDs/counts/field names and never store source values.
    return {
        "operation": group["operation"],
        "source_contract_ids": group["contract_ids"],
        "deleted_contract_ids": group["delete_ids"],
        "survivor_contract_id": group["survivor_id"],
        "changed_fields": sorted(set(changed_fields)),
        "source_id_decisions": {
            key: int(value) if value is not None else None
            for key, value in sorted(decisions.items())
        },
        "reparented_rows": dict(moved),
    }


async def _insert_resolution_rates(
    db: AsyncSession,
    table: str,
    survivor_id: int,
    trajectory: Sequence[Mapping[str, Any]],
) -> None:
    if table not in {
        "contract_candidate_rates",
        "contract_client_rates",
        "contract_framework_rates",
    }:
        raise ContractMergeError("unsafe rate table")
    for item in trajectory:
        if item.get("rate") is None:
            continue
        await db.execute(
            text(
                f"INSERT INTO {table} "
                "(contract_id, rate, effective_from, note, created_at, updated_at) "
                "VALUES (:contract_id, :rate, :effective_from, :note, NOW(), NOW())"
            ),
            {
                "contract_id": survivor_id,
                "rate": Decimal(str(item["rate"])),
                "effective_from": _date_value(item["effective_from"]),
                "note": "Rozstrzygnięcie scalania zduplikowanych kontraktów 2026-08",
            },
        )


async def _assert_no_fk_rows(
    db: AsyncSession, catalog: Sequence[Mapping[str, Any]], ids: Sequence[int]
) -> None:
    inventory = await _child_inventory(db, catalog, ids)
    leftovers = {
        cid: value
        for cid, value in inventory.items()
        if any(bool(child_ids) for child_ids in value.values())
    }
    if leftovers:
        raise ContractMergeError(f"FK rows remain before DELETE: {leftovers}")


def _selected_snapshot(
    rate_plan: Mapping[str, Any], source_id: int | None
) -> Mapping[str, Any] | None:
    snapshots = [dict(item) for item in rate_plan.get("snapshots", [])]
    if source_id is not None:
        return next(
            (item for item in snapshots if int(item["contract_id"]) == source_id),
            None,
        )
    return snapshots[0] if snapshots else None


def _selected_trajectory(
    rate_plan: Mapping[str, Any], source_id: int | None
) -> list[dict[str, Any]]:
    if source_id is None:
        return []
    return [
        dict(item) for item in rate_plan.get("trajectories", {}).get(str(source_id), [])
    ]


def _trajectory_rate_on(trajectory: Sequence[Mapping[str, Any]], boundary: date) -> Any:
    for item in trajectory:
        if _date_value(item["effective_from"]) == boundary:
            return item.get("rate")
    raise ContractMergeError(f"rate trajectory misses boundary {boundary}")


async def _assert_rate_trajectory(
    db: AsyncSession,
    survivor_id: int,
    kind: str,
    trajectory: Sequence[Mapping[str, Any]],
) -> None:
    if not trajectory:
        return
    table = {
        "candidate": "contract_candidate_rates",
        "client": "contract_client_rates",
        "framework": "contract_framework_rates",
    }[kind]
    contract = (await _fetch_contracts(db, [survivor_id], False))[survivor_id]
    schedule = await _fetch_rows(db, table, [survivor_id])
    for expected in trajectory:
        boundary = _date_value(expected["effective_from"])
        actual = _rate_snapshot(contract, schedule, kind, boundary).get("rate")
        if (Decimal(str(actual)) if actual is not None else None) != (
            Decimal(str(expected.get("rate")))
            if expected.get("rate") is not None
            else None
        ):
            raise ContractMergeError(
                f"{kind} resolution trajectory postcondition failed for {survivor_id}"
            )


async def _assert_contract_postconditions(
    db: AsyncSession, plan: Mapping[str, Any]
) -> None:
    for group in plan["groups"]:
        contract_ids = [int(value) for value in group["contract_ids"]]
        operation = group["operation"]
        existing = [
            int(value)
            for value in (
                await db.execute(
                    text("SELECT id FROM contracts WHERE id = ANY(:ids) ORDER BY id"),
                    {"ids": contract_ids},
                )
            )
            .scalars()
            .all()
        ]
        if operation == "sequential_history_noop":
            if existing != sorted(contract_ids):
                raise ContractMergeError(
                    f"sequential history changed for group {group['group_key']}"
                )
            continue
        survivor_id = int(group["survivor_id"])
        if existing != [survivor_id]:
            raise ContractMergeError(
                f"contract delete postcondition failed for group {group['group_key']}"
            )
        if operation == "merge_same_client":
            survivor_row = next(
                row for row in group["contract_rows"] if int(row["id"]) == survivor_id
            )
            scoped = [
                int(value)
                for value in (
                    await db.execute(
                        text(
                            "SELECT id FROM contracts WHERE candidate_id = :candidate_id "
                            "AND client_id = :client_id ORDER BY id"
                        ),
                        {
                            "candidate_id": survivor_row["candidate_id"],
                            "client_id": survivor_row["client_id"],
                        },
                    )
                )
                .scalars()
                .all()
            ]
            if scoped != [survivor_id]:
                raise ContractMergeError(
                    f"same-client cardinality postcondition failed for group {group['group_key']}"
                )


async def apply_contract_merge_plan(
    db: AsyncSession,
    manifest: ContractMergeManifest,
    *,
    expected_fingerprint: str,
    expected_approval_fingerprint: str,
    candidate_rate_sources: Mapping[int, int] | None = None,
    client_rate_sources: Mapping[int, int] | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Lock, re-audit, merge, and physically delete duplicates atomically."""
    if not _SHA256_RE.fullmatch(expected_fingerprint):
        raise ContractMergeError(
            "apply requires a 64-character lowercase SHA-256 fingerprint"
        )
    if not _SHA256_RE.fullmatch(expected_approval_fingerprint):
        raise ContractMergeError(
            "apply requires a 64-character lowercase approval fingerprint"
        )
    candidate_decisions = {
        _positive_int(group, "candidate rate decision group"): _positive_int(
            source, "candidate rate decision source"
        )
        for group, source in (candidate_rate_sources or {}).items()
    }
    client_decisions = {
        _positive_int(group, "client rate decision group"): _positive_int(
            source, "client rate decision source"
        )
        for group, source in (client_rate_sources or {}).items()
    }
    calculated_approval = approval_fingerprint(
        expected_fingerprint, candidate_decisions, client_decisions
    )
    if calculated_approval != expected_approval_fingerprint:
        raise ContractMergeError("approval fingerprint does not match rate decisions")

    boundary = today or business_today()
    # Must be the first database statement of apply.  Operational audit/apply
    # runs use separate sessions; direct callers must likewise end any prior
    # read transaction before invoking apply.
    await db.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
    acquired = await db.scalar(
        text("SELECT pg_try_advisory_xact_lock(:lock_id)"),
        {"lock_id": 2026082601},
    )
    if acquired is not True:
        raise ContractMergeError("another contract merge transaction is running")
    # Blocks a new duplicate contract INSERT between the audit and the final
    # cardinality assertion.  Lock order is advisory -> contracts table ->
    # contract rows -> polymorphic tables -> FK child rows.
    await db.execute(text("SET LOCAL lock_timeout = '5s'"))
    await db.execute(text("LOCK TABLE contracts IN SHARE ROW EXCLUSIVE MODE"))
    plan = await build_contract_merge_plan(db, manifest, lock=True, today=boundary)
    if plan["fingerprint"] != expected_fingerprint:
        raise ContractMergeError(
            f"plan drift: expected {expected_fingerprint}, live {plan['fingerprint']}"
        )
    catalog = plan["schema"]["contract_foreign_keys"]
    if plan["global_blockers"]:
        raise ContractMergeError(f"global blockers: {plan['global_blockers']}")

    valid_keys = {
        int(group["group_key"])
        for group in plan["groups"]
        if group["operation"] == "merge_same_client"
    }
    extra = (set(candidate_decisions) | set(client_decisions)) - valid_keys
    if extra:
        raise ContractMergeError(
            f"rate decisions reference unknown groups: {sorted(extra)}"
        )

    # Resolve and validate *every* group before the first UPDATE.  Locks are
    # harmless; a blocker or bad decision still leaves the transaction with no
    # data mutation and the caller rolls it back.
    prepared: list[dict[str, Any]] = []
    sequential_groups_verified = 0
    for group in plan["groups"]:
        blockers = [
            item
            for item in group["blockers"]
            if item["code"] not in {"candidate_rate_conflict", "client_rate_conflict"}
        ]
        if blockers:
            raise ContractMergeError(
                f"group {group['group_key']} has blockers: {blockers}"
            )
        if group["operation"] == "sequential_history_noop":
            sequential_groups_verified += 1
            continue
        survivor_id = int(group["survivor_id"])
        loser_ids = [int(cid) for cid in group["delete_ids"]]
        decisions: dict[str, Any] = {}

        if group["operation"] == "explicit_delete_wrong_project":
            prepared.append(
                {
                    "group": group,
                    "survivor_id": survivor_id,
                    "loser_ids": loser_ids,
                    "decisions": decisions,
                    "safe_updates": {},
                    "financial_values": {},
                    "resolution_trajectories": {},
                    "changed_fields": [],
                }
            )
            continue

        candidate_source = _validate_decision(group, "candidate", candidate_decisions)
        client_source = _validate_decision(group, "client", client_decisions)
        framework_source = group["framework_rates"]["single_source_contract_id"]
        decisions = {
            "candidate_rate_source_contract_id": candidate_source,
            "client_rate_source_contract_id": client_source,
            "framework_rate_source_contract_id": framework_source,
        }
        chosen_candidate = _selected_snapshot(
            group["candidate_rates"], candidate_source
        )
        chosen_client = _selected_snapshot(group["client_rates"], client_source)
        metadata = [
            item for item in (chosen_candidate, chosen_client) if item is not None
        ]
        if len(metadata) == 2 and _metadata_key(metadata[0]) != _metadata_key(
            metadata[1]
        ):
            raise ContractMergeError(
                f"candidate/client rate metadata disagree in group {group['group_key']}"
            )
        selected_meta = metadata[0] if metadata else None
        safe_updates = dict(group["field_updates"])

        trajectories = {
            "candidate": _selected_trajectory(
                group["candidate_rates"], candidate_source
            ),
            "client": _selected_trajectory(group["client_rates"], client_source),
            "framework": _selected_trajectory(
                group["framework_rates"], framework_source
            ),
        }
        financial_values: dict[str, Any] = {}
        for kind, field in (
            ("candidate", "rate_candidate"),
            ("client", "rate_client"),
            ("framework", "framework_rate"),
        ):
            trajectory = trajectories[kind]
            if trajectory:
                current = _trajectory_rate_on(trajectory, boundary)
                if current is not None:
                    financial_values[field] = _database_value(field, current)
        if selected_meta:
            financial_values.update(
                rate_unit=selected_meta["rate_unit"],
                currency=selected_meta["currency"],
                billing_hours_per_month=selected_meta["billing_hours_per_month"],
            )
        changed_fields = sorted(set(safe_updates) | set(financial_values))
        if {"rate_candidate", "rate_client"}.intersection(financial_values):
            changed_fields.append("margin")
        prepared.append(
            {
                "group": group,
                "survivor_id": survivor_id,
                "loser_ids": loser_ids,
                "decisions": decisions,
                "safe_updates": safe_updates,
                "financial_values": financial_values,
                "resolution_trajectories": trajectories,
                "changed_fields": sorted(set(changed_fields)),
            }
        )

    applied: list[dict[str, Any]] = []
    for item in prepared:
        group = item["group"]
        survivor_id = item["survivor_id"]
        loser_ids = item["loser_ids"]
        decisions = item["decisions"]
        if group["operation"] == "explicit_delete_wrong_project":
            # Preserve historical polymorphic Activity/Notification references;
            # moving them to a different client would rewrite history.
            moved: dict[str, int] = {}
        else:
            await _update_contract_fields(db, survivor_id, item["safe_updates"])
            financial_values = item["financial_values"]
            if financial_values:
                assignments = ", ".join(
                    f"{field} = :{field}" for field in financial_values
                )
                await db.execute(
                    text(
                        f"UPDATE contracts SET {assignments}, "
                        "margin = CASE WHEN COALESCE(:new_client, rate_client) IS NOT NULL "
                        "AND COALESCE(:new_candidate, rate_candidate) IS NOT NULL "
                        "THEN COALESCE(:new_client, rate_client) - COALESCE(:new_candidate, rate_candidate) ELSE NULL END, "
                        "updated_at = NOW() WHERE id = :contract_id"
                    ),
                    {
                        **financial_values,
                        "new_client": financial_values.get("rate_client"),
                        "new_candidate": financial_values.get("rate_candidate"),
                        "contract_id": survivor_id,
                    },
                )
            moved = await _reparent_fks(db, catalog, loser_ids, survivor_id)
            moved.update(await _repoint_polymorphic(db, loser_ids, survivor_id))
            moved["contract_alert_dedup_aliases"] = await _alias_alert_dedup(
                db, loser_ids, survivor_id
            )
            for kind, table in (
                ("candidate", "contract_candidate_rates"),
                ("client", "contract_client_rates"),
                ("framework", "contract_framework_rates"),
            ):
                trajectory = item["resolution_trajectories"][kind]
                await _insert_resolution_rates(db, table, survivor_id, trajectory)
                await _assert_rate_trajectory(db, survivor_id, kind, trajectory)

        # Every true FK must be gone/reparented before physical deletion.  This
        # catches both a coding omission and a concurrent child insert (parent
        # contracts are row-locked, so normal writers cannot race silently).
        await _assert_no_fk_rows(db, catalog, loser_ids)
        deleted = await db.execute(
            text("DELETE FROM contracts WHERE id = ANY(:ids)"), {"ids": loser_ids}
        )
        if int(deleted.rowcount or 0) != len(loser_ids):
            raise ContractMergeError(
                f"DELETE count mismatch in group {group['group_key']}"
            )

        details = _snapshot_for_source(group, decisions, moved, item["changed_fields"])
        await db.execute(
            text(
                "INSERT INTO activities "
                "(entity_type, entity_id, action, details, external_source, external_id, created_at, updated_at) "
                "VALUES ('contract', :survivor, :action, CAST(:details AS jsonb), "
                "'contract_merge_2026_08', :external_id, NOW(), NOW())"
            ),
            {
                "survivor": survivor_id,
                "action": "contracts_merged"
                if group["operation"] == "merge_same_client"
                else "wrong_contract_deleted",
                "details": json.dumps(
                    _stable(details), ensure_ascii=False, sort_keys=True
                ),
                "external_id": f"{group['operation']}:{group['group_key']}:{expected_approval_fingerprint[:16]}",
            },
        )
        applied.append(
            {
                "group_key": group["group_key"],
                "operation": group["operation"],
                "survivor_id": survivor_id,
                "deleted_ids": loser_ids,
                "reparented": moved,
                "rate_decisions": decisions,
            }
        )

    await _assert_contract_postconditions(db, plan)
    result: dict[str, Any] = {
        "mode": "apply",
        "ok": True,
        "generated_at": datetime.now().astimezone().isoformat(),
        "business_date": boundary.isoformat(),
        "fingerprint": expected_fingerprint,
        "approval_fingerprint": expected_approval_fingerprint,
        "summary": {
            "groups_applied": len(applied),
            "sequential_groups_verified_unchanged": sequential_groups_verified,
            "contracts_deleted": sum(len(item["deleted_ids"]) for item in applied),
        },
        "applied": applied,
    }
    return result
