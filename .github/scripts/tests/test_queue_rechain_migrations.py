import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "queue_rechain_migrations", ROOT / ".github/scripts/queue_rechain_migrations.py"
)
QRM = importlib.util.module_from_spec(SPEC)
sys.modules["queue_rechain_migrations"] = QRM
SPEC.loader.exec_module(QRM)

SCRIPT = str(ROOT / "backend/scripts/rechain_migration.py")
VERSIONS = "backend/alembic/versions"
ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_CONFIG_NOSYSTEM": "1",
}


def sh(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, env=ENV, check=True, capture_output=True, text=True
    ).stdout


def migration(revision, down):
    return (
        f'"""{revision}\n\nRevision ID: {revision}\nRevises: {down}\n"""\n\n'
        f'revision = "{revision}"\ndown_revision = "{down}"\n'
    )


def write(root, rel, text):
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def runner(args, **kwargs):
    return subprocess.run(args, env={**ENV, "HOME": kwargs["cwd"]}, **kwargs)


def pr(number, branch="b", draft=False, labels=(), files=(), fork=False):
    return {
        "number": number,
        "headRefName": branch,
        "isDraft": draft,
        "isCrossRepository": fork,
        "labels": [{"name": n} for n in labels],
        "files": [{"path": p} for p in files],
    }


class PickCandidatesTests(unittest.TestCase):
    def test_only_ready_same_repo_prs_with_migration(self):
        mig = f"{VERSIONS}/0500_x.py"
        prs = [
            pr(5, "with-mig", files=["backend/app/x.py", mig]),
            pr(3, "no-mig", files=["backend/app/x.py"]),
            pr(4, "draft", draft=True, files=[mig]),
            pr(6, "held", labels=["wstrzymaj"], files=[mig]),
            pr(7, "fork", fork=True, files=[mig]),
            pr(2, "readme", files=[f"{VERSIONS}/README"]),
            pr(1, "first", files=[mig]),
        ]
        picked = QRM.pick_candidates(prs)
        self.assertEqual(
            [(c.number, c.branch) for c in picked], [(1, "first"), (5, "with-mig")]
        )


