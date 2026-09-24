import importlib.util
import json
import io
import urllib.parse
from unittest.mock import Mock
from pathlib import Path
import unittest
from uuid import UUID

spec = importlib.util.spec_from_file_location(
    "audit", Path(__file__).parents[1] / "app_mail_config_audit.py"
)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class MailConfigAuditTests(unittest.TestCase):
    def test_only_valid_non_secret_identities(self):
        app_id = str(UUID(int=1))
        secret = "token-private-content"
        result = audit.summarize(
            [
                {"key": "M365_CLIENT_ID", "value": app_id},
                {"key": "M365_APP_MAIL_ENABLED", "value": "true"},
                {"key": "M365_CLIENT_SECRET", "value": secret},
                {"key": "M365_MAIL_SENDER_UPN", "value": "nexus@b2bnetwork.pl"},
                {"key": "M365_MAIL_SENDER_UPN", "value": secret, "is_preview": True},
            ]
        )
        self.assertNotIn(secret, json.dumps(result))
        self.assertEqual(
            result,
            {
                "M365_CLIENT_ID": app_id,
                "M365_APP_MAIL_ENABLED": "true",
                "M365_MAIL_SENDER_UPN": "nexus@b2bnetwork.pl",
            },
        )

    def test_arbitrary_values_are_redacted(self):
        result = audit.summarize(
            [
                {"key": "M365_CLIENT_ID", "value": "secret"},
                {"key": "M365_MAIL_SENDER_UPN", "value": "https://secret"},
            ]
        )
        self.assertEqual(set(result.values()), {"unavailable"})


class ProbeTests(unittest.TestCase):
    def rows(self):
        return [
            {"key": k, "value": v}
            for k, v in {
                "M365_CLIENT_ID": str(UUID(int=1)),
                "M365_TENANT_ID": str(UUID(int=2)),
                "M365_CLIENT_SECRET": "synthetic-secret",
                "M365_MAIL_SENDER_UPN": "nexus-powiadomienia@b2bnetwork.pl",
            }.items()
        ]

    def test_only_fixed_synthetic_message_and_no_credentials_in_result(self):
        token = io.BytesIO(b'{"access_token":"synthetic-token"}')
        response = Mock(status=202)
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        opener = Mock(side_effect=[token, response])
        result = audit.send_probe(self.rows(), opener)
        self.assertTrue(result["accepted"])
        self.assertFalse(result["delivery_confirmed"])
        request = opener.call_args_list[1].args[0]
        payload = json.loads(request.data)
        self.assertEqual(
            payload["message"]["toRecipients"],
            [{"emailAddress": {"address": "artur.twardowski@b2bnetwork.pl"}}],
        )
        self.assertNotIn("synthetic-token", json.dumps(result))
        self.assertNotIn("synthetic-secret", json.dumps(result))
        self.assertEqual(
            request.full_url,
            "https://graph.microsoft.com/v1.0/users/"
            "nexus-powiadomienia@b2bnetwork.pl/sendMail",
        )

    def test_personal_mailbox_is_not_an_allowed_probe_sender(self):
        rows = self.rows()
        for row in rows:
            if row["key"] == "M365_MAIL_SENDER_UPN":
                row["value"] = "artur.twardowski@b2bnetwork.pl"
        opener = Mock()

        self.assertEqual(
            audit.send_probe(rows, opener),
            {"accepted": False, "result": "configuration_unavailable"},
        )
        opener.assert_not_called()

    def test_dedicated_sender_credentials_override_order_mail(self):
        rows = self.rows() + [
            {"key": "M365_APP_MAIL_CLIENT_ID", "value": str(UUID(int=3))},
            {"key": "M365_APP_MAIL_CLIENT_SECRET", "value": "dedicated-secret"},
        ]
        token = io.BytesIO(b'{"access_token":"synthetic-token"}')
        response = Mock(status=202)
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        opener = Mock(side_effect=[token, response])
        self.assertTrue(audit.send_probe(rows, opener)["accepted"])
        token_request = opener.call_args_list[0].args[0]
        params = urllib.parse.parse_qs(token_request.data.decode())
        self.assertEqual(params["client_id"], [str(UUID(int=3))])
        self.assertEqual(params["client_secret"], ["dedicated-secret"])

    def test_uncertain_post_is_not_retried(self):
        opener = Mock(
            side_effect=[
                io.BytesIO(b'{"access_token":"synthetic-token"}'),
                TimeoutError("private provider response"),
            ]
        )
        result = audit.send_probe(self.rows(), opener)
        self.assertEqual(result, {"accepted": False, "result": "delivery_uncertain"})
        self.assertEqual(opener.call_count, 2)

    def test_missing_configuration_fails_without_network(self):
        opener = Mock()
        self.assertFalse(audit.send_probe([], opener)["accepted"])
        opener.assert_not_called()
