#!/usr/bin/env python3
"""Validate a Coolify Atlas execution report without printing its raw output."""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any

MODES = {"dry-run", "apply", "files-dry-run", "files-apply", "verify"}
COUNT_TABLES = {
    "sales_companies",
    "sales_contacts",
    "sales_opportunities",
    "sales_activities",
    "sales_leads",
    "sales_files",
}
IMPORT_COUNTS_REQUIRED = {
    "companies_imported",
    "contacts_imported",
    "opportunities_imported",
    "activities_imported",
    "leads_imported",
    "files_pending_storage_copy",
}
IMPORT_COUNTS = IMPORT_COUNTS_REQUIRED | {
    "person_references_without_nexus_account",
    "stages_mapped_by_outcome",
    "pipelines_extra",
    "stages_mapped",
    "companies_skipped_junk",
    "companies_review",
    "companies_parent_links",
    "companies_linked_to_clients",
    "contacts_skipped_nameless",
    "opportunities_company_adopted",
    "opportunities_company_created",
    "opportunities_skipped_unknown_stage",
    "opportunity_contacts_imported",
    "notes_skipped_empty",
    "leads_skipped_closed",
    "leads_skipped_existing_client",
}
FILE_COUNTS = {
    "files_already_copied",
    "files_skipped_owner_not_imported",
    "files_would_copy",
    "files_missing_in_storage",
    "files_copied",
}


class ReportValidationError(ValueError):
    """The execution did not contain the expected numeric report."""


def _numeric_counts(counts: Any) -> bool:
    return (
        isinstance(counts, dict)
        and bool(counts)
        and all(
            isinstance(key, str)
            and re.fullmatch(r"[a-z][a-z0-9_]{0,79}", key)
            and type(value) is int
            and value >= 0
            for key, value in counts.items()
        )
    )


def validate_report(message: str, mode: str) -> dict[str, Any]:
    """Return only a validated report, ignoring surrounding execution logs."""
    if mode not in MODES:
        raise ReportValidationError
    decoder = json.JSONDecoder()
    reports = []
    for match in re.finditer(r"\{", message):
        try:
            candidate, _ = decoder.raw_decode(message, match.start())
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict) and (
            "applied" in candidate or "error" in candidate
        ):
            reports.append(candidate)
    if not reports:
        raise ReportValidationError
    report = reports[-1]
    if "error" in report:
        error = report["error"]
        if (
            report.get("applied") is not False
            or not isinstance(error, str)
            or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", error)
        ):
            raise ReportValidationError
        return {"applied": False, "error": error}
    expected_applied = mode in {"apply", "files-apply"}
    if report.get("applied") is not expected_applied:
        raise ReportValidationError
    if mode == "verify":
        counts = report.get("counts")
        if (
            set(report) != {"applied", "mode", "counts"}
            or report.get("mode") != "counts-only"
            or not _numeric_counts(counts)
            or set(counts) != COUNT_TABLES
        ):
            raise ReportValidationError
        return {"applied": False, "mode": "counts-only", "counts": counts}
    counts = {key: value for key, value in report.items() if key != "applied"}
    if not _numeric_counts(counts):
        raise ReportValidationError
    if mode.startswith("files-"):
        if not set(counts) <= FILE_COUNTS:
            raise ReportValidationError
    elif not IMPORT_COUNTS_REQUIRED <= set(counts) <= IMPORT_COUNTS:
        raise ReportValidationError
    return {"applied": expected_applied, **counts}


def main() -> int:
    try:
        report = validate_report(sys.stdin.read(), os.environ.get("MODE", ""))
    except Exception as exc:  # noqa: BLE001 — raw execution output stays private
        print(json.dumps({"applied": False, "error": type(exc).__name__}))
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return 1 if "error" in report else 0


if __name__ == "__main__":
    sys.exit(main())
