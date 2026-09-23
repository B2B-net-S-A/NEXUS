"""alert_issue.sh (OPS-N08, audyt 22.09.2026): alarm się otwiera I zamyka.

Zamiast `gh` na PATH leży atrapa, która zapisuje wywołania i zwraca
przygotowaną listę issue — sprawdzamy, co skrypt z nią robi.
"""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / ".github/scripts/alert_issue.sh"

FAKE_GH = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE_GH_LOG"
if [ "$1 $2" = "issue list" ]; then
  if [ -n "${FAKE_GH_LIST_FAIL:-}" ]; then exit 1; fi
  cat "$FAKE_GH_LIST"
fi
exit 0
"""


class AlertIssueTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        gh = self.dir / "gh"
        gh.write_text(FAKE_GH)
        gh.chmod(0o755)
        self.log = self.dir / "gh.log"
        self.list = self.dir / "list.json"
        self.body = self.dir / "body.md"
        self.body.write_text("treść alarmu\n")

    def run_script(self, *args, issues=(), list_fails=False):
        self.list.write_text(json.dumps(list(issues)))
        env = {
            **os.environ,
            "PATH": f"{self.dir}:{os.environ['PATH']}",
            "FAKE_GH_LOG": str(self.log),
            "FAKE_GH_LIST": str(self.list),
            "REPO": "o/r",
            "RUN_URL": "https://example.invalid/run/1",
        }
        if list_fails:
            env["FAKE_GH_LIST_FAIL"] = "1"
        result = subprocess.run(
            ["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True
        )
        calls = self.log.read_text().splitlines() if self.log.exists() else []
        return result, calls

    def test_open_creates_issue_when_none_matches_exactly(self):
        # Wyszukiwarka zwraca podobny tytuł — to NIE jest ten sam alarm.
        result, calls = self.run_script(
            "open",
            "Deploy NEXUS jest czerwony",
            str(self.body),
            issues=[{"number": 7, "title": "⚠️ Deploy NEXUS jest wstrzymany"}],
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any(c.startswith("issue create") for c in calls), calls)
        self.assertIn("⚠️ Deploy NEXUS jest czerwony", "\n".join(calls))

    def test_open_comments_on_newest_matching_issue(self):
        result, calls = self.run_script(
            "open",
            "NEXUS host disk high",
            str(self.body),
            issues=[
                {"number": 825, "title": "⚠️ NEXUS host disk high"},
                {"number": 900, "title": "🚨 NEXUS host disk high"},
            ],
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any(c.startswith("issue comment 900") for c in calls), calls)
        self.assertFalse(any(c.startswith("issue create") for c in calls))

    def test_resolve_closes_every_matching_issue_only(self):
        result, calls = self.run_script(
            "resolve",
            "NEXUS health checks unhealthy",
            issues=[
                {"number": 1413, "title": "⚠️ NEXUS health checks unhealthy"},
                {"number": 2000, "title": "Inny temat"},
            ],
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        closes = [c for c in calls if c.startswith("issue close")]
        self.assertEqual(len(closes), 1, calls)
        self.assertTrue(closes[0].startswith("issue close 1413"))
        self.assertIn("https://example.invalid/run/1", self.log.read_text())

    def test_resolve_never_fails_the_green_run(self):
        result, calls = self.run_script(
            "resolve", "NEXUS host disk high", list_fails=True
        )
        self.assertEqual(result.returncode, 0)
        self.assertFalse(any(c.startswith("issue close") for c in calls))

    def test_open_without_body_is_rejected(self):
        result, _ = self.run_script("open", "X", str(self.dir / "missing.md"))
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
