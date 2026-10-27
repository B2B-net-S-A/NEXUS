"""Dzień podpisu umowy B2B z okna „Oznacz jako podpisaną” (0514) — bez bazy.

``signing_day_or_reject`` pilnuje pola „Data podpisu”: domyślnie dziś
w kalendarzu firmy, nie z przyszłości, nie sprzed dnia wygenerowania umowy.
Przebieg całej trasy z bazą sprawdza ``test_b2b_signature_automation.py``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.api.b2b_contract_generator import signing_day_or_reject
from app.core.scheduling import business_date, business_today
from app.models.b2b_generated_contract import B2BGeneratedContract


def _row(created_at: datetime | None) -> B2BGeneratedContract:
    return B2BGeneratedContract(contract_number="1/2099", created_at=created_at)


def test_without_a_date_the_signing_day_is_today_in_warsaw():
    row = _row(datetime.now(timezone.utc) - timedelta(days=10))
    assert signing_day_or_reject(row, None) == business_today()


def test_a_past_day_after_generation_is_kept():
    row = _row(datetime.now(timezone.utc) - timedelta(days=10))
    day = business_today() - timedelta(days=3)
    assert signing_day_or_reject(row, day) == day


def test_the_generation_day_itself_is_allowed():
    generated = datetime.now(timezone.utc) - timedelta(days=4)
    row = _row(generated)
    day = business_date(generated)
    assert signing_day_or_reject(row, day) == day


def test_a_future_day_is_refused():
    row = _row(datetime.now(timezone.utc) - timedelta(days=10))
    with pytest.raises(HTTPException) as exc:
        signing_day_or_reject(row, business_today() + timedelta(days=1))
    assert exc.value.status_code == 422
    assert "z przyszłości" in exc.value.detail


def test_a_day_before_the_contract_was_generated_is_refused():
    generated = datetime.now(timezone.utc) - timedelta(days=4)
    row = _row(generated)
    with pytest.raises(HTTPException) as exc:
        signing_day_or_reject(row, business_today() - timedelta(days=6))
    assert exc.value.status_code == 422
    assert "wcześniejsza niż wygenerowanie umowy" in exc.value.detail


def test_generation_just_after_midnight_in_warsaw_counts_as_that_day():
    """23:30 UTC to już następny dzień w Warszawie (UTC+1 zimą, UTC+2 latem)
    — dzień UTC byłby o jeden za wcześnie i przepuścił podpis z dnia przed
    wygenerowaniem. Do 27.10.2026 stało tu 22:45 UTC: następny dzień tylko
    latem, więc po zmianie czasu 25.10 test padał codziennie."""
    today = business_today()
    two_days_ago = today - timedelta(days=2)
    generated = datetime(
        two_days_ago.year,
        two_days_ago.month,
        two_days_ago.day,
        23,
        30,
        tzinfo=timezone.utc,
    )
    row = _row(generated)
    generated_on = business_date(generated)
    assert generated_on == today - timedelta(days=1)
    with pytest.raises(HTTPException):
        signing_day_or_reject(row, two_days_ago)
    assert signing_day_or_reject(row, generated_on) == generated_on
