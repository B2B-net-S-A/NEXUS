"""PII-safe logging regression tests for shared provider and e-mail paths."""

from __future__ import annotations

import logging

from app.core.config import settings
from app.services.email import send_email


def test_disabled_smtp_log_does_not_expose_recipient_or_subject(
    monkeypatch, caplog
) -> None:
    recipient = "anna.private@example.com"
    subject = "Poufny projekt dla Klienta X"
    monkeypatch.setattr(settings, "SMTP_ENABLED", False)

    with caplog.at_level(logging.DEBUG):
        assert send_email(recipient, subject, "body") is False

    assert recipient not in caplog.text
    assert subject not in caplog.text
    assert "recipient_ref=" in caplog.text
    assert "subject_len=" in caplog.text
