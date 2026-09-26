"""Runda 8: wyszukiwanie adresu e-mail w CV ma czas liniowy (ReDoS)."""

import time

from app.services.cv_parser import _EMAIL_RE


def test_email_regex_is_linear_on_long_text_without_at_sign():
    for text in ("a" * 16000, "a" * 8000 + "@" + "b" * 8000, "a.b" * 5000):
        started = time.perf_counter()
        _EMAIL_RE.search(text)
        assert time.perf_counter() - started < 0.05


def test_email_regex_still_finds_the_address():
    assert _EMAIL_RE.search("Kontakt: jan.kowalski+cv@firma.pl, tel").group() == "jan.kowalski+cv@firma.pl"
    assert _EMAIL_RE.search("mail:a_b-c%d@sub.domena.com.pl.").group() == "a_b-c%d@sub.domena.com.pl"
    assert _EMAIL_RE.search("brak adresu") is None
