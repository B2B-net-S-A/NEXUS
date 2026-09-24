import importlib.util
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / ".github/scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "queue_weekly_report", SCRIPTS / "queue_weekly_report.py"
)
QWR = importlib.util.module_from_spec(SPEC)
sys.modules["queue_weekly_report"] = QWR
SPEC.loader.exec_module(QWR)
Failure = QWR.qff.Failure


def run(conclusion, start="2026-09-23T10:00:00Z", end="2026-09-23T10:20:00Z"):
    return {"conclusion": conclusion, "run_started_at": start, "updated_at": end}


class SummaryTests(unittest.TestCase):
    def test_counts_rate_and_median_of_green_runs_only(self):
        runs = [
            run("success", end="2026-09-23T10:10:00Z"),
            run("success", end="2026-09-23T10:30:00Z"),
            run("success", end="2026-09-23T10:20:00Z"),
            run("failure", end="2026-09-23T12:00:00Z"),
            run("cancelled"),
            {"conclusion": None, "status": "in_progress"},
        ]
        summary = QWR.summarize_runs(runs)
        self.assertEqual(
            (
                summary["total"],
                summary["success"],
                summary["failure"],
                summary["cancelled"],
            ),
            (6, 3, 1, 1),
        )
        self.assertEqual(summary["other"], 1)
        self.assertAlmostEqual(summary["fail_rate"], 0.25)
        self.assertEqual(summary["median_green_minutes"], 20.0)

    def test_empty_week(self):
        summary = QWR.summarize_runs([])
        self.assertEqual(summary["fail_rate"], 0.0)
        self.assertIsNone(summary["median_green_minutes"])

    def test_iso_week_label_names_the_week_that_just_ended(self):
        monday = datetime(2026, 9, 28, 6, 7, tzinfo=timezone.utc)
        self.assertEqual(QWR.iso_week_label(monday), "2026-W39")


def results():
    return [
        QWR.RunFailures(
            1,
            "u1",
            1749,
            [
                Failure("pytest", "tests/test_a.py::t1"),
                Failure("pytest", "tests/test_a.py::t2"),
                Failure("vitest", "src/x.test.tsx > y"),
            ],
        ),
        QWR.RunFailures(2, "u2", 1749, [Failure("pytest", "tests/test_a.py::t1")]),
        QWR.RunFailures(
            3,
            "u3",
            1766,
            [
                Failure("pytest", "tests/test_b.py::t"),
                Failure("pytest", "tests/test_c.py::t"),
            ],
        ),
        QWR.RunFailures(4, "u4", None, [Failure("tsc", "src/z.ts(1,1)")]),
    ]


class AggregationTests(unittest.TestCase):
    def test_counts_once_per_run_per_file_and_per_pr(self):
        per_file, per_pr = QWR.count_failures(results())
        self.assertEqual(per_file["tests/test_a.py"], 2)
        self.assertEqual(per_file["src/x.test.tsx"], 1)
        self.assertEqual(per_file["src/z.ts"], 1)
        self.assertEqual(dict(per_pr), {1749: 2, 1766: 1})

    def test_sieve_misses_split_unselected_and_budget(self):
        calls = []

        def choose(changed):
            calls.append(tuple(changed))
            if changed == ["backend/app/a.py"]:
                return ["tests/test_a.py"], []
            return ["tests/test_x.py"], ["tests/test_c.py"]

        changed = {1749: ["backend/app/a.py"], 1766: ["frontend/src/q.tsx"]}
        misses = QWR.sieve_misses(results(), changed, choose)
        self.assertNotIn("tests/test_a.py", misses)
        self.assertEqual(misses["tests/test_b.py"]["niewybrany"], {1766})
        self.assertEqual(misses["tests/test_c.py"]["budżet"], {1766})
        # Sito liczone raz na PR, frontend nie jest oceniany.
        self.assertEqual(len(calls), 2)
        self.assertNotIn("src/x.test.tsx", misses)

    def test_pr_without_files_is_skipped(self):
        misses = QWR.sieve_misses(results(), {}, lambda changed: ([], []))
        self.assertEqual(misses, {})

    def test_real_sieve_is_importable_and_callable(self):
        choose = QWR.make_chooser()
        kept, dropped = choose(["backend/tests/test_screen_guides_freshness.py"])
        self.assertIn("tests/test_screen_guides_freshness.py", kept)
        self.assertIsInstance(dropped, list)


class RenderTests(unittest.TestCase):
    def test_report_contains_tables_and_sieve_candidates(self):
        per_file, per_pr = QWR.count_failures(results())
        misses = {"tests/test_b.py": {"niewybrany": {1766}}}
        body = QWR.render_report(
            datetime(2026, 9, 21, tzinfo=timezone.utc),
            datetime(2026, 9, 28, tzinfo=timezone.utc),
            QWR.summarize_runs([run("success"), run("failure")]),
            per_file,
            per_pr,
            misses,
            "owner/repo",
        )
        self.assertIn("| 2 | 1 | 1 | 0 | 50% | 20.0 min |", body)
        self.assertIn("| `tests/test_a.py` | 2 |", body)
        self.assertIn("| #1749 | 2 |", body)
        self.assertIn("| `tests/test_b.py` | #1766 | — |", body)

    def test_empty_report_says_so(self):
        body = QWR.render_report(
            datetime(2026, 9, 21, tzinfo=timezone.utc),
            datetime(2026, 9, 28, tzinfo=timezone.utc),
            QWR.summarize_runs([]),
            QWR.Counter(),
            QWR.Counter(),
            {},
            "o/r",
        )
        self.assertIn("Brak rozpoznanych czerwonych testów.", body)
        self.assertIn("brak kandydatów", body)
        self.assertIn("| 0 | 0 | 0 | 0 | 0% | — |", body)


if __name__ == "__main__":
    unittest.main()
