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

try:
    from pythonjsonlogger import jsonlogger  # type: ignore
except ImportError:  # pragma: no cover
    jsonlogger = None


_TRAFFIT_WEBHOOK_SECRET_RE = re.compile(
    r"(/api/integrations/traffit/webhooks/[^/\s?]+/)[^\s?\"']+"
)


def redact_sensitive_path(value: str) -> str:
    """Remove URL credentials before a request line reaches any formatter."""
    return _TRAFFIT_WEBHOOK_SECRET_RE.sub(r"\1[REDACTED]", value)


class SensitivePathFilter(logging.Filter):
    """Redact path-bound webhook secrets from uvicorn access records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_sensitive_path(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(
                redact_sensitive_path(value) if isinstance(value, str) else value
                for value in record.args
            )
        elif isinstance(record.args, dict):
            record.args = {
                key: redact_sensitive_path(value)
                if isinstance(value, str)
                else value
                for key, value in record.args.items()
            }
        return True


def _install_sensitive_path_filter(handler: logging.Handler) -> None:
    if not any(isinstance(item, SensitivePathFilter) for item in handler.filters):
        handler.addFilter(SensitivePathFilter())


def configure_json_logging(debug: bool = False) -> None:
    """Install JSON formatter on the root logger when not in debug mode."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # URL-secret fallback credentials must never be emitted by uvicorn.access,
    # including in local/debug mode where existing handlers are retained.
    for logger_name in ("", "uvicorn", "uvicorn.access", "uvicorn.error"):
        for existing_handler in logging.getLogger(logger_name).handlers:
            _install_sensitive_path_filter(existing_handler)

    if debug or jsonlogger is None:
        # Keep default formatter — easier to read during local dev
        return

    # Remove any existing handlers (uvicorn may have added one already)
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    _install_sensitive_path_filter(handler)
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
