import importlib.util
import json
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "audit", Path(__file__).parents[1] / "coolify_release_audit.py"
)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class ReleaseAuditTests(unittest.TestCase):
    def test_only_flags_are_emitted_even_when_values_contain_secrets(self):
        secret = "private-token-CV-name@example.com"
        result = audit.summarize(
            {
                "settings": {"include_source_commit_in_build": True},
                "dockerfile": secret,
            },
            [
                {"key": "SENTRY_AUTH_TOKEN", "value": secret, "is_buildtime": True},
                {"key": "GIT_SHA", "value": secret, "is_runtime": True},
                {"key": "DATABASE_URL", "value": secret},
            ],
        )
        self.assertNotIn(secret, json.dumps(result))
        self.assertNotIn("DATABASE_URL", json.dumps(result))
        self.assertTrue(result["source_commit_in_build"])
        self.assertTrue(result["envs"][0]["is_buildtime"])
        self.assertFalse(result["envs"][1]["value_is_full_sha"])

    def test_missing_api_field_is_distinct_from_disabled(self):
        self.assertFalse(audit.summarize({}, [])["source_commit_setting_exposed"])
        self.assertTrue(
            audit.summarize(
                {"settings": {"include_source_commit_in_build": False}}, []
            )["source_commit_setting_exposed"]
        )


if __name__ == "__main__":
    unittest.main()
