import importlib.util
import json
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "audit", Path(__file__).parents[1] / "app_mail_config_audit.py"
)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class MailConfigAuditTests(unittest.TestCase):
    def test_only_valid_non_secret_identities(self):
        app_id = "00000000-0000-0000-0000-000000000001"
        secret = "token-private-content"
        result = audit.summarize([
            {"key": "M365_CLIENT_ID", "value": app_id},
            {"key": "M365_APP_MAIL_ENABLED", "value": "true"},
            {"key": "M365_CLIENT_SECRET", "value": secret},
            {"key": "M365_MAIL_SENDER_UPN", "value": "nexus@b2bnetwork.pl"},
            {"key": "M365_MAIL_SENDER_UPN", "value": secret, "is_preview": True},
        ])
        self.assertNotIn(secret, json.dumps(result))
        self.assertEqual(result, {
            "M365_CLIENT_ID": app_id, "M365_APP_MAIL_ENABLED": "true",
            "M365_MAIL_SENDER_UPN": "nexus@b2bnetwork.pl",
        })

    def test_arbitrary_values_are_redacted(self):
        result = audit.summarize([
            {"key": "M365_CLIENT_ID", "value": "secret"},
            {"key": "M365_MAIL_SENDER_UPN", "value": "https://secret"},
        ])
        self.assertEqual(set(result.values()), {"unavailable"})
