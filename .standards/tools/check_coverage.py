#!/usr/bin/env python3
"""Enforce changed-line coverage and an exact, non-decreasing total ratchet."""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit

from _common import ValidationError, parse_utc, read_json, require_sha, safe_join

HUNK_RE = re.compile(r"^@@ -[0-9]+(?:,[0-9]+)? \+([0-9]+)(?:,([0-9]+))? @@")
EXCEPTION_ID_RE = re.compile(r"^COV-EX-[0-9]{4}-[0-9]{3,}$")


@dataclass(frozen=True)
class Ratio:
    covered: int
    found: int

    def validate(self, field: str, *, allow_zero_found: bool = False) -> None:
        if not isinstance(self.covered, int) or isinstance(self.covered, bool):
            raise ValidationError(f"{field}.covered must be an integer")
        if not isinstance(self.found, int) or isinstance(self.found, bool):
            raise ValidationError(f"{field}.found must be an integer")
        minimum_found = 0 if allow_zero_found else 1
        if self.found < minimum_found or self.covered < 0 or self.covered > self.found:
            raise ValidationError(
                f"{field} must satisfy 0 <= covered <= found"
                + ("" if allow_zero_found else " and found > 0")
            )

    def at_least(self, other: "Ratio") -> bool:
        return self.covered * other.found >= other.covered * self.found

    def equal_rate(self, other: "Ratio") -> bool:
        return self.covered * other.found == other.covered * self.found

    def percent(self) -> float:
        return 100.0 * self.covered / self.found if self.found else 100.0


@dataclass(frozen=True)
class Ratchet:
    minimum_changed_lines_percent: int
    total_lines: Ratio
    source_extensions: tuple[str, ...]
    exclude_globs: tuple[str, ...]


@dataclass(frozen=True)
class CoverageException:
    identifier: str
    changed_lines_minimum_percent: int | None
    total_lines_minimum: Ratio | None


@dataclass(frozen=True)
class GateResult:
    changed: Ratio
    total: Ratio
    ratchet: Ratio
    exception_id: str | None


