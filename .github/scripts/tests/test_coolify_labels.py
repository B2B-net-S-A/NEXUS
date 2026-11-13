import base64
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("coolify_labels", Path(__file__).parents[1] / "coolify_labels.py")
labels_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(labels_mod)

RETRY = "nexus-front-retry"
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


class RetryLabelTests(unittest.TestCase):
    def test_every_router_gets_retry_first_in_its_chain(self):
        labels = labels_mod.with_retry(COOLIFY_LABELS, RETRY)
        self.assertIn("traefik.http.routers.https-0-x.middlewares=nexus-front-retry,gzip-sse", labels)
        self.assertIn("traefik.http.routers.http-0-x.middlewares=nexus-front-retry,redirect-to-https", labels)
        self.assertIn("traefik.http.routers.https-1-x.middlewares=nexus-front-retry", labels)
        self.assertIn("traefik.http.middlewares.nexus-front-retry.retry.attempts=3", labels)
        self.assertIn("traefik.http.middlewares.nexus-front-retry.retry.initialinterval=100ms", labels)
        self.assertEqual(len([line for line in labels if ".middlewares=" in line and ".routers." in line]), 3)

    def test_applying_twice_changes_nothing(self):
        # Inne etykiety przy kolejnym wdrożeniu = Coolify zatrzymuje stary kontener bez czekania.
        once = labels_mod.with_retry(COOLIFY_LABELS, RETRY)
        self.assertEqual(labels_mod.with_retry(once, RETRY), once)

    def test_middleware_name_is_per_application(self):
        labels = labels_mod.with_retry(COOLIFY_LABELS, "nexus-api-retry")
        self.assertIn("traefik.http.middlewares.nexus-api-retry.retry.attempts=3", labels)
        self.assertFalse([line for line in labels if RETRY in line])

    def test_labels_without_routers_are_refused(self):
        with self.assertRaises(ValueError):
            labels_mod.with_retry(["traefik.enable=true"], RETRY)

    def test_labels_round_trip_plain_or_base64(self):
        plain = "\n".join(COOLIFY_LABELS)
        encoded = labels_mod.encode_labels(COOLIFY_LABELS)
        self.assertEqual(base64.b64decode(encoded).decode(), plain)
        self.assertEqual(labels_mod.decode_labels(plain), COOLIFY_LABELS)
        self.assertEqual(labels_mod.decode_labels(encoded), COOLIFY_LABELS)
        self.assertEqual(labels_mod.decode_labels(None), [])

    def test_shutdown_gives_traffic_time_to_move(self):
        self.assertGreater(labels_mod.SHUTDOWN_SETTINGS["rolling_update_drain_seconds"], 5)
        self.assertGreaterEqual(labels_mod.SHUTDOWN_SETTINGS["stop_grace_period"], 30)


if __name__ == "__main__":
    unittest.main()