class RechainBranchTests(unittest.TestCase):
    """origin (bare) ← main z 0001..0002; PR dodaje 0003_pr na 0002_b."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.origin = str(root / "origin.git")
        self.seed = str(root / "seed")
        self.work = str(root / "work")
        sh(root, "init", "-q", "--bare", "-b", "main", self.origin)
        sh(root, "clone", "-q", self.origin, self.seed)
        write(
            self.seed,
            f"{VERSIONS}/0001_a.py",
            '"""a"""\nrevision = "0001_a"\ndown_revision = None\n',
        )
        write(self.seed, f"{VERSIONS}/0002_b.py", migration("0002_b", "0001_a"))
        write(self.seed, "backend/entrypoint.sh", "# 0002: b\n")
        self.commit_push(self.seed, "main", "base")
        sh(self.seed, "checkout", "-q", "-b", "feature")
        write(self.seed, f"{VERSIONS}/0003_pr.py", migration("0003_pr", "0002_b"))
        write(self.seed, "backend/entrypoint.sh", "# 0002: b\n# 0003: pr (0003_pr)\n")
        write(
            self.seed, "backend/tests/test_pr.py", 'assert down_revision == "0002_b"\n'
        )
        self.commit_push(self.seed, "feature", "pr")
        sh(root, "clone", "-q", self.origin, self.work)

    def tearDown(self):
        self.tmp.cleanup()

    def commit_push(self, cwd, branch, message):
        sh(cwd, "add", "-A")
        sh(cwd, "commit", "-q", "-m", message)
        sh(cwd, "push", "-q", "origin", f"HEAD:refs/heads/{branch}")

    def main_gets_0003(self):
        sh(self.seed, "checkout", "-q", "main")
        write(self.seed, f"{VERSIONS}/0003_main.py", migration("0003_main", "0002_b"))
        write(self.seed, "backend/entrypoint.sh", "# 0002: b\n# 0003: main\n")
        self.commit_push(self.seed, "main", "main: 0003_main")
        sh(self.work, "fetch", "-q", "origin")

    def remote_file(self, path, branch="feature"):
        return sh(self.origin, "show", f"{branch}:{path}")

    def test_collision_is_rechained_committed_and_pushed(self):
        self.main_gets_0003()

        outcome = QRM.rechain_branch(
            self.work, QRM.Candidate(9, "feature"), SCRIPT, runner=runner
        )

        self.assertEqual(outcome.state, "pushed", outcome.log)
        moved = self.remote_file(f"{VERSIONS}/0004_pr.py")
        self.assertIn('revision = "0004_pr"', moved)
        self.assertIn('down_revision = "0003_main"', moved)
        self.assertEqual(
            self.remote_file("backend/entrypoint.sh"),
            "# 0002: b\n# 0004: pr (0004_pr)\n",
        )
        self.assertEqual(
            self.remote_file("backend/tests/test_pr.py"),
            'assert down_revision == "0003_main"\n',
        )
        log = sh(self.origin, "log", "-1", "--format=%an|%s", "feature")
        self.assertTrue(log.startswith(f"{QRM.BOT_NAME}|fix(migracje):"), log)

    def test_branch_already_on_head_is_left_alone(self):
        before = sh(self.origin, "rev-parse", "feature")

        outcome = QRM.rechain_branch(
            self.work, QRM.Candidate(9, "feature"), SCRIPT, runner=runner
        )

        self.assertEqual(outcome.state, "noop", outcome.log)
        self.assertEqual(sh(self.origin, "rev-parse", "feature"), before)

    def test_dry_run_plans_without_pushing(self):
        self.main_gets_0003()
        before = sh(self.origin, "rev-parse", "feature")

        outcome = QRM.rechain_branch(
            self.work, QRM.Candidate(9, "feature"), SCRIPT, dry_run=True, runner=runner
        )

        self.assertEqual(outcome.state, "planned", outcome.log)
        self.assertIn("0004_pr", outcome.log)
        self.assertEqual(sh(self.origin, "rev-parse", "feature"), before)

    def test_session_push_in_between_is_not_overwritten(self):
        self.main_gets_0003()
        real_run = runner

        def racing(args, **kwargs):
            if args[:2] == ["git", "push"]:
                sh(self.seed, "checkout", "-q", "feature")
                write(self.seed, "notes.txt", "sesja pracuje\n")
                self.commit_push(self.seed, "feature", "sesja")
            return real_run(args, **kwargs)

        outcome = QRM.rechain_branch(
            self.work, QRM.Candidate(9, "feature"), SCRIPT, runner=racing
        )

        self.assertEqual(outcome.state, "push_failed", outcome.log)
        self.assertEqual(self.remote_file("notes.txt"), "sesja pracuje\n")
        comment = QRM.build_comment(outcome, "abcdef1234567")
        self.assertIn(QRM.MARKER, comment)
        self.assertIn("rechain_migration.py", comment)

    def test_rechain_error_reported_without_push(self):
        sh(self.seed, "checkout", "-q", "main")
        write(self.seed, f"{VERSIONS}/0003_x.py", migration("0003_x", "0001_a"))
        self.commit_push(self.seed, "main", "main: druga głowa")
        sh(self.work, "fetch", "-q", "origin")
        before = sh(self.origin, "rev-parse", "feature")

        outcome = QRM.rechain_branch(
            self.work, QRM.Candidate(9, "feature"), SCRIPT, runner=runner
        )

        self.assertEqual(outcome.state, "error")
        self.assertIn("głowy", outcome.log)
        self.assertEqual(sh(self.origin, "rev-parse", "feature"), before)


class BuildCommentTests(unittest.TestCase):
    def test_pushed_comment_tells_session_to_pull(self):
        body = QRM.build_comment(
            QRM.Outcome(1, "pushed", "Zmiany: ..."), "abcdef1234567"
        )
        self.assertTrue(body.startswith(QRM.MARKER))
        self.assertIn("abcdef123", body)
        self.assertIn("git pull", body)


if __name__ == "__main__":
    unittest.main()
