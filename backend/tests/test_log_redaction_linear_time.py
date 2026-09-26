"""Runda 7 (R7-V5-1): redakcja logów nie może być kwadratowa.

Access log uvicorna redaguje URL od ANONIMOWEGO żądania, synchronicznie, na
pętli zdarzeń jedynego procesu API. Do rundy 7 wzorce iCal (lookahead po
cofającym się hoście), e-mail (start od każdej granicy słowa) i sekretów
z etykietą (powtarzany prefiks) były kwadratowe: 8 KB URL = ok. 2 s, 16 KB =
kilkanaście sekund zablokowanego API, łącznie z `/api/health/live`.

Czasy liczone na wzorcach BEZ limitu długości (`_MAX_REDACT_CHARS`), bo limit
jest drugą linią obrony — liniowe muszą być same wzorce.
"""

from __future__ import annotations

import io
import logging
import time

import pytest

import app.core.logging_config as logging_config
from app.core.logging_config import redact_sensitive

_MALICIOUS = {
    "ical_host_backtrack": lambda n: "/x?u=http://" + "a-" * n,
    "ical_scheme_chain": lambda n: "http://" * n,
    "email_dots": lambda n: "/x?u=" + "a." * n,
    "email_dashes": lambda n: "/x?u=" + "a-" * n,
    "email_after_at": lambda n: "x@" + "a-" * n,
    "email_at_chain": lambda n: "a@" * n,
    "secret_prefix_dashes": lambda n: "a-" * n,
    "secret_keyword_chain": lambda n: "token_" * n,
    "secret_spaces": lambda n: "token=" + " " * n + "ab",
    "key_prefix_chain": lambda n: "sk-" * n,
    "public_path": lambda n: "/public/" + "a-" * n,
    "mixed_prose": lambda n: "a-b.c+d " * n,
}


@pytest.fixture
def no_length_cap(monkeypatch):
    monkeypatch.setattr(logging_config, "_MAX_REDACT_CHARS", 10**9)


def _elapsed(text: str) -> float:
    started = time.perf_counter()
    redact_sensitive(text)
    return time.perf_counter() - started


@pytest.mark.parametrize("name", sorted(_MALICIOUS))
@pytest.mark.parametrize("target_len", [16_384, 65_536])
def test_redaction_is_linear_on_hostile_input(name, target_len, no_length_cap):
    build = _MALICIOUS[name]
    unit = len(build(2)) - len(build(1))
    text = build(target_len // unit + 1)
    assert len(text) >= target_len
    assert _elapsed(text) < 0.05, f"{name}: {len(text)} znaków"


def test_long_text_is_truncated_with_marker_and_keeps_both_ends():
    text = "POCZĄTEK " + "x" * 100_000 + " KONIEC"
    out = redact_sensitive(text)
    assert len(out) <= logging_config._MAX_REDACT_CHARS
    assert out.startswith("POCZĄTEK ")
    assert out.endswith(" KONIEC")
    assert "[ucięto" in out


def test_redaction_is_idempotent_including_truncation():
    samples = [
        "jan.kowalski@example.com i jan%40firma.pl",
        "GET /api/contacts?search=Nowak&q=Kowalski HTTP/1.1",
        "refresh_token=NotARealTokenValue00 Bearer notARealBearerToken0000",  # gitleaks:allow
        "sk-notARealKeyPlaceholder0000",  # gitleaks:allow
        "https://outlook.office365.com/owa/calendar/abc/reachcalendar.ics",
        "GET /cv/abcdefgh12345678 HTTP/1.1",
        "z" * 100_000,
    ]
    for sample in samples:
        once = redact_sensitive(sample)
        assert redact_sensitive(once) == once


def test_ical_decision_moved_out_of_the_pattern_keeps_semantics():
    masked = redact_sensitive(
        "fetch https://calendar.google.com/calendar/ical/x/basic.ics failed"
    )
    assert masked == "fetch https://calendar.google.com/[redacted-path] failed"
    plain = "fetch https://api.example.com/v1/items?id=5 failed"
    assert redact_sensitive(plain) == plain


def test_email_starting_with_punctuation_is_still_redacted():
    out = redact_sensitive("from .jan.kowalski@example.com here")
    assert "kowalski" not in out


def test_labelled_secret_after_prefix_keeps_prefix():
    out = redact_sensitive("refresh_token=NotARealTokenValue00")  # gitleaks:allow
    assert out == "refresh_token=[redacted]"
    # Słowo kluczowe wewnątrz słowa nie jest etykietą (jak przed rundą 7).
    assert redact_sensitive("csrftoken=abcdefgh") == "csrftoken=abcdefgh"


def test_search_and_nip_query_values_are_redacted():
    """R7-V5-3: `search=` (kontakty, czaty) i `nip=` (Partner bywa JDG)."""
    out = redact_sensitive(
        "GET /api/contacts?search=Nowak&limit=20 HTTP/1.1 "
        "GET /api/b2b/partner-lookup?nip=5261040828 HTTP/1.1"
    )
    assert "Nowak" not in out
    assert "5261040828" not in out
    assert "limit=20" in out
    assert "search=[redacted]" in out


@pytest.mark.skipif(
    logging_config.JsonFormatter is None, reason="python-json-logger nieobecny"
)
def test_full_log_record_with_hostile_url_is_fast():
    """Filtr + formatter (dwie redakcje wiadomości) na 64 KB URL."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(
        logging_config.RedactingJsonFormatter("%(levelname)s %(name)s %(message)s")
    )
    handler.addFilter(logging_config.RedactingFilter())
    logger = logging.getLogger("tests.r7.redaction.linear")
    logger.handlers = [handler]
    logger.propagate = False
    try:
        started = time.perf_counter()
        logger.warning("GET %s HTTP/1.1", "/x?u=http://" + "a-" * 32_768)
        assert time.perf_counter() - started < 0.2
    finally:
        logger.handlers = []
    # JSON zapisuje „ę” jako \\u0119.
    assert "[uci" in stream.getvalue()
