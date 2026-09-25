"""Exercise real SDK transport and dedupe across retry and operation boundaries."""
import asyncio
import json
import unittest

import sentry_sdk
from sentry_sdk.integrations.dedupe import DedupeIntegration
from sentry_sdk.transport import Transport

from app.core.sentry_privacy import scrub_event
from app.core.terminal_failure import capture_terminal_failure, terminal_operation


class TerminalFailureTests(unittest.TestCase):
    def test_recovered_attempt_is_not_failure_and_two_mutations_survive(self):
        events = []

        class MemoryTransport(Transport):
            def capture_envelope(self, envelope):
                for item in envelope.items:
                    if item.type == "event":
                        events.append(json.loads(item.get_bytes()))

        client = sentry_sdk.Client(
            dsn="https://test@example.invalid/1",
            default_integrations=False,
            integrations=[DedupeIntegration()],
            transport=MemoryTransport(),
            before_send=scrub_event,
            include_local_variables=False,
        )

        @terminal_operation("cv-chat")
        async def operation(recover):
            try:
                raise ValueError("CV private@example.com secret-share-token")
            except ValueError as exc:
                # Mirrors the SDK integration's capture of the provider attempt.
                sentry_sdk.capture_exception(exc)
                if recover:
                    return "ready"
                capture_terminal_failure(exc, operation="cv-chat", failure_kind="provider_unavailable")
                # Repeated handling of this SAME operation must not duplicate it.
                capture_terminal_failure(exc, operation="cv-chat", failure_kind="provider_unavailable")
                raise

        async def run():
            with sentry_sdk.isolation_scope() as scope:
                scope.set_client(client)
                self.assertEqual(await operation(True), "ready")
                self.assertEqual(events, [])
                for _ in range(2):
                    with self.assertRaises(ValueError):
                        await operation(False)

        asyncio.run(run())
        self.assertEqual(len(events), 2)
        self.assertNotEqual(events[0]["contexts"]["correlation"], events[1]["contexts"]["correlation"])
        for event in events:
            self.assertEqual(event["tags"]["terminal"], "true")
            self.assertEqual(event["exception"]["values"][0]["type"], "ValueError")
            self.assertIn("lineno", str(event["exception"]))
            self.assertNotIn("private@example.com", json.dumps(event))
            self.assertNotIn("secret-share-token", json.dumps(event))


class TerminalFailureStatusTagTests(unittest.TestCase):
    def test_provider_http_status_is_tagged(self):
        events = []

        class MemoryTransport(Transport):
            def capture_envelope(self, envelope):
                for item in envelope.items:
                    if item.type == "event":
                        events.append(json.loads(item.get_bytes()))

        client = sentry_sdk.Client(
            dsn="https://test@example.invalid/1",
            default_integrations=False,
            transport=MemoryTransport(),
            before_send=scrub_event,
        )

        class ProviderError(Exception):
            status_code = 402

        with sentry_sdk.isolation_scope() as scope:
            scope.set_client(client)
            capture_terminal_failure(
                ProviderError("Insufficient Balance"),
                operation="notes-extraction",
                failure_kind="APIStatusError",
            )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["tags"]["http_status"], "402")
