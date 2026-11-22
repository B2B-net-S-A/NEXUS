import base64
import importlib.util
import io
import json
import unittest
from email import message_from_bytes, policy
from pathlib import Path
from unittest import mock
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
        self.assertTrue(
            mails[0].full_url.endswith("/users/kariera@b2bnetwork.pl/sendMail")
        )
        msg = message_from_bytes(base64.b64decode(mails[1].data), policy=policy.default)
        self.assertEqual(msg["To"], "artur.test@gmail.com")
        self.assertEqual(msg["From"], "kariera@b2bnetwork.pl")
        self.assertIsNone(msg["Reply-To"])
        self.assertEqual(msg["List-Unsubscribe-Post"], "List-Unsubscribe=One-Click")
        self.assertIn("/api/public/candidate-terms/proba-", msg["List-Unsubscribe"])
        self.assertIn("Senior Java Developer", msg.get_body(("plain",)).get_content())
        self.assertIn("<", msg.get_body(("html",)).get_content())

    def test_both_exact_header_values_are_checked_in_every_serialized_message(self):
        with mock.patch.object(
            probe.secrets, "token_urlsafe", return_value="private-token"
        ):
            result, calls = self._run()
        expected = (
            b"List-Unsubscribe: <https://api.nexus.dynaminds.pl/api/public/"
            b"candidate-terms/proba-private-token/opt-out>"
        )
        mails = [c for c in calls if "sendMail" in c.full_url]
        self.assertEqual(len(mails), 2)
        for request in mails:
            headers = (
                base64.b64decode(request.data).split(b"\r\n\r\n", 1)[0].split(b"\r\n")
            )
            self.assertEqual(headers.count(expected), 1)
            self.assertEqual(
                headers.count(b"List-Unsubscribe-Post: List-Unsubscribe=One-Click"), 1
            )
        self.assertTrue(result["outbound_mime_header_pair_verified"])
        self.assertNotIn("received_headers_verified", result)

    def test_bad_serialized_headers_prevent_all_network_calls(self):
        message = probe.mime_message(probe.OWNER_WORK)
        valid = message.as_bytes(policy=policy.SMTP.clone(max_line_length=998))
        post = b"List-Unsubscribe-Post: List-Unsubscribe=One-Click\r\n"
        unsubscribe = str(message["List-Unsubscribe"]).encode("ascii")
        cases = {
            "post_missing": valid.replace(post, b""),
            "post_wrong": valid.replace(post, b"List-Unsubscribe-Post: wrong\r\n"),
            "post_duplicate": valid.replace(post, post + post),
            "post_folded": valid.replace(post, post + b" wrong\r\n"),
            "post_body_only": valid.replace(post, b"") + b"\r\n" + post,
            "unsubscribe_encoded": valid.replace(unsubscribe, b"=?utf-8?q?encoded?="),
            "unsubscribe_wrong": valid.replace(
                unsubscribe, b"<https://example.com/wrong>"
            ),
            "unsubscribe_folded": valid.replace(
                unsubscribe, unsubscribe + b"\r\n wrong"
            ),
        }
        for name, raw in cases.items():
            with (
                self.subTest(name=name),
                mock.patch.object(probe, "mime_message", return_value=message),
                mock.patch.object(message, "as_bytes", return_value=raw),
            ):
                result, calls = self._run()
                self.assertEqual(
                    result, {"result": "outbound_headers_invalid", "sent": []}
                )
                self.assertEqual(calls, [])

    def test_invalid_second_message_blocks_the_first_send_too(self):
        first = probe.mime_message(probe.OWNER_WORK)
        second = probe.mime_message("artur.test@gmail.com")
        raw = second.as_bytes(policy=policy.SMTP.clone(max_line_length=998)).replace(
            b"List-Unsubscribe-Post: List-Unsubscribe=One-Click\r\n", b""
        )
        with (
            mock.patch.object(probe, "mime_message", side_effect=[first, second]),
            mock.patch.object(second, "as_bytes", return_value=raw),
        ):
            result, calls = self._run()
        self.assertEqual(result, {"result": "outbound_headers_invalid", "sent": []})
        self.assertEqual(calls, [])

    def test_output_has_no_addresses_or_secret(self):
        result, _ = self._run()
        text = json.dumps(result)
        self.assertNotIn("@", text)
        self.assertNotIn(SECRET, text)
        self.assertNotIn("proba-", text)
        self.assertNotIn("https://", text)
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
