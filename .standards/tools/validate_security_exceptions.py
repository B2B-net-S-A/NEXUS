#!/usr/bin/env python3
"""Validate temporary HIGH/CRITICAL exceptions and optional Trivy ignores."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from _common import ValidationError, parse_utc, read_json

ID_RE = re.compile(r"^SEC-EX-[0-9]{4}-[0-9]{3,}$")
CVE_RE = re.compile(r"^CVE-[0-9]{4}-[0-9]{4,}$")
ALLOWED_TOP_LEVEL = {
    "$schema",
    "id",
    "finding",
    "justification",
    "scope",
    "owner",
    "approved_by",
    "created_at",
    "expires_at",
    "compensating_controls",
    "tracking_issue",
    "status",
}
REQUIRED_TOP_LEVEL = ALLOWED_TOP_LEVEL - {"$schema", "tracking_issue"}


def _nonempty_strings(value: Any, field: str, minimum: int = 1) -> list[str]:
    if not isinstance(value, list) or len(value) < minimum:
        raise ValidationError(f"{field} must contain at least {minimum} item(s)")
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise ValidationError(f"{field} must contain non-empty strings")
    return value


def validate_exception(document: Any, *, now: datetime | None = None) -> str | None:
    if not isinstance(document, dict):
        raise ValidationError("exception must be a JSON object")
    missing = REQUIRED_TOP_LEVEL - set(document)
    unknown = set(document) - ALLOWED_TOP_LEVEL
    if missing:
        raise ValidationError(f"missing fields: {', '.join(sorted(missing))}")
    if unknown:
        raise ValidationError(f"unknown fields: {', '.join(sorted(unknown))}")
    if not isinstance(document["id"], str) or not ID_RE.fullmatch(document["id"]):
        raise ValidationError("id must match SEC-EX-YYYY-NNN")
    if not isinstance(document["justification"], str) or len(document["justification"].strip()) < 40:
        raise ValidationError("justification must be at least 40 characters")
    for field in ("owner", "approved_by"):
        if not isinstance(document[field], str) or len(document[field].strip()) < 3:
            raise ValidationError(f"{field} must identify a responsible person or team")
    _nonempty_strings(document["scope"], "scope")
    controls = _nonempty_strings(document["compensating_controls"], "compensating_controls")
    if any(len(item.strip()) < 10 for item in controls):
        raise ValidationError("each compensating control must be specific (10+ characters)")
    if document["status"] not in {"active", "revoked", "remediated"}:
        raise ValidationError("status must be active, revoked or remediated")

    finding = document["finding"]
    if not isinstance(finding, dict) or set(finding) - {"tool", "identifier", "cve", "severity"}:
        raise ValidationError("finding contains unknown fields")
    for field in ("tool", "identifier", "severity"):
        if field not in finding:
            raise ValidationError(f"finding.{field} is required")
    if finding["severity"] not in {"HIGH", "CRITICAL"}:
        raise ValidationError("only HIGH/CRITICAL findings use this exception process")
    cve = finding.get("cve")
    if cve is not None and (not isinstance(cve, str) or not CVE_RE.fullmatch(cve)):
        raise ValidationError("finding.cve must be null or a CVE identifier")

    created = parse_utc(document["created_at"], "created_at")
    expires = parse_utc(document["expires_at"], "expires_at")
    if expires <= created:
        raise ValidationError("expires_at must be later than created_at")
    if expires - created > timedelta(days=30):
        raise ValidationError("security exceptions cannot exceed 30 days")
    effective_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if document["status"] == "active" and expires <= effective_now:
        raise ValidationError("active security exception has expired")
    return cve


def read_trivy_ignores(path: Path) -> set[str]:
    ignored: set[str] = set()
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if not CVE_RE.fullmatch(line):
            raise ValidationError(f"{path}:{line_number}: expected one CVE per line")
        ignored.add(line)
    return ignored


def validate_paths(paths: list[Path], trivy_ignore: Path | None = None) -> int:
    active_cves: set[str] = set()
    identifiers: set[str] = set()
    for path in paths:
        document = read_json(path)
        cve = validate_exception(document)
        identifier = document["id"]
        if identifier in identifiers:
            raise ValidationError(f"duplicate exception id: {identifier}")
        identifiers.add(identifier)
        if document["status"] == "active" and cve:
            active_cves.add(cve)
    if trivy_ignore and trivy_ignore.exists():
        unapproved = read_trivy_ignores(trivy_ignore) - active_cves
        if unapproved:
            raise ValidationError(
                "Trivy ignores without an active matching exception: " + ", ".join(sorted(unapproved))
            )
    return len(paths)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--directory", type=Path, default=Path(".security/exceptions"))
    parser.add_argument("--trivy-ignore", type=Path, default=Path(".trivyignore"))
    args = parser.parse_args(argv)
    if args.paths:
        paths = args.paths
    elif args.directory.exists():
        paths = sorted(args.directory.glob("*.json"))
    else:
        paths = []
    try:
        count = validate_paths(list(paths), args.trivy_ignore)
    except ValidationError as exc:
        print(f"security exception validation failed: {exc}", file=sys.stderr)
        return 1
    print(f"security exceptions valid: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
