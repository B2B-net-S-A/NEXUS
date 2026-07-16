"""Regression test for Module 6 finding P1.18 (SMTP TLS fail-closed).

`send_email` called ``starttls()`` with no SSL context (no CA/hostname
verification) and would fall back to plaintext when TLS was off. Now, with
``SMTP_REQUIRE_TLS`` (default True), it refuses to send over plaintext, and
STARTTLS uses a verifying default context.
"""

import pytest

from app.core.config import settings
from app.services import email as email_service


def test_require_tls_refuses_plaintext(monkeypatch):
    monkeypatch.setattr(settings, "SMTP_ENABLED", True)
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(settings, "SMTP_REQUIRE_TLS", True)
    monkeypatch.setattr(settings, "SMTP_USE_TLS", False)

    def _boom(*a, **k):  # pragma: no cover - must never be reached
        raise AssertionError("SMTP connection attempted despite TLS being required")

    monkeypatch.setattr(email_service.smtplib, "SMTP", _boom)

    # Refused before any socket is opened.
    assert email_service.send_email("x@example.com", "s", "b") is False


def test_default_require_tls_is_true():
    # The safe default ships on: a missing env must not silently allow cleartext.
    assert settings.SMTP_REQUIRE_TLS is True


def test_disabled_smtp_is_noop(monkeypatch):
    monkeypatch.setattr(settings, "SMTP_ENABLED", False)
    assert email_service.send_email("x@example.com", "s", "b") is False
