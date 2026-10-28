"""Synthetic execution logs must never turn a failed Atlas job green."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "atlas_import_report_under_test", ROOT / ".github/scripts/atlas_import_report.py"
)
assert SPEC and SPEC.loader
reporter = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = reporter
SPEC.loader.exec_module(reporter)

DATA = {
    "companies_imported": 9123,
    "contacts_imported": 9920,
    "opportunities_imported": 1635,
    "activities_imported": 11318,
    "leads_imported": 2500,
    "files_pending_storage_copy": 6029,
}
COUNTS = {
    "sales_companies": 9123,
    "sales_contacts": 9920,
    "sales_opportunities": 1635,
    "sales_activities": 11318,
    "sales_leads": 2500,
    "sales_files": 6029,
}
SENTINEL = "===NEXUS-ATLAS-IMPORT-END==="


class AtlasImportWorkflowReportTests(unittest.TestCase):
    def validate(self, payload, mode):
        return reporter.validate_report(json.dumps(payload), mode)

    def run_main(self, message, mode):
        output = io.StringIO()
        with (
            patch.dict(os.environ, {"MODE": mode}, clear=True),
            patch.object(sys, "stdin", io.StringIO(message)),
            contextlib.redirect_stdout(output),
        ):
            result = reporter.main()
        return result, json.loads(output.getvalue())

    def test_pretty_report_after_logger_and_before_sentinel_is_extracted(self):
        payload = {"applied": False, **DATA, "companies_skipped_junk": 28}
        message = (
            "2026-10-28 INFO [atlas-import] {'companies_imported': 9123}\n"
            "SYNTHETIC_PRIVATE_LOG_MARKER\n"
            + json.dumps(payload, indent=2)
            + "\n"
            + SENTINEL
        )
        result, report = self.run_main(message, "dry-run")
        self.assertEqual(result, 0)
        self.assertEqual(report, payload)
        self.assertNotIn("SYNTHETIC_PRIVATE_LOG_MARKER", json.dumps(report))

    def test_all_five_modes_accept_only_their_success_report(self):
        cases = [
            ("dry-run", {"applied": False, **DATA}),
            ("apply", {"applied": True, **DATA}),
            ("files-dry-run", {"applied": False, "files_would_copy": 6029}),
            (
                "files-apply",
                {"applied": True, "files_copied": 6000, "files_missing_in_storage": 29},
            ),
            ("verify", {"applied": False, "mode": "counts-only", "counts": COUNTS}),
        ]
        for mode, payload in cases:
            with self.subTest(mode=mode):
                result, report = self.run_main(
                    json.dumps(payload) + "\n" + SENTINEL, mode
                )
                self.assertEqual((result, report), (0, payload))

    def test_no_json_or_applied_only_cannot_be_success(self):
        messages = [
            "",
            SENTINEL,
            "Brak ATLAS_DATABASE_URL\n" + SENTINEL,
            "SystemExit: missing configuration\n" + SENTINEL,
            "Traceback: SYNTHETIC_PRIVATE_LOG_MARKER\n" + SENTINEL,
            '{"applied": false',
            '{"applied": false}',
            '{"applied": true}',
            '{"unexpected": 1}',
        ]
        for message in messages:
            for mode in ("dry-run", "apply", "files-dry-run", "files-apply", "verify"):
                with self.subTest(message=message, mode=mode):
                    result, report = self.run_main(message, mode)
                    self.assertEqual(result, 1)
                    self.assertEqual(
                        report, {"applied": False, "error": "ReportValidationError"}
                    )

    def test_applied_status_must_be_exact_boolean_matching_selected_mode(self):
        for mode, wrong in (
            ("dry-run", True),
            ("apply", False),
            ("apply", 1),
            ("dry-run", 0),
            ("apply", "true"),
        ):
            with (
                self.subTest(mode=mode, applied=wrong),
                self.assertRaises(reporter.ReportValidationError),
            ):
                self.validate({"applied": wrong, **DATA}, mode)

    def test_counts_must_be_nonnegative_integers_excluding_booleans(self):
        for value in (True, False, -1, 1.5, "10", None, {}, []):
            with (
                self.subTest(value=value),
                self.assertRaises(reporter.ReportValidationError),
            ):
                self.validate(
                    {"applied": False, **DATA, "contacts_imported": value}, "dry-run"
                )
        self.assertEqual(
            self.validate({"applied": False, **dict.fromkeys(DATA, 0)}, "dry-run")[
                "contacts_imported"
            ],
            0,
        )

    def test_data_requires_all_baseline_counters_and_rejects_unknown_keys(self):
        for missing in DATA:
            payload = {"applied": False, **DATA}
            del payload[missing]
            with (
                self.subTest(missing=missing),
                self.assertRaises(reporter.ReportValidationError),
            ):
                self.validate(payload, "dry-run")
        for key in ("unknown_counter", "private_name", "files_copied"):
            with (
                self.subTest(key=key),
                self.assertRaises(reporter.ReportValidationError),
            ):
                self.validate({"applied": False, **DATA, key: 1}, "dry-run")

    def test_file_mode_rejects_data_and_unknown_counters(self):
        for payload in (
            {"applied": True, **DATA},
            {"applied": True, "files_copied": 1, "unexpected": 2},
            {"applied": True, "files_copied": True},
        ):
            with (
                self.subTest(payload=payload),
                self.assertRaises(reporter.ReportValidationError),
            ):
                self.validate(payload, "files-apply")
        self.assertEqual(
            self.validate(
                {"applied": False, "files_already_copied": 6029}, "files-dry-run"
            )["files_already_copied"],
            6029,
        )

    def test_file_counters_must_match_dry_run_or_apply(self):
        cases = [
            ("files-dry-run", {"applied": False, "files_copied": 1}),
            ("files-dry-run", {"applied": False, "files_missing_in_storage": 1}),
            ("files-apply", {"applied": True, "files_would_copy": 1}),
        ]
        for mode, payload in cases:
            with (
                self.subTest(mode=mode, payload=payload),
                self.assertRaises(reporter.ReportValidationError),
            ):
                self.validate(payload, mode)

    def test_external_file_references_are_valid_only_in_both_file_modes(self):
        for mode, applied in (("files-dry-run", False), ("files-apply", True)):
            payload = {"applied": applied, "files_external_reference": 5909}
            with self.subTest(mode=mode):
                self.assertEqual(self.validate(payload, mode), payload)
        for mode, applied in (("dry-run", False), ("apply", True)):
            with (
                self.subTest(mode=mode),
                self.assertRaises(reporter.ReportValidationError),
            ):
                self.validate(
                    {"applied": applied, **DATA, "files_external_reference": 5909},
                    mode,
                )
        with self.assertRaises(reporter.ReportValidationError):
            self.validate(
                {
                    "applied": False,
                    "mode": "counts-only",
                    "counts": {**COUNTS, "files_external_reference": 5909},
                },
                "verify",
            )

    def test_verify_requires_exact_six_tables_and_counts_only_mode(self):
        base = {"applied": False, "mode": "counts-only", "counts": COUNTS}
        for missing in COUNTS:
            with (
                self.subTest(missing=missing),
                self.assertRaises(reporter.ReportValidationError),
            ):
                self.validate(
                    {
                        **base,
                        "counts": {k: v for k, v in COUNTS.items() if k != missing},
                    },
                    "verify",
                )
        invalid = [
            {**base, "mode": "apply"},
            {**base, "applied": True},
            {**base, "counts": {**COUNTS, "users": 1}},
            {**base, "counts": {**COUNTS, "sales_files": True}},
            {**base, "unexpected": 1},
        ]
        for payload in invalid:
            with (
                self.subTest(payload=payload),
                self.assertRaises(reporter.ReportValidationError),
            ):
                self.validate(payload, "verify")

    def test_source_exception_is_failure_and_extra_private_data_is_removed(self):
        payload = {
            "applied": False,
            "error": "InvalidPasswordError",
            "detail": "SYNTHETIC_PRIVATE_MARKER",
        }
        for mode in ("dry-run", "apply", "files-apply", "verify"):
            with self.subTest(mode=mode):
                result, report = self.run_main(json.dumps(payload), mode)
                self.assertEqual(result, 1)
                self.assertEqual(
                    report, {"applied": False, "error": "InvalidPasswordError"}
                )
                self.assertNotIn("SYNTHETIC_PRIVATE_MARKER", json.dumps(report))

    def test_untrusted_exception_text_is_not_emitted(self):
        for error in (
            "ValueError: SYNTHETIC_PRIVATE_MARKER",
            "bad\nsecret",
            "",
            1,
            {},
            None,
        ):
            result, report = self.run_main(
                json.dumps({"applied": False, "error": error}), "apply"
            )
            self.assertEqual(result, 1)
            self.assertEqual(
                report, {"applied": False, "error": "ReportValidationError"}
            )

    def test_last_error_after_numeric_report_overrides_success(self):
        message = (
            json.dumps({"applied": True, **DATA})
            + "\n"
            + json.dumps({"applied": False, "error": "RuntimeError"})
        )
        self.assertEqual(
            self.run_main(message, "apply"),
            (1, {"applied": False, "error": "RuntimeError"}),
        )

    def test_unknown_mode_is_failure_without_echoing_input(self):
        result, report = self.run_main(
            json.dumps({"applied": False, **DATA}), "SYNTHETIC_PRIVATE_MARKER"
        )
        self.assertEqual(
            (result, report), (1, {"applied": False, "error": "ReportValidationError"})
        )


if __name__ == "__main__":
    unittest.main()
