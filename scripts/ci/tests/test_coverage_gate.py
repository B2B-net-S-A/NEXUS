from __future__ import annotations

import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
COMBINE = REPOSITORY_ROOT / "scripts/ci/combine-lcov"
CHECKER = REPOSITORY_ROOT / ".standards/tools/check_coverage.py"


class CombineLcovTests(unittest.TestCase):
    def test_combines_absolute_and_relative_sources_at_repository_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            backend = root / "backend.lcov"
            frontend = root / "frontend.lcov"
            output = root / "combined.lcov"
            backend.write_text(
                "TN:\nSF:/home/runner/work/Nexus/Nexus/backend/app/main.py\nDA:1,1\nend_of_record\n",
                encoding="utf-8",
            )
            frontend.write_text(
                "TN:\nSF:src/app/page.tsx\nDA:1,0\nend_of_record\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    str(COMBINE),
                    "--backend",
                    str(backend),
                    "--frontend",
                    str(frontend),
                    "--output",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            combined = output.read_text(encoding="utf-8")
            self.assertIn("SF:backend/app/main.py", combined)
            self.assertIn("SF:frontend/src/app/page.tsx", combined)

    def test_rejects_a_source_path_that_cannot_be_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            backend = root / "backend.lcov"
            frontend = root / "frontend.lcov"
            output = root / "combined.lcov"
            backend.write_text(
                "TN:\nSF:/unrelated/location/main.py\nDA:1,1\nend_of_record\n",
                encoding="utf-8",
            )
            frontend.write_text(
                "TN:\nSF:src/app/page.tsx\nDA:1,1\nend_of_record\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    str(COMBINE),
                    "--backend",
                    str(backend),
                    "--frontend",
                    str(frontend),
                    "--output",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("cannot make LCOV source repository-relative", result.stderr)
            self.assertFalse(output.exists())


class CoveragePolicyIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self._git("init", "-b", "main")
        self._git("config", "user.email", "coverage@example.invalid")
        self._git("config", "user.name", "Coverage Gate Test")
        (self.root / "app").mkdir()
        (self.root / ".standards").mkdir()
        self.source = self.root / "app/code.py"
        self.source.write_text(
            "".join(f"value_{line} = {line}\n" for line in range(1, 11)),
            encoding="utf-8",
        )
        self._write_ratchet(8, 10)
        self._git("add", ".")
        self._git("commit", "-m", "baseline")
        self.base_sha = self._git("rev-parse", "HEAD").stdout.strip()
        self.source.write_text(
            "".join(
                f"value_{line} = {line * 10 if line <= 5 else line}\n"
                for line in range(1, 11)
            ),
            encoding="utf-8",
        )
        self._git("add", "app/code.py")
        self._git("commit", "-m", "change five executable lines")
        self.lcov = self.root / "coverage.lcov"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _git(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(self.root), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )

    def _write_ratchet(self, covered: int, found: int) -> None:
        (self.root / ".standards/coverage-ratchet.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "minimum_changed_lines_percent": 80,
                    "total_lines": {"covered": covered, "found": found},
                    "source_extensions": [".py"],
                    "exclude_globs": ["**/test_*.py"],
                }
            ),
            encoding="utf-8",
        )

    def _write_lcov(self, covered: set[int]) -> None:
        records = ["TN:", "SF:app/code.py"]
        records.extend(
            f"DA:{line},{1 if line in covered else 0}" for line in range(1, 11)
        )
        records.extend(["end_of_record", ""])
        self.lcov.write_text("\n".join(records), encoding="utf-8")

    def _run_gate(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "python3",
                str(CHECKER),
                "--repo-root",
                str(self.root),
                "--lcov",
                str(self.lcov),
                "--ratchet",
                str(self.root / ".standards/coverage-ratchet.json"),
                "--base-sha",
                self.base_sha,
            ],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_exact_ratchet_and_eighty_percent_changed_lines_pass(self) -> None:
        self._write_lcov({1, 2, 3, 4, 6, 7, 8, 9})
        result = self._run_gate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("changed=4/5 (80.00%)", result.stdout)
        self.assertIn("total=8/10", result.stdout)

    def test_below_eighty_percent_changed_lines_blocks(self) -> None:
        self._write_lcov({1, 2, 3, 6, 7, 8, 9, 10})
        result = self._run_gate()
        self.assertEqual(result.returncode, 1)
        self.assertIn("changed-lines coverage 60.00% is below 80%", result.stderr)

    def test_total_coverage_regression_blocks(self) -> None:
        self._write_lcov({1, 2, 3, 4, 6, 7, 8})
        result = self._run_gate()
        self.assertEqual(result.returncode, 1)
        self.assertIn("regressed below the tracked ratchet", result.stderr)

    def test_quality_gate_requires_coverage_policy(self) -> None:
        workflow = (REPOSITORY_ROOT / ".github/workflows/ci.yml").read_text(
            encoding="utf-8"
        )
        self.assertRegex(workflow, re.compile(r"(?m)^  coverage-policy:$"))
        quality_gate = workflow.split("\n  quality-gate:\n", 1)[1]
        self.assertRegex(quality_gate, re.compile(r"(?m)^      - coverage-policy$"))
        self.assertIn("COVERAGE: ${{ needs.coverage-policy.result }}", quality_gate)

    def test_repository_ratchet_is_initialized_and_requires_eighty_percent(self) -> None:
        ratchet = json.loads(
            (REPOSITORY_ROOT / ".standards/coverage-ratchet.json").read_text(
                encoding="utf-8"
            )
        )
        total = ratchet["total_lines"]
        self.assertEqual(ratchet["minimum_changed_lines_percent"], 80)
        self.assertGreater(total["found"], 0)
        self.assertGreaterEqual(total["covered"], 0)
        self.assertLessEqual(total["covered"], total["found"])


if __name__ == "__main__":
    unittest.main()
