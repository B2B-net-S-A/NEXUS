import importlib.util
import io
import json
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock

spec = importlib.util.spec_from_file_location(
    "probe", Path(__file__).parents[1] / "teams_prep_probe.py"
)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def response(payload, status=200):
    body = io.BytesIO(json.dumps(payload).encode())
    body.status = status
    return body


def denied():
    return urllib.error.HTTPError("private-url", 403, "private-error", {}, None)


class TeamsProbeTests(unittest.TestCase):
    def rows(self):
        return [
            {"key": key, "value": value}
            for key, value in {
                "TEAMS_PREP_CLIENT_ID": probe.CLIENT,
                "TEAMS_PREP_CLIENT_SECRET": "private-secret",
                "M365_TENANT_ID": probe.TENANT,
            }.items()
        ]

    def initial(self):
        return [
            response({"access_token": "private-token"}),
            response({"id": "private-calendar"}),
            denied(),
            response(
                {"id": "private-event", "onlineMeeting": {"joinUrl": "private-join"}},
                201,
            ),
            response({"id": "organizer-id"}),
            response({"value": [{"id": "private-meeting"}]}),
        ]

    def assert_private(self, result):
        for private in (
            "private-secret",
            "private-token",
            "private-event",
            "private-join",
            "private-meeting",
            "private-calendar",
            "private-error",
        ):
            self.assertNotIn(private, json.dumps(result))

    def test_scope_expansion_blocks_write_without_disclosing_responses(self):
        opener = Mock(
            side_effect=[
                response({"access_token": "private-token"}),
                response({"id": "private-calendar"}),
                response({}),
            ]
        )
        result = probe.probe(self.rows(), write=True, opener=opener)
        self.assertFalse(result["passed"])
        self.assertEqual(result["failed_stage"], "calendar_scope")
        self.assertEqual(opener.call_count, 3)
        self.assert_private(result)

    def test_failed_patch_still_cancels_only_the_synthetic_event(self):
        opener = Mock(side_effect=self.initial() + [denied(), response({}, 202)])
        result = probe.probe(self.rows(), write=True, opener=opener)
        self.assertFalse(result["passed"])
        self.assertTrue(result["event_cancelled"])
        self.assertEqual(result["failed_stage"], "automatic_recording")
        self.assertEqual(
            json.loads(opener.call_args_list[3].args[0].data)["attendees"], []
        )
        cleanup = opener.call_args_list[-1].args[0]
        self.assertTrue(cleanup.full_url.endswith("/events/private-event/cancel"))
        self.assertEqual(cleanup.method, "POST")
        self.assert_private(result)

    def test_success_does_not_claim_real_recording_or_transcript(self):
        opener = Mock(
            side_effect=self.initial()
            + [
                response({}),
                response({"recordAutomatically": True, "allowTranscription": True}),
                response({"value": []}),
                response({}, 202),
            ]
        )
        result = probe.probe(self.rows(), write=True, opener=opener)
        self.assertTrue(result["passed"])
        self.assertTrue(result["event_cancelled"])
        self.assertFalse(result["recording_generated_verified"])
        self.assertFalse(result["transcript_generated_verified"])
        self.assert_private(result)

    def test_failed_cleanup_cannot_pass(self):
        opener = Mock(side_effect=self.initial() + [denied(), denied()])
        result = probe.probe(self.rows(), write=True, opener=opener)
        self.assertFalse(result["passed"])
        self.assertTrue(result["cleanup_required"])
        self.assert_private(result)

    def test_lost_creation_response_requires_cleanup_without_claiming_success(self):
        opener = Mock(side_effect=self.initial()[:3] + [TimeoutError("private-secret")])
        result = probe.probe(self.rows(), write=True, opener=opener)
        self.assertFalse(result["passed"])
        self.assertTrue(result["event_creation_uncertain"])
        self.assertTrue(result["cleanup_required"])
        self.assertEqual(opener.call_count, 4)
        self.assert_private(result)


if __name__ == "__main__":
    unittest.main()
