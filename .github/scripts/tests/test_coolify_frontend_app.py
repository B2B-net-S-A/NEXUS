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


def fake_api(apps=None, destinations=None):
    calls = []

    def request(method, path, payload=None):
        calls.append((method, path, payload))
        if path == "servers/srv/destinations":
            if method == "POST":
                return {"uuid": "front-net", "network": payload["network"]}
            return destinations or [{"uuid": "dest", "network": "coolify"}]
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

    def test_create_copies_envs_into_own_network_and_leaves_compose_alone(self):
        request, calls = fake_api()
        with contextlib.redirect_stdout(io.StringIO()):
            frontend_app.create(request, "src")
        posted = [c for c in calls if c[1] == "applications/new/envs"]
        self.assertEqual(len(posted), 4)
        self.assertIn(
            ("POST", "servers/srv/destinations", {"name": "nexus-front", "network": "nexus-front"}),
            calls,
        )
        app = next(c[2] for c in calls if c[1] == "applications/private-deploy-key")
        self.assertEqual(app["destination_uuid"], "front-net")
        self.assertIs(app["is_consistent_container_name_enabled"], False)
        # `connect_to_docker_network` wpiąłby `postgres` NEXUSA do sieci z `postgres` Coolify.
        self.assertFalse([c for c in calls if c[1] == "applications/src" and c[0] != "GET"])

    def test_create_reuses_existing_network(self):
        request, calls = fake_api(destinations=[{"uuid": "net1", "network": "nexus-front"}])
        with contextlib.redirect_stdout(io.StringIO()):
            frontend_app.create(request, "src")
        self.assertFalse([c for c in calls if c[1] == "servers/srv/destinations" and c[0] == "POST"])
        app = next(c[2] for c in calls if c[1] == "applications/private-deploy-key")
        self.assertEqual(app["destination_uuid"], "net1")

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


def deploy_api(deployment, app_status="running:healthy"):
    def request(method, path, payload=None):
        if path == "applications":
            return [{"name": frontend_app.APP_NAME, "uuid": "x"}]
        if path.startswith("deploy?"):
            return {"deployments": [{"deployment_uuid": "d"}]}
        if path == "deployments/d":
            return deployment
        if path == "applications/x":
            return {"status": app_status}
        raise AssertionError(path)

    return request


SHA = "a" * 40
BUILD_LOG = '[{"output": "version.json → /app/public/version.json (sha=' + SHA + ')"}, {"output": "' + SECRET + '"}]'


class DeployTests(unittest.TestCase):
    def run_deploy(self, request):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            frontend_app.deploy(request, SHA, poll_seconds=0, health_polls=2)
        return out.getvalue()

    def test_deploy_pins_the_commit_before_queueing(self):
        calls = []
        api = deploy_api({"status": "finished", "commit": SHA, "logs": BUILD_LOG})

        def request(method, path, payload=None):
            calls.append((method, path, payload))
            return api(method, path, payload)

        self.run_deploy(request)
        pin = calls.index(("PATCH", "applications/x", {"git_commit_sha": SHA}))
        queued = next(i for i, c in enumerate(calls) if c[1].startswith("deploy?"))
        self.assertLess(pin, queued)

    def test_trigger_refuses_anything_but_a_full_sha(self):
        for commit in ["", "HEAD", SHA[:7], SHA + "; rm -rf /"]:
            with self.subTest(commit=commit), self.assertRaises(ValueError):
                frontend_app.trigger(deploy_api({}), commit)

    def test_compose_commit_waits_until_coolify_resolves_head(self):
        answers = iter([{"status": "queued", "commit": "HEAD"}, {"status": "in_progress", "commit": SHA}])
        self.assertEqual(
            frontend_app.compose_commit(lambda *a, **k: next(answers), "c", poll_seconds=0), SHA
        )

    def test_compose_failure_leaves_front_alone(self):
        with self.assertRaises(ValueError):
            frontend_app.compose_commit(lambda *a, **k: {"status": "failed", "commit": "HEAD"}, "c", poll_seconds=0)

    def test_healthy_container_with_matching_build_passes_without_leaking_logs(self):
        out = self.run_deploy(deploy_api({"status": "finished", "commit": SHA, "logs": BUILD_LOG}))
        self.assertIn("running:healthy", out)
        self.assertIn("w logu builda: tak", out)
        self.assertNotIn(SECRET, out)

    def test_unhealthy_container_is_an_error(self):
        request = deploy_api({"status": "finished", "commit": SHA, "logs": BUILD_LOG}, "running:unhealthy")
        with self.assertRaises(ValueError):
            self.run_deploy(request)

    def test_build_with_other_sha_is_an_error(self):
        logs = BUILD_LOG.replace(SHA, "unknown")
        with self.assertRaises(ValueError):
            self.run_deploy(deploy_api({"status": "finished", "commit": SHA, "logs": logs}))

    def test_missing_logs_are_reported_not_assumed(self):
        out = self.run_deploy(deploy_api({"status": "finished", "commit": SHA}))
        self.assertIn("niepotwierdzone", out)

    def test_failed_deployment_is_an_error(self):
        def request(method, path, payload=None):
            if path == "applications":
                return [{"name": frontend_app.APP_NAME, "uuid": "x"}]
            if path.startswith("deploy?"):
                return {"deployments": [{"deployment_uuid": "d"}]}
            return {"status": "failed"}

        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(ValueError):
                frontend_app.deploy(request, SHA, poll_seconds=0)


