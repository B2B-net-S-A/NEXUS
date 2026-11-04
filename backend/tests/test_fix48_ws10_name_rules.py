"""Reguła dopisków w imieniu po audycie 13.10.2026 (WS10) — bez bazy.

- „(nie aktywny)” i „[not active]” to NIE „szuka aktywnie”;
- wielowyrazowy nawias z „czarną listą” ustawia status, nie tylko znika;
- zdanie 422 wskazuje pola, które naprawdę są w oknie („Dyspozycyjność”;
  czarna lista od 17.10.2026 w menu profilu), a nie pole „Dostępność”,
  które jest datą.

Imiona są wymyślone (repo jest publiczne).
"""

from __future__ import annotations

import pytest

from app.services.candidate_name_rules import (
    has_active_marker,
    has_blacklist_marker,
    name_marker_message,
    strip_name_markers,
)


@pytest.mark.parametrize(
    "value",
    [
        "Testowy (dodany do czarnej listy przez klienta)",
        "Testowy (klient: czarna lista, nie proponować)",
        "[na czarnej liście u klienta - czarna lista] Jan",
    ],
)
def test_multi_word_bracket_with_blacklist_sets_the_status(value: str) -> None:
    assert strip_name_markers(value)[1], "nawias i tak znika z imienia"
    assert has_blacklist_marker(value) is True


def test_stripped_multi_word_marker_is_read_as_blacklist_too() -> None:
    # Korekta 0436 woła regułę na zdjętych dopiskach, nie na imieniu.
    markers = strip_name_markers("Testowy (dodany do czarnej listy przez klienta)")[1]
    assert has_blacklist_marker(*markers) is True


@pytest.mark.parametrize(
    "value",
    [
        "Blacklista",
        "Anna (Kowalska)",
        "Testowy (zaakceptowany)",
        "Testowy (nie aktywny)",
        "",
    ],
)
def test_surname_and_other_markers_are_not_a_blacklist(value: str) -> None:
    assert has_blacklist_marker(value) is False


@pytest.mark.parametrize(
    "markers",
    [
        ["(nie aktywny)"],
        ["[not active]"],
        ["(non active)"],
        ["(non-active)"],
        ["[NIE AKTYWNA]"],
        ["(nieaktywny)"],
        ["[inactive]"],
    ],
)
def test_negated_active_is_not_actively_looking(markers: list[str]) -> None:
    assert has_active_marker(markers) is False


@pytest.mark.parametrize(
    "markers", [["[ACTIVE]"], ["(aktywny)"], ["(aktywnie szuka)"], ["ACTIVE"]]
)
def test_plain_active_still_means_actively_looking(markers: list[str]) -> None:
    assert has_active_marker(markers) is True


def test_422_message_points_to_the_fields_of_the_candidate_window() -> None:
    message = name_marker_message()
    # Okna „Dodaj kandydata” / „Edytuj dane” (AppShell): „Dostępność” to data,
    # „szuka aktywnie” ustawia się w „Dyspozycyjności”, czarną listę — od
    # 17.10.2026 oknem „Czarna lista…” w menu profilu (pola „Status” nie ma).
    assert "Dyspozycyjność" in message
    assert "„Czarna lista…”" in message
    assert "Zablokowany" not in message
    assert "polu Dostępność" not in message
