"""Redakcja obejmuje TRACEBACK i pola `extra`, nie tylko `record.msg`.

Regresja jest cicha z definicji: log wychodzi, wygląda na zredagowany
(`message` ma `[email]`), a PII kandydata jedzie obok — w polu `exc_info`,
które formatter renderuje wprost z `record.exc_info`. Tam właśnie SQLAlchemy
wkłada `[SQL: ...] [parameters: ('Jan','Kowalski','jan@x.pl','+48601234567')]`
przy każdym `IntegrityError`/`DataError`, a `create_async_engine` nie ustawia
`hide_parameters=True`. Cel podróży: stdout → Docker json-file → Alloy → Loki.

Istniejące testy `RedactingFilter` konstruują rekord z `exc_info=None`, więc
żaden z nich tej ścieżki nie dotyka.
"""

from __future__ import annotations

import json
import logging
import sys

import pytest

from app.core.logging_config import RedactingJsonFormatter, redact_sensitive

pytestmark = pytest.mark.skipif(
    RedactingJsonFormatter.__bases__[0] is logging.Formatter,
    reason="python-json-logger niedostępny — produkcyjny formatter nie istnieje",
)


def _formatter() -> RedactingJsonFormatter:
    return RedactingJsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(taskName)s %(message)s",
        rename_fields={"asctime": "timestamp", "levelname": "level"},
    )


def _record_with_exception(message: str, exc: Exception) -> logging.LogRecord:
    try:
        raise exc
    except Exception:  # noqa: BLE001 — celowo chwytamy, by dostać exc_info
        exc_info = sys.exc_info()
    return logging.LogRecord(
        name="app.test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=None,
        exc_info=exc_info,
    )


def test_exception_payload_is_redacted_in_json_output():
    record = _record_with_exception(
        "candidate create failed",
        ValueError(
            "duplicate key value violates unique constraint 'ix_candidates_email'\n"
            "[SQL: INSERT INTO candidates (name, lastname, email, phone) VALUES ...]\n"
            "[parameters: ('Jan', 'Kowalski', 'jan.kowalski@example.pl', '+48601234567')]"
        ),
    )
    emitted = json.loads(_formatter().format(record))

    assert "exc_info" in emitted, "traceback musi nadal być emitowany"
    assert "jan.kowalski@example.pl" not in emitted["exc_info"]
    assert "[email]" in emitted["exc_info"]
    # Cały wiersz logu, nie tylko jedno pole — to on ląduje w Loki.
    assert "jan.kowalski@example.pl" not in json.dumps(emitted)


def test_extra_fields_are_redacted():
    """`extra={...}` omija `record.msg` w całości."""
    record = logging.LogRecord(
        name="app.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="candidate synced",
        args=None,
        exc_info=None,
    )
    record.candidate_email = "ewa.nowak@example.pl"
    emitted = json.loads(_formatter().format(record))

    assert emitted["candidate_email"] == "[email]"


def test_record_exc_info_is_left_intact_for_sentry():
    """Redakcja NIE MOŻE zerować `exc_info`.

    sentry-sdk czyta ten sam rekord PO handlerach (`callHandlers` opakowany
    `finally`), więc skasowanie `exc_info` odebrałoby Sentry stack trace'y —
    lekarstwo gorsze od choroby.
    """
    record = _record_with_exception("boom", ValueError("kontakt: a@b.pl"))
    _formatter().format(record)
    assert record.exc_info is not None
    assert record.exc_info[0] is ValueError


def test_underscored_secret_labels_are_redacted():
    """`\\b` przed `token` NIE dopasowuje się po podkreślniku.

    `refresh_token=` jechało przez filtr dosłownie, a to 30-dniowe
    poświadczenie, które access log uvicorna zapisuje razem z query stringiem.
    """
    raw = "POST /api/auth/refresh?refresh_token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    redacted = redact_sensitive(raw)
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in redacted
    assert "refresh_token=[redacted]" in redacted

    # Nie psujemy dotychczasowego zachowania dla gołej etykiety.
    assert redact_sensitive("token=abcdef123456") == "token=[redacted]"
    # Ani nie zjadamy zwykłej prozy.
    assert redact_sensitive("user changed password successfully") == (
        "user changed password successfully"
    )