COMPOSE_RAW = "services:\n  postgres:\n    image: x\n  backend:\n    build: .\n"
DOMAINS = (
    '{"backend": {"domain": "https://api.example.pl"},'
    ' "frontend": {"domain": "https://app.example.pl,https://kariera.example.pl", "redirect": "non-www"}}'
)


def switch_api(domains=DOMAINS, raw=COMPOSE_RAW, fqdn=""):
    calls = []
    deploy = deploy_api({"status": "finished", "commit": SHA, "logs": BUILD_LOG})

    def request(method, path, payload=None):
        calls.append((method, path, payload))
        if path == "applications/src":
            return {"docker_compose_domains": domains, "docker_compose_raw": raw}
        if path == "applications/x" and method == "GET":
            return {"status": "running:healthy", "fqdn": fqdn, "redirect": "non-www"}
        return deploy(method, path, payload)

    return request, calls


class SwitchTests(unittest.TestCase):
    def run_switch(self, request):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            frontend_app.switch(request, "src", SHA, poll_seconds=0, health_polls=2)
        return out.getvalue()

    def test_new_app_serves_the_domains_before_compose_lets_go(self):
        request, calls = switch_api()
        out = self.run_switch(request)
        patches = [(c[1], c[2]) for c in calls if c[0] == "PATCH"]
        self.assertEqual(
            patches[0],
            (
                "applications/x",
                {
                    "domains": "https://app.example.pl,https://kariera.example.pl",
                    "force_domain_override": True,
                    "redirect": "non-www",
                },
            ),
        )
        rolled = next(i for i, c in enumerate(calls) if c[1].startswith("deploy?"))
        released = calls.index(
            (
                "PATCH",
                "applications/src",
                {"docker_compose_domains": [{"name": "backend", "domain": "https://api.example.pl"}]},
            )
        )
        self.assertLess(rolled, released, "compose oddaje domeny dopiero po zdrowym wdrożeniu frontu")
        self.assertIn("przeniesiono domen frontu: 2", out)
        self.assertNotIn("app.example.pl", out)

    def test_unhealthy_front_keeps_domains_in_compose(self):
        request, calls = switch_api()
        deploy = deploy_api({"status": "failed"})

        def failing(method, path, payload=None):
            if path.startswith("deploy?") or path.startswith("deployments/"):
                return deploy(method, path, payload)
            return request(method, path, payload)

        with self.assertRaises(ValueError):
            self.run_switch(failing)
        self.assertFalse([c for c in calls if c[1] == "applications/src" and c[0] == "PATCH"])

    def test_switch_twice_is_refused(self):
        request, calls = switch_api(domains='{"backend": {"domain": "https://api.example.pl"}}')
        with self.assertRaises(ValueError):
            self.run_switch(request)
        self.assertFalse([c for c in calls if c[0] != "GET"])


class RollbackTests(unittest.TestCase):
    def test_rollback_needs_compose_with_frontend_service(self):
        request, calls = switch_api(fqdn="https://app.example.pl")
        with self.assertRaises(ValueError):
            frontend_app.rollback(request, "src")
        self.assertFalse([c for c in calls if c[0] != "GET"])

    def test_rollback_gives_domains_back_to_compose(self):
        raw = COMPOSE_RAW + "  frontend:\n    build: ./frontend\n"
        request, calls = switch_api(
            domains='{"backend": {"domain": "https://api.example.pl"}}', raw=raw, fqdn="https://app.example.pl"
        )
        with contextlib.redirect_stdout(io.StringIO()):
            frontend_app.rollback(request, "src")
        self.assertIn(
            (
                "PATCH",
                "applications/src",
                {
                    "docker_compose_domains": [
                        {"name": "backend", "domain": "https://api.example.pl"},
                        {"name": "frontend", "domain": "https://app.example.pl", "redirect": "non-www"},
                    ],
                    "force_domain_override": True,
                },
            ),
            calls,
        )


if __name__ == "__main__":
    unittest.main()
