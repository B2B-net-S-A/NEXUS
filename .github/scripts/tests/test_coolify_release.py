import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "configure_release", ROOT / ".github/scripts/configure_coolify_release.py"
)
CONFIG = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONFIG)
SHA = "b" * 40


class ReleaseConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.application = {"build_pack": "dockercompose", "base_directory": "/", "docker_compose_location": "/docker-compose.yml"}
        self.cycle = {"key": "SOURCE_COMMIT", "value": "${GIT_SHA:-unknown}", "is_preview": False, "uuid": "cycle"}

    def test_repairs_only_known_production_cycle_and_is_idempotent(self):
        envs = [self.cycle.copy(), {**self.cycle, "is_preview": True, "uuid": "preview"}, {"key": "SENTRY_AUTH_TOKEN", "value": "synthetic-private-token"}]
        calls = []

        def request(method, path, payload=None):
            calls.append((method, path, payload))
            if method == "PATCH":
                self.application.update(payload)
            if method == "DELETE":
                envs[:] = [row for row in envs if row.get("uuid") != path.rsplit("/", 1)[1]]
            return envs if path.endswith("/envs") else self.application

        CONFIG.configure(request, "nexus")
        self.assertEqual([c[1] for c in calls if c[0] == "DELETE"], ["applications/nexus/envs/cycle"])
        self.assertEqual(envs[-1]["value"], "synthetic-private-token")
        calls.clear()
        CONFIG.configure(request, "nexus")
        self.assertTrue(all(c[0] == "GET" for c in calls))

    def test_does_not_overwrite_unrelated_configuration(self):
        for application, envs in [
            ({**self.application, "docker_compose_custom_build_command": "existing-command"}, []),
            (self.application, [{**self.cycle, "value": "a" * 40}]),
            ({**self.application, "base_directory": "/other"}, []),
        ]:
            with self.subTest(application=application), self.assertRaises(ValueError):
                CONFIG.planned_changes(application, envs)

    def test_unpersisted_patch_fails_readback(self):
        def request(method, path, payload=None):
            return [] if path.endswith("/envs") else self.application
        with self.assertRaises(ValueError):
            CONFIG.configure(request, "nexus")


class RemoteBuildWrapperTests(unittest.TestCase):
    """A native CLI stand-in records calls; no Docker daemon or real CLI runs."""

    def run_wrapper(self, images, exit_status=0):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docker-compose.yml").write_text("services: {}\n")
            # This file must never be sourced/evaluated by the wrapper.
            (root / "build.env").write_text("SECRET=synthetic-private-token\nTRAP=$(touch unexpected-file)\n")
            record = root / "calls.jsonl"
            standin = root / "docker"
            standin.write_text(
                "#!" + sys.executable + "\n"
                "import os,sys,json\n"
                "with open(os.environ['CALLS'], 'a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')\n"
                "if sys.argv[-2:] == ['config','--images']: print(os.environ['IMAGES'])\n"
                "elif 'build' in sys.argv: sys.exit(int(os.environ['BUILD_EXIT']))\n"
                "else: sys.exit(90)\n"
            )
            standin.chmod(0o755)
            result = subprocess.run(
                ["sh", str(ROOT / ".github/scripts/release.sh"), "--project-directory", str(root), "--env-file", str(root / "build.env")],
                env={**os.environ, "PATH": str(root) + os.pathsep + os.environ["PATH"], "CALLS": str(record), "IMAGES": images, "BUILD_EXIT": str(exit_status), "GIT_SHA": "a" * 40},
                cwd=root, capture_output=True, text=True,
            )
            calls = [json.loads(line) for line in record.read_text().splitlines()]
            self.assertFalse((root / "unexpected-file").exists())
            self.assertNotIn("synthetic-private-token", result.stdout + result.stderr)
            return result, calls

    def test_actual_checkout_overrides_stale_workflow_sha_for_both_builds(self):
        result, calls = self.run_wrapper(f"postgres:16\napp123_backend:{SHA}\napp123_frontend:{SHA}\napp123_backup:{SHA}")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("GIT_SHA=" + SHA, calls[-1])
        self.assertIn("NEXT_PUBLIC_GIT_SHA=" + SHA, calls[-1])
        self.assertIn("--pull", calls[-1])
        self.assertIn("-f", calls[-1])
        self.assertNotIn("a" * 40, result.stdout)

    def test_unknown_mixed_or_ambiguous_tags_never_start_build(self):
        for images in [
            "app123_backend:unknown\napp123_frontend:unknown",
            f"app123_backend:{SHA}\napp123_frontend:{'a' * 40}",
            f"app123_backend:{SHA}\nother_backend:{SHA}\napp123_frontend:{SHA}",
            f"app123_backend:{SHA}\nother_frontend:{SHA}",
        ]:
            with self.subTest(images=images):
                result, calls = self.run_wrapper(images)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any("build" in call for call in calls))

    def test_build_failure_propagates(self):
        result, _ = self.run_wrapper(f"app123_backend:{SHA}\napp123_frontend:{SHA}", 7)
        self.assertEqual(result.returncode, 7)

    def test_runtime_prefers_immutable_image_sha_over_platform_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sha"
            helper = ROOT / "backend/scripts/load-build-release.sh"
            for value, expected in [(SHA, SHA), ("unknown", "legacy")]:
                path.write_text(value + "\n")
                result = subprocess.run(["bash", "-c", 'source "$1"; GIT_SHA=legacy; load_build_release "$2"; printf "%s" "$GIT_SHA"', "test", str(helper), str(path)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stdout, expected)


if __name__ == "__main__":
    unittest.main()
