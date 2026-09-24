"""Audyt 24.09.2026 (S7): numer zamówienia z samych cyfr bez zer wiodących.

Excel zapisuje numer zamówienia jako liczbę i obcina zera wiodące — na
produkcji wiersz 546 z „87020188" nie trafił w zamówienie „0087020188".
Porównanie numerów czysto cyfrowych idzie po postaci bez zer, w obu
kierunkach; numery z literami i ukośnikami zostają porównywane dosłownie.
Czysty moduł — bez bazy.
"""

from __future__ import annotations

from app.services.finance_order_matching import (
    build_order_number_index,
    canonical_digits,
    explicit_order_hints,
    finance_order_number_matches,
)


def test_canonical_digits_strips_leading_zeros_only_from_pure_digits():
    assert canonical_digits("0087020188") == "87020188"
    assert canonical_digits("87020188") == "87020188"
    assert canonical_digits("000") == "0"
    assert canonical_digits("87_2026") is None
    assert canonical_digits("CeZ/45/2026") is None
    assert canonical_digits(None) is None


def test_matching_ignores_leading_zeros_in_both_directions():
    assert finance_order_number_matches(
        client_id=7, order_number="0087020188", numeric_hints=["87020188"]
    )
    assert finance_order_number_matches(
        client_id=7, order_number="87020188", numeric_hints=["0087020188"]
    )
    assert not finance_order_number_matches(
        client_id=7, order_number="0087020188", numeric_hints=["87020189"]
    )


def test_non_numeric_numbers_stay_exact():
    assert not finance_order_number_matches(
        client_id=7, order_number="087_2026", numeric_hints=["87"]
    )


def test_explicit_hint_without_zeros_binds_the_stored_number():
    bik = 18
    index = build_order_number_index([(bik, "0087020188")])
    assert explicit_order_hints(["87020188"], index, {bik}) == ["87020188"]
    index = build_order_number_index([(bik, "87020188")])
    assert explicit_order_hints(["0087020188"], index, {bik}) == ["0087020188"]
