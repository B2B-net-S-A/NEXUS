#!/usr/bin/env python3
"""Render a pinned integration bundle for an application repository."""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

from _common import ValidationError, file_sha256, read_json, require_sha, write_json

DEFAULT_REPOSITORY = "artur-t-96/engineering-standards"


def _central_files(root: Path) -> list[Path]:
    explicit = [root / "VERSION", root / "standard.json"]
    patterns = (
        "standards/*.md",
        "contracts/*.md",
        "schemas/*.json",
        ".github/actions/*/*.yml",
        ".github/workflows/reusable-*.yml",
        "scripts/*.py",
    )
    files = list(explicit)
    for pattern in patterns:
        files.extend(root.glob(pattern))
    return sorted(set(path for path in files if path.is_file()))


def _render_template(source: Path, target: Path, replacements: dict[str, str]) -> None:
    text = source.read_text(encoding="utf-8")
    for marker, replacement in replacements.items():
        text = text.replace(marker, replacement)
    remaining = sorted(set(re.findall(r"__[A-Z][A-Z0-9_]+__", text)))
    if remaining:
        raise ValidationError(f"unresolved template markers in {source}: {', '.join(remaining)}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def render(root: Path, output: Path, repository: str, standards_ref: str, *, force: bool = False) -> Path:
    require_sha(standards_ref, "standards_ref")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValidationError("repository must be owner/name")
    if output.exists() and any(output.iterdir()) and not force:
        raise ValidationError("output directory is not empty (use --force for a generated directory)")
    output.mkdir(parents=True, exist_ok=True)
    template = root / "integration/template"
    baseline = (template / ".standards/AGENTS.baseline.md").read_text(encoding="utf-8").strip() + "\n"
    replacements = {
        "__STANDARDS_REPOSITORY__": repository,
        "__STANDARDS_REF__": standards_ref,
        "__AGENTS_BASELINE__": baseline,
    }
    for source in sorted(template.rglob("*")):
        if not source.is_file():
            continue
        relative = source.relative_to(template)
        if relative.as_posix() == "AGENTS.md.tpl":
            target = output / "AGENTS.md"
            _render_template(source, target, replacements)
        elif source.name.endswith(".tpl"):
            target = output / relative.with_name(source.name[:-4])
            _render_template(source, target, replacements)
        else:
            target = output / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)

    snapshot_standard = output / ".standards/standard.json"
    shutil.copyfile(root / "standard.json", snapshot_standard)
    tools_directory = output / ".standards/tools"
    tools_directory.mkdir(parents=True, exist_ok=True)
    for source in sorted((root / "scripts").glob("*.py")):
        shutil.copyfile(source, tools_directory / source.name)
    local_release_workflow = output / ".github/workflows/_reusable-coolify-release.yml"
    local_release_workflow.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(
        root / ".github/workflows/reusable-coolify-release.yml",
        local_release_workflow,
    )
    central_mapping = {
        str(path.relative_to(root)): file_sha256(path)
        for path in _central_files(root)
    }
    local_paths = [output / ".standards/AGENTS.baseline.md", snapshot_standard]
    local_paths.extend(sorted(tools_directory.glob("*.py")))
    local_paths.append(local_release_workflow)
    local_mapping = {
        str(path.relative_to(output)): file_sha256(path)
        for path in local_paths
    }
    metadata = read_json(root / "standard.json")
    lock = {
        "$schema": f"https://raw.githubusercontent.com/{repository}/{standards_ref}/schemas/standards-lock.schema.json",
        "schema_version": 1,
        "repository": repository,
        "ref": standards_ref,
        "version": metadata["version"],
        "central_files": central_mapping,
        "local_files": local_mapping,
    }
    lock_path = output / ".standards/standards.lock.json"
    write_json(lock_path, lock)
    return lock_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--standards-ref", required=True)
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parent.parent
    try:
        lock = render(root, args.output, args.repository, args.standards_ref, force=args.force)
    except (OSError, ValidationError, KeyError) as exc:
        print(f"integration rendering failed: {exc}", file=sys.stderr)
        return 1
    print(f"integration bundle rendered; lock={lock}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
