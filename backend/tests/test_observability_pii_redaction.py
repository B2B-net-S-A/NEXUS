from __future__ import annotations

import json
import logging

from app.core.logging_config import SensitiveDataFilter, redact_sensitive_text


def test_sensitive_data_filter_redacts_message_and_structured_fields() -> None:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="provider failed for %s at %s",
        args=("anna.private@example.com", "+48 501 234 567"),
        exc_info=None,
    )
    record.provider_context = {
        "recipient": "candidate@example.com",
        "callback": "+1 (415) 555-2671",
    }

    assert SensitiveDataFilter().filter(record) is True
    rendered = record.getMessage()
    structured = json.dumps(record.provider_context)

    assert "anna.private@example.com" not in rendered
    assert "+48 501 234 567" not in rendered
    assert "candidate@example.com" not in structured
    assert "415" not in structured
    assert "[REDACTED_EMAIL]" in rendered
    assert "[REDACTED_PHONE]" in rendered


def test_redact_sensitive_text_leaves_diagnostic_identifiers() -> None:
    value = redact_sensitive_text(
        "candidate_id=123 model=voyage-3-large status=429 date=2026-07-14"
    )
    assert value == ("candidate_id=123 model=voyage-3-large status=429 date=2026-07-14")


def test_sentry_scrubber_drops_payloads_and_direct_identifiers() -> None:
    # Importing main exercises the exact callback registered with sentry_sdk.
    from app.main import _scrub_sentry_event

    event = {
        "request": {
            "data": {"safe_id": 17, "raw_cv_text": "secret CV body"},
            "headers": {"Authorization": "Bearer secret"},
        },
        "user": {"id": 42, "email": "anna.private@example.com"},
        "extra": {
            "prompt": "full model prompt",
            "transcript": "full meeting transcript",
            "safe_id": 99,
            "diagnostic": "call +48 501 234 567 failed",
        },
        "exception": {
            "values": [
                {
                    "type": "ProviderError",
                    "value": "response for anna.private@example.com failed",
                    "stacktrace": {"frames": [{"vars": {"cv": "secret CV body"}}]},
                }
            ]
        },
    }

    scrubbed = _scrub_sentry_event(event)
    serialized = json.dumps(scrubbed)

    for secret in (
        "secret CV body",
        "Bearer secret",
        "anna.private@example.com",
        "full model prompt",
        "full meeting transcript",
        "+48 501 234 567",
    ):
        assert secret not in serialized
    assert scrubbed["user"]["id"] == 42
    assert scrubbed["extra"]["safe_id"] == 99
    assert scrubbed["exception"]["values"][0]["value"] == "[REDACTED_EXCEPTION_MESSAGE]"
    assert "[REDACTED]" in serialized
