"""Unit tests for central log PII/secret redaction (app.core.logging_config).

The fixtures below are deliberately secret-SHAPED placeholders (never real
credentials) so the redaction regexes are exercised; the ``# gitleaks:allow``
markers keep the secret scanner from flagging these intentional decoys.
"""

from __future__ import annotations

import logging

from app.core.logging_config import RedactingFilter, redact_sensitive


def test_redacts_email():
    out = redact_sensitive("candidate jan.kowalski@example.com applied")
    assert "jan.kowalski@example.com" not in out
    assert "[email]" in out


def test_redacts_provider_key():
    out = redact_sensitive("using key sk-notARealKeyPlaceholder0000 now")  # gitleaks:allow
    assert "sk-notARealKeyPlaceholder0000" not in out
    assert "[redacted-key]" in out


def test_redacts_bearer_token():
    out = redact_sensitive("header: Bearer notARealBearerToken0000")  # gitleaks:allow
    assert "notARealBearerToken0000" not in out
    assert "[redacted]" in out


def test_redacts_labelled_secrets():
    assert "[redacted]" in redact_sensitive("password=NotARealPasswordValue")  # gitleaks:allow
    assert "[redacted]" in redact_sensitive('api_key: "NotARealApiKeyValue"')  # gitleaks:allow
    assert "[redacted]" in redact_sensitive("token = NotARealTokenValue00")  # gitleaks:allow
    # the label itself is preserved for debuggability
    out = redact_sensitive("password=NotARealPasswordValue")  # gitleaks:allow
    assert out.startswith("password")


def test_leaves_benign_text_unchanged():
    benign = "matching completed in 342ms for job 12345 (pool=200)"
    assert redact_sensitive(benign) == benign


def test_empty_input():
    assert redact_sensitive("") == ""


def test_prose_after_password_word_not_redacted():
    # "password" as a word (no '='/':' value) must not swallow following prose.
    text = "user changed password successfully"
    assert redact_sensitive(text) == text


def test_filter_mutates_record_message():
    filt = RedactingFilter()
    record = logging.LogRecord(
        name="x",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="emailing %s",
        args=("jan@example.com",),
        exc_info=None,
    )
    assert filt.filter(record) is True
    assert "jan@example.com" not in record.getMessage()
    assert "[email]" in record.getMessage()


def test_filter_never_drops_record():
    filt = RedactingFilter()
    record = logging.LogRecord(
        name="x",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="nothing sensitive here",
        args=None,
        exc_info=None,
    )
    assert filt.filter(record) is True
