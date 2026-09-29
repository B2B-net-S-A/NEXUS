import base64
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "provision", Path(__file__).parents[1] / "contract_docs_secret.py"
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class TransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.path = Path(cls.temp.name)
        with patch.dict(os.environ, GITHUB_RUN_ID="123", GITHUB_RUN_ATTEMPT="1"):
            with contextlib.redirect_stdout(io.StringIO()):
                m.prepare(cls.path)
        cls.offer = json.loads((cls.path / "offer.json").read_text())
        (cls.path / "public.pem").write_text(cls.offer["public_key"])

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def encrypt(self, **changes):
        payload = {
            "identity": self.offer["identity"],
            "challenge": self.offer["challenge"],
            "client_id": m.CLIENT,
            "secret": "synthetic-test-credential-123456",
        }
        payload.update(changes)
        encrypted = subprocess.run(
            [
                "openssl",
                "pkeyutl",
                "-encrypt",
                "-pubin",
                "-inkey",
                str(self.path / "public.pem"),
                "-pkeyopt",
                "rsa_padding_mode:oaep",
                "-pkeyopt",
                "rsa_oaep_md:sha256",
                "-pkeyopt",
                "rsa_mgf1_md:sha256",
            ],
            input=json.dumps(payload).encode(),
            capture_output=True,
            check=True,
        ).stdout
        return base64.b64encode(encrypted).decode()

    def test_real_oaep_roundtrip(self):
        self.assertEqual(
            m.decrypt(self.path, self.encrypt()), "synthetic-test-credential-123456"
        )

    def test_replay_wrong_run_and_wrong_app_rejected(self):
        for change in [
            {"identity": "999-1"},
            {"challenge": "wrong"},
            {"client_id": "wrong"},
        ]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                m.decrypt(self.path, self.encrypt(**change))

    def test_expired_offer_rejected(self):
        ciphertext = self.encrypt()
        with patch.object(m.time, "time", return_value=self.offer["expires_at"] + 1):
            with self.assertRaises(ValueError):
                m.decrypt(self.path, ciphertext)

    def test_wrong_workflow_actor_sha_branch_and_event_rejected(self):
        receiver = {"head_sha": "abc", "actor": {"id": 42}}
        sender = {
            "path": m.WORKFLOW,
            "head_branch": "main",
            "event": "workflow_dispatch",
            "conclusion": "success",
            "head_sha": "abc",
            "actor": {"id": 42},
            "run_attempt": 1,
        }
        self.assertTrue(m.validate_sender(sender, receiver))
        for key, value in [
            ("path", "other.yml"),
            ("head_branch", "feature"),
            ("head_sha", "other"),
            ("actor", {"id": 43}),
            ("event", "pull_request"),
            ("run_attempt", 2),
        ]:
            with self.subTest(key=key):
                self.assertFalse(m.validate_sender({**sender, key: value}, receiver))


class ProvisionTests(unittest.TestCase):
    def fake_api(self, url, method="GET", data=None, token=None, form=False):
        if "login.microsoftonline.com" in url:
            claims = {"tid": m.TENANT, "roles": self.roles}
            encoded = (
                base64.urlsafe_b64encode(json.dumps(claims).encode())
                .decode()
                .rstrip("=")
            )
            return {"access_token": "header." + encoded + ".signature"}
        if "graph.microsoft.com" in url:
            return {"id": m.SITE}
        if method == "GET":
            return [
                {"key": k, "value": v, "is_preview": False}
                for k, v in self.envs.items()
            ]
        self.writes.append(data)
        self.envs[data["key"]] = data["value"]
        return {}

    def setUp(self):
        self.roles = ["Sites.Selected"]
        self.envs = {
            "CONTRACT_DOCS_SP_CLIENT_ID": m.CLIENT,
            "M365_MAIL_TENANT_ID": m.TENANT,
            "CONTRACT_DOCS_SP_SYNC_ENABLED": "false",
        }
        self.writes = []
        self.patch_api = patch.object(m, "api", side_effect=self.fake_api)
        self.patch_api.start()
        self.patch_env = patch.dict(
            os.environ,
            COOLIFY_URL="https://coolify.example",
            COOLIFY_APP_UUID="app",
            COOLIFY_TOKEN="synthetic",
        )
        self.patch_env.start()
        self.addCleanup(self.patch_api.stop)
        self.addCleanup(self.patch_env.stop)

    def test_only_dedicated_secret_is_written_and_never_printed(self):
        output = io.StringIO()
        secret = "synthetic-test-credential-123456"
        with contextlib.redirect_stdout(output):
            m.provision(secret)
        self.assertEqual([w["key"] for w in self.writes], [m.KEY])
        self.assertNotIn(secret, output.getvalue())
        self.assertEqual(self.envs["CONTRACT_DOCS_SP_SYNC_ENABLED"], "false")

    def test_broader_permissions_block_write(self):
        self.roles.append("Mail.Read")
        with self.assertRaises(ValueError):
            m.provision("synthetic-secret")
        self.assertEqual(self.writes, [])

    def test_existing_secret_is_not_rotated(self):
        self.envs[m.KEY] = "existing-secret"
        with self.assertRaises(ValueError):
            m.provision("synthetic-secret")
        self.assertEqual(self.writes, [])

    def test_wrong_tenant_or_enabled_sync_blocks_write(self):
        for key, value in [
            ("M365_MAIL_TENANT_ID", "other"),
            ("CONTRACT_DOCS_SP_SYNC_ENABLED", "true"),
        ]:
            old = self.envs[key]
            self.envs[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                m.provision("synthetic-secret")
            self.envs[key] = old
        self.assertEqual(self.writes, [])


if __name__ == "__main__":
    unittest.main()
