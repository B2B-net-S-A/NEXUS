"""Pure-unit tests for the matcher's non-DB helpers.

We test the synchronous helpers that don't require a database session — they
cover 80% of the matcher's logic. The async `match()` function itself is
covered by integration tests against a live DB (separate file).
"""

from __future__ import annotations

import pytest

from app.services.m365.matcher import (
    PUBLIC_EMAIL_DOMAINS,
    _contains_name,
    _email_domain,
    _fold_diacritics,
    _normalize_email,
)


def test_normalize_email_lowercases_and_trims() -> None:
    assert _normalize_email("  Foo@Bar.COM ") == "foo@bar.com"


def test_normalize_email_empty() -> None:
    assert _normalize_email("") == ""
    assert _normalize_email(None) == ""  # type: ignore[arg-type]


def test_email_domain_plain() -> None:
    assert _email_domain("jan@b2bnet.pl") == "b2bnet.pl"


def test_email_domain_missing_at_returns_none() -> None:
    assert _email_domain("not-an-email") is None


def test_email_domain_mixed_case() -> None:
    assert _email_domain("Jan.Kowalski@Company.COM") == "company.com"


def test_public_domains_include_common_free_mail() -> None:
    for d in ["gmail.com", "wp.pl", "onet.pl", "interia.pl", "outlook.com"]:
        assert d in PUBLIC_EMAIL_DOMAINS


def test_fold_diacritics_pl() -> None:
    assert _fold_diacritics("Łąka żółw Kowalski") == "laka zolw kowalski"


def test_contains_name_order_flexibility() -> None:
    assert _contains_name("Re: CV Jan Kowalski", "Jan", "Kowalski") is True
    assert _contains_name("Re: Kowalski, Jan - senior dev", "Jan", "Kowalski") is True


def test_contains_name_diacritics() -> None:
    assert _contains_name("CV Łukasz Żółw", "Lukasz", "Zolw") is True


def test_contains_name_requires_both() -> None:
    assert _contains_name("Jan z ATS-u", "Jan", "Kowalski") is False


def test_contains_name_empty_subject() -> None:
    assert _contains_name("", "Jan", "Kowalski") is False
    assert _contains_name(None, "Jan", "Kowalski") is False  # type: ignore[arg-type]
