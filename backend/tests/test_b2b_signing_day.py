"""Dzień podpisu umowy B2B z okna „Oznacz jako podpisaną” (0514) — bez bazy.

``signing_day_or_reject`` pilnuje pola „Data podpisu”: domyślnie dziś
w kalendarzu firmy, nie z przyszłości, nie sprzed dnia wygenerowania umowy.
Przebieg całej trasy z bazą sprawdza ``test_b2b_signature_automation.py``.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.api import b2b_contract_generator
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


@pytest.mark.parametrize(
    ("generated", "generated_on"),
    [
        # Lato (UTC+2): 22:45 UTC = 00:45 następnego dnia w Warszawie.
        (datetime(2026, 7, 15, 22, 45, tzinfo=timezone.utc), date(2026, 7, 16)),
        # Zima (UTC+1): 22:45 UTC = 23:45, nadal ten sam dzień.
        (datetime(2026, 11, 10, 22, 45, tzinfo=timezone.utc), date(2026, 11, 10)),
        (datetime(2026, 11, 10, 23, 30, tzinfo=timezone.utc), date(2026, 11, 11)),
        # Dzień zmiany czasu 25.10.2026: wieczorem już UTC+1.
        (datetime(2026, 10, 25, 22, 45, tzinfo=timezone.utc), date(2026, 10, 25)),
        (datetime(2026, 10, 25, 23, 30, tzinfo=timezone.utc), date(2026, 10, 26)),
        # Wiosenna zmiana 29.03.2026: wieczorem już UTC+2.
        (datetime(2026, 3, 29, 22, 15, tzinfo=timezone.utc), date(2026, 3, 30)),
    ],
)
def test_generation_day_is_the_warsaw_calendar_day(
    monkeypatch, generated, generated_on
):
    """Dzień wygenerowania liczy się w kalendarzu warszawskim, nie UTC —
    dzień UTC byłby latem o jeden za wcześnie i przepuścił podpis z dnia przed
    wygenerowaniem. Stałe daty, bo wersja liczona od ``business_today()``
    padała po zmianie czasu 25.10.2026."""
    monkeypatch.setattr(
        b2b_contract_generator,
        "business_today",
        lambda: generated_on + timedelta(days=2),
    )
    row = _row(generated)
    assert business_date(generated) == generated_on
    with pytest.raises(HTTPException):
        signing_day_or_reject(row, generated_on - timedelta(days=1))
    assert signing_day_or_reject(row, generated_on) == generated_on
