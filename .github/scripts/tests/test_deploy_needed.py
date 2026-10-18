import importlib.util
import io
import json
import os
from contextlib import redirect_stdout
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("deploy_needed", ROOT / "scripts/deploy_needed.py")
NEEDED = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NEEDED)

LIVE = "b" * 40
RELEASE = "c" * 40
REPO = "o/r"


def job(trigger="success", wait="success", started="2026-10-18T12:33:50Z"):
    return {
        "name": "Deploy + smoke test",
        "steps": [
            {"name": "Trigger deployment", "conclusion": trigger, "started_at": started},
            {"name": "Wait for deployment to finish (fail fast on server-side failure)", "conclusion": wait},
        ],
    }


class FakeGitHub:
    """Odpowiedzi API GitHuba; ``runs`` od najnowszego, jak zwraca API."""

    def __init__(self, files=None, status="ahead", runs=None):
        self.files = files if files is not None else []
        self.status = status
        self.runs = runs if runs is not None else [(1, [job()])]
        self.calls = []

    def __call__(self, path):
        self.calls.append(path)
        if "/compare/" in path:
            return {"status": self.status, "files": [{"filename": f} for f in self.files]}
        if path.endswith("per_page=30") and "/workflows/deploy.yml/runs" in path:
            return {"workflow_runs": [{"id": run_id} for run_id, _ in self.runs]}
        for run_id, jobs in self.runs:
            if f"/runs/{run_id}/jobs" in path:
                return {"jobs": jobs}
        raise AssertionError(path)


def envs(*stamps):
    return [{"key": f"K{i}", "updated_at": s} for i, s in enumerate(stamps)]


class DecisionTests(unittest.TestCase):
    def evaluate(self, gh, env_rows, live=LIVE, release=RELEASE, unknown_ok=False):
        return NEEDED.evaluate(gh, REPO, live, release, env_rows, unknown_ok)

    def test_docs_only_merge_with_unchanged_envs_skips(self):
        """18.10, 13:25Z: merge #2313 (sam `docs/`) przebudował produkcję."""
        gh = FakeGitHub(files=["docs/claude/ludzie/runbook-przelaczenia-z-compassa.md"])
        decision = self.evaluate(gh, envs("2026-10-18T12:32:56.000000Z"))
        self.assertTrue(decision.skip, decision.reason)

    def test_env_changed_after_last_deploy_rebuilds_even_without_code_change(self):
        """18.10, 13:29Z: zmienne po wdrożeniu — ten jeden rebuild jest potrzebny."""
        gh = FakeGitHub(files=["docs/a.md"])
        decision = self.evaluate(gh, envs("2026-10-18T12:00:00Z", "2026-10-18T13:29:22.000000Z"))
        self.assertFalse(decision.skip)
        self.assertIn("zmienna", decision.reason)

    def test_dispatch_after_a_deploy_that_already_took_the_envs_skips(self):
        gh = FakeGitHub(runs=[(9, [job(started="2026-10-18T13:35:22Z")])])
        decision = self.evaluate(gh, envs("2026-10-18T13:29:22Z"), live=RELEASE)
        self.assertTrue(decision.skip, decision.reason)
        self.assertFalse(any("/compare/" in c for c in gh.calls), "ten sam SHA — bez porównania")

    def test_env_changed_during_the_last_build_rebuilds(self):
        """Coolify robi zrzut zmiennych na starcie wdrożenia, nie na końcu."""
        gh = FakeGitHub(runs=[(9, [job(started="2026-10-18T13:25:49Z")])])
        decision = self.evaluate(gh, envs("2026-10-18T13:29:08Z"), live=RELEASE)
        self.assertFalse(decision.skip)

    def test_code_change_always_rebuilds(self):
        for path in ("backend/app/main.py", "frontend/src/a.tsx", "docker-compose.yml",
                     ".github/scripts/release.sh", "alloy/config.alloy", "backend/README.md"):
            with self.subTest(path=path):
                decision = self.evaluate(FakeGitHub(files=["docs/x.md", path]), envs("2026-01-01T00:00:00Z"))
                self.assertFalse(decision.skip)
                self.assertIn(path, decision.reason)

    def test_inert_paths(self):
        for path in ("docs/a/b.md", "CLAUDE.md", "README.md", ".github/workflows/deploy.yml",
                     ".github/scripts/tests/test_x.py"):
            with self.subTest(path=path):
                self.assertTrue(NEEDED.is_inert(path))

    def test_renamed_file_counts_its_old_path(self):
        original = FakeGitHub()

        def fetch(path):
            if "/compare/" in path:
                return {"status": "ahead", "files": [{"filename": "docs/moved.py", "previous_filename": "backend/app/x.py"}]}
            return original(path)

        self.assertFalse(self.evaluate(fetch, envs("2026-01-01T00:00:00Z")).skip)

    def test_unknown_relation_or_truncated_diff_rebuilds(self):
        for gh in (FakeGitHub(status="diverged"), FakeGitHub(status="behind"),
                   FakeGitHub(files=["docs/x.md"] * 300)):
            with self.subTest(status=gh.status, n=len(gh.files)):
                self.assertFalse(self.evaluate(gh, envs("2026-01-01T00:00:00Z"), unknown_ok=True).skip)

    def test_live_version_not_a_sha_rebuilds(self):
        for live in ("", "unknown", "abc1234"):
            with self.subTest(live=live):
                self.assertFalse(self.evaluate(FakeGitHub(), envs("2026-01-01T00:00:00Z"), live=live, unknown_ok=True).skip)

    def test_unknown_env_state_depends_on_the_event(self):
        """Ręczny bieg bez odczytu zmiennych wdraża; automatyczny pomija jak dotąd."""
        for rows in (None, [], [{"key": "A"}], envs("nie-data")):
            with self.subTest(rows=rows):
                self.assertFalse(self.evaluate(FakeGitHub(), rows, live=RELEASE).skip)
                self.assertTrue(self.evaluate(FakeGitHub(), rows, live=RELEASE, unknown_ok=True).skip)

    def test_no_successful_deploy_in_history_is_unknown(self):
        runs = [(3, [job(trigger="skipped", wait="skipped")]), (2, [job(wait="failure")]), (1, [])]
        gh = FakeGitHub(runs=runs)
        self.assertFalse(self.evaluate(gh, envs("2026-01-01T00:00:00Z"), live=RELEASE).skip)

    def test_reference_is_the_newest_deploy_that_finished(self):
        runs = [
            (3, [job(trigger="skipped", wait="skipped", started=None)]),  # pominięty rebuild
            (2, [job(wait="failure", started="2026-10-18T14:00:00Z")]),  # padło w Coolify
            (1, [job(started="2026-10-18T13:00:00Z")]),
        ]
        self.assertEqual(
            NEEDED.last_trigger_time(FakeGitHub(runs=runs), REPO).isoformat(), "2026-10-18T13:00:00+00:00"
        )


