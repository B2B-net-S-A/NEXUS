import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "queue_failure_feedback", ROOT / ".github/scripts/queue_failure_feedback.py"
)
QFF = importlib.util.module_from_spec(SPEC)
sys.modules["queue_failure_feedback"] = QFF
SPEC.loader.exec_module(QFF)

TS = "2026-09-23T22:02:46.6556296Z "
ESC = "\x1b"

PYTEST_LOG = "\n".join(
    [
        TS + "tests/test_x.py::test_y FAILED [ 87%]",
        TS
        + "=========================== short test summary info ============================",
        TS
        + "FAILED tests/test_x.py::test_y - AssertionError: łańcuch rozszczepiony, głowy: ['0364', '0368']",
        TS
        + "ERROR tests/test_db.py::test_setup - sqlalchemy.exc.OperationalError: boom",
        TS
        + "FAILED tests/test_x.py::test_y - AssertionError: duplicate line from rerun",
        TS + "FAILED tests/test_param.py::test_p[a-b] ",
        TS + "##[error]Process completed with exit code 1.",
    ]
)

VITEST_LOG = "\n".join(
    [
        TS
        + f"{ESC}[41m{ESC}[1m FAIL {ESC}[22m{ESC}[49m src/app/cv/i/[token]/page.test.tsx"
        f"{ESC}[2m > {ESC}[22mapproved public CV{ESC}[2m > {ESC}[22mkeeps approved HTML",
        TS
        + f'{ESC}[31m{ESC}[1mError{ESC}[22m: {ESC}[2mexpect(element).toHaveAttribute("srcdoc")',
        TS + " FAIL  src/lib/__tests__/x.test.ts [ src/lib/__tests__/x.test.ts ]",
        TS + "TypeError: Cannot read properties of undefined",
    ]
)

TSC_LOG = "\n".join(
    [
        TS
        + "src/components/Foo.tsx(12,3): error TS2322: Type 'string' is not assignable to type 'number'.",
        TS + "src/lib/bar.ts:4:10 - error TS2304: Cannot find name 'baz'.",
    ]
)


class ParseFailuresTests(unittest.TestCase):
    def test_pytest_summary_lines_with_reason_deduplicated(self):
        failures = QFF.parse_failures(PYTEST_LOG)
        ids = [(f.kind, f.test_id) for f in failures]
        self.assertEqual(
            ids,
            [
                ("pytest", "tests/test_x.py::test_y"),
                ("pytest", "tests/test_db.py::test_setup"),
                ("pytest", "tests/test_param.py::test_p[a-b]"),
            ],
        )
        self.assertTrue(failures[0].reason.startswith("AssertionError: łańcuch"))
        self.assertEqual(failures[0].file, "tests/test_x.py")
        # Linia postępu („… FAILED [ 87%]”) nie jest drugim wpisem.
        self.assertEqual(
            len([f for f in failures if f.test_id == "tests/test_x.py::test_y"]), 1
        )

    def test_vitest_fail_lines_strip_ansi_and_take_reason(self):
        failures = QFF.parse_failures(VITEST_LOG)
        self.assertEqual(
            [f.test_id for f in failures],
            [
                "src/app/cv/i/[token]/page.test.tsx > approved public CV > keeps approved HTML",
                "src/lib/__tests__/x.test.ts",
            ],
        )
        self.assertTrue(failures[0].reason.startswith("Error: expect(element)"))
        self.assertEqual(failures[0].file, "src/app/cv/i/[token]/page.test.tsx")
        self.assertTrue(failures[1].reason.startswith("TypeError"))

    def test_tsc_errors_in_both_formats(self):
        failures = QFF.parse_failures(TSC_LOG)
        self.assertEqual([f.kind for f in failures], ["tsc", "tsc"])
        self.assertEqual(failures[0].test_id, "src/components/Foo.tsx(12,3)")
        self.assertTrue(failures[0].reason.startswith("TS2322"))
        self.assertEqual(failures[1].test_id, "src/lib/bar.ts(4,10)")
        self.assertEqual(failures[1].file, "src/lib/bar.ts")

    def test_long_reason_is_shortened_and_backticks_neutralised(self):
        log = TS + "FAILED tests/test_a.py::t - AssertionError: `x` " + "y" * 400
        (failure,) = QFF.parse_failures(log)
        self.assertLessEqual(len(failure.reason), QFF.MAX_REASON)
        self.assertNotIn("`", failure.reason)

    def test_first_job_error_skips_exit_code_line(self):
        log = "\n".join(
            [
                TS + "##[error]Process completed with exit code 1.",
                TS
                + "##[error]Co najmniej jeden shard pytest nie przeszedł (result=failure)",
            ]
        )
        self.assertEqual(
            QFF.first_job_error(log),
            "Co najmniej jeden shard pytest nie przeszedł (result=failure)",
        )
        self.assertEqual(QFF.first_job_error(TS + "nothing"), "")


