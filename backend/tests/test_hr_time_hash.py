"""Suma kontrolna timesheetu = funkcja Compassa co do bajtu.

Wektory policzono, WYKONUJĄC ``computeTimesheetHash`` z Compassa
(``lib/hr/timesheet-hash.ts``, HEAD ``e7f512b``) przez ``tsx`` na tych samych
fikcyjnych wpisach. Zaimportowany zaakceptowany timesheet z Compassa musi
dawać w NEXUSIE tę samą sumę — inaczej każdy jego PDF zgłosiłby rozbieżność.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.services.hr.time_hash import (
    HashEntry,
    canonical_text,
    compute_timesheet_hash,
    js_number_text,
    js_to_fixed_2,
)

VECTORS: dict[str, tuple[list[HashEntry], str]] = {
    "empty": (
        [],
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    ),
    "single": (
        [HashEntry("2026-10-01", 8, None, "Praca standardowa")],
        "d9f4a181d1c46adccc6be68ee1baa5048317dd5b1de1369f28bb1ca674da1763",
    ),
    "several": (
        [
            HashEntry("2026-10-05", 3.5, "Projekt Alfa", "Analiza wymagań"),
            HashEntry("2026-10-02", "8.00", None, "Praca standardowa"),
            HashEntry("2026-10-05", 4.5, "Projekt Beta", "Przegląd kodu"),
            HashEntry("2026-10-01", 7.25, "Projekt Alfa", "Spotkanie z zespołem"),
        ],
        "dc12cd1e5b982e700864eface925b39f13afcd8929213c07cef84528f10e5661",
    ),
    "polish": (
        [
            HashEntry(
                "2026-10-07", 6, None, "Ćwiczenia z obsługi zgłoszeń, łączenie świąt"
            ),
            HashEntry("2026-10-06", 8, "Wdrożenie", "Zażółć gęślą jaźń — źródła ŁĘCKI"),
        ],
        "40793ab7bf79eb5eb94d7ec6c1292e4d17e7bed924a67155f07ae0ab08c02318",
    ),
    "overtime": (
        [
            HashEntry("2026-10-08", 2.5, "Projekt Gamma", "Dyżur"),
            HashEntry("2026-10-09", 16, None, "Migracja danych w weekend"),
            HashEntry("2026-10-08", 12, "Projekt Gamma", "Wdrożenie po godzinach"),
        ],
        "f2a4b0c7ae0147c65642daafa4bd045d19269807c24b53e5820d8e06100a44fc",
    ),
}


@pytest.mark.parametrize("name", sorted(VECTORS))
def test_hash_matches_compass_reference_vector(name: str) -> None:
    entries, expected = VECTORS[name]
    assert compute_timesheet_hash(entries) == expected


def test_database_types_give_the_same_hash_as_json_numbers() -> None:
    """Wpisy z bazy (``date`` + ``Decimal`` z NUMERIC(4,2)) = te same wektory."""

    entries = [
        HashEntry(date(2026, 10, 8), Decimal("2.50"), "Projekt Gamma", "Dyżur"),
        HashEntry(
            date(2026, 10, 9), Decimal("16.00"), None, "Migracja danych w weekend"
        ),
        HashEntry(
            date(2026, 10, 8),
            Decimal("12.00"),
            "Projekt Gamma",
            "Wdrożenie po godzinach",
        ),
    ]
    assert compute_timesheet_hash(entries) == VECTORS["overtime"][1]


def test_same_day_order_compares_text_like_javascript() -> None:
    # „12|…” < „2.5|…” jako tekst — porządek liczbowy dałby inną sumę.
    text = canonical_text(VECTORS["overtime"][0])
    assert text.splitlines()[0].startswith("2026-10-08|12.00|")
    assert text.splitlines()[1].startswith("2026-10-08|2.50|")


@pytest.mark.parametrize(
    ("value", "number", "fixed"),
    [
        (Decimal("8.00"), "8", "8.00"),
        (Decimal("10.00"), "10", "10.00"),
        (Decimal("0.50"), "0.5", "0.50"),
        (Decimal("7.25"), "7.25", "7.25"),
        (7.5, "7.5", "7.50"),
        ("4", "4", "4.00"),
        (Decimal("0"), "0", "0.00"),
    ],
)
def test_number_formatting_follows_javascript(value, number: str, fixed: str) -> None:
    assert js_number_text(value) == number
    assert js_to_fixed_2(value) == fixed


def test_any_change_of_entries_changes_the_hash() -> None:
    base = [HashEntry("2026-10-01", 8, None, "Praca standardowa")]
    original = compute_timesheet_hash(base)
    assert (
        compute_timesheet_hash(
            [HashEntry("2026-10-01", 7.5, None, "Praca standardowa")]
        )
        != original
    )
    assert (
        compute_timesheet_hash([HashEntry("2026-10-01", 8, "", "Praca standardowa ")])
        != original
    )