class TimeParsingTests(unittest.TestCase):
    def test_github_and_laravel_formats(self):
        self.assertEqual(NEEDED.parse_time("2026-10-18T13:29:22Z").isoformat(), "2026-10-18T13:29:22+00:00")
        self.assertEqual(
            NEEDED.parse_time("2026-10-18T13:29:22.000000Z").isoformat(), "2026-10-18T13:29:22+00:00"
        )
        self.assertEqual(NEEDED.parse_time("2026-10-18T15:29:22+02:00").hour, 13)
        self.assertIsNone(NEEDED.parse_time(None))
        self.assertIsNone(NEEDED.parse_time("wczoraj"))


class MainTests(unittest.TestCase):
    def run_main(self, fetch, rows, *extra):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            env_file = Path(tmp) / "envs.json"
            env_file.write_text(json.dumps(rows))
            old = os.environ.get("GITHUB_OUTPUT")
            os.environ["GITHUB_OUTPUT"] = str(out)
            try:
                with redirect_stdout(io.StringIO()):
                    code = NEEDED.main(
                        ["--repo", REPO, "--live", LIVE, "--release", RELEASE, "--envs-file", str(env_file), *extra],
                        fetch=fetch,
                    )
            finally:
                if old is None:
                    del os.environ["GITHUB_OUTPUT"]
                else:
                    os.environ["GITHUB_OUTPUT"] = old
            return code, out.read_text()

    def test_writes_skip_output(self):
        code, out = self.run_main(FakeGitHub(files=["docs/a.md"]), envs("2026-01-01T00:00:00Z"))
        self.assertEqual((code, out), (0, "skip=true\n"))

    def test_api_error_fails_open_to_deploy(self):
        def broken(path):
            raise OSError("api down")

        code, out = self.run_main(broken, envs("2026-01-01T00:00:00Z"), "--env-unknown-is-unchanged")
        self.assertEqual((code, out), (0, "skip=false\n"))


if __name__ == "__main__":
    unittest.main()
