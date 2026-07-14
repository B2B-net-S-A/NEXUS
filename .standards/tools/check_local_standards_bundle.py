#!/usr/bin/env python3
"""Verify the hash-locked standards snapshot carried by a consumer checkout."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from _common import ValidationError, read_json, require_sha
from check_standards_drift import check_hashes, validate_lock


def check_local_bundle(lock_path: Path, consumer_root: Path, expected_ref: str) -> list[str]:
    lock = read_json(lock_path)
    validate_lock(lock)
    expected = require_sha(expected_ref, "expected_ref")
    if lock["ref"] != expected:
        return ["standards lock ref does not match the reusable workflow ref"]
    return check_hashes(consumer_root, lock["local_files"], "local snapshot")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--consumer-root", type=Path, default=Path("."))
    parser.add_argument("--lock", type=Path)
    parser.add_argument("--expected-ref", required=True)
    args = parser.parse_args(argv)
    lock_path = args.lock or args.consumer_root / ".standards/standards.lock.json"
    try:
        failures = check_local_bundle(lock_path, args.consumer_root, args.expected_ref)
    except (OSError, ValidationError) as exc:
        print(f"local standards bundle check failed: {exc}", file=sys.stderr)
        return 1
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print("local standards bundle check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
