"""„datePosted” strony kariery to dzień kalendarza firmy, nie data UTC
(audyt 22.10.2026, F63; reguła „dziś = Europe/Warsaw” z CLAUDE.md)."""

from datetime import datetime, timezone

from app.api.public_career import _published_on


def test_approval_after_midnight_in_warsaw_is_dated_by_the_company_calendar():
    # 22.10.2026, 00:30 w Warszawie = 21.10.2026, 22:30 UTC.
    approved_at = datetime(2026, 10, 21, 22, 30, tzinfo=timezone.utc)
    assert _published_on(approved_at) == "2026-10-22"


def test_daytime_approval_keeps_the_same_day():
    approved_at = datetime(2026, 10, 22, 10, 0, tzinfo=timezone.utc)
    assert _published_on(approved_at) == "2026-10-22"


def test_never_approved_has_no_date():
    assert _published_on(None) is None
