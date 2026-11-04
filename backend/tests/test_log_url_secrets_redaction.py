"""Sekrety w adresach URL nie mogą trafić do logów (runda 6 audytu, W1 i W4).

Logi backendu idą do Loki/Coolify, a repo jest publiczne — odczyt logu nie może
dawać tego, co daje adres:

- ``httpx`` na INFO pisze „HTTP Request: POST https://hooks.slack.com/services/…”
  przy KAŻDYM udanym webhooku, a adres webhooka Slacka JEST sekretem (kto go zna,
  pisze na nasz kanał); tak samo adresy prywatnych kalendarzy iCal;
- access log uvicorna zapisuje query string z ``%40`` zamiast ``@``
  (``check-exists?email=jan%40firma.pl``), więc dosłowny wzorzec e-maila go
  nie łapał, a ``q=``/``phone=`` niosą nazwiska i telefony kandydatów.
"""

from __future__ import annotations

import logging

import httpx
import pytest

from app.core.logging_config import configure_json_logging, redact_sensitive
from app.services import ical_import as ii

_SLACK = "https://hooks.slack.com/services/T0NOTREAL/B0NOTREAL/notARealSlackSecret00"  # gitleaks:allow


@pytest.fixture
def restore_logging():
    root = logging.getLogger()
    saved = (list(root.handlers), root.level)
    names = ("httpx", "httpcore", "uvicorn", "uvicorn.access", "uvicorn.error")
    saved_named = {
        n: (
            list(logging.getLogger(n).handlers),
            logging.getLogger(n).propagate,
            logging.getLogger(n).level,
        )
        for n in names
    }
    yield
    for h in list(root.handlers):
        root.removeHandler(h)
    for h in saved[0]:
        root.addHandler(h)
    root.setLevel(saved[1])
    for n, (handlers, propagate, level) in saved_named.items():
        lg = logging.getLogger(n)
        lg.handlers = handlers
        lg.propagate = propagate
        lg.setLevel(level)


@pytest.mark.parametrize("debug", [False, True])
def test_httpx_request_lines_are_not_logged(restore_logging, debug):
    """„HTTP Request: POST <adres>” (INFO) nie może wyjść z procesu w żadnym trybie."""
    configure_json_logging(debug=debug)
    for name in ("httpx", "httpcore"):
        assert not logging.getLogger(name).isEnabledFor(logging.INFO), name
        assert logging.getLogger(name).isEnabledFor(logging.WARNING), name


def test_slack_webhook_secret_is_masked():
    line = f'HTTP Request: POST {_SLACK} "HTTP/1.1 200 OK"'
    out = redact_sensitive(line)
    assert "notARealSlackSecret00" not in out
    assert "B0NOTREAL" not in out
    assert "hooks.slack.com" in out  # wiadomo, dokąd szło żądanie


@pytest.mark.parametrize(
    "url, secret",
    [
        (
            "https://outlook.office365.com/owa/calendar/abc123def/"
            "s3cretPart0000/calendar.ics",
            "s3cretPart0000",
        ),
        (
            "https://calendar.google.com/calendar/ical/someone/"
            "private-notARealIcalKey00/basic.ics",
            "private-notARealIcalKey00",
        ),
        ("webcal://cal.example.com/feed/notARealFeedKey00.ics", "notARealFeedKey00"),
        ("https://cal.example.com/feed.ics?key=notARealFeedKey00", "notARealFeedKey00"),
    ],
)
def test_ical_url_path_and_query_are_masked(url, secret):
    out = redact_sensitive(f'HTTP Request: GET {url} "HTTP/1.1 200 OK"')
    assert secret not in out
    assert ".ics" not in out
    assert "HTTP/1.1 200 OK" in out


def test_ordinary_urls_are_not_touched():
    line = "GET https://api.nexus.dynaminds.pl/api/health HTTP/1.1 200"
    assert redact_sensitive(line) == line


@pytest.mark.parametrize(
    "line, leaked",
    [
        (
            '1.2.3.4:5 - "GET /api/candidates/check-exists?email=jan%40firma.pl HTTP/1.1" 200',
            "jan%40firma.pl",
        ),
        ("bounce for Jan.K%40Firma.PL", "Firma.PL"),
        (
            '1.2.3.4:5 - "GET /api/candidates?q=Jan%20Kowalski&page=2 HTTP/1.1" 200',
            "Kowalski",
        ),
        (
            '1.2.3.4:5 - "GET /api/candidates?page=2&phone=%2B48601234567 HTTP/1.1" 200',
            "601234567",
        ),
        (
            '1.2.3.4:5 - "GET /api/candidates?q_all=kowalsk*&x=1 HTTP/1.1" 200',
            "kowalsk",
        ),
    ],
)
def test_access_log_query_pii_is_masked(line, leaked):
    out = redact_sensitive(line)
    assert leaked not in out


def test_access_log_keeps_harmless_params():
    out = redact_sensitive(
        '"GET /api/candidates?q=Jan&page=2&sort=newest HTTP/1.1" 200'
    )
    assert "page=2" in out and "sort=newest" in out
    assert "HTTP/1.1" in out
    assert "q=Jan" not in out


async def test_ical_http_error_is_logged_without_url(monkeypatch, caplog):
    """HTTPStatusError niesie adres w treści — log ma mieć tylko kod HTTP i klasę."""
    url = "https://cal.example.com/private/notARealFeedKey00/feed.ics"

    async def boom(_url):
        request = httpx.Request("GET", _url)
        response = httpx.Response(404, request=request)
        raise httpx.HTTPStatusError(
            f"Client error '404' for url '{_url}'", request=request, response=response
        )

    monkeypatch.setattr(ii, "_fetch_ical_safely", boom)

    with caplog.at_level(logging.DEBUG, logger=ii.logger.name):
        res = await ii.import_ical_url(object(), url, creator_id=1)

    assert res.errors == 1
    assert "notARealFeedKey00" not in " ".join(res.error_samples)
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "notARealFeedKey00" not in logged
    assert "404" in logged
    assert "HTTPStatusError" in logged
    # traceback HTTPStatusError też niesie adres — nie może jechać do logu (ani Sentry)
    assert not any(r.exc_info for r in caplog.records)
