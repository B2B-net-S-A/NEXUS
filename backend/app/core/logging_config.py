"""
Phase 7d — structured JSON logging.

In production (DEBUG=False) we emit single-line JSON log records so log
aggregators (Coolify's Vector, Loki, Datadog, etc.) can parse them. In DEBUG
we keep the default human-readable formatter.

Call `configure_json_logging()` once from main.py after settings are loaded.
"""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

try:
    from pythonjsonlogger import jsonlogger  # type: ignore
except ImportError:  # pragma: no cover
    jsonlogger = None


_EMAIL_RE = re.compile(
    r"(?i)(?<![\w.+-])[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+(?![\w.-])"
)
_PHONE_CANDIDATE_RE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{5,}\d(?!\w)")


def _redact_phone_candidate(match: re.Match[str]) -> str:
    digits = re.sub(r"\D", "", match.group(0))
    # ATS phone data is stored with at least nine digits.  The lower bound also
    # avoids treating ISO dates such as 2026-07-14 as phone numbers.
    if 9 <= len(digits) <= 15:
        return "[REDACTED_PHONE]"
    return match.group(0)


def redact_sensitive_text(value: str) -> str:
    """Remove common direct identifiers from diagnostic text.

    This is a defence-in-depth guard for messages originating in third-party
    SDK exceptions. Call sites handling CVs, transcripts and provider payloads
    must still avoid logging those values in the first place.
    """
    redacted = _EMAIL_RE.sub("[REDACTED_EMAIL]", value)
    return _PHONE_CANDIDATE_RE.sub(_redact_phone_candidate, redacted)


def redact_sensitive_value(value: Any) -> Any:
    """Recursively redact strings in structured logging/Sentry metadata."""
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if isinstance(value, dict):
        return {key: redact_sensitive_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_sensitive_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive_value(item) for item in value)
    return value


class SensitiveDataFilter(logging.Filter):
    """Last-line redaction for log messages and structured extra fields."""

    _STANDARD_FIELDS = frozenset(logging.makeLogRecord({}).__dict__)

    def filter(self, record: logging.LogRecord) -> bool:
        # Render first so identifiers passed through %-style args cannot bypass
        # the filter, then clear args to prevent a second interpolation.
        record.msg = redact_sensitive_text(record.getMessage())
        record.args = ()
        for key, value in list(record.__dict__.items()):
            if key not in self._STANDARD_FIELDS:
                record.__dict__[key] = redact_sensitive_value(value)
        return True


def configure_json_logging(debug: bool = False) -> None:
    """Install JSON formatter on the root logger when not in debug mode."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    sensitive_filter = SensitiveDataFilter()
    for existing_handler in root.handlers:
        existing_handler.addFilter(sensitive_filter)

    if debug or jsonlogger is None:
        # Keep default formatter — easier to read during local dev
        return

    # Remove any existing handlers (uvicorn may have added one already)
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(sensitive_filter)
    formatter = jsonlogger.JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        rename_fields={"asctime": "timestamp", "levelname": "level"},
    )
    handler.setFormatter(formatter)
    root.addHandler(handler)

    # Make uvicorn loggers use the same handler
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        logger = logging.getLogger(name)
        logger.handlers = [handler]
        logger.propagate = False

    logging.getLogger(__name__).info(
        "json_logging_enabled", extra={"component": "logging"}
    )
