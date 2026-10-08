"""Priorytet rekrutacji w trzech poziomach (decyzja Artura 02.10.2026).

Kolumna ``jobs.priority`` ma cztery wartości (``low``/``medium``/``high``/
``urgent``), a od 22.09.2026 nie było jej na żadnym ekranie — każda rekrutacja
miała ``medium``. Wraca w trzech poziomach, tak jak zespół prowadził to
w Traffit („P1 – URGENT”, „WILL ACCEPT CANDIDATES”):

* ``p1`` — „P1 Pilne”: ``urgent`` (i historyczne ``high``); pierwsze w kolejce
  automatu przydziału i na górze sortowania „Wymaga uwagi”;
* ``p2`` — „P2 Standard”: ``medium``; tak czyta się też wartość pustą
  i nieznaną;
* ``accepting`` — „Przyjmujemy kandydatów”: ``low``; nie szukamy aktywnie,
  więc automat nikogo do takiego requestu nie proponuje.

Ekrany i filtry mówią poziomami, baza zostaje przy enumie (bez migracji).

Nowa rekrutacja zaczyna od P1 (decyzja Artura 08.10.2026, do tej daty P2):
``default_priority_for_new_job`` jest domyślną wartością ``POST /api/jobs``,
a ``/jobs/new`` zaznacza ten sam poziom (``NEW_JOB_PRIORITY_LEVEL`` w
``frontend/src/lib/request-priority.ts``). Priorytet nie spada sam — zmienia go
człowiek. Domyślna kolumny w modelu zostaje ``medium``: rekrutacje z importu
Traffita są archiwum, nie nowymi requestami.
"""

from __future__ import annotations

from typing import Iterable, Literal, Optional

from sqlalchemy import case

from app.models.job import Job, JobPriority

PriorityLevel = Literal["p1", "p2", "accepting"]

PRIORITY_LEVELS: tuple[str, ...] = ("p1", "p2", "accepting")

# Poziom, od którego zaczyna rekrutacja zakładana w NEXUSIE.
NEW_JOB_PRIORITY_LEVEL: PriorityLevel = "p1"

_VALUES_BY_LEVEL: dict[str, tuple[JobPriority, ...]] = {
    "p1": (JobPriority.urgent, JobPriority.high),
    "p2": (JobPriority.medium,),
    "accepting": (JobPriority.low,),
}

_LEVEL_BY_VALUE: dict[str, str] = {
    value.value: level for level, values in _VALUES_BY_LEVEL.items() for value in values
}


def default_priority_for_new_job() -> JobPriority:
    """Wartość kolumny dla rekrutacji zakładanej bez podanego priorytetu."""
    return _VALUES_BY_LEVEL[NEW_JOB_PRIORITY_LEVEL][0]


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
