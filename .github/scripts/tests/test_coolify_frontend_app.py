import base64
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


COMPOSE_RAW_NO_NETWORK = "services:\n  postgres:\n    image: x\n  backend:\n    build: .\n"
COMPOSE_RAW = COMPOSE_RAW_NO_NETWORK + "\nnetworks:\n  nexus-front:\n    external: true\n    name: nexus-front\n"
DOMAINS = (
    '{"backend": {"domain": "https://api.example.pl"},'
    ' "frontend": {"domain": "https://app.example.pl,https://kariera.example.pl", "redirect": "non-www"}}'
)


# Wycinek etykiet, które Coolify 4.5.3 generuje dla aplikacji z domeną (fqdnLabelsForTraefik).
COOLIFY_LABELS = [
    "traefik.enable=true",
    "traefik.http.middlewares.gzip-sse.compress=true",
    "traefik.http.middlewares.redirect-to-https.redirectscheme.scheme=https",
    "traefik.http.routers.http-0-x.entryPoints=http",
    "traefik.http.routers.http-0-x.middlewares=redirect-to-https",
    "traefik.http.routers.http-0-x.rule=Host(`app.example.pl`) && PathPrefix(`/`)",
    "traefik.http.routers.https-0-x.entryPoints=https",
    "traefik.http.routers.https-0-x.middlewares=gzip-sse",
    "traefik.http.routers.https-0-x.rule=Host(`app.example.pl`) && PathPrefix(`/`)",
    "traefik.http.routers.https-0-x.tls=true",
    "traefik.http.routers.https-1-x.rule=Host(`kariera.example.pl`) && PathPrefix(`/`)",
    "traefik.http.routers.https-1-x.tls=true",
]


# Compose złożony przez Coolify (Yaml::dump, wcięcie 2) — tak jak zwraca go API.
RENDERED = (
    "services:\n  postgres:\n    image: x\n    networks:\n      ocgkw: null\n"
    "  backend:\n    build:\n      context: .\n    networks:\n      nexus-front: null\n      ocgkw: null\n"
    "networks:\n  nexus-front:\n    name: nexus-front\n    external: true\n"
)
# 13.11.2026: plik miał sieć na najwyższym poziomie, a parser Coolify zgubił ją w usłudze.
RENDERED_LOST = RENDERED.replace("      nexus-front: null\n", "")
SERVER_IP = "203.0.113.7"


def user_path(callback="https://app.example.pl/login?error=access_denied", sha=SHA, login=200):
    """Fałszywe `get`: odpowiedzi frontu jak dla przeglądarki; zapisuje wywołania."""
    seen = []

    def get(url, host=None):
        seen.append((url, host))
        if url.endswith("/version.json"):
            return 200, {}, ('{"sha": "%s"}' % sha).encode()
        if "/auth/microsoft/callback" in url:
            return 302, {"location": callback}, b""
        return login, {}, b""

    return get, seen


BROKEN = "https://app.example.pl/login?error=backend_unreachable"


def switch_api(domains=DOMAINS, raw=COMPOSE_RAW, fqdn="", rendered=RENDERED):
    calls = []
    deploy = deploy_api({"status": "finished", "commit": SHA, "logs": BUILD_LOG})
    labels = base64.b64encode("\n".join(COOLIFY_LABELS).encode()).decode()

    def request(method, path, payload=None):
        calls.append((method, path, payload))
        if path == "applications/src":
            return {
                "docker_compose_domains": domains,
                "docker_compose_raw": raw,
                "docker_compose": rendered,
                "destination": {"server": {"uuid": "srv", "ip": SERVER_IP}},
            }
        if path == "applications/x" and method == "GET":
            return {"status": "running:healthy", "fqdn": fqdn, "redirect": "non-www", "custom_labels": labels}
        if path == "applications/x/stop":
            return {}
        return deploy(method, path, payload)

    return request, calls


