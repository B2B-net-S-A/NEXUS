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
    # python-json-logger >= 3.1 moved the formatter to `pythonjsonlogger.json`.
    # The old `pythonjsonlogger.jsonlogger` path still resolves in 4.x but emits a
    # DeprecationWarning on import, so prefer the new one.
    from pythonjsonlogger.json import JsonFormatter
except ImportError:  # pragma: no cover — python-json-logger < 3.1
    try:
        from pythonjsonlogger.jsonlogger import JsonFormatter  # type: ignore
    except ImportError:
        JsonFormatter = None  # type: ignore[assignment]


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
# Prefiks `(?:[a-z0-9]+[_-])*` przed etykietą jest load-bearing: samo `\b` NIE
# dopasowuje się po podkreślniku (`_` jest znakiem słowa), więc `refresh_token=…`
# przechodziło przez ten filtr dosłownie — a to poświadczenie o 30-dniowym życiu,
# które access log uvicorna zapisuje razem z query stringiem.
_LABELED_SECRET_RE = re.compile(
    r"(?i)\b((?:[a-z0-9]+[_-])*(?:token|api[_-]?key|secret|password|passwd"
    r"|access[_-]?key|client[_-]?secret|authorization))(\s*[=:]\s*)(['\"]?)([^\s'\"]{4,})"
)
# Capability tokens that travel in the URL PATH — signature links, CV / champion
# / apply share links, CloudTalk webhooks. The default uvicorn access log writes
# the full path (`GET /sign/abc123... HTTP/1.1`), so the raw token lands in
# Loki/Grafana and any reverse-proxy log. The labelled-secret pattern above does
# NOT catch these because a path segment is not a `token=value` pair. Mask the
# segment immediately after each known public prefix, keeping the prefix so the
# log line still says which flow it was.
_PATH_TOKEN_RE = re.compile(
    r"(?i)(/(?:sign|cv|champion-card|apply|champion-share|calls/webhook|share-token|public/[\w-]+)/)"
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
    """Logging filter that scrubs PII/secrets from the record's MESSAGE.

    Attached to the production JSON handler so redaction is central. Never drops a
    record and never raises — logging must not break because redaction hit an edge.

    Świadomie obejmuje wyłącznie `record.msg`: traceback i pola `extra` formatter
    emituje osobno i redaguje je :class:`RedactingJsonFormatter` (mutowanie
    `record.exc_info` tutaj zabrałoby Sentry stack trace'y — patrz tamten docstring).
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


# Baza formattera trzymana w zmiennej, żeby moduł dał się zaimportować także bez
# python-json-logger (ten sam fallback co wyżej) — instancjonujemy tę klasę
# WYŁĄCZNIE gdy `JsonFormatter is not None`.
_JsonFormatterBase = JsonFormatter if JsonFormatter is not None else logging.Formatter


class RedactingJsonFormatter(_JsonFormatterBase):  # type: ignore[misc,valid-type]
    """JSON formatter, który redaguje CAŁY emitowany rekord, nie tylko wiadomość.

    ``RedactingFilter`` przepisuje `record.msg` — a formatter emituje `exc_info`
    OSOBNYM polem, renderując je wprost z `record.exc_info` (ustawienie
    `record.exc_text` jest przez python-json-logger ignorowane, gdy `exc_info`
    jest obecne). Tam właśnie SQLAlchemy wkłada `[parameters: ('Jan','Kowalski',
    'jan@x.pl','+48601234567')]` przy każdym `IntegrityError`/`DataError`, więc
    „zredagowana" wiadomość jechała do Loki razem z niezredagowanym PII kandydata.

    Redakcji NIE robimy przez wyzerowanie `record.exc_info` w filtrze: sentry-sdk
    czyta ten sam rekord PO handlerach, więc skasowanie `exc_info` odebrałoby
    Sentry stack trace'y. Nadpisujemy tylko to, co formatter sam wypisuje.
    """

    def formatException(self, ei) -> str:  # noqa: N802 — nazwa z logging.Formatter
        return redact_sensitive(super().formatException(ei))

    def formatStack(self, stack_info) -> str:  # noqa: N802 — j.w.
        return redact_sensitive(super().formatStack(stack_info))

    def process_log_record(self, log_record):
        """Ostatnia bramka: redakcja każdej wartości tekstowej w gotowym rekordzie.

        Obejmuje też `extra={...}` — dowolne pole dołożone przez wywołującego
        (np. `extra={"email": ...}`) trafia do JSON-a z pominięciem `record.msg`.
        """
        processed = super().process_log_record(log_record)
        return {
            key: (redact_sensitive(value) if isinstance(value, str) else value)
            for key, value in processed.items()
        }


def configure_json_logging(debug: bool = False) -> None:
    """Install JSON formatter on the root logger when not in debug mode."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    if debug or JsonFormatter is None:
        # Keep default formatter — easier to read during local dev
        return

    # Remove any existing handlers (uvicorn may have added one already)
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    # `taskName` is listed explicitly on purpose. Under python-json-logger 2.0.7 it
    # leaked into every record as an "extra" (that release's reserved-attrs list
    # predates the Python 3.12 LogRecord attribute), so prod logs in Loki already
    # carry it. Versions >= 3 correctly treat it as reserved and drop it, which
    # would silently change the log contract — naming it here keeps the emitted key
    # set identical (null outside a task, the task name inside one).
    formatter = RedactingJsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(taskName)s %(message)s",
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
