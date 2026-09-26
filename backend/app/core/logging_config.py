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

# `(?:@|%40)`: access log uvicorna zapisuje query string ZAKODOWANY, więc
# `check-exists?email=jan%40firma.pl` nie miał dosłownego `@` i przechodził
# (runda 6 audytu).
# Runda 7 (R7-V5-1): część lokalna zaczyna się WYŁĄCZNIE na początku ciągu
# znaków adresu (lookbehind) i jest zaborcza. Z samym `\b` każda granica słowa
# w `a-a-a-…` była osobnym startem, który skanował resztę napisu — kwadratowo,
# a access log uvicorna redaguje URL od anonimowego żądania na pętli zdarzeń.
_EMAIL_RE = re.compile(r"(?i)(?<![\w.+-])[\w.+-]++(?:@|%40)[\w-]+\.[\w.-]+\b")
# sk-... provider keys (Anthropic/OpenAI/Voyage); min length avoids matching prose.
_KEY_PREFIX_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b")
_BEARER_RE = re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._\-]{8,}")
# label=value / label: value — only '=' or ':' separators, so ordinary prose after
# the word "password" etc. is not touched.
# Etykieta może stać po `_`/`-` (`refresh_token=…` — poświadczenie o 30-dniowym
# życiu, które access log uvicorna zapisuje razem z query stringiem), ale nie po
# literze ani cyfrze (`(?<![^\W_])`). Prefiks (`refresh_`) zostaje w tekście
# przed dopasowaniem. Runda 7 (R7-V5-1): do tej pory prefiks był powtórzeniem
# `(?:[a-z0-9]+[_-])*` od każdej granicy słowa, które na `a-a-a-…` cofało się
# po całym napisie — kwadratowo.
_LABELED_SECRET_RE = re.compile(
    r"(?i)(?<![^\W_])((?:token|api[_-]?key|secret|password|passwd"
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
    r"(?i)(/(?:sign|cv|champion-card|apply|champion-share|calls/webhook|share-token|public/[\w-]++)/)"
    r"([A-Za-z0-9._\-]{8,})"
)


# Adres webhooka Slacka JEST sekretem (kto go zna, pisze na nasz kanał), a httpx
# i komunikaty wyjątków wypisują go w całości. Zostaje sam host (runda 6 audytu).
_SLACK_WEBHOOK_RE = re.compile(
    r"(?i)(hooks\.slack\.com/(?:services|workflows|triggers)/)[^\s'\"]+"
)
# Prywatny kalendarz iCal (Outlook `/owa/calendar/…/calendar.ics`, Google
# `/calendar/ical/…/basic.ics`, dowolne `.ics`) — ścieżka i query dają odczyt
# całego kalendarza, więc maskujemy wszystko po hoście (runda 6 audytu).
#
# Runda 7 (R7-V5-1): bez lookaheadu. Host z lookaheadem cofał się znak po znaku
# i każde cofnięcie ponawiało przeszukanie reszty napisu (16 KB URL = sekundy
# zablokowanej pętli zdarzeń). Wzorzec łapie cały adres, a o maskowaniu decyduje
# `_mask_ical_url`.
_ICAL_URL_RE = re.compile(r"(?i)\b((?:https?|webcal)://[^\s/'\"?#]++)([^\s'\"]*+)")
_ICAL_MARKER_RE = re.compile(r"(?i)\.ics\b|/ical/|/calendar/")
# Wartości parametrów z danymi osobowymi w query stringu (access log uvicorna):
# `q=` niesie nazwisko wpisane w wyszukiwarkę, `phone=` telefon (runda 6 audytu).
# `search=` (kontakty klienta, czaty) i `nip=` (Partner B2B bywa JDG, więc NIP
# jest daną osobową) — runda 7 (R7-V5-3).
_QUERY_PII_RE = re.compile(
    r"(?i)([?&](?:email|phone|q|q_all|q_any|q_any_group|q_none|name|first_name"
    r"|last_name|lastname|full_name|search|nip)=)[^&\s\"'#]+"
)


# Runda 7 (R7-V5-1): górny limit długości redagowanego tekstu. Wzorce są
# liniowe, limit jest drugą linią obrony — koszt redakcji rekordu nie może
# zależeć od tego, ile bajtów przyśle anonimowe żądanie. Zostaje początek
# i koniec (w tracebacku na końcu stoi sam wyjątek).
_MAX_REDACT_CHARS = 32_768
_TRUNCATION_MARKER = "…[ucięto {} znaków]…"


def _truncate_for_redaction(text: str) -> str:
    if len(text) <= _MAX_REDACT_CHARS:
        return text
    cut = len(text) - _MAX_REDACT_CHARS
    marker = _TRUNCATION_MARKER.format(cut)
    # Wynik (razem ze znacznikiem) mieści się w limicie, więc ponowna redakcja
    # tego samego tekstu przez formatter niczego już nie ucina.
    keep = _MAX_REDACT_CHARS - len(marker)
    head = keep // 2
    return text[:head] + marker + text[len(text) - (keep - head) :]


def _mask_ical_url(match: re.Match[str]) -> str:
    if _ICAL_MARKER_RE.search(match.group(2)):
        return f"{match.group(1)}/[redacted-path]"
    return match.group(0)


def redact_sensitive(text: str) -> str:
    """Mask emails, provider keys, bearer tokens and labelled secrets in ``text``.

    Best-effort and conservative — returns ``text`` unchanged when nothing matches.
    Idempotent: redacting an already redacted text returns it unchanged, so the
    formatter's second pass over the message costs one linear scan.
    """
    if not text:
        return text
    text = _truncate_for_redaction(text)
    text = _SLACK_WEBHOOK_RE.sub(r"\1[redacted]", text)
    text = _ICAL_URL_RE.sub(_mask_ical_url, text)
    text = _QUERY_PII_RE.sub(r"\1[redacted]", text)
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
    # httpx/httpcore na INFO piszą „HTTP Request: POST <pełny adres>” przy KAŻDYM
    # żądaniu — w tym adres webhooka Slacka i prywatnego kalendarza iCal, czyli
    # sekrety. Ustawiane PRZED gałęzią debug, bo lokalny log też bywa wklejany
    # do zgłoszeń (runda 6 audytu).
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)

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