class SwitchTests(unittest.TestCase):
    def run_switch(self, request, get=None):
        get = get or user_path()[0]
        with contextlib.redirect_stdout(io.StringIO()) as out:
            frontend_app.switch(
                request, "src", SHA, get=get, watch_seconds=10, probe_every=5,
                sleep=lambda _s: None, poll_seconds=0, health_polls=2,
            )
        return out.getvalue()

    def test_new_app_serves_the_domains_before_compose_lets_go(self):
        request, calls = switch_api()
        out = self.run_switch(request)
        patches = [(c[1], c[2]) for c in calls if c[0] == "PATCH"]
        real = next(i for i, p in enumerate(patches) if (p[1] or {}).get("domains", "").startswith("https://"))
        self.assertEqual(
            patches[real],
            (
                "applications/x",
                {
                    "domains": "https://app.example.pl,https://kariera.example.pl",
                    "force_domain_override": True,
                    "is_container_label_readonly_enabled": True,
                    "redirect": "non-www",
                },
            ),
        )
        path, labels_patch = patches[real + 1]
        self.assertEqual(path, "applications/x")
        self.assertIs(labels_patch["is_container_label_readonly_enabled"], False)
        self.assertEqual(labels_patch["rolling_update_drain_seconds"], 10)
        self.assertEqual(labels_patch["stop_grace_period"], 30)
        written = base64.b64decode(labels_patch["custom_labels"]).decode().splitlines()
        self.assertEqual(written, frontend_app.with_retry(COOLIFY_LABELS, "nexus-front-retry"))
        labelled = calls.index(("PATCH", "applications/x", labels_patch))
        deploys = [i for i, c in enumerate(calls) if c[1].startswith("deploy?")]
        self.assertEqual(len(deploys), 2, "najpierw adres próbny, potem domeny")
        self.assertLess(labelled, deploys[1])
        rolled = deploys[1]
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

    def test_switch_before_compose_joins_the_network_is_refused(self):
        # Healthcheck frontu (`wget /`) nie sprawdza backendu, więc bez tej odmowy ruch
        # trafiłby na front, który nie widzi `backend:8000` (logowanie Microsoft, SSR).
        request, calls = switch_api(raw=COMPOSE_RAW_NO_NETWORK)
        with self.assertRaises(ValueError):
            self.run_switch(request)
        self.assertFalse([c for c in calls if c[0] != "GET"])

    def test_gate_tries_the_new_front_on_the_test_address_before_any_user_domain(self):
        request, calls = switch_api()
        get, seen = user_path()
        self.run_switch(request, get)
        first = next(c for c in calls if c[0] == "PATCH")
        self.assertEqual(first[2]["domains"], "http://" + frontend_app.paths.CHECK_HOST)
        gate = [s for s in seen if s[1] == frontend_app.paths.CHECK_HOST]
        self.assertEqual({u.split(SERVER_IP, 1)[1] for u, _ in gate}, {
            "/version.json", frontend_app.paths.CALLBACK_PATH, "/login",
        })
        self.assertTrue(all(u.startswith("http://" + SERVER_IP) for u, _ in gate))

    def test_front_that_cannot_see_the_backend_never_gets_user_domains(self):
        # Dokładnie 13.11.2026: kontener zdrowy, a callback logowania = backend_unreachable.
        request, calls = switch_api()
        with self.assertRaises(ValueError) as caught:
            self.run_switch(request, user_path(callback=BROKEN)[0])
        self.assertIn("domeny zostają w compose", str(caught.exception))
        domain_patches = [c[2]["domains"] for c in calls if c[0] == "PATCH" and "domains" in (c[2] or {})]
        self.assertFalse([d for d in domain_patches if d.startswith("https://")])
        self.assertFalse([c for c in calls if c[1] == "applications/src" and c[0] == "PATCH"])

    def test_failure_after_switch_stops_new_front_and_keeps_compose_domains(self):
        request, calls = switch_api()
        state = {"public": 0}

        def get(url, host=None):
            if host is None and "/auth/microsoft/callback" in url:
                state["public"] += 1
                return 302, {"location": BROKEN}, b""
            return user_path()[0](url, host)

        with self.assertRaises(ValueError) as caught:
            self.run_switch(request, get)
        self.assertIn("ruch wrócił do frontu z compose", str(caught.exception))
        self.assertIn(("POST", "applications/x/stop", None), calls)
        self.assertEqual(
            calls[-1],
            ("PATCH", "applications/x", {"domains": "http://" + frontend_app.paths.CHECK_HOST, "force_domain_override": True}),
        )
        self.assertFalse([c for c in calls if c[1] == "applications/src" and c[0] == "PATCH"])
        self.assertGreaterEqual(state["public"], 2, "przerwanie dopiero po dwóch rundach z usterką")

    def test_single_blip_after_switch_does_not_roll_back(self):
        request, calls = switch_api()
        state = {"n": 0}

        def get(url, host=None):
            if host is None and "/auth/microsoft/callback" in url:
                state["n"] += 1
                if state["n"] == 1:
                    return 502, {}, b""
            return user_path()[0](url, host)

        self.run_switch(request, get)
        self.assertNotIn(("POST", "applications/x/stop", None), calls)

    def test_switch_refuses_when_coolify_dropped_the_network(self):
        request, calls = switch_api(rendered=RENDERED_LOST)
        with self.assertRaises(ValueError) as caught:
            self.run_switch(request)
        self.assertIn("backend", str(caught.exception))
        self.assertFalse([c for c in calls if c[0] != "GET"])

    def test_switch_refuses_without_rendered_compose(self):
        request, calls = switch_api(rendered="")
        with self.assertRaises(ValueError):
            self.run_switch(request)
        self.assertFalse([c for c in calls if c[0] != "GET"])

    def test_gate_output_never_shows_the_server_address(self):
        request, _ = switch_api()
        out = self.run_switch(request)
        self.assertNotIn(SERVER_IP, out)
        self.assertIn("adres próbny", out)

    def test_switch_twice_is_refused(self):
        request, calls = switch_api(domains='{"backend": {"domain": "https://api.example.pl"}}')
        with self.assertRaises(ValueError):
            self.run_switch(request)
        self.assertFalse([c for c in calls if c[0] != "GET"])


