"""Warunek „para jest na liście” dla listy dowolnej długości."""

from __future__ import annotations

from typing import Any, Sequence

from sqlalchemy import ARRAY, ColumnElement, Integer, func, literal, select, tuple_


def in_pairs(
    first_column: Any, second_column: Any, pairs: Sequence[tuple[int, int]]
) -> ColumnElement[bool]:
    """`(a, b) IN` z listą par podaną dwiema tablicami przez `unnest`.

    `(a, b) IN ((…), (…))` Postgres rozwija w zagnieżdżone OR i powyżej 6–8 tys.
    par kończy się `stack depth limit exceeded` (500 na tablicy rekrutacji 3413
    z 14 679 kartami, 09.11.2026). Dwie tablice nie zmieniają głębokości
    zapytania, więc liczba par przestaje mieć znaczenie.
    """
    listed = (
        func.unnest(
            literal([first for first, _ in pairs], type_=ARRAY(Integer)),
            literal([second for _, second in pairs], type_=ARRAY(Integer)),
        )
        .table_valued("first_value", "second_value")
        .render_derived(name="wanted_pairs")
    )
    return tuple_(first_column, second_column).in_(
        select(listed.c.first_value, listed.c.second_value)
    )
