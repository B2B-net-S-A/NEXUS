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


def raw_response(raw):
    body = io.BytesIO(raw)
    body.status = 200
    return body


class TeamsProbeTests(unittest.TestCase):
    def session_initial(self, *, attendees=None, events=None):
        event = {
            "id": "private-event",
            "subject": probe.SESSION_SUBJECT,
            "onlineMeeting": {"joinUrl": "private-join"},
            "attendees": attendees
            if attendees is not None
            else [{"emailAddress": {"address": probe.EXCLUDED}}],
        }
        return self.initial()[:3] + [
            response({"value": events if events is not None else [event]}),
            response({"id": "organizer-id"}),
            response(
                {
                    "value": [
                        {
                            "id": "private-meeting",
                            "recordAutomatically": True,
                            "allowTranscription": True,
                        }
                    ]
                }
            ),
        ]

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

    def test_session_content_proves_speech_without_disclosing_it_or_writing(self):
        opener = Mock(
            side_effect=self.session_initial()
            + [
                response({"value": [{"id": "private-transcript"}]}),
                raw_response(
                    b"WEBVTT\n\n00:00:01.000 --> 00:00:03.000\n<v private-speaker>private-speech</v>\n\n"
                ),
            ]
        )
        result = probe.probe(self.rows(), session=True, opener=opener)
        self.assertTrue(result["passed"])
        self.assertTrue(result["transcript_generated_verified"])
        self.assertFalse(result["recording_generated_verified"])
        self.assertEqual(result["spoken_cue_count"], 1)
        self.assertTrue(
            all(c.args[0].get_method() == "GET" for c in opener.call_args_list[1:])
        )
        for private in ("private-transcript", "private-speaker", "private-speech"):
            self.assertNotIn(private, json.dumps(result))
        self.assert_private(result)

    def test_session_empty_list_is_not_success_or_generated_media(self):
        opener = Mock(side_effect=self.session_initial() + [response({"value": []})])
        result = probe.probe(self.rows(), session=True, opener=opener)
        self.assertFalse(result["passed"])
        self.assertFalse(result["transcript_generated_verified"])
        self.assertEqual(result["failed_stage"], "transcript_not_ready")
        self.assertEqual(result["transcripts_http"], 200)

    def test_session_content_denial_identifies_stage_without_disclosing_errors(self):
        opener = Mock(
            side_effect=self.session_initial()
            + [
                response({"value": [{"id": "private-transcript"}]}),
                denied(),
            ]
        )
        result = probe.probe(self.rows(), session=True, opener=opener)
        self.assertFalse(result["passed"])
        self.assertEqual(result["session_stage"], "read_session_transcripts")
        self.assertEqual(result["http_status"], 403)
        self.assert_private(result)

    def test_session_rejects_non_owner_attendees_and_ambiguous_event(self):
        for kwargs, expected in (
            (
                {"attendees": [{"emailAddress": {"address": "other@example.com"}}]},
                "test_attendees_mismatch",
            ),
            ({"events": []}, "test_event_not_unique"),
        ):
            opener = Mock(side_effect=self.session_initial(**kwargs))
            result = probe.probe(self.rows(), session=True, opener=opener)
            self.assertFalse(result["passed"])
            self.assertEqual(result["failed_stage"], expected)
            self.assertEqual(opener.call_count, 4)

    def test_session_timestamp_only_transcript_is_not_speech(self):
        opener = Mock(
            side_effect=self.session_initial()
            + [
                response({"value": [{"id": "private-transcript"}]}),
                raw_response(
                    b"WEBVTT\n\n00:00:01.000 --> 00:00:03.000\n<v private-speaker></v>\n\n"
                ),
            ]
        )
        result = probe.probe(self.rows(), session=True, opener=opener)
        self.assertFalse(result["passed"])
        self.assertEqual(result["spoken_cue_count"], 0)

    def test_session_cannot_be_combined_with_write_mode(self):
        opener = Mock()
        result = probe.probe(self.rows(), session=True, write=True, opener=opener)
        self.assertFalse(result["passed"])
        opener.assert_not_called()


if __name__ == "__main__":
    unittest.main()
