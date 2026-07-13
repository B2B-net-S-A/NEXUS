#!/usr/bin/env python3
"""Run dependency-free structural validation for this standards repository."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from _common import ValidationError, read_json
from check_action_pins import validate_file
from check_standards_drift import check_drift
from render_integration import render

ROOT = Path(__file__).resolve().parent.parent
REQUIRED = {
    "VERSION",
    "standard.json",
    "standards/deployment.md",
    "standards/security.md",
    "standards/database.md",
    "standards/backend.md",
    "standards/frontend.md",
    "standards/incident-response.md",
    "contracts/health.md",
    ".github/workflows/reusable-quality-gate.yml",
    ".github/workflows/reusable-coolify-release.yml",
    "schemas/security-exception.schema.json",
    "schemas/release-manifest.schema.json",
    "config/branch-protection.json",
    "scripts/build_release_manifest.py",
    "scripts/coolify_exact_sha.py",
    "scripts/validate_health.py",
    "scripts/validate_release_config.py",
}


def validate_yaml(path: Path) -> None:
    if not shutil.which("ruby"):
        raise ValidationError("Ruby/Psych is required for local YAML validation")
    result = subprocess.run(
        ["ruby", "-e", "require 'yaml'; YAML.parse_file(ARGV.fetch(0))", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        safe_error = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "unknown parser error"
        raise ValidationError(f"invalid YAML {path}: {safe_error}")


def validate_python(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    try:
        compile(source, str(path), "exec")
    except SyntaxError as exc:
        raise ValidationError(f"invalid Python {path}:{exc.lineno}: {exc.msg}") from exc


def validate() -> list[str]:
    failures: list[str] = []
    for relative in sorted(REQUIRED):
        if not (ROOT / relative).is_file():
            failures.append(f"required file missing: {relative}")
    for path in sorted(ROOT.rglob("*.json")):
        try:
            read_json(path)
        except ValidationError as exc:
            failures.append(str(exc))
    metadata = read_json(ROOT / "standard.json")
    if metadata.get("version") != (ROOT / "VERSION").read_text(encoding="utf-8").strip():
        failures.append("VERSION and standard.json version differ")
    for path in sorted((ROOT / ".github/workflows").glob("*.yml")):
        try:
            validate_yaml(path)
        except ValidationError as exc:
            failures.append(str(exc))
        failures.extend(validate_file(path))
    for path in sorted((ROOT / "integration/template").rglob("*.yml.tpl")):
        try:
            validate_yaml(path)
        except ValidationError as exc:
            failures.append(str(exc))
        failures.extend(validate_file(path, allow_template_placeholder=True))
    for path in sorted((ROOT / "scripts").glob("*.py")) + sorted((ROOT / "tests").glob("*.py")):
        try:
            validate_python(path)
        except ValidationError as exc:
            failures.append(str(exc))
    try:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "bundle"
            ref = "1" * 40
            lock = render(ROOT, output, "artur-t-96/engineering-standards", ref)
            failures.extend(check_drift(lock, ROOT, output, ref))
            for path in sorted((output / ".github/workflows").glob("*.yml")):
                validate_yaml(path)
                failures.extend(validate_file(path))
    except (OSError, ValidationError, KeyError, json.JSONDecodeError) as exc:
        failures.append(f"integration bundle validation failed: {exc}")
    return failures


def main() -> int:
    failures = validate()
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print("repository validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
