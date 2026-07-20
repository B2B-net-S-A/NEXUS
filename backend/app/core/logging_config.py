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


# ── PII / secret redaction ───────────────────────────────────────────────────
# NEXUS ships structured logs to Loki/Grafana, so candidate PII (emails) and any
# secret that leaks into an exception message must be scrubbed before emission.
# Done centrally here (one filter) rather than sprinkled across every service's
# logging call. Deliberately conservative — only unambiguous, high-value patterns
# so ordinary log lines stay useful.

_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
# sk-... provider keys (Anthropic/OpenAI/Voyage); min length avoids matching prose.
_KEY_PREFIX_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b")
_BEARER_RE = re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._\-]{8,}")
# label=value / label: value — only '=' or ':' separators, so ordinary prose after
# the word "password" etc. is not touched.
_LABELED_SECRET_RE = re.compile(
    r"(?i)\b(token|api[_-]?key|secret|password|passwd|access[_-]?key"
    r"|client[_-]?secret|authorization)(\s*[=:]\s*)(['\"]?)([^\s'\"]{4,})"
)
# Capability tokens that travel in the URL PATH — signature links, CV / champion
# / apply share links, CloudTalk webhooks. The default uvicorn access log writes
# the full path (`GET /sign/abc123... HTTP/1.1`), so the raw token lands in
# Loki/Grafana and any reverse-proxy log. The labelled-secret pattern above does
# NOT catch these because a path segment is not a `token=value` pair. Mask the
# segment immediately after each known public prefix, keeping the prefix so the
# log line still says which flow it was.
_PATH_TOKEN_RE = re.compile(
    r"(?i)(/(?:sign|cv|champion-card|apply|champion-share|calls/webhook|public/[\w-]+)/)"
    r"([A-Za-z0-9._\-]{8,})"
)


def redact_sensitive(text: str) -> str:
    """Mask emails, provider keys, bearer tokens and labelled secrets in ``text``.

    Best-effort and conservative — returns ``text`` unchanged when nothing matches.
    """
    if not text:
        return text
    text = _EMAIL_RE.sub("[email]", text)
    text = _KEY_PREFIX_RE.sub("[redacted-key]", text)
    text = _BEARER_RE.sub(r"\1 [redacted]", text)
    text = _LABELED_SECRET_RE.sub(
        lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}[redacted]", text
    )
    text = _PATH_TOKEN_RE.sub(r"\1[redacted-token]", text)
    return text


class RedactingFilter(logging.Filter):
    """Logging filter that scrubs PII/secrets from every emitted record.

    Attached to the production JSON handler so redaction is central. Never drops a
    record and never raises — logging must not break because redaction hit an edge.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 — malformed args: emit as-is, don't drop
            return True
        redacted = redact_sensitive(message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


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
    handler.addFilter(RedactingFilter())  # scrub PII/secrets before they reach Loki
    root.addHandler(handler)

    # Make uvicorn loggers use the same handler
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        logger = logging.getLogger(name)
        logger.handlers = [handler]
        logger.propagate = False

    logging.getLogger(__name__).info(
        "json_logging_enabled", extra={"component": "logging"}
    )
