"""Public diagnostic must export only safe config and route counters."""

import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "linkedin_extension_audit",
    Path(__file__).parents[1] / "linkedin-extension-audit.py",
)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class AuditTests(unittest.TestCase):
    def test_only_public_extension_ids_and_safe_flags_escape(self):
        result = audit.configured_envs(
            [
                {"key": "SMTP_PASSWORD", "value": "private-secret"},
                {
                    "key": "LINKEDIN_EXTENSION_IDS",
                    "value": "a" * 32 + ",private-secret," + "a" * 32,
                    "is_runtime": True,
                },
                {"key": "LINKEDIN_EXTENSION_ENABLED", "value": "true"},
                {"key": "LINKEDIN_EXTENSION_TTL_DAYS", "value": "180"},
                {
                    "key": "LINKEDIN_EXTENSION_DAILY_READ_LIMIT",
                    "value": "private-secret",
                },
            ]
        )
        self.assertNotIn("private-secret", json.dumps(result))
        ids = result["entries"][0]
        self.assertEqual(ids["public_extension_ids"], ["a" * 32])
        self.assertEqual(ids["invalid_id_count"], 1)
        self.assertIs(result["entries"][1]["configured_enabled"], True)
        self.assertEqual(result["entries"][2]["configured_integer"], 180)
        self.assertIsNone(result["entries"][3]["configured_integer"])

    def test_route_counts_do_not_export_queries_users_or_raw_logs(self):
        result = audit.project_logs("""2026-10-28T16:00:00Z user private@example.test
2026-10-28T16:01:00Z INFO: 10.0.0.1:123 - "POST /api/candidates/from-linkedin?email=private@example.test HTTP/1.1" 201 Created
2026-10-28T17:01:00+01:00 INFO: "POST /api/candidates/from-linkedin HTTP/1.1" 401 Unauthorized
2026-10-28T16:02:00Z INFO: "GET /api/extension/me HTTP/1.1" 200 OK
2026-10-28T16:03:00Z INFO: "POST /api/candidates/from-linkedin-extra HTTP/1.1" 201 Created
2026-10-28T16:04:00Z INFO: "GET /api/candidates/from-linkedin HTTP/1.1" 405 Method Not Allowed
invalid log "POST /api/candidates/from-linkedin HTTP/1.1" secret data""")
        self.assertEqual(result["legacy_post_count"], 2)
        self.assertEqual(result["legacy_post_status_counts"], {"201": 1, "401": 1})
        self.assertEqual(result["extension_status_counts"], {"200": 1})
        self.assertEqual(result["legacy_first_at_utc"], "2026-10-28T16:01:00+00:00")
        self.assertNotIn("private", json.dumps(result))
        self.assertNotIn("secret", json.dumps(result))
        self.assertIs(result["historical_nonuse_established"], False)

    def test_missing_timestamps_and_empty_logs_are_explicit(self):
        result = audit.project_logs(
            'INFO: "POST /api/candidates/from-linkedin HTTP/1.1" 201 Created'
        )
        self.assertEqual(result["legacy_post_count"], 1)
        self.assertIsNone(result["first_observed_at_utc"])
        self.assertEqual(result["timestamped_line_count"], 0)
        self.assertEqual(audit.project_logs("")["legacy_post_count"], 0)
        self.assertIs(audit.project_logs("")["historical_nonuse_established"], False)

    def test_production_json_access_message_is_parsed_without_double_count(self):
        access = json.dumps(
            {
                "name": "uvicorn.access",
                "timestamp": "2026-10-28 16:00:00,000",
                "message": '10.0.0.1:123 - "POST /api/candidates/from-linkedin HTTP/1.1" 201 Created',
            }
        )
        outcome = json.dumps(
            {
                "name": "app.core.request_correlation",
                "event_kind": "http_outcome",
                "method": "POST",
                "route": "/api/candidates/from-linkedin",
                "status_code": 201,
                "message": "private@example.test",
            }
        )
        result = audit.project_logs("2026-10-28T16:00:00Z " + access + "\n" + outcome)
        self.assertEqual(result["legacy_post_count"], 1)
        self.assertEqual(result["timestamped_line_count"], 1)
        self.assertNotIn("private@example.test", json.dumps(result))

    def test_numeric_candidate_routes_are_counted_in_text_and_json_logs(self):
        text = (
            'INFO: "POST /api/extension/candidates/123/contacts HTTP/1.1" 201 Created'
        )
        production = json.dumps(
            {
                "name": "uvicorn.access",
                "message": '10.0.0.1:123 - "POST /api/extension/candidates/456/jobs HTTP/1.1" 200 OK',
            }
        )
        revoked = 'INFO: "POST /api/extension/connections/v1$abcdef123456/revoke HTTP/1.1" 204 No Content'
        result = audit.project_logs(text + "\n" + production + "\n" + revoked)
        self.assertEqual(
            result["extension_status_counts"], {"200": 1, "201": 1, "204": 1}
        )
        self.assertEqual(result["recognized_extension_access_lines"], 3)
        self.assertNotIn("123", json.dumps(result))
        self.assertNotIn("456", json.dumps(result))
        self.assertNotIn("abcdef", json.dumps(result))

    def test_overlong_extension_path_does_not_match(self):
        line = 'INFO: "POST /api/extension/' + "a" * 161 + ' HTTP/1.1" 200 OK'
        self.assertEqual(audit.project_logs(line)["extension_status_counts"], {})

    def test_percent_encoded_key_revocation_paths_are_counted_without_ids(self):
        message = '"POST /api/extension/connections/v1%24abcdef123456/revoke HTTP/1.1" 204 No Content'
        production = json.dumps({"name": "uvicorn.access", "message": message})
        result = audit.project_logs(message + "\n" + production)
        self.assertEqual(result["extension_status_counts"], {"204": 2})
        self.assertNotIn("abcdef", json.dumps(result))
        self.assertNotIn("%24", json.dumps(result))
        invalid = message.replace("%24", "%GG")
        self.assertEqual(audit.project_logs(invalid)["extension_status_counts"], {})

    def test_invalid_api_shapes_fail_closed(self):
        for bad in ({}, ["bad"]):
            with self.assertRaises(audit.ops.OpsError):
                audit.configured_envs(bad)
        with self.assertRaises(audit.ops.OpsError):
            audit.project_logs(None)

    def test_diagnostic_has_only_fixed_get_requests(self):
        requests = []

        class Api:
            def request(self, method, path):
                requests.append((method, path))
                return [] if path.endswith("/envs") else {"logs": ""}

        with (
            patch.object(audit.ops, "Api", return_value=Api()),
            patch.dict(audit.os.environ, {"APP_UUID": "application"}),
            patch("builtins.print"),
        ):
            audit.main()
        self.assertEqual(
            requests,
            [
                ("GET", "/api/v1/applications/application/envs"),
                (
                    "GET",
                    "/api/v1/applications/application/logs?lines=10000"
                    "&service_name=backend&show_timestamps=true",
                ),
            ],
        )


if __name__ == "__main__":
    unittest.main()
