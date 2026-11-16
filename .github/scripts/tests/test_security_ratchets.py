"""Zapadki skanerów bezpieczeństwa: Semgrep (`semgrep_ratchet.py`) i audyt
zależności (`dependency_audit.py`). Bez sieci i bez Semgrepa — wynik skanu
podajemy jako JSON w kształcie `semgrep --json`."""

import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"scripts/{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RATCHET = _load("semgrep_ratchet")
AUDIT = _load("dependency_audit")

SQL_RULE = "python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text"
SOURCE = (
    "from sqlalchemy import text\n"
    "# zażółć gęślą jaźń\n"
    "def count(table):\n"
    "    return text(f\"SELECT count(*) FROM {table}\")\n"
)
SNIPPET = 'text(f"SELECT count(*) FROM {table}")'


def _result(source, snippet, path="backend/app/x.py", rule=SQL_RULE):
    raw = source.encode("utf-8")
    start = raw.index(snippet.encode("utf-8"))
    line = raw[:start].count(b"\n") + 1
    return {
        "check_id": rule,
        "path": path,
        "start": {"line": line, "col": 1, "offset": start},
        "end": {"line": line, "col": 1, "offset": start + len(snippet.encode("utf-8"))},
        "extra": {"message": "Avoid sqlalchemy text"},
    }


class SemgrepRatchetTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "backend/app").mkdir(parents=True)
        self.baseline = self.root / ".semgrep-baseline.json"
        self.baseline.write_text(json.dumps({"findings": []}), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _scan(self, source, snippets, scanned=("backend/app/x.py",)):
        (self.root / "backend/app/x.py").write_text(source, encoding="utf-8")
        results = self.root / "semgrep.json"
        results.write_text(
            json.dumps(
                {
                    "results": [_result(source, s) for s in snippets],
                    "paths": {"scanned": list(scanned)},
                }
            ),
            encoding="utf-8",
        )
        return results

    def _run(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            code = RATCHET.main(list(argv))
        return code, out.getvalue()

    def _compare(self, results):
        return self._run(
            "compare", "--results", str(results), "--baseline", str(self.baseline),
            "--root", str(self.root),
        )

    def _update(self, results, reason="powód", status="zweryfikowane"):
        return self._run(
            "update", "--results", str(results), "--baseline", str(self.baseline),
            "--root", str(self.root), "--reason", reason, "--status", status,
        )

    def test_new_finding_fails_with_file_and_line_annotation(self):
        code, out = self._compare(self._scan(SOURCE, [SNIPPET]))
        self.assertEqual(code, 1)
        self.assertIn("::error file=backend/app/x.py,line=4,", out)

    def test_baselined_finding_passes_even_when_code_above_moves(self):
        self.assertEqual(self._update(self._scan(SOURCE, [SNIPPET]))[0], 0)
        moved = "import os\n\n" + SOURCE
        code, out = self._compare(self._scan(moved, [SNIPPET]))
        self.assertEqual(code, 0, out)

    def test_changing_the_matched_sql_is_a_new_finding(self):
        self._update(self._scan(SOURCE, [SNIPPET]))
        changed = SOURCE.replace("{table}", "{table} WHERE id = {user_input}")
        snippet = SNIPPET.replace("{table}", "{table} WHERE id = {user_input}")
        code, _ = self._compare(self._scan(changed, [snippet]))
        self.assertEqual(code, 1)

    def test_one_entry_covers_one_occurrence(self):
        self._update(self._scan(SOURCE, [SNIPPET]))
        twice = SOURCE + "\ndef again(table):\n    return " + SNIPPET + "\n"
        results = self._scan(twice, [SNIPPET])
        data = json.loads(results.read_text(encoding="utf-8"))
        second = _result(twice, SNIPPET)
        raw = twice.encode("utf-8")
        offset = raw.rindex(SNIPPET.encode("utf-8"))
        second["start"].update(offset=offset, line=raw[:offset].count(b"\n") + 1)
        second["end"]["offset"] = offset + len(SNIPPET.encode("utf-8"))
        data["results"].append(second)
        results.write_text(json.dumps(data), encoding="utf-8")
        code, out = self._compare(results)
        self.assertEqual(code, 1)
        self.assertIn("nowe: 1", out)

    def test_entry_without_reason_or_with_unknown_status_fails(self):
        self._update(self._scan(SOURCE, [SNIPPET]))
        data = json.loads(self.baseline.read_text(encoding="utf-8"))
        data["findings"][0]["reason"] = " "
        self.baseline.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(self._compare(self._scan(SOURCE, [SNIPPET]))[0], 1)
        data["findings"][0].update(reason="ok", status="zaakceptowane")
        self.baseline.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(self._compare(self._scan(SOURCE, [SNIPPET]))[0], 1)

    def test_update_requires_a_reason_for_new_findings(self):
        code, _ = self._update(self._scan(SOURCE, [SNIPPET]), reason="")
        self.assertEqual(code, 2)

    def test_partial_scan_does_not_drop_entries_of_unscanned_files(self):
        self._update(self._scan(SOURCE, [SNIPPET]))
        self._update(self._scan(SOURCE, [], scanned=("backend/app/other.py",)))
        self.assertEqual(len(json.loads(self.baseline.read_text())["findings"]), 1)
        # Plik przeskanowany bez znaleziska — wpis znika.
        self._update(self._scan(SOURCE, []))
        self.assertEqual(json.loads(self.baseline.read_text())["findings"], [])

    def test_stale_entry_is_a_notice_not_a_failure(self):
        self._update(self._scan(SOURCE, [SNIPPET]))
        code, out = self._compare(self._scan(SOURCE, []))
        self.assertEqual(code, 0)
        self.assertIn("::notice file=backend/app/x.py", out)

    def test_include_escapes_next_route_brackets(self):
        self.assertEqual(
            RATCHET.escape_include("frontend/src/app/kariera/r/[slug]/page.tsx"),
            "/frontend/src/app/kariera/r/\\[slug\\]/page.tsx",
        )
        self.assertEqual(RATCHET.escape_include("a/*?.py"), "/a/\\*\\?.py")


class RepoBaselineTest(unittest.TestCase):
    def test_repo_baseline_is_valid_and_sql_in_named_services_is_verified(self):
        baseline = json.loads((ROOT.parent / ".semgrep-baseline.json").read_text("utf-8"))
        self.assertEqual(RATCHET.baseline_problems(baseline), [])
        for path in (
            "backend/app/services/candidate_merge.py",
            "backend/app/services/nexus_data_correction.py",
            "backend/app/services/keyword_suggest.py",
        ):
            entries = [e for e in baseline["findings"] if e["path"] == path]
            self.assertTrue(entries, path)
            self.assertEqual({e["status"] for e in entries}, {"zweryfikowane"}, path)

    def test_repo_dependency_baseline_entries_have_reason_and_date(self):
        baseline = json.loads(
            (ROOT / "dependency-audit-baseline.json").read_text(encoding="utf-8")
        )
        for entry in baseline["python"] + baseline["npm"]:
            self.assertTrue(entry["reason"].strip(), entry["id"])
            date.fromisoformat(entry["expires"])


PIP_REPORT = {
    "dependencies": [
        {"name": "python-jose", "version": "3.5.0", "vulns": [
            {"id": "PYSEC-1", "aliases": ["GHSA-aaaa-bbbb-cccc"], "fix_versions": []}
        ]},
        {"name": "fastapi", "version": "0.115.0", "vulns": []},
    ]
}
NPM_REPORT = {
    "vulnerabilities": {
        "next": {"severity": "high", "via": [
            {"source": 1, "name": "next", "severity": "high", "title": "SSRF",
             "url": "https://github.com/advisories/GHSA-1111-2222-3333", "range": "<15.1.2"}
        ]},
        "glob": {"severity": "moderate", "via": [
            {"source": 2, "name": "glob", "severity": "moderate", "title": "x",
             "url": "https://github.com/advisories/GHSA-4444-5555-6666", "range": "<10"},
            "minimatch",
        ]},
    }
}
TODAY = date(2026, 11, 13)


class DependencyAuditTest(unittest.TestCase):
    def test_python_vuln_is_matched_by_alias_until_it_expires(self):
        vulns = AUDIT.python_vulns(PIP_REPORT)
        entry = {"id": "GHSA-aaaa-bbbb-cccc", "reason": "brak poprawki", "expires": "2026-12-01"}
        self.assertEqual(AUDIT.check(vulns, [entry], TODAY), ([], []))
        errors, _ = AUDIT.check(vulns, [entry], date(2026, 12, 2))
        self.assertIn("wygasł", errors[0])

    def test_new_python_vuln_fails(self):
        errors, _ = AUDIT.check(AUDIT.python_vulns(PIP_REPORT), [], TODAY)
        self.assertEqual(len(errors), 1)
        self.assertIn("PYSEC-1", errors[0])

    def test_npm_counts_only_high_and_above_by_default(self):
        vulns = AUDIT.npm_vulns(NPM_REPORT, "high")
        self.assertEqual([v["id"] for v in vulns], ["GHSA-1111-2222-3333"])
        self.assertEqual(len(AUDIT.npm_vulns(NPM_REPORT, "moderate")), 2)

    def test_npm_error_report_is_not_a_silent_pass(self):
        with self.assertRaises(ValueError):
            AUDIT.npm_vulns({"error": {"code": "ENOLOCK"}}, "high")

    def test_unused_exception_is_a_notice_and_missing_reason_fails(self):
        entries = [{"id": "GHSA-zzzz-zzzz-zzzz", "reason": "", "expires": "2027-01-01"}]
        errors, notes = AUDIT.check([], entries, TODAY)
        self.assertEqual(len(notes), 1)
        self.assertIn("uzasadnienia", errors[0])

    def test_missing_report_file_fails(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = AUDIT.main(["npm", "--report", "/nonexistent/npm.json"])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
