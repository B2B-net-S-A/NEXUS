"""Unit tests for central log PII/secret redaction (app.core.logging_config).

The fixtures below are deliberately secret-SHAPED placeholders (never real
credentials) so the redaction regexes are exercised; the ``# gitleaks:allow``
markers keep the secret scanner from flagging these intentional decoys.

The second half of this file locks the *log contract* — the exact JSON key set we
emit to Loki. Grafana LogQL queries are written against these field names, so a
library upgrade that silently renames or drops one is a production observability
outage with a perfectly healthy-looking app. Assert the keys, not just the values.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import re

import pytest

from app.core.logging_config import (
    RedactingFilter,
    configure_json_logging,
    redact_sensitive,
)


def test_redacts_email():
    out = redact_sensitive("candidate jan.kowalski@example.com applied")
    assert "jan.kowalski@example.com" not in out
    assert "[email]" in out


def test_redacts_provider_key():
    out = redact_sensitive(
        "using key sk-notARealKeyPlaceholder0000 now"
    )  # gitleaks:allow
    assert "sk-notARealKeyPlaceholder0000" not in out
    assert "[redacted-key]" in out


def test_redacts_bearer_token():
    out = redact_sensitive("header: Bearer notARealBearerToken0000")  # gitleaks:allow
    assert "notARealBearerToken0000" not in out
    assert "[redacted]" in out


def test_redacts_labelled_secrets():
    assert "[redacted]" in redact_sensitive(
        "password=NotARealPasswordValue"
    )  # gitleaks:allow
    assert "[redacted]" in redact_sensitive(
        'api_key: "NotARealApiKeyValue"'
    )  # gitleaks:allow
    assert "[redacted]" in redact_sensitive(
        "token = NotARealTokenValue00"
    )  # gitleaks:allow
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


# ── log contract (JSON key set shipped to Loki) ──────────────────────────────

# Field names Grafana LogQL queries rely on. Changing this set is a breaking
# change for dashboards/alerts and must be a deliberate, announced migration —
# never a side effect of a dependency bump.
EXPECTED_LOG_FIELDS = {"timestamp", "level", "name", "taskName", "message"}

_UVICORN_LOGGERS = ("uvicorn", "uvicorn.access", "uvicorn.error")


@pytest.fixture
def json_logging():
    """Install the production JSON handler, yield a reader, then restore logging.

    ``configure_json_logging`` rips handlers off the root and uvicorn loggers, so
    the surrounding pytest session must be put back exactly as it was.

    The handler's stream is swapped for an in-memory buffer rather than reading
    ``capsys``: the handler binds ``sys.stdout`` at construction time, and
    ``capsys.readouterr()`` resets pytest's buffer underneath that reference.
    """
    root = logging.getLogger()
    saved_root_handlers = list(root.handlers)
    saved_root_level = root.level
    saved_uvicorn = {
        name: (
            list(logging.getLogger(name).handlers),
            logging.getLogger(name).propagate,
        )
        for name in _UVICORN_LOGGERS
    }

    configure_json_logging(debug=False)

    # Redirect the handler configure_json_logging just installed into our buffer.
    # This also discards its own "json_logging_enabled" startup line, so tests only
    # ever see the records they emitted themselves.
    buffer = io.StringIO()
    for handler in root.handlers:
        if isinstance(handler, logging.StreamHandler):
            handler.setStream(buffer)

    def read_records() -> list[dict]:
        lines = [line for line in buffer.getvalue().splitlines() if line.strip()]
        buffer.seek(0)
        buffer.truncate(0)
        return [json.loads(line) for line in lines]

    try:
        yield read_records
    finally:
        for handler in list(root.handlers):
            root.removeHandler(handler)
        for handler in saved_root_handlers:
            root.addHandler(handler)
        root.setLevel(saved_root_level)
        for name, (handlers, propagate) in saved_uvicorn.items():
            logger = logging.getLogger(name)
            logger.handlers = handlers
            logger.propagate = propagate


def test_log_contract_exact_key_set(json_logging):
    logging.getLogger("app.contract").info("hello")

    records = json_logging()
    assert len(records) == 1
    assert set(records[0]) == EXPECTED_LOG_FIELDS


def test_log_contract_field_values(json_logging):
    logging.getLogger("app.contract").warning("something odd")

    record = json_logging()[0]
    assert record["level"] == "WARNING"
    assert record["name"] == "app.contract"
    assert record["message"] == "something odd"
    # asctime style: "2026-07-27 14:35:30,941" (comma before milliseconds)
    assert re.fullmatch(
        r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}", record["timestamp"]
    )


def test_log_contract_task_name_null_outside_asyncio_task(json_logging):
    logging.getLogger("app.contract").info("sync context")

    assert json_logging()[0]["taskName"] is None


def test_log_contract_task_name_populated_inside_asyncio_task(json_logging):
    """NEXUS runs ~24 named background loops; `taskName` is how they're told apart."""

    async def emit():
        logging.getLogger("app.contract").info("in task")

    async def main():
        await asyncio.create_task(emit(), name="traffit_sync")

    asyncio.run(main())

    assert json_logging()[0]["taskName"] == "traffit_sync"


def test_log_contract_extra_fields_pass_through(json_logging):
    logging.getLogger("app.contract").info("with extra", extra={"component": "logging"})

    record = json_logging()[0]
    assert record["component"] == "logging"
    assert set(record) == EXPECTED_LOG_FIELDS | {"component"}


def test_log_contract_redaction_applies_to_json_output(json_logging):
    """The redacting filter must sit on the JSON handler, not just exist in isolation."""
    logging.getLogger("app.contract").info("candidate jan.kowalski@example.com applied")

    record = json_logging()[0]
    assert "jan.kowalski@example.com" not in record["message"]
    assert "[email]" in record["message"]
