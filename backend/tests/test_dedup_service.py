"""Unit tests for dedup helpers (Phase 1)."""

from app.services import dedup_service as dd


# ── _normalize_email ─────────────────────────────────────────────────────────


def test_email_lowercased_and_trimmed():
    assert dd._normalize_email("  JAN@mail.pl ") == "jan@mail.pl"


def test_email_none_returns_none():
    assert dd._normalize_email(None) is None


def test_email_empty_returns_none():
    assert dd._normalize_email("  ") is None


# ── _normalize_phone ─────────────────────────────────────────────────────────


def test_phone_digits_only_last_9():
    assert dd._normalize_phone("+48 500-100-200") == "500100200"


def test_phone_matches_same_number_different_formats():
    a = dd._normalize_phone("+48 500 100 200")
    b = dd._normalize_phone("0048-500.100.200")
    c = dd._normalize_phone("500100200")
    assert a == b == c == "500100200"


def test_phone_short_number_returned_as_is():
    assert dd._normalize_phone("1234") == "1234"


def test_phone_none_returns_none():
    assert dd._normalize_phone(None) is None


# ── _normalize_name ──────────────────────────────────────────────────────────


def test_name_lowercased_and_trimmed():
    assert dd._normalize_name("  Jan  ") == "jan"


def test_name_none_returns_none():
    assert dd._normalize_name(None) is None


# ── _linkedin_slug ───────────────────────────────────────────────────────────


def test_linkedin_slug_from_full_url():
    assert dd._linkedin_slug("https://linkedin.com/in/jan-kowalski/") == "jan-kowalski"


def test_linkedin_slug_preserves_trailing_slash_behavior():
    assert (
        dd._linkedin_slug("https://www.linkedin.com/in/jan-kowalski") == "jan-kowalski"
    )


def test_linkedin_slug_case_insensitive():
    assert dd._linkedin_slug("https://linkedin.com/in/Jan-Kowalski") == "jan-kowalski"


def test_linkedin_slug_empty_returns_none():
    assert dd._linkedin_slug(None) is None
    assert dd._linkedin_slug("  ") is None
