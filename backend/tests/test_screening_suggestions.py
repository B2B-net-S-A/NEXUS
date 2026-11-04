"""Podpowiedź stawki z notatek do formularza screeningu (R3, 17.10.2026).

Ekstrakcja notatek zostawia kwotę bez jednostki, gdy rekruter napisał
„Stawka: 90”. Ta sama reguła co karta rekomendacji (`parse_rate`) czyta takie
„90” jako PLN/h — tylko gdy wynik zgadza się z kwotą z ekstrakcji.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.screening_suggestions import suggestions_from_notes


def _candidate(rate: dict) -> SimpleNamespace:
    return SimpleNamespace(
        cv_extracted_data={
            "_notes_insights": {
                "expected_rate": rate,
                "_extracted_at": "2026-10-09T04:34:02+00:00",
            }
        }
    )


@pytest.mark.parametrize("raw", ["Stawka: 90", "90", "90 zł", "ok. 90 netto"])
def test_rate_without_unit_reads_like_card(raw):
    out = suggestions_from_notes(
        _candidate({"value": 90.0, "period": None, "currency": None, "raw": raw}),
        include_rate=True,
    )
    assert (out["rate"]["value"], out["rate"]["unit"], out["rate"]["currency"]) == (
        90.0,
        "hour",
        "PLN",
    )


@pytest.mark.parametrize(
    "rate",
    [
        # Ekstrakcja mówi co innego niż tekst — nie zgadujemy.
        {"value": 95.0, "period": None, "currency": None, "raw": "Stawka: 90"},
        # Kwota miesięczna zostaje bez jednostki.
        {"value": 14000.0, "period": None, "currency": "PLN", "raw": "14 000 zł netto"},
        # Inna waluta.
        {"value": 90.0, "period": None, "currency": "EUR", "raw": "90 EUR"},
        # Bez tekstu źródłowego.
        {"value": 90.0, "period": None, "currency": None, "raw": None},
    ],
)
def test_rate_that_would_need_guessing_keeps_no_unit(rate):
    out = suggestions_from_notes(_candidate(rate), include_rate=True)
    assert out["rate"]["unit"] is None


def test_rate_with_unit_is_unchanged():
    out = suggestions_from_notes(
        _candidate(
            {"value": 1200.0, "period": "md", "currency": "PLN", "raw": "1200/MD"}
        ),
        include_rate=True,
    )
    assert (out["rate"]["unit"], out["rate"]["currency"]) == ("day", "PLN")
