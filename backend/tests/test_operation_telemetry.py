import unittest
from unittest.mock import patch

from app.core.operation_telemetry import record_job_outcome


class OperationTelemetryTests(unittest.TestCase):
    def test_success_is_metric_not_error(self):
        with (
            patch("app.core.operation_telemetry.sentry_sdk.capture_message") as capture,
            self.assertLogs("app.core.operation_telemetry", level="INFO") as logs,
        ):
            record_job_outcome("notes_insights", True, interval_seconds=86400)
        capture.assert_not_called()
        self.assertEqual(logs.records[0].outcome, "success")
        self.assertEqual(logs.records[0].expected_interval_seconds, 86400)

    def test_terminal_failure_has_stable_job_and_separate_operation_id(self):
        import sentry_sdk

        seen = []

        def capture(*args, **kwargs):
            scope = sentry_sdk.get_current_scope()
            seen.append(scope._tags.copy())

        with (
            patch(
                "app.core.operation_telemetry.sentry_sdk.capture_message",
                side_effect=capture,
            ),
            self.assertLogs("app.core.operation_telemetry", level="INFO") as logs,
        ):
            record_job_outcome("m365_sync", False, interval_seconds=300, subject_id=42)
        self.assertEqual(seen[0]["terminal"], "true")
        self.assertEqual(seen[0]["operation"], "m365_sync")
        self.assertEqual(logs.records[0].subject_id, 42)
        self.assertEqual(len(logs.records[0].operation_id), 36)
