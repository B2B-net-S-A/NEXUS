"""
Phase 7d — structured JSON logging.

In production (DEBUG=False) we emit single-line JSON log records so log
aggregators (Coolify's Vector, Loki, Datadog, etc.) can parse them. In DEBUG
we keep the default human-readable formatter.

Call `configure_json_logging()` once from main.py after settings are loaded.
"""

from __future__ import annotations

import logging
import sys

try:
    from pythonjsonlogger import jsonlogger  # type: ignore
except ImportError:  # pragma: no cover
    jsonlogger = None


def configure_json_logging(debug: bool = False) -> None:
    """Install JSON formatter on the root logger when not in debug mode."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    if debug or jsonlogger is None:
        # Keep default formatter — easier to read during local dev
        return

    # Remove any existing handlers (uvicorn may have added one already)
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
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
