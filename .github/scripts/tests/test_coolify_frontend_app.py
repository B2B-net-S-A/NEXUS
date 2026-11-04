import contextlib
import importlib.util
import io
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "frontend_app", Path(__file__).parents[1] / "coolify_frontend_app.py"
)
frontend_app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(frontend_app)

SECRET = "private-token-CV-name@example.com"
SOURCE = {
    "git_repository": "git@github.com:B2B-net-S-A/NEXUS.git",
    "environment_id": 7,
    "private_key_id": 3,
    "destination": {"uuid": "dest", "server": {"uuid": "srv"}},
    "settings": {"connect_to_docker_network": False},
}
ENVS = [
    {"key": "DATABASE_URL", "value": SECRET},
    {"key": "ANTHROPIC_API_KEY", "value": SECRET},
    {"key": "NEXT_PUBLIC_API_URL", "value": "https://api.example.pl"},
    {"key": "NEXT_PUBLIC_API_URL", "value": "https://podglad", "is_preview": True},
    {"key": "SENTRY_AUTH_TOKEN", "value": SECRET},
    {"key": "SENTRY_DSN", "value": SECRET},
    {"key": "GIT_SHA", "value": "stary"},
    {"key": "TZ", "value": ""},
]


def fake_api(apps=None):
    calls = []

    def request(method, path, payload=None):
        calls.append((method, path, payload))
        if path == "projects":
            return [{"uuid": "prj"}]
        if path == "projects/prj":
            return {"environments": [{"id": 7, "uuid": "env"}]}
        if path == "security/keys":
            return [{"id": 3, "uuid": "key"}]
        if path == "applications":
            return apps or []
        if path == "applications/src":
            return SOURCE
        if path == "applications/src/envs":
            return ENVS
        if path == "applications/private-deploy-key":
            return {"uuid": "new"}
        return {}

    return request, calls


class EnvSelectionTests(unittest.TestCase):
    def test_only_frontend_keys_cross_over(self):
        keys = {row["key"] for row in frontend_app.frontend_envs(ENVS)}
        self.assertEqual(
            keys,
            {"NEXT_PUBLIC_API_URL", "SENTRY_AUTH_TOKEN", "SENTRY_DSN", "INTERNAL_API_URL"},
        )

    def test_auth_token_is_never_available_at_runtime(self):
        rows = {row["key"]: row for row in frontend_app.frontend_envs(ENVS)}
        self.assertFalse(rows["SENTRY_AUTH_TOKEN"]["is_runtime"])
        self.assertTrue(rows["SENTRY_AUTH_TOKEN"]["is_buildtime"])
        self.assertFalse(rows["SENTRY_DSN"]["is_buildtime"])
        self.assertTrue(rows["NEXT_PUBLIC_API_URL"]["is_buildtime"])

    def test_preview_value_does_not_replace_production(self):
        values = [
            row["value"]
            for row in frontend_app.frontend_envs(ENVS)
            if row["key"] == "NEXT_PUBLIC_API_URL"
        ]
        self.assertEqual(values, ["https://api.example.pl"])

    def test_release_sha_is_not_copied_because_it_would_go_stale(self):
        self.assertNotIn("GIT_SHA", {r["key"] for r in frontend_app.frontend_envs(ENVS)})
        self.assertNotIn("NEXT_PUBLIC_GIT_SHA", frontend_app.RUNTIME_ENV_KEYS)


class CreateTests(unittest.TestCase):
    def test_new_application_takes_no_traffic(self):
        payload = frontend_app.application_payload(
            {k: k for k in ("project", "environment", "server", "destination", "private_key")},
            "repo",
        )
        self.assertNotIn("domains", payload)
        self.assertIs(payload["autogenerate_domain"], False)
        self.assertIs(payload["instant_deploy"], False)
        self.assertIs(payload["is_auto_deploy_enabled"], False)
        self.assertEqual(payload["build_pack"], "dockerfile")
        self.assertNotIn("ports_mappings", payload, "mapowanie portów wyłącza rolling update")

    def test_create_copies_envs_and_joins_shared_network(self):
        request, calls = fake_api()
        with contextlib.redirect_stdout(io.StringIO()):
            frontend_app.create(request, "src")
        posted = [c for c in calls if c[1] == "applications/new/envs"]
        self.assertEqual(len(posted), 4)
        self.assertIn(("PATCH", "applications/src", {"connect_to_docker_network": True}), calls)

    def test_create_refuses_a_second_application(self):
        request, calls = fake_api(apps=[{"name": frontend_app.APP_NAME, "uuid": "x"}])
        with self.assertRaises(ValueError):
            frontend_app.create(request, "src")
        self.assertFalse([c for c in calls if c[0] in {"POST", "PATCH"}])

    def test_missing_identifier_stops_before_any_write(self):
        def request(method, path, payload=None):
            if path == "projects":
                return []
            if path == "security/keys":
                return []
            raise AssertionError(path)

        with self.assertRaises(ValueError):
            frontend_app.resolve_ids(request, SOURCE)


class OutputTests(unittest.TestCase):
    def test_plan_prints_names_and_flags_never_values(self):
        request, calls = fake_api()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            frontend_app.plan(request, "src")
        self.assertNotIn(SECRET, out.getvalue())
        self.assertNotIn("api.example.pl", out.getvalue())
        self.assertIn("SENTRY_AUTH_TOKEN", out.getvalue())
        self.assertFalse([c for c in calls if c[0] != "GET"], "plan tylko czyta")


class DeployTests(unittest.TestCase):
    def test_failed_deployment_is_an_error(self):
        def request(method, path, payload=None):
            if path == "applications":
                return [{"name": frontend_app.APP_NAME, "uuid": "x"}]
            if path.startswith("deploy?"):
                return {"deployments": [{"deployment_uuid": "d"}]}
            return {"status": "failed"}

        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(ValueError):
                frontend_app.deploy(request, poll_seconds=0)


if __name__ == "__main__":
    unittest.main()
