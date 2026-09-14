"""Regression tests inspect the outbound event, not just a redaction helper."""

import asyncio
import unittest
from copy import deepcopy

from app.core.sentry_privacy import scrub_event
from app.core.request_correlation import RequestCorrelationMiddleware


class SentryPrivacyTests(unittest.TestCase):
    def test_private_content_removed_but_source_and_trace_retained(self):
        secret = "CV Jan Testowy private@example.com +48600111222 token=secret-value"
        event = {
            "message": secret,
            "logentry": {"formatted": secret},
            "request": {"url": "/api/public/cv/secret-value", "data": secret},
            "extra": {"question": secret},
            "user": {"email": secret},
            "tags": {"candidate": secret, "terminal": "true"},
            "contexts": {
                "ai": {"prompt": secret},
                "trace": {"trace_id": "a" * 32, "data": secret},
            },
            "exception": {
                "values": [
                    {
                        "type": "JSONDecodeError",
                        "value": secret,
                        "mechanism": {"type": "logging", "data": secret},
                        "stacktrace": {
                            "frames": [
                                {
                                    "filename": "parser.py",
                                    "lineno": 42,
                                    "vars": {"cv": secret},
                                }
                            ]
                        },
                    }
                ]
            },
            "breadcrumbs": {
                "values": [
                    {"message": secret, "data": {"body": secret}, "category": "http"}
                ]
            },
            "spans": [
                {"description": secret, "data": {"body": secret}, "span_id": "b" * 16}
            ],
        }
        result = scrub_event(deepcopy(event))
        self.assertNotIn(secret, str(result))
        self.assertEqual(
            result["exception"]["values"][0]["stacktrace"]["frames"][0],
            {"filename": "parser.py", "lineno": 42},
        )
        self.assertEqual(result["contexts"]["trace"]["trace_id"], "a" * 32)
        self.assertEqual(result["tags"], {"terminal": "true"})

    def test_request_ids_and_operation_id_are_not_private_caller_text(self):
        sent = []

        async def app(scope, receive, send):
            self.assertNotIn("private", str(scope["state"]))
            await send({"type": "http.response.start", "status": 200, "headers": []})

        async def send(message):
            sent.append(message)

        asyncio.run(
            RequestCorrelationMiddleware(app)(
                {
                    "type": "http",
                    "headers": [(b"x-operation-id", b"private@example.com")],
                },
                None,
                send,
            )
        )
        self.assertEqual(len(dict(sent[0]["headers"])[b"x-request-id"]), 36)


if __name__ == "__main__":
    unittest.main()
