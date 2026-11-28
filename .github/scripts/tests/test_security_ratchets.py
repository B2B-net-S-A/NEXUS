"""Zapadki skanerów bezpieczeństwa: Semgrep (`semgrep_ratchet.py`), audyt
zależności (`dependency_audit.py`), zizmor (`zizmor_ratchet.py`) i wyjątki
Trivy obrazów (`.trivyignore-images`). Bez sieci i bez skanerów — wynik skanu
podajemy jako JSON w kształcie `semgrep --json` / `zizmor --format json`."""

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
ZIZMOR = _load("zizmor_ratchet")

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

    def _dojo(self, results):
        output = self.root / "semgrep-dojo.json"
        code, out = self._run(
            "dojo", "--results", str(results), "--baseline", str(self.baseline),
            "--root", str(self.root), "--output", str(output),
        )
        return code, out, json.loads(output.read_text(encoding="utf-8"))

    def test_dojo_report_drops_only_verified_baseline_findings(self):
        """DefectDojo (i ekran Bezpieczeństwo) dostaje to, na co trzeba
        zareagować: przejrzany wyjątek z baseline nie wraca jako „czeka na
        reakcję” co tydzień, a nowe i „do-przegladu” zostają (28.11.2026)."""
        self._update(self._scan(SOURCE, [SNIPPET]))
        other = "text(f\"SELECT 1 FROM {other}\")"
        source = SOURCE + "\ndef more(other):\n    return " + other + "\n"
        code, out, report = self._dojo(self._scan(source, [SNIPPET, other]))
        self.assertEqual(code, 0, out)
        self.assertEqual([r["start"]["line"] for r in report["results"]], [7])
        self.assertIn("paths", report)
        self.assertIn("pominięte jako zweryfikowane: 1", out)

        data = json.loads(self.baseline.read_text(encoding="utf-8"))
        data["findings"][0]["status"] = "do-przegladu"
        self.baseline.write_text(json.dumps(data), encoding="utf-8")
        _, _, report = self._dojo(self._scan(source, [SNIPPET, other]))
        self.assertEqual(len(report["results"]), 2)

    def test_dojo_report_keeps_second_occurrence_of_verified_snippet(self):
        self._update(self._scan(SOURCE, [SNIPPET]))
        twice = SOURCE + "\ndef again(table):\n    return " + SNIPPET + "\n"
        raw = twice.encode("utf-8")
        second = _result(twice, SNIPPET)
        offset = raw.rindex(SNIPPET.encode("utf-8"))
        second["start"].update(offset=offset, line=raw[:offset].count(b"\n") + 1)
        second["end"]["offset"] = offset + len(SNIPPET.encode("utf-8"))
        results = self._scan(twice, [SNIPPET])
        data = json.loads(results.read_text(encoding="utf-8"))
        data["results"].append(second)
        results.write_text(json.dumps(data), encoding="utf-8")
        _, _, report = self._dojo(results)
        self.assertEqual(len(report["results"]), 1)

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


def _zizmor_finding(ident="template-injection", path="./.github/workflows/x.yml",
                    route=("jobs", "build", "steps", 2, "run"), feature='run: echo "${{ github.head_ref }}"',
                    row=41):
    parts = [{"Index": p} if isinstance(p, int) else {"Key": p} for p in route]
    return {
        "ident": ident,
        "desc": "code injection via template expansion",
        "determinations": {"severity": "High", "confidence": "High"},
        "locations": [
            {
                "symbolic": {
                    "key": {"Local": {"verbatim_path": path}},
                    "annotation": "may expand into attacker-controllable code",
                    "route": {"route": parts},
                    "kind": "Related",
                },
                "concrete": {"location": {"start_point": {"row": 3}}, "feature": "on: pull_request"},
            },
            {
                "symbolic": {
                    "key": {"Local": {"verbatim_path": path}},
                    "annotation": "may expand into attacker-controllable code",
                    "route": {"route": parts},
                    "kind": "Primary",
                },
                "concrete": {"location": {"start_point": {"row": row}}, "feature": feature},
            },
        ],
    }


class ZizmorRatchetTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.baseline = self.root / "zizmor-baseline.json"
        self.baseline.write_text(json.dumps({"zizmor": "1.33.1", "findings": []}), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _results(self, *findings):
        path = self.root / "zizmor.json"
        path.write_text(json.dumps(list(findings)), encoding="utf-8")
        return path

    def _run(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            code = ZIZMOR.main(list(argv))
        return code, out.getvalue()

    def _compare(self, results):
        return self._run("compare", "--results", str(results), "--baseline", str(self.baseline))

    def _update(self, results, reason="powód", status="zweryfikowane"):
        return self._run(
            "update", "--results", str(results), "--baseline", str(self.baseline),
            "--reason", reason, "--status", status,
        )

    def test_new_finding_fails_with_primary_location_annotation(self):
        code, out = self._compare(self._results(_zizmor_finding()))
        self.assertEqual(code, 1)
        self.assertIn("::error file=.github/workflows/x.yml,line=42,title=zizmor template-injection", out)

    def test_baselined_finding_passes_when_lines_and_step_index_move(self):
        self._update(self._results(_zizmor_finding()))
        moved = _zizmor_finding(route=("jobs", "build", "steps", 5, "run"), row=80)
        code, out = self._compare(self._results(moved))
        self.assertEqual(code, 0, out)
        entry = json.loads(self.baseline.read_text(encoding="utf-8"))["findings"][0]
        self.assertEqual(entry["path"], ".github/workflows/x.yml")
        self.assertEqual(entry["route"], "jobs.build.steps.run")

    def test_changed_match_or_other_job_is_a_new_finding(self):
        self._update(self._results(_zizmor_finding()))
        changed = _zizmor_finding(feature='run: echo "${{ github.head_ref }} ${{ github.event.issue.title }}"')
        self.assertEqual(self._compare(self._results(changed))[0], 1)
        other_job = _zizmor_finding(route=("jobs", "deploy", "steps", 2, "run"))
        self.assertEqual(self._compare(self._results(other_job))[0], 1)

    def test_one_entry_covers_one_occurrence(self):
        self._update(self._results(_zizmor_finding()))
        code, out = self._compare(self._results(_zizmor_finding(), _zizmor_finding(row=60)))
        self.assertEqual(code, 1)
        self.assertIn("nowe: 1", out)

    def test_fixed_finding_is_stale_notice_and_update_drops_it(self):
        self._update(self._results(_zizmor_finding()))
        code, out = self._compare(self._results())
        self.assertEqual(code, 0)
        self.assertIn("::notice file=.github/workflows/x.yml", out)
        self._update(self._results())
        self.assertEqual(json.loads(self.baseline.read_text(encoding="utf-8"))["findings"], [])

    def test_entry_without_reason_fails_and_update_requires_reason(self):
        self.assertEqual(self._update(self._results(_zizmor_finding()), reason=" ")[0], 2)
        self._update(self._results(_zizmor_finding()))
        data = json.loads(self.baseline.read_text(encoding="utf-8"))
        data["findings"][0]["reason"] = ""
        self.baseline.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(self._compare(self._results(_zizmor_finding()))[0], 1)

    def _sarif(self, *locations):
        path = self.root / "zizmor.sarif"
        results = [
            {
                "ruleId": f"zizmor/{rule}",
                "level": "error",
                "message": {"text": "x"},
                "locations": [{"physicalLocation": {
                    "artifactLocation": {"uri": uri}, "region": {"startLine": line},
                }}],
            }
            for rule, uri, line in locations
        ]
        path.write_text(json.dumps({"version": "2.1.0", "runs": [
            {"tool": {"driver": {"name": "zizmor"}}, "results": results}
        ]}), encoding="utf-8")
        return path

    def _dojo(self, results, sarif):
        output = self.root / "zizmor-dojo.sarif"
        code, out = self._run(
            "dojo", "--results", str(results), "--sarif", str(sarif),
            "--baseline", str(self.baseline), "--output", str(output),
        )
        return code, out, json.loads(output.read_text(encoding="utf-8"))

    def test_dojo_sarif_drops_only_verified_baseline_findings(self):
        self._update(self._results(_zizmor_finding()))
        results = self._results(_zizmor_finding(), _zizmor_finding(ident="github-env", row=99))
        sarif = self._sarif(
            ("template-injection", ".github/workflows/x.yml", 42),
            ("github-env", ".github/workflows/x.yml", 100),
        )
        code, out, report = self._dojo(results, sarif)
        self.assertEqual(code, 0, out)
        kept = report["runs"][0]["results"]
        self.assertEqual([r["ruleId"] for r in kept], ["zizmor/github-env"])
        self.assertEqual(report["runs"][0]["tool"]["driver"]["name"], "zizmor")

        data = json.loads(self.baseline.read_text(encoding="utf-8"))
        data["findings"][0]["status"] = "do-przegladu"
        self.baseline.write_text(json.dumps(data), encoding="utf-8")
        _, _, report = self._dojo(results, sarif)
        self.assertEqual(len(report["runs"][0]["results"]), 2)

    def test_dojo_sarif_without_matching_json_finding_is_red(self):
        """SARIF i JSON z tego samego biegu muszą się zgadzać; rozjazd to
        błąd, nie cicha wysyłka wszystkiego albo niczego."""
        self._update(self._results(_zizmor_finding()))
        sarif = self._sarif(("template-injection", ".github/workflows/x.yml", 7))
        output = self.root / "zizmor-dojo.sarif"
        code, _ = self._run(
            "dojo", "--results", str(self._results(_zizmor_finding())), "--sarif", str(sarif),
            "--baseline", str(self.baseline), "--output", str(output),
        )
        self.assertEqual(code, 1)
        self.assertFalse(output.exists())

    def test_unreadable_result_is_red_not_a_silent_pass(self):
        broken = self.root / "zizmor.json"
        broken.write_text('{"error": "no audit was performed"}', encoding="utf-8")
        self.assertEqual(self._compare(broken)[0], 1)
        self.assertEqual(self._compare(self.root / "brak.json")[0], 1)


class RepoZizmorAndImageIgnoresTest(unittest.TestCase):
    def test_repo_zizmor_baseline_is_verified_and_matches_installed_version(self):
        baseline = json.loads((ROOT / "zizmor-baseline.json").read_text(encoding="utf-8"))
        self.assertEqual(ZIZMOR.baseline_problems(baseline), [])
        self.assertEqual({e["status"] for e in baseline["findings"]}, {"zweryfikowane"})
        for entry in baseline["findings"]:
            self.assertGreater(len(entry["reason"]), 40, entry["path"])
        install = (ROOT / "scripts/install_zizmor.sh").read_text(encoding="utf-8")
        self.assertIn(f'VERSION="{baseline["zizmor"]}"', install)
        self.assertRegex(install, r'SHA256="[0-9a-f]{64}"')
        self.assertIn("sha256sum -c", install)

    def test_checkout_credentials_stay_only_where_a_push_needs_them(self):
        """artipacked: token z checkoutu zostaje w `.git/config` dla każdego
        kroku joba (także testów z kodu PR-a). Wyjątek tylko z baseline."""
        allowed = {
            e["path"] for e in json.loads((ROOT / "zizmor-baseline.json").read_text("utf-8"))["findings"]
            if e["rule"] == "artipacked"
        }
        self.assertEqual(allowed, {".github/workflows/migration-rechain.yml"})

    def test_defectdojo_gets_only_reports_after_the_ratchets(self):
        """Do DefectDojo idą raporty po zapadkach: bez zweryfikowanych wpisów
        baseline i bez wyjątków z `.trivyignore-images`. 28.11.2026 surowe
        raporty dały na ekranie 287 pozycji „czeka na reakcję”, wszystkie
        dawno przejrzane."""
        workflow = (ROOT / "workflows/security-weekly.yml").read_text(encoding="utf-8")
        imports = [line for line in workflow.splitlines() if "defectdojo_import.sh" in line]
        self.assertTrue(imports)
        self.assertIn('"Semgrep" semgrep-dojo.json', workflow)
        self.assertIn('"zizmor" zizmor-dojo.sarif', workflow)
        self.assertIn('"pip-audit" pip-audit-dojo.json', workflow)
        self.assertIn('"npm audit" npm-audit-dojo.json', workflow)
        self.assertNotIn(" semgrep.json\n", "\n".join(imports) + "\n")
        trivy = (ROOT / "scripts/trivy_images.sh").read_text(encoding="utf-8")
        self.assertRegex(
            trivy, r'--ignorefile "\$ignorefile" --format json --output "\$outdir/trivy-\$safe\.json"'
        )

    def test_image_ignores_have_reason_and_valid_expiry(self):
        lines = (ROOT.parent / ".trivyignore-images").read_text(encoding="utf-8").splitlines()
        previous_comment = False
        for line in lines:
            stripped = line.strip()
            if not stripped:
                previous_comment = False
                continue
            if stripped.startswith("#"):
                previous_comment = True
                continue
            ident, _, rest = stripped.partition(" ")
            self.assertRegex(ident, r"^(CVE-\d{4}-\d+|GHSA(-[0-9a-z]{4}){3})$", line)
            self.assertRegex(rest, r"^exp:\d{4}-\d{2}-\d{2}$", f"Wyjątek bez terminu: {line!r}")
            expires = date.fromisoformat(rest[4:])
            self.assertLessEqual(
                (expires - date(2026, 11, 27)).days, 400,
                f"Termin dalej niż ~rok — wyjątek bez przeglądu: {line!r}",
            )
            self.assertTrue(previous_comment, f"Wyjątek bez uzasadnienia w komentarzu nad nim: {line!r}")


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

    def test_dojo_npm_report_drops_excepted_advisories_and_their_chains(self):
        """Do DefectDojo nie idzie porada z ważnym wyjątkiem ani pakiety, które
        są na liście tylko przez nią (28.11.2026: glob/minimatch pod wtyczką
        Sentry dały 6 pozycji na ekranie Bezpieczeństwo)."""
        report = json.loads(json.dumps(NPM_REPORT))
        report["vulnerabilities"]["minimatch"] = {"severity": "moderate", "via": [
            {"source": 3, "name": "minimatch", "severity": "moderate", "title": "ReDoS",
             "url": "https://github.com/advisories/GHSA-7777-8888-9999", "range": "<11"}
        ]}
        report["vulnerabilities"]["@sentry/nextjs"] = {"severity": "moderate", "via": ["glob"]}
        both = [
            {"id": "GHSA-4444-5555-6666", "reason": "tylko build", "expires": "2027-01-01"},
            {"id": "GHSA-7777-8888-9999", "reason": "tylko build", "expires": "2027-01-01"},
        ]
        out, skipped = AUDIT.dojo_report("npm", report, both, TODAY)
        self.assertEqual(sorted(out["vulnerabilities"]), ["next"])
        self.assertEqual(skipped, 2)

        out, _ = AUDIT.dojo_report("npm", report, both[:1], TODAY)
        self.assertEqual(sorted(out["vulnerabilities"]), ["@sentry/nextjs", "glob", "minimatch", "next"])
        self.assertEqual(out["vulnerabilities"]["glob"]["via"], ["minimatch"])

        expired = [dict(e, expires="2026-11-01") for e in both]
        out, skipped = AUDIT.dojo_report("npm", report, expired, TODAY)
        self.assertEqual(len(out["vulnerabilities"]), 4)
        self.assertEqual(skipped, 0)

    def test_dojo_python_report_drops_excepted_vuln_by_alias(self):
        entry = {"id": "GHSA-aaaa-bbbb-cccc", "reason": "brak poprawki", "expires": "2026-12-01"}
        out, skipped = AUDIT.dojo_report("python", PIP_REPORT, [entry], TODAY)
        self.assertEqual(skipped, 1)
        self.assertEqual([d["vulns"] for d in out["dependencies"]], [[], []])
        self.assertEqual(len(PIP_REPORT["dependencies"][0]["vulns"]), 1)

    def test_moderate_exception_under_high_gate_is_not_reported_as_unused(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "npm.json").write_text(json.dumps(NPM_REPORT), encoding="utf-8")
        (root / "baseline.json").write_text(json.dumps({"python": [], "npm": [
            {"id": "GHSA-4444-5555-6666", "reason": "tylko build", "expires": "2099-01-01"},
            {"id": "GHSA-1111-2222-3333", "reason": "brak poprawki", "expires": "2099-01-01"},
        ]}), encoding="utf-8")
        out = io.StringIO()
        with redirect_stdout(out):
            code = AUDIT.main([
                "npm", "--report", str(root / "npm.json"), "--baseline", str(root / "baseline.json"),
                "--dojo-output", str(root / "dojo.json"),
            ])
        self.assertEqual(code, 0, out.getvalue())
        self.assertNotIn("już nie występuje", out.getvalue())
        self.assertEqual(json.loads((root / "dojo.json").read_text("utf-8"))["vulnerabilities"], {})

    def test_missing_report_file_fails(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = AUDIT.main(["npm", "--report", "/nonexistent/npm.json"])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
