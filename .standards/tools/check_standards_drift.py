#!/usr/bin/env python3
"""Compare a consumer lock and snapshots with an immutable central checkout."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

from _common import ValidationError, file_sha256, read_json, require_sha, safe_join

CENTRAL_REF_RE_TEMPLATE = (
    r"uses:\s*{repository}/\.github/(?:workflows|actions)/[^@\s]+@([0-9a-f]{{40}})"
)


def _require_mapping(value: Any, field: str) -> dict[str, str]:
    if not isinstance(value, dict) or not value:
        raise ValidationError(f"{field} must be a non-empty object")
    if not all(isinstance(key, str) and isinstance(digest, str) for key, digest in value.items()):
        raise ValidationError(f"{field} must map paths to SHA-256 strings")
    return value


def validate_lock(lock: Any) -> None:
    if not isinstance(lock, dict) or lock.get("schema_version") != 1:
        raise ValidationError("unsupported standards lock")
    repository = lock.get("repository")
    if not isinstance(repository, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValidationError("invalid central repository in lock")
    require_sha(str(lock.get("ref", "")), "standards ref")
    if not isinstance(lock.get("version"), str) or not lock["version"]:
        raise ValidationError("lock version is required")
    for field in ("central_files", "local_files"):
        mapping = _require_mapping(lock.get(field), field)
        for path, digest in mapping.items():
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValidationError(f"invalid digest for {path}")


def check_hashes(root: Path, mapping: dict[str, str], label: str) -> list[str]:
    failures: list[str] = []
    for relative, expected in mapping.items():
        path = safe_join(root, relative)
        if not path.is_file():
            failures.append(f"{label} file missing: {relative}")
        elif file_sha256(path) != expected:
            failures.append(f"{label} drift: {relative}")
    return failures


def check_workflow_refs(consumer_root: Path, repository: str, expected_ref: str) -> list[str]:
    failures: list[str] = []
    pattern = re.compile(CENTRAL_REF_RE_TEMPLATE.format(repository=re.escape(repository)))
    for path in sorted((consumer_root / ".github/workflows").glob("*.y*ml")):
        for actual in pattern.findall(path.read_text(encoding="utf-8")):
            if actual != expected_ref:
                failures.append(f"workflow uses central ref {actual}, lock expects {expected_ref}: {path}")
    return failures


def check_drift(lock_path: Path, central_root: Path, consumer_root: Path, expected_ref: str | None = None) -> list[str]:
    lock = read_json(lock_path)
    validate_lock(lock)
    if expected_ref and lock["ref"] != require_sha(expected_ref, "expected_ref"):
        return ["standards lock ref does not match the checked-out central ref"]
    central_version = (central_root / "VERSION").read_text(encoding="utf-8").strip()
    failures: list[str] = []
    if central_version != lock["version"]:
        failures.append(f"version drift: central={central_version}, lock={lock['version']}")
    failures.extend(check_hashes(central_root, lock["central_files"], "central"))
    failures.extend(check_hashes(consumer_root, lock["local_files"], "local snapshot"))
    failures.extend(check_workflow_refs(consumer_root, lock["repository"], lock["ref"]))
    baseline = consumer_root / ".standards/AGENTS.baseline.md"
    agents = consumer_root / "AGENTS.md"
    if baseline.is_file():
        if not agents.is_file():
            failures.append("tracked AGENTS.md is missing")
        elif baseline.read_text(encoding="utf-8").strip() not in agents.read_text(encoding="utf-8"):
            failures.append("AGENTS.md no longer contains the locked shared baseline")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", type=Path, default=Path(".standards/standards.lock.json"))
    parser.add_argument("--central-root", type=Path, required=True)
    parser.add_argument("--consumer-root", type=Path, default=Path("."))
    parser.add_argument("--expected-ref")
    args = parser.parse_args(argv)
    try:
        failures = check_drift(args.lock, args.central_root, args.consumer_root, args.expected_ref)
    except (OSError, ValidationError) as exc:
        print(f"standards drift check failed: {exc}", file=sys.stderr)
        return 1
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print("standards drift check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