COMPARE = {
    "status": "diverged",
    "commits": [
        {
            "sha": "626bbe",
            "commit": {"message": "feat(ui): responsywność (#1749)\n\nbody (#1)"},
        },
        {"sha": "43a46d", "commit": {"message": "test: testy po północy (#1766)"}},
        {"sha": "abc", "commit": {"message": "Merge branch 'main' into x"}},
        {"sha": "def", "commit": {"message": "chore: again (#1749)"}},
    ],
}


class GroupTests(unittest.TestCase):
    def test_parse_queue_branch(self):
        self.assertEqual(
            QFF.parse_queue_branch(
                "gh-readonly-queue/main/pr-1766-626bbe5e5a69ba999d47b335c1c8f0c24d8f9045"
            ),
            (1766, "626bbe5e5a69ba999d47b335c1c8f0c24d8f9045"),
        )
        self.assertEqual(QFF.parse_queue_branch("main"), (None, None))
        self.assertEqual(QFF.parse_queue_branch(""), (None, None))

    def test_prs_from_compare_reads_subject_only_in_order(self):
        self.assertEqual(QFF.prs_from_compare(COMPARE), [1749, 1766])

    def test_group_falls_back_to_branch_name(self):
        branch = "gh-readonly-queue/main/pr-1800-" + "a" * 40
        self.assertEqual(QFF.group_prs(None, branch), [1800])
        self.assertEqual(QFF.group_prs(COMPARE, branch), [1749, 1766, 1800])
        self.assertEqual(QFF.group_prs({"commits": []}, "main"), [])


class MessageTests(unittest.TestCase):
    def test_polish_plural(self):
        self.assertEqual(
            [QFF.plural_tests(n) for n in (1, 2, 4, 5, 12, 22, 25)],
            [
                "1 test",
                "2 testy",
                "4 testy",
                "5 testów",
                "12 testów",
                "22 testy",
                "25 testów",
            ],
        )

    def test_status_description_fits_github_limit(self):
        failures = [QFF.Failure("pytest", f"tests/t.py::t{i}") for i in range(3)]
        self.assertEqual(
            QFF.status_description(failures, []),
            "Wypadł z kolejki: 3 testy — szczegóły w komentarzu",
        )
        long_job = [("J" * 200, "")]
        self.assertLessEqual(len(QFF.status_description([], long_job)), 140)
        self.assertIn("Wypadł z kolejki", QFF.status_description([], []))

    def test_comment_has_marker_tests_run_link_and_group_note(self):
        failures = [
            QFF.Failure("pytest", f"tests/t.py::t{i}", "boom") for i in range(25)
        ]
        body = QFF.build_comment(
            1749,
            [1749, 1766],
            1766,
            "https://run/1",
            failures,
            [("Frontend", "build failed")],
        )
        self.assertTrue(body.startswith(QFF.MARKER))
        self.assertIn("https://run/1", body)
        self.assertIn("`tests/t.py::t0` — boom", body)
        self.assertNotIn("tests/t.py::t20`", body)
        self.assertIn("…i jeszcze 5", body)
        self.assertIn("#1749, #1766", body)
        self.assertIn("Winny może być inny PR", body)
        self.assertIn("Bieg dotyczył wpisu #1766", body)
        self.assertIn("Frontend: build failed", body)

    def test_single_pr_comment_has_no_group_note(self):
        body = QFF.build_comment(
            1766, [1766], 1766, "u", [QFF.Failure("tsc", "a.ts(1,1)")], []
        )
        self.assertNotIn("Grupa w kolejce", body)


if __name__ == "__main__":
    unittest.main()


class HeadChangedAfterRunTest(unittest.TestCase):
    def test_commit_after_run_start_skips_status(self) -> None:
        self.assertTrue(
            QFF.head_changed_after_run("2026-09-24T10:30:00Z", "2026-09-24T10:18:04Z")
        )

    def test_commit_before_run_start_keeps_status(self) -> None:
        self.assertFalse(
            QFF.head_changed_after_run("2026-09-24T10:02:00Z", "2026-09-24T10:18:04Z")
        )

    def test_missing_dates_keep_status(self) -> None:
        self.assertFalse(QFF.head_changed_after_run("", "2026-09-24T10:18:04Z"))
