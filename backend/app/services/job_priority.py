"""Priorytet rekrutacji w trzech poziomach (decyzja Artura 02.10.2026).

Kolumna ``jobs.priority`` ma cztery wartości (``low``/``medium``/``high``/
``urgent``), a od 22.09.2026 nie było jej na żadnym ekranie — każda rekrutacja
miała ``medium``. Wraca w trzech poziomach, tak jak zespół prowadził to
w Traffit („P1 – URGENT”, „WILL ACCEPT CANDIDATES”):

* ``p1`` — „P1 Pilne”: ``urgent`` (i historyczne ``high``); pierwsze w kolejce
  automatu przydziału i na górze sortowania „Wymaga uwagi”;
* ``p2`` — „P2 Standard”: ``medium``, stan domyślny;
* ``accepting`` — „Przyjmujemy kandydatów”: ``low``; nie szukamy aktywnie,
  więc automat nikogo do takiego requestu nie proponuje.

Ekrany i filtry mówią poziomami, baza zostaje przy enumie (bez migracji).
"""

from __future__ import annotations

from typing import Iterable, Literal, Optional

from sqlalchemy import case

from app.models.job import Job, JobPriority

PriorityLevel = Literal["p1", "p2", "accepting"]

PRIORITY_LEVELS: tuple[str, ...] = ("p1", "p2", "accepting")

_VALUES_BY_LEVEL: dict[str, tuple[JobPriority, ...]] = {
    "p1": (JobPriority.urgent, JobPriority.high),
    "p2": (JobPriority.medium,),
    "accepting": (JobPriority.low,),
}

_LEVEL_BY_VALUE: dict[str, str] = {
    value.value: level for level, values in _VALUES_BY_LEVEL.items() for value in values
}


def _value(priority: object) -> str:
    return str(getattr(priority, "value", priority) or "")


def level_of(priority: object) -> str:
    """Poziom dla wartości kolumny; nieznana albo pusta = ``p2``."""
    return _LEVEL_BY_VALUE.get(_value(priority), "p2")


def priorities_for_levels(levels: Iterable[str]) -> list[JobPriority]:
    """Wartości kolumny dla wybranych poziomów (filtr listy)."""
    out: list[JobPriority] = []
    for level in levels:
        for value in _VALUES_BY_LEVEL.get(level, ()):
            if value not in out:
                out.append(value)
    return out


def priority_rank(priority: object) -> int:
    """0 = P1, 1 = reszta — kolejność automatu przydziału."""
    return 0 if level_of(priority) == "p1" else 1


def is_passive(priority: object) -> bool:
    """„Przyjmujemy kandydatów” — automat nikogo nie proponuje."""
    return level_of(priority) == "accepting"


def priority_rank_expr(column: Optional[object] = None):
    """To samo co ``priority_rank`` w SQL (sortowanie „Wymaga uwagi”)."""
    target = Job.priority if column is None else column
    return case((target.in_(_VALUES_BY_LEVEL["p1"]), 0), else_=1)
