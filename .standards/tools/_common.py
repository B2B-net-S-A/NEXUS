"""Shared dependency-free helpers for the engineering standards tooling."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ValidationError(ValueError):
    """A safe, user-facing validation failure."""


def require_sha(value: str, field: str = "sha", *, allow_zero: bool = False) -> str:
    if not SHA40_RE.fullmatch(value):
        raise ValidationError(f"{field} must be a lowercase 40-character Git SHA")
    if not allow_zero and value == "0" * 40:
        raise ValidationError(f"{field} cannot be the all-zero template SHA")
    return value


def require_https_url(value: str, field: str, *, allow_local_http: bool = False) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValidationError(f"{field} must be a non-empty URL without surrounding whitespace")
    if any(ord(character) < 33 or ord(character) == 127 for character in value):
        raise ValidationError(f"{field} must not contain whitespace or control characters")
    try:
        parsed = urlsplit(value)
        # Accessing port forces urllib to validate malformed/non-numeric ports.
        parsed.port
    except ValueError as exc:
        raise ValidationError(f"{field} is not a valid URL") from exc
    local_http = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not (allow_local_http and local_http):
        raise ValidationError(f"{field} must use HTTPS")
    if not parsed.hostname:
        raise ValidationError(f"{field} must contain a hostname")
    if parsed.username is not None or parsed.password is not None:
        raise ValidationError(f"{field} must not contain embedded credentials")
    if parsed.query or parsed.fragment:
        raise ValidationError(f"{field} must not contain a query string or fragment")
    return value


def parse_utc(value: str, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be an ISO-8601 string")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValidationError(f"{field} must be a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValidationError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def utc_now_string() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def read_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot read valid JSON from {path}: {exc}") from exc


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    temporary.replace(path)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_join(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    resolved_root = root.resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise ValidationError(f"unsafe path outside repository: {relative}") from exc
    return candidate
