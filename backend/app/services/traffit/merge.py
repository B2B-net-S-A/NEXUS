"""Deterministic three-way merge primitives for the Traffit integration.

The merge is deliberately pure and independent from SQLAlchemy.  Both inbound
and outbound workers compare Nexus and Traffit to the last acknowledged shared
snapshot.  A field changed on only one side is safe to propagate; a field
changed differently on both sides becomes an explicit admin conflict.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping


_MISSING = object()


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def snapshot_hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _flatten(value: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, child in value.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(child, Mapping):
            nested = _flatten(child, path)
            # Preserve an explicitly empty mapping as a meaningful value.
            if nested:
                result.update(nested)
            else:
                result[path] = {}
        else:
            result[path] = child
    return result


def _set_path(target: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cursor = target
    for part in parts[:-1]:
        nested = cursor.get(part)
        if not isinstance(nested, dict):
            nested = {}
            cursor[part] = nested
        cursor = nested
    cursor[parts[-1]] = value


def _public_value(value: Any) -> Any:
    # Missing and explicit null are operationally equivalent for our field
    # adapters, but this keeps conflict payloads JSON serializable.
    return None if value is _MISSING else value


@dataclass(frozen=True)
class FieldConflict:
    field_path: str
    base_value: Any
    nexus_value: Any
    traffit_value: Any
    conflict_type: str = "concurrent_update"


@dataclass
class MergeResult:
    merged: dict[str, Any] = field(default_factory=dict)
    conflicts: list[FieldConflict] = field(default_factory=list)
    apply_to_nexus: dict[str, Any] = field(default_factory=dict)
    apply_to_traffit: dict[str, Any] = field(default_factory=dict)

    @property
    def is_conflicted(self) -> bool:
        return bool(self.conflicts)


def three_way_merge(
    base: Mapping[str, Any],
    nexus: Mapping[str, Any],
    traffit: Mapping[str, Any],
    *,
    ignored_fields: Iterable[str] = (),
) -> MergeResult:
    """Merge snapshots while preserving conflicts instead of choosing a winner.

    Nested mappings are compared by dotted path. Lists are atomic because
    Traffit does not expose stable element IDs for all multi-value field types.
    Conflicted paths are omitted from both propagation patches and retain the
    base value in ``merged`` until an administrator resolves them.
    """
    base_flat = _flatten(base)
    nexus_flat = _flatten(nexus)
    traffit_flat = _flatten(traffit)
    ignored = set(ignored_fields)
    paths = sorted(set(base_flat) | set(nexus_flat) | set(traffit_flat))
    result = MergeResult()

    for path in paths:
        if path in ignored or any(path.startswith(f"{item}.") for item in ignored):
            continue
        b = base_flat.get(path, _MISSING)
        n = nexus_flat.get(path, _MISSING)
        t = traffit_flat.get(path, _MISSING)

        if n == t:
            chosen = n
        elif n == b:
            chosen = t
            _set_path(result.apply_to_nexus, path, _public_value(t))
        elif t == b:
            chosen = n
            _set_path(result.apply_to_traffit, path, _public_value(n))
        else:
            result.conflicts.append(
                FieldConflict(
                    field_path=path,
                    base_value=_public_value(b),
                    nexus_value=_public_value(n),
                    traffit_value=_public_value(t),
                )
            )
            chosen = b

        if chosen is not _MISSING:
            _set_path(result.merged, path, chosen)

    return result

