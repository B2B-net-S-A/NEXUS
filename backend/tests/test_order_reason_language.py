"""Powody niepewności odczytu zamówienia są po polsku (UAT B77).

Wierszowy `uncertain_reason` modelu wracał po angielsku i kolejka poczty
zamówień pokazywała „Odczyt niepewny: kept as printed.”.
"""

import pytest

from app.services.order_pdf_parser import (
    MODEL_REASON_FALLBACK_PL,
    _normalize,
    _polish_model_reason,
    polish_gate_reason,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "reason",
    ["kept as printed", "Gross/net not marked", "Name-to-rate binding is ambiguous"],
)
def test_english_model_reason_becomes_polish_hint(reason):
    assert _polish_model_reason(reason) == MODEL_REASON_FALLBACK_PL


@pytest.mark.parametrize(
    "reason",
    [
        "Nie znaleziono jednoznacznej daty końca",
        "Stawka bez oznaczenia netto/brutto",
        "Brak daty konca",
        "Okres rate w wierszu",
    ],
)
def test_polish_reasons_are_kept_verbatim(reason):
    assert _polish_model_reason(reason) == reason


def test_row_and_top_level_reasons_are_normalised_at_parse_time():
    extraction = _normalize(
        {
            "title": "ZAM/1",
            "uncertain": True,
            "uncertain_reasons": ["kept as printed", "Nie znaleziono daty końca"],
            "consultant_rows": [
                {"consultant_name": "Jan Nowak", "uncertain": True, "uncertain_reason": "kept as printed"}
            ],
        },
        source="claude",
    )
    assert extraction.consultant_rows[0].uncertain_reason == MODEL_REASON_FALLBACK_PL
    assert extraction.consultant_rows[0].uncertain is True
    assert MODEL_REASON_FALLBACK_PL in extraction.uncertain_reasons
    assert "kept as printed" not in extraction.uncertain_reasons


def test_stored_gate_reason_is_shown_in_polish():
    assert polish_gate_reason("Odczyt niepewny: kept as printed.") == (
        f"Odczyt niepewny: {MODEL_REASON_FALLBACK_PL}"
    )
    assert polish_gate_reason("Odczyt niepewny: brak daty") == "Odczyt niepewny: brak daty"
    assert polish_gate_reason("Tekst dokumentu ucięty przed odczytem") == (
        "Tekst dokumentu ucięty przed odczytem"
    )