def _run_git(repo_root: Path, arguments: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    if check and result.returncode:
        safe_error = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "git failed"
        raise ValidationError(safe_error)
    return result


def _repository_relative(path: Path, repo_root: Path, field: str) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError as exc:
        raise ValidationError(f"{field} must be inside the repository") from exc


def _ratio_from_document(value: Any, field: str, *, allow_zero_found: bool = False) -> Ratio:
    if not isinstance(value, dict) or set(value) != {"covered", "found"}:
        raise ValidationError(f"{field} must contain only covered and found")
    ratio = Ratio(value["covered"], value["found"])
    ratio.validate(field, allow_zero_found=allow_zero_found)
    return ratio


def parse_ratchet(document: Any, *, allow_uninitialized: bool = False) -> Ratchet:
    allowed = {
        "$schema",
        "schema_version",
        "minimum_changed_lines_percent",
        "total_lines",
        "source_extensions",
        "exclude_globs",
    }
    required = allowed - {"$schema"}
    if not isinstance(document, dict):
        raise ValidationError("coverage ratchet must be a JSON object")
    missing = required - set(document)
    unknown = set(document) - allowed
    if missing:
        raise ValidationError(f"coverage ratchet missing fields: {', '.join(sorted(missing))}")
    if unknown:
        raise ValidationError(f"coverage ratchet has unknown fields: {', '.join(sorted(unknown))}")
    if document["schema_version"] != 1:
        raise ValidationError("coverage ratchet schema_version must be 1")
    changed_minimum = document["minimum_changed_lines_percent"]
    if (
        not isinstance(changed_minimum, int)
        or isinstance(changed_minimum, bool)
        or changed_minimum < 80
        or changed_minimum > 100
    ):
        raise ValidationError("minimum_changed_lines_percent must be an integer from 80 to 100")
    extensions = document["source_extensions"]
    if (
        not isinstance(extensions, list)
        or not extensions
        or not all(
            isinstance(item, str)
            and re.fullmatch(r"\.[A-Za-z0-9]+", item)
            for item in extensions
        )
        or len(set(extensions)) != len(extensions)
    ):
        raise ValidationError("source_extensions must contain unique extensions such as .ts or .py")
    globs = document["exclude_globs"]
    if (
        not isinstance(globs, list)
        or not all(isinstance(item, str) and item and not item.startswith("/") for item in globs)
        or len(set(globs)) != len(globs)
    ):
        raise ValidationError("exclude_globs must contain unique repository-relative glob strings")
    total = _ratio_from_document(
        document["total_lines"],
        "total_lines",
        allow_zero_found=allow_uninitialized,
    )
    if total.found == 0 and not allow_uninitialized:
        raise ValidationError(
            "coverage ratchet is not initialized; generate LCOV and record its exact total_lines"
        )
    return Ratchet(changed_minimum, total, tuple(extensions), tuple(globs))


def _nonempty_strings(value: Any, field: str) -> None:
    if not isinstance(value, list) or not value:
        raise ValidationError(f"{field} must contain at least one item")
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise ValidationError(f"{field} must contain non-empty strings")


def parse_coverage_exception(
    document: Any,
    *,
    now: datetime | None = None,
) -> CoverageException:
    allowed = {
        "$schema",
        "schema_version",
        "id",
        "justification",
        "scope",
        "owner",
        "approved_by",
        "created_at",
        "expires_at",
        "compensating_controls",
        "tracking_issue",
        "status",
        "allow",
    }
    required = allowed - {"$schema"}
    if not isinstance(document, dict):
        raise ValidationError("coverage exception must be a JSON object")
    missing = required - set(document)
    unknown = set(document) - allowed
    if missing:
        raise ValidationError(f"coverage exception missing fields: {', '.join(sorted(missing))}")
    if unknown:
        raise ValidationError(f"coverage exception has unknown fields: {', '.join(sorted(unknown))}")
    if document["schema_version"] != 1:
        raise ValidationError("coverage exception schema_version must be 1")
    if not isinstance(document["id"], str) or not EXCEPTION_ID_RE.fullmatch(document["id"]):
        raise ValidationError("coverage exception id must match COV-EX-YYYY-NNN")
    if not isinstance(document["justification"], str) or len(document["justification"].strip()) < 40:
        raise ValidationError("coverage exception justification must be at least 40 characters")
    for field in ("owner", "approved_by", "tracking_issue"):
        if not isinstance(document[field], str) or len(document[field].strip()) < 3:
            raise ValidationError(f"coverage exception {field} must identify an accountable owner")
    _nonempty_strings(document["scope"], "coverage exception scope")
    _nonempty_strings(document["compensating_controls"], "coverage exception compensating_controls")
    if any(len(item.strip()) < 10 for item in document["compensating_controls"]):
        raise ValidationError("each coverage compensating control must be specific (10+ characters)")
    if document["status"] != "active":
        raise ValidationError("the configured coverage exception must have status active")

    created = parse_utc(document["created_at"], "coverage exception created_at")
    expires = parse_utc(document["expires_at"], "coverage exception expires_at")
    if expires <= created:
        raise ValidationError("coverage exception expires_at must be later than created_at")
    if expires - created > timedelta(days=30):
        raise ValidationError("coverage exceptions cannot exceed 30 days")
    effective_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if expires <= effective_now:
        raise ValidationError("active coverage exception has expired")

    allowance = document["allow"]
    if not isinstance(allowance, dict) or not allowance:
        raise ValidationError("coverage exception allow must define a bounded allowance")
    unknown_allowance = set(allowance) - {
        "changed_lines_minimum_percent",
        "total_lines_minimum",
    }
    if unknown_allowance:
        raise ValidationError(
            "coverage exception allow has unknown fields: " + ", ".join(sorted(unknown_allowance))
        )
    changed_minimum = allowance.get("changed_lines_minimum_percent")
    if changed_minimum is not None and (
        not isinstance(changed_minimum, int)
        or isinstance(changed_minimum, bool)
        or changed_minimum < 0
        or changed_minimum > 100
    ):
        raise ValidationError("exception changed_lines_minimum_percent must be 0..100")
    total_minimum = None
    if "total_lines_minimum" in allowance:
        total_minimum = _ratio_from_document(
            allowance["total_lines_minimum"],
            "coverage exception allow.total_lines_minimum",
        )
    if changed_minimum is None and total_minimum is None:
        raise ValidationError("coverage exception allow must define at least one threshold")
    return CoverageException(document["id"], changed_minimum, total_minimum)


def _normalize_lcov_source(value: str, repo_root: Path) -> str | None:
    source = value.strip()
    if source.startswith("file://"):
        parsed = urlsplit(source)
        source = unquote(parsed.path)
    path = Path(source)
    candidate = path if path.is_absolute() else repo_root / path
    try:
        return candidate.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return None


def parse_lcov(path: Path, repo_root: Path) -> dict[str, dict[int, int]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValidationError(f"cannot read LCOV report {path}: {exc}") from exc
    coverage: dict[str, dict[int, int]] = {}
    current_source: str | None = None
    saw_source = False
    for line_number, raw in enumerate(lines, start=1):
        if raw.startswith("SF:"):
            saw_source = True
            current_source = _normalize_lcov_source(raw[3:], repo_root)
            if current_source is not None:
                coverage.setdefault(current_source, {})
        elif raw.startswith("DA:") and current_source is not None:
            parts = raw[3:].split(",")
            if len(parts) < 2:
                raise ValidationError(f"{path}:{line_number}: malformed DA record")
            try:
                source_line = int(parts[0])
                hit_count = int(parts[1])
            except ValueError as exc:
                raise ValidationError(f"{path}:{line_number}: malformed DA record") from exc
            if source_line < 1 or hit_count < 0:
                raise ValidationError(f"{path}:{line_number}: DA values must be non-negative")
            previous = coverage[current_source].get(source_line, 0)
            coverage[current_source][source_line] = max(previous, hit_count)
        elif raw == "end_of_record":
            current_source = None
    if not saw_source or not coverage:
        raise ValidationError("LCOV report contains no repository source files")
    return coverage


def _decode_patch_path(value: str) -> str | None:
    value = value.strip()
    if value == "/dev/null":
        return None
    if value.startswith('"'):
        try:
            value = ast.literal_eval(value)
        except (SyntaxError, ValueError) as exc:
            raise ValidationError("cannot decode a quoted path in git diff") from exc
    if value.startswith("b/"):
        value = value[2:]
    return PurePosixPath(value).as_posix()


def changed_lines(repo_root: Path, base_sha: str) -> dict[str, set[int]]:
    require_sha(base_sha, "coverage_base_sha")
    _run_git(repo_root, ["cat-file", "-e", f"{base_sha}^{{commit}}"])
    patch = _run_git(
        repo_root,
        [
            "-c",
            "core.quotePath=false",
            "diff",
            "--unified=0",
            "--no-ext-diff",
            "--no-color",
            "--find-renames",
            "--diff-filter=ACMR",
            f"{base_sha}...HEAD",
            "--",
        ],
    ).stdout
    result: dict[str, set[int]] = {}
    current_path: str | None = None
    for raw in patch.splitlines():
        if raw.startswith("+++ "):
            current_path = _decode_patch_path(raw[4:])
            if current_path is not None:
                result.setdefault(current_path, set())
            continue
        match = HUNK_RE.match(raw)
        if match and current_path is not None:
            start = int(match.group(1))
            count = int(match.group(2) or "1")
            result[current_path].update(range(start, start + count))
    return result


def _is_excluded(path: str, ratchet: Ratchet) -> bool:
    return any(
        fnmatch.fnmatchcase(path, pattern)
        or (pattern.startswith("**/") and fnmatch.fnmatchcase(path, pattern[3:]))
        for pattern in ratchet.exclude_globs
    )


def _is_source(path: str, ratchet: Ratchet) -> bool:
    return path.endswith(ratchet.source_extensions) and not _is_excluded(path, ratchet)


def _filter_coverage(
    coverage: dict[str, dict[int, int]],
    ratchet: Ratchet,
) -> dict[str, dict[int, int]]:
    return {
        path: lines
        for path, lines in coverage.items()
        if _is_source(path, ratchet)
    }


def _coverage_ratio(coverage: dict[str, dict[int, int]]) -> Ratio:
    found = sum(len(lines) for lines in coverage.values())
    covered = sum(sum(1 for count in lines.values() if count > 0) for lines in coverage.values())
    ratio = Ratio(covered, found)
    ratio.validate("LCOV total_lines")
    return ratio


def _changed_ratio(
    changed: dict[str, set[int]],
    coverage: dict[str, dict[int, int]],
    ratchet: Ratchet,
) -> Ratio:
    missing = sorted(
        path
        for path, lines in changed.items()
        if lines
        and _is_source(path, ratchet)
        and (path not in coverage or not coverage[path])
    )
    if missing:
        raise ValidationError(
            "changed source files are missing from LCOV (enable all/source coverage or add a reviewed exclusion): "
            + ", ".join(missing)
        )
    found = 0
    covered = 0
    for path, added_lines in changed.items():
        if not _is_source(path, ratchet):
            continue
        instrumented = coverage.get(path, {})
        for line in added_lines:
            if line not in instrumented:
                continue
            found += 1
            covered += int(instrumented[line] > 0)
    return Ratio(covered, found)


def _read_base_ratchet(repo_root: Path, base_sha: str, ratchet_path: Path) -> Ratchet | None:
    relative = _repository_relative(ratchet_path, repo_root, "ratchet path")
    result = _run_git(repo_root, ["show", f"{base_sha}:{relative}"], check=False)
    if result.returncode:
        return None
    try:
        document = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValidationError("base branch coverage ratchet is invalid JSON") from exc
    return parse_ratchet(document)


def _validate_ratchet_change(current: Ratchet, base: Ratchet | None) -> None:
    if base is None:
        return
    if current.minimum_changed_lines_percent < base.minimum_changed_lines_percent:
        raise ValidationError("minimum changed-lines coverage cannot be lowered")
    if not set(current.source_extensions).issuperset(base.source_extensions):
        raise ValidationError("source_extensions cannot remove previously covered extensions")
    if not set(current.exclude_globs).issubset(base.exclude_globs):
        raise ValidationError("exclude_globs cannot be broadened in a feature PR")
    if not current.total_lines.at_least(base.total_lines):
        raise ValidationError("tracked total-lines coverage ratchet cannot decrease")


def validate_gate(
    *,
    repo_root: Path,
    lcov_path: Path,
    ratchet_path: Path,
    base_sha: str,
    exception_path: Path | None = None,
    now: datetime | None = None,
) -> GateResult:
    repo_root = repo_root.resolve()
    require_sha(base_sha, "coverage_base_sha")
    lcov_path = safe_join(repo_root, _repository_relative(lcov_path, repo_root, "LCOV path"))
    ratchet_path = safe_join(
        repo_root,
        _repository_relative(ratchet_path, repo_root, "ratchet path"),
    )
    ratchet = parse_ratchet(read_json(ratchet_path))
    base_ratchet = _read_base_ratchet(repo_root, base_sha, ratchet_path)
    _validate_ratchet_change(ratchet, base_ratchet)

    exception = None
    if exception_path is not None and exception_path.exists():
        safe_exception = safe_join(
            repo_root,
            _repository_relative(exception_path, repo_root, "exception path"),
        )
        exception = parse_coverage_exception(read_json(safe_exception), now=now)

    coverage = _filter_coverage(parse_lcov(lcov_path, repo_root), ratchet)
    total = _coverage_ratio(coverage)
    changed = _changed_ratio(changed_lines(repo_root, base_sha), coverage, ratchet)

    changed_minimum = ratchet.minimum_changed_lines_percent
    if exception and exception.changed_lines_minimum_percent is not None:
        changed_minimum = exception.changed_lines_minimum_percent
    if changed.found and changed.covered * 100 < changed_minimum * changed.found:
        raise ValidationError(
            f"changed-lines coverage {changed.percent():.2f}% is below {changed_minimum}% "
            f"({changed.covered}/{changed.found})"
        )

    if total.equal_rate(ratchet.total_lines):
        pass
    elif total.at_least(ratchet.total_lines):
        raise ValidationError(
            f"total-lines coverage {total.covered}/{total.found} ({total.percent():.4f}%) improved above "
            f"the tracked ratchet {ratchet.total_lines.covered}/{ratchet.total_lines.found} "
            f"({ratchet.total_lines.percent():.4f}%); update the ratchet to the new exact ratio"
        )
    elif exception and exception.total_lines_minimum is not None:
        if not total.at_least(exception.total_lines_minimum):
            raise ValidationError(
                f"total-lines coverage {total.percent():.4f}% is below exception floor "
                f"{exception.total_lines_minimum.percent():.4f}%"
            )
    else:
        raise ValidationError(
            f"total-lines coverage {total.covered}/{total.found} ({total.percent():.4f}%) regressed below "
            f"the tracked ratchet {ratchet.total_lines.covered}/{ratchet.total_lines.found} "
            f"({ratchet.total_lines.percent():.4f}%); use a valid bounded exception for a regression"
        )

    return GateResult(
        changed=changed,
        total=total,
        ratchet=ratchet.total_lines,
        exception_id=exception.identifier if exception else None,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--lcov", type=Path, required=True)
    parser.add_argument("--ratchet", type=Path, default=Path(".standards/coverage-ratchet.json"))
    parser.add_argument("--base-sha", required=True)
    parser.add_argument(
        "--exception",
        type=Path,
        default=Path(".security/exceptions/coverage.json"),
    )
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    lcov_path = args.lcov if args.lcov.is_absolute() else repo_root / args.lcov
    ratchet_path = args.ratchet if args.ratchet.is_absolute() else repo_root / args.ratchet
    exception_path = args.exception if args.exception.is_absolute() else repo_root / args.exception
    try:
        result = validate_gate(
            repo_root=repo_root,
            lcov_path=lcov_path,
            ratchet_path=ratchet_path,
            base_sha=args.base_sha,
            exception_path=exception_path,
        )
    except ValidationError as exc:
        print(f"coverage gate failed: {exc}", file=sys.stderr)
        return 1
    changed = "n/a (no executable changed lines)"
    if result.changed.found:
        changed = f"{result.changed.covered}/{result.changed.found} ({result.changed.percent():.2f}%)"
    exception = f", exception={result.exception_id}" if result.exception_id else ""
    print(
        f"coverage gate passed: changed={changed}, "
        f"total={result.total.covered}/{result.total.found} ({result.total.percent():.4f}%){exception}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
