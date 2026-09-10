"""Versioned, integrity-checked CV job inputs; no pickle or dynamic imports.

The private object contains the chosen source bytes and rule values. Its key and
SHA belong in the durable job record, never in the public CV payload.
"""

import base64
from dataclasses import fields, is_dataclass
from datetime import date
import hashlib
import json

from app.services.ai_quota import QuotaState
from app.services.cv_generator_b2b.client_rules import CvRuleSnapshot
from app.services.cv_generator_b2b.standalone_service import (
    CandidateGenerationSource,
    PreparedSourceFacts,
    UploadGenerationInput,
)

MAX_SNAPSHOT_BYTES = 160 * 1024 * 1024
_TYPES = {
    kind.__name__: kind
    for kind in (
        CandidateGenerationSource,
        PreparedSourceFacts,
        UploadGenerationInput,
        CvRuleSnapshot,
        QuotaState,
    )
}


def _encode(value, depth=0):
    if depth > 32:
        raise ValueError("Snapshot nesting exceeds limit")
    if value is None or type(value) in (str, int, float, bool):
        return value
    if isinstance(value, bytes):
        return {"type": "bytes", "value": base64.b64encode(value).decode("ascii")}
    if type(value) is date:
        return {"type": "date", "value": value.isoformat()}
    if (
        is_dataclass(value)
        and type(value).__name__ in _TYPES
        and _TYPES[type(value).__name__] is type(value)
    ):
        return {
            "type": type(value).__name__,
            "value": {
                field.name: _encode(getattr(value, field.name), depth + 1)
                for field in fields(value)
            },
        }
    if type(value) in (list, tuple):
        return {
            "type": "tuple" if isinstance(value, tuple) else "list",
            "value": [_encode(item, depth + 1) for item in value],
        }
    if type(value) is dict and all(type(key) is str for key in value):
        return {
            "type": "mapping",
            "value": {key: _encode(item, depth + 1) for key, item in value.items()},
        }
    raise ValueError("Unsupported CV snapshot value")


def _decode(value, depth=0):
    if depth > 32:
        raise ValueError("Snapshot nesting exceeds limit")
    if value is None or type(value) in (str, int, float, bool):
        return value
    if not isinstance(value, dict) or set(value) != {"type", "value"}:
        raise ValueError("Invalid snapshot envelope")
    kind, data = value["type"], value["value"]
    if kind == "bytes" and isinstance(data, str):
        return base64.b64decode(data, validate=True)
    if kind == "date" and isinstance(data, str):
        return date.fromisoformat(data)
    if kind in ("list", "tuple") and isinstance(data, list):
        decoded = [_decode(item, depth + 1) for item in data]
        return tuple(decoded) if kind == "tuple" else decoded
    if kind == "mapping" and isinstance(data, dict):
        return {key: _decode(item, depth + 1) for key, item in data.items()}
    if isinstance(kind, str) and kind in _TYPES and isinstance(data, dict):
        cls = _TYPES[kind]
        if set(data) != {field.name for field in fields(cls)}:
            raise ValueError("Snapshot type fields changed")
        return cls(**{key: _decode(item, depth + 1) for key, item in data.items()})
    raise ValueError("Unsupported CV snapshot type")


def serialize_job_inputs(kind: str, kwargs: dict) -> tuple[bytes, str]:
    if not isinstance(kind, str) or kind not in {"new", "upload", "preview"}:
        raise ValueError("Unsupported CV job kind")
    if type(kwargs) is not dict:
        raise ValueError("CV job inputs must be a mapping")
    raw = json.dumps(
        {"version": 1, "kind": kind, "inputs": _encode(kwargs)},
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode()
    if len(raw) > MAX_SNAPSHOT_BYTES:
        raise ValueError("CV snapshot too large")
    return raw, hashlib.sha256(raw).hexdigest()


def deserialize_job_inputs(raw: bytes, expected_sha256: str) -> tuple[str, dict]:
    if (
        len(raw) > MAX_SNAPSHOT_BYTES
        or hashlib.sha256(raw).hexdigest() != expected_sha256
    ):
        raise ValueError("CV snapshot integrity mismatch")
    data = json.loads(
        raw, object_pairs_hook=_unique_object, parse_constant=_invalid_constant
    )
    if (
        not isinstance(data, dict)
        or set(data) != {"version", "kind", "inputs"}
        or type(data["version"]) is not int
        or data["version"] != 1
        or not isinstance(data["kind"], str)
        or data["kind"] not in {"new", "upload", "preview"}
    ):
        raise ValueError("Unsupported CV snapshot version or kind")
    inputs = _decode(data["inputs"])
    if not isinstance(inputs, dict):
        raise ValueError("CV job inputs must be a mapping")
    return data["kind"], inputs


def _invalid_constant(value):
    raise ValueError("Non-finite JSON number in snapshot")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate snapshot key")
        result[key] = value
    return result
