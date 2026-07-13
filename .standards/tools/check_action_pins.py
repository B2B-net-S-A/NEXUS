#!/usr/bin/env python3
"""Reject moving GitHub Action references in workflows."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

USES_RE = re.compile(r"^\s*(?:-\s*)?uses:\s*['\"]?([^'\"\s#]+)", re.MULTILINE)
SHA_ACTION_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[^@\s]+)?@[0-9a-f]{40}$")
DOCKER_DIGEST_RE = re.compile(r"^docker://[^@\s]+@sha256:[0-9a-f]{64}$")


def validate_file(path: Path, *, allow_template_placeholder: bool = False) -> list[str]:
    failures: list[str] = []
    text = path.read_text(encoding="utf-8")
    for reference in USES_RE.findall(text):
        if reference.startswith("./"):
            continue
        if allow_template_placeholder and reference.endswith("@__STANDARDS_REF__"):
            continue
        if SHA_ACTION_RE.fullmatch(reference) or DOCKER_DIGEST_RE.fullmatch(reference):
            continue
        failures.append(f"{path}: unpinned action reference: {reference}")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*", type=Path)
    args = parser.parse_args(argv)
    paths = args.paths or sorted(Path(".github/workflows").glob("*.y*ml"))
    if not args.paths:
        paths += sorted(Path(".github/actions").glob("*/action.yml"))
        paths += sorted(Path("integration/template").rglob("*.yml.tpl"))
    failures: list[str] = []
    for path in paths:
        failures.extend(validate_file(path, allow_template_placeholder=path.suffix == ".tpl"))
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(f"action pins valid: {len(paths)} workflow file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
