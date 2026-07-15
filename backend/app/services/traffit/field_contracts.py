"""Tenant metadata normalization and typed candidate field adapters."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.traffit_integration import TraffitEntityLink, TraffitFieldContract
from app.models.traffit_sync_state import TraffitSyncState
from app.services.traffit.client import TraffitClient
from app.services.traffit.merge import canonical_json


LOCAL_TO_TRAFFIT: dict[str, str] = {
    "name": "name",
    "lastname": "lastname",
    "email": "email",
    "phone": "mobile",
    "location": "candidate_location",
    "linkedin": "linkedin",
    "status": "status",
    "source": "source",
    "profile_about": "candidate_about",
    "availability_date": "availability",
    "languages": "candidate_languages",
}
TRAFFIT_TO_LOCAL = {remote: local for local, remote in LOCAL_TO_TRAFFIT.items()}
TRAFFIT_TO_LOCAL["location"] = "location"


@dataclass(frozen=True)
class FieldContract:
    remote_name: str
    capability: str
    field_type: str
    required: bool = False
    choices: tuple[Any, ...] = ()
    local_path: Optional[str] = None
    adapter: str = "passthrough"
    raw: Optional[dict[str, Any]] = None

    @property
    def quarantined(self) -> bool:
        return self.adapter == "unsupported"


def _metadata_fields(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("fields", "properties", "metadata", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            return [
                {"name": name, **(spec if isinstance(spec, dict) else {})}
                for name, spec in value.items()
            ]
    # Some tenants return a name -> specification object at the root.
    if payload and all(isinstance(v, dict) for v in payload.values()):
        return [{"name": name, **value} for name, value in payload.items()]
    return []


def _adapter_for(field_type: str) -> str:
    normalized = field_type.lower().replace("-", "_")
    if normalized in {"string", "text", "textarea", "email", "phone", "url"}:
        return "string"
    if normalized in {"integer", "int", "number", "decimal", "float"}:
        return "number"
    if normalized in {"boolean", "bool", "checkbox"}:
        return "boolean"
    if normalized in {"date", "datetime", "timestamp"}:
        return normalized
    if normalized in {"select", "choice", "dictionary", "object"}:
        return "choice"
    if normalized in {
        "multiselect",
        "multi_select",
        "array",
        "list",
        "languages",
    }:
        return "list"
    return "unsupported"


def normalize_metadata(payload: Any, capability: str) -> list[FieldContract]:
    """Normalize the documented and observed Traffit metadata response shapes."""
    contracts: list[FieldContract] = []
    for item in _metadata_fields(payload):
        name = item.get("name") or item.get("key") or item.get("id")
        if not name:
            continue
        remote_name = str(name)
        raw_type = (
            item.get("type")
            or item.get("field_type")
            or item.get("input_type")
            or "unknown"
        )
        if isinstance(raw_type, dict):
            raw_type = raw_type.get("value") or raw_type.get("name") or "unknown"
        choices_raw = item.get("choices") or item.get("options") or item.get("values")
        choices: tuple[Any, ...]
        if isinstance(choices_raw, list):
            choices = tuple(choices_raw)
        else:
            choices = ()
        # The tenant metadata is the write allow-list. Fields without a
        # dedicated Nexus column still round-trip through custom_fields,
        # including both `_SID` fields and tenant-specific system fields.
        local_path = TRAFFIT_TO_LOCAL.get(remote_name) or (
            f"custom_fields.{remote_name}"
        )
        contracts.append(
            FieldContract(
                remote_name=remote_name,
                capability=capability,
                field_type=str(raw_type),
                required=bool(item.get("required", False)),
                choices=choices,
                local_path=local_path,
                adapter=_adapter_for(str(raw_type)),
                raw=dict(item),
            )
        )
    return contracts


def metadata_hash(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _encode(value: Any, adapter: str) -> Any:
    if value is None:
        return None
    if adapter == "string":
        return str(value)
    if adapter == "number":
        return value if isinstance(value, (int, float)) else float(value)
    if adapter == "boolean":
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "tak"}
        return bool(value)
    if adapter == "date":
        return value.isoformat() if isinstance(value, (date, datetime)) else str(value)
    if adapter in {"datetime", "timestamp"}:
        return value.isoformat() if isinstance(value, (date, datetime)) else str(value)
    if adapter == "choice":
        return value.get("id", value.get("value")) if isinstance(value, dict) else value
    if adapter == "list":
        if not isinstance(value, (list, tuple, set)):
            value = [value]
        return [
            item.get("lang", item.get("name", item.get("value", item.get("id"))))
            if isinstance(item, dict)
            else item
            for item in value
        ]
    if adapter == "passthrough":
        return value
    raise ValueError(f"Unsupported Traffit field adapter: {adapter}")


def _choice_tokens(choices: Iterable[Any]) -> set[str]:
    tokens: set[str] = set()
    for choice in choices:
        values = [choice]
        if isinstance(choice, Mapping):
            values.extend(
                choice.get(key)
                for key in ("id", "value", "name", "label")
                if choice.get(key) is not None
            )
        tokens.update(canonical_json(value) for value in values)
    return tokens


def candidate_to_traffit(
    snapshot: Mapping[str, Any],
    contracts: Iterable[FieldContract],
    *,
    changed_fields: Optional[Iterable[str]] = None,
) -> tuple[dict[str, Any], list[str]]:
    """Build a write payload and return quarantined field names separately."""
    changed = set(changed_fields or ())
    payload: dict[str, Any] = {}
    quarantined: list[str] = []
    custom = snapshot.get("custom_fields")
    custom = custom if isinstance(custom, Mapping) else {}

    for contract in contracts:
        local_path = contract.local_path
        if not local_path:
            continue
        local_root = local_path.split(".", 1)[0]
        if (
            changed
            and local_path not in changed
            and local_root not in changed
            and contract.remote_name not in changed
        ):
            continue
        if local_path.startswith("custom_fields."):
            remote_key = local_path.split(".", 1)[1]
            value = custom.get(remote_key)
            if value is None:
                # Compatibility with values written by the one-shot importer.
                value = custom.get(f"traffit_{remote_key.lstrip('_')}")
            if value is None:
                value = custom.get(f"traffit{remote_key}")
        else:
            value = snapshot.get(local_path)
        if contract.quarantined:
            quarantined.append(contract.remote_name)
            continue
        try:
            encoded = _encode(value, contract.adapter)
        except (TypeError, ValueError):
            quarantined.append(contract.remote_name)
            continue
        if contract.choices and encoded is not None:
            allowed = _choice_tokens(contract.choices)
            selected = (
                list(encoded)
                if contract.adapter == "list" and isinstance(encoded, (list, tuple))
                else [encoded]
            )
            if any(canonical_json(item) not in allowed for item in selected):
                quarantined.append(contract.remote_name)
                continue
        payload[contract.remote_name] = encoded
    return payload, quarantined


def contract_from_row(row: TraffitFieldContract) -> FieldContract:
    return FieldContract(
        remote_name=row.field_name,
        capability=row.capability,
        field_type=row.data_type or "unknown",
        required=bool(row.required),
        choices=tuple(row.choices or ()),
        local_path=row.local_path,
        adapter=row.adapter,
        raw=dict(row.raw_metadata or {}),
    )


async def refresh_candidate_contracts(
    db: AsyncSession,
    client: TraffitClient,
    *,
    sample_employee_id: Optional[str | int] = None,
) -> dict[str, Any]:
    """Discover and persist POST/PATCH contracts without committing."""
    now = datetime.now(timezone.utc)
    seen: set[tuple[str, str]] = set()
    counts = {"active": 0, "quarantined": 0, "removed": 0, "skipped": 0}
    endpoints = [("create", "POST", "/employees/")]
    if sample_employee_id is not None:
        endpoints.append(
            ("patch", "PATCH", f"/employees/{sample_employee_id}")
        )
    else:
        counts["skipped"] += 1
    refreshed_capabilities: set[str] = set()
    for capability, method, endpoint in endpoints:
        refreshed_capabilities.add(capability)
        metadata = await client.fetch_metadata(method, endpoint)
        schema_digest = metadata_hash(metadata)
        for contract in normalize_metadata(metadata, capability):
            key = (contract.remote_name, capability)
            seen.add(key)
            row = await db.scalar(
                select(TraffitFieldContract).where(
                    TraffitFieldContract.field_name == contract.remote_name,
                    TraffitFieldContract.capability == capability,
                )
            )
            status = "quarantined" if contract.quarantined else "active"
            if row is None:
                row = TraffitFieldContract(
                    field_name=contract.remote_name,
                    capability=capability,
                    discovered_at=now,
                )
                db.add(row)
            row.endpoint = endpoint
            row.local_path = contract.local_path
            row.data_type = contract.field_type
            row.adapter = contract.adapter
            row.required = contract.required
            row.readable = True
            row.writable = not contract.quarantined
            row.choices = list(contract.choices)
            row.raw_metadata = contract.raw or {}
            row.schema_hash = schema_digest
            row.status = status
            row.quarantine_reason = (
                f"unsupported metadata type: {contract.field_type}"
                if contract.quarantined
                else None
            )
            row.last_seen_at = now
            counts[status] += 1

    existing = list((await db.scalars(select(TraffitFieldContract))).all())
    for row in existing:
        if (
            row.capability in refreshed_capabilities
            and (row.field_name, row.capability) not in seen
        ):
            row.status = "removed"
            row.writable = False
            counts["removed"] += 1
    await db.flush()
    return counts


async def refresh_contracts_if_due(
    db: AsyncSession,
    client: TraffitClient,
    *,
    interval: timedelta = timedelta(hours=24),
    force: bool = False,
) -> Optional[dict[str, Any]]:
    """Refresh metadata at most once per interval, with persisted health state."""
    now = datetime.now(timezone.utc)
    phase_name = "integration:field_contracts"
    state = await db.get(TraffitSyncState, phase_name)
    if state is None:
        state = TraffitSyncState(phase=phase_name, consecutive_failures=0)
        db.add(state)
        await db.flush()
    if (
        not force
        and state.last_success_at is not None
        and state.last_success_at > now - interval
    ):
        return None
    sample_id = await db.scalar(
        select(TraffitEntityLink.traffit_entity_id)
        .where(
            TraffitEntityLink.entity_type == "candidate",
            TraffitEntityLink.traffit_entity_id.is_not(None),
        )
        .limit(1)
    )
    state.last_attempt_at = now
    try:
        result = await refresh_candidate_contracts(
            db, client, sample_employee_id=sample_id
        )
        state.last_success_at = now
        state.last_status = "ok"
        state.consecutive_failures = 0
        state.last_error = None
        state.next_due_at = now + interval
        state.stats = result
        await db.flush()
        return result
    except Exception as exc:
        state.last_status = "error"
        state.consecutive_failures += 1
        state.last_error = str(exc)[:2000]
        state.next_due_at = now + timedelta(minutes=5)
        await db.flush()
        return {"error": str(exc)[:1000]}