def preflight_api(networks=("nexus-front",), apps=None, fqdn="", domains=DOMAINS):
    def request(method, path, payload=None):
        assert method == "GET", "preflight tylko czyta"
        if path == "applications/src":
            return {"destination": {"server": {"uuid": "srv"}}, "docker_compose_domains": domains}
        if path == "servers/srv/destinations":
            return [{"uuid": "d-" + n, "network": n} for n in ("coolify", *networks)]
        if path == "applications":
            return apps if apps is not None else [{"name": frontend_app.APP_NAME, "uuid": "x"}]
        if path == "applications/x":
            return {"fqdn": fqdn}
        raise AssertionError(path)

    return request


BACKEND_ONLY = '{"backend": {"domain": "https://api.example.pl"}}'


class PreflightTests(unittest.TestCase):
    def check(self, request, required):
        with contextlib.redirect_stdout(io.StringIO()):
            frontend_app.preflight(request, "src", required)

    def test_missing_network_stops_deploy_before_compose(self):
        with self.assertRaises(ValueError):
            self.check(preflight_api(networks=()), False)

    def test_network_is_enough_before_the_switch(self):
        self.check(preflight_api(), False)

    def test_after_cutover_front_must_own_the_domains(self):
        cases = [
            preflight_api(fqdn="", domains=BACKEND_ONLY),  # aplikacja bez domen → 404
            preflight_api(fqdn="https://app.example.pl", domains=DOMAINS),  # switch nie zrobiony
            preflight_api(apps=[], domains=BACKEND_ONLY),  # brak aplikacji
        ]
        for request in cases:
            with self.subTest(), self.assertRaises(ValueError):
                self.check(request, True)
        self.check(preflight_api(fqdn="https://app.example.pl", domains=BACKEND_ONLY), True)


class RenderedComposeTests(unittest.TestCase):
    def test_reads_service_networks_as_coolify_dumps_them(self):
        self.assertEqual(frontend_app.rendered_service_networks(RENDERED, "backend"), {"nexus-front", "ocgkw"})
        self.assertEqual(frontend_app.rendered_service_networks(RENDERED, "postgres"), {"ocgkw"})
        self.assertIsNone(frontend_app.rendered_service_networks(RENDERED, "frontend"))

    def test_list_form_and_quoted_names(self):
        rendered = "services:\n  'backend':\n    networks:\n      - 'nexus-front'\n      - ocgkw\n"
        self.assertEqual(frontend_app.rendered_service_networks(rendered, "backend"), {"nexus-front", "ocgkw"})

    def test_top_level_network_is_not_a_service_network(self):
        self.assertEqual(frontend_app.rendered_network_gap({"docker_compose": RENDERED_LOST}), ["backend"])
        self.assertEqual(frontend_app.rendered_network_gap({"docker_compose": RENDERED}), [])


class TestAddressTests(unittest.TestCase):
    def test_test_address_is_not_a_user_domain(self):
        check = "http://" + frontend_app.paths.CHECK_HOST
        self.assertEqual(frontend_app.real_domains(check), "")
        self.assertIsNone(frontend_app.deploy_target(preflight_api(fqdn=check)))
        with self.assertRaises(ValueError), contextlib.redirect_stdout(io.StringIO()):
            frontend_app.preflight(preflight_api(fqdn=check, domains=BACKEND_ONLY), "src", True)


class VerifyPublicTests(unittest.TestCase):
    def test_deploy_turns_red_when_front_loses_the_backend(self):
        request = preflight_api(fqdn="https://app.example.pl,https://kariera.example.pl")
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ValueError) as caught:
            frontend_app.verify_public(request, "", get=user_path(callback=BROKEN)[0], sleep=lambda _s: None)
        self.assertIn("mode=deploy", str(caught.exception))

    def test_healthy_path_passes_and_front_without_domains_is_skipped(self):
        get, seen = user_path()
        with contextlib.redirect_stdout(io.StringIO()):
            frontend_app.verify_public(preflight_api(fqdn="https://app.example.pl"), "", get=get)
            frontend_app.verify_public(preflight_api(fqdn=""), "", get=get)
        self.assertTrue(all(u.startswith("https://app.example.pl/") for u, _ in seen))
        self.assertEqual(len(seen), 3)


class DeployTargetTests(unittest.TestCase):
    def test_front_without_domains_is_left_to_compose(self):
        self.assertIsNone(frontend_app.deploy_target(preflight_api(fqdn="")))
        self.assertIsNone(frontend_app.deploy_target(preflight_api(apps=[])))
        self.assertEqual(frontend_app.deploy_target(preflight_api(fqdn="https://app.example.pl")), "x")


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
