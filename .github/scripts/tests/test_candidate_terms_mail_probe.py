import base64
import importlib.util
import io
import json
import unittest
from email import message_from_bytes, policy
from pathlib import Path
from uuid import UUID

spec = importlib.util.spec_from_file_location(
    "probe", Path(__file__).parents[1] / "candidate_terms_mail_probe.py"
)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

APP = str(UUID(int=1))
TENANT = str(UUID(int=2))
SECRET = "client-secret-private"


def _envs(sender="kariera@b2bnetwork.pl"):
    return [
        {"key": "M365_APP_MAIL_CLIENT_ID", "value": APP},
        {"key": "M365_APP_MAIL_CLIENT_SECRET", "value": SECRET},
        {"key": "M365_MAIL_TENANT_ID", "value": TENANT},
        {"key": "CANDIDATE_MAIL_SENDER_UPN", "value": sender},
    ]


class _Resp(io.BytesIO):
    def __init__(self, status, body=b"{}"):
        super().__init__(body)
        self.status = status


class CandidateTermsProbeTests(unittest.TestCase):
    def _run(self, gmail="artur.test@gmail.com", sender="kariera@b2bnetwork.pl"):
        calls = []

        def opener(request, timeout=None):
            calls.append(request)
            if "oauth2" in request.full_url:
                return _Resp(200, json.dumps({"access_token": "tok"}).encode())
            return _Resp(202)

        return probe.send(_envs(sender), gmail, opener=opener), calls

    def test_sends_real_template_as_mime_to_both_owner_addresses(self):
        result, calls = self._run()
        self.assertEqual(result["result"], "accepted")
        mails = [c for c in calls if "sendMail" in c.full_url]
        self.assertEqual(len(mails), 2)
        self.assertTrue(mails[0].full_url.endswith("/users/kariera@b2bnetwork.pl/sendMail"))
        msg = message_from_bytes(base64.b64decode(mails[1].data), policy=policy.default)
        self.assertEqual(msg["To"], "artur.test@gmail.com")
        self.assertEqual(msg["From"], "kariera@b2bnetwork.pl")
        self.assertIsNone(msg["Reply-To"])
        self.assertEqual(msg["List-Unsubscribe-Post"], "List-Unsubscribe=One-Click")
        self.assertIn("/api/public/candidate-terms/proba-", msg["List-Unsubscribe"])
        self.assertIn("Senior Java Developer", msg.get_body(("plain",)).get_content())
        self.assertIn("<", msg.get_body(("html",)).get_content())

    def test_output_has_no_addresses_or_secret(self):
        result, _ = self._run()
        text = json.dumps(result)
        self.assertNotIn("@", text)
        self.assertNotIn(SECRET, text)
        self.assertEqual([r["to"] for r in result["sent"]], ["work", "gmail"])

    def test_refuses_other_sender_and_sends_nothing(self):
        result, calls = self._run(sender="nexus-powiadomienia@b2bnetwork.pl")
        self.assertEqual(result["result"], "configuration_unavailable")
        self.assertEqual(calls, [])

    def test_only_owner_work_address_without_valid_gmail(self):
        self.assertEqual(probe.recipients(""), [probe.OWNER_WORK])
        self.assertEqual(probe.recipients("someone@example.com"), [probe.OWNER_WORK])


if __name__ == "__main__":
    unittest.main()
