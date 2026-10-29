"""Zasady automatu przydziału requestów — edytowane w Ustawieniach.

Ustawienia → Zespół rekrutacji → „Automat przydziału” (decyzja Artura
29.10.2026, wariant B z makiet: administrator i Head of Recruitment zmieniają
zasady bez deployu, obok widzą skutki na dzisiejszych danych).

* ``review_time`` — o której (czas warszawski) automat robi codzienny pełny
  przegląd przydziałów, przed daily.
* ``include_p2`` — automat dobiera ludzi także do rekrutacji P2 (P0 i P1
  zawsze, „Przyjmujemy kandydatów” nigdy).
* ``people_per_p1`` — ilu rekruterów automat chce mieć przy rekrutacji P0/P1.
* ``max_load`` — najwięcej rekrutacji P1 na osobę; kto ma tyle, nie dostaje
  nowej (``None`` = bez limitu).
* ``overflow`` — o ile najmniej obłożona osoba z kategorii może mieć więcej
  rekrutacji P1 niż najmniej obłożona w zespole, zanim automat weźmie kogoś
  z innej kategorii.
* ``outsiders`` — czy osoba bez kategorii rekrutacji może ją dostać, gdy
  w 1. i 2. priorytecie nie ma nikogo.
* ``order`` — którą rekrutację obsadzić najpierw.
* ``leave_policy`` — co robi tryb „Przydziela sam”, gdy urlopy z Compassa są
  nieaktualne.

**Zasady działają tylko na nowe przydziały** (Artur 29.10.2026: „nic nie
zmieniaj w tych, co są już przydzielone”). Żadna z nich nie zwalnia osoby,
która już pracuje przy rekrutacji.

Trzymane w ``app_settings['request_allocation_rules']``. Brak wiersza albo
brak klucza = wartości domyślne, czyli zachowanie sprzed 29.10.2026. Do 0411
był tu też próg ``sourcer_threshold`` — zniknął razem z rolą sourcera; stary
klucz w zapisanej wartości jest ignorowany.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, fields
from datetime import time
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting

RULES_KEY = "request_allocation_rules"
_TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

PEOPLE_PER_P1 = (1, 2, 3)
MAX_LOAD_RANGE = (1, 30)
OVERFLOW_RANGE = (0, 3)
ORDERS = ("sent_first", "deadline_first")
LEAVE_POLICIES = ("wait", "ignore")


@dataclass(frozen=True)
class AllocationRules:
    review_time: str = "08:30"
    include_p2: bool = False
    people_per_p1: int = 1
    max_load: Optional[int] = None
    overflow: int = 1
    outsiders: bool = True
    order: str = "sent_first"
    leave_policy: str = "wait"

    @property
    def review_clock(self) -> time:
        hour, minute = self.review_time.split(":")
        return time(int(hour), int(minute))

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


_DEFAULTS = AllocationRules()


def _int_in(value: Any, low: int, high: int) -> bool:
    return (
        isinstance(value, int) and not isinstance(value, bool) and low <= value <= high
    )


def _checks() -> dict[str, tuple[Any, str]]:
    """Pole → (czy wartość poprawna, komunikat dla zapisu)."""
    return {
        "review_time": (
            lambda v: isinstance(v, str) and bool(_TIME.match(v)),
            "Godzina przeglądu musi mieć postać GG:MM, np. 08:30.",
        ),
        "include_p2": (
            lambda v: isinstance(v, bool),
            "Pole „P2” musi być tak albo nie.",
        ),
        "people_per_p1": (
            lambda v: _int_in(v, PEOPLE_PER_P1[0], PEOPLE_PER_P1[-1]),
            "Osób na rekrutację P1: od 1 do 3.",
        ),
        "max_load": (
            lambda v: v is None or _int_in(v, *MAX_LOAD_RANGE),
            f"Limit na osobę: od {MAX_LOAD_RANGE[0]} do {MAX_LOAD_RANGE[1]} albo bez limitu.",
        ),
        "overflow": (
            lambda v: _int_in(v, *OVERFLOW_RANGE),
            "Różnica obłożenia przy innej kategorii: od 0 do 3.",
        ),
        "outsiders": (
            lambda v: isinstance(v, bool),
            "Pole „osoby bez kategorii” musi być tak albo nie.",
        ),
        "order": (lambda v: v in ORDERS, "Nieznana kolejność obsadzania."),
        "leave_policy": (
            lambda v: v in LEAVE_POLICIES,
            "Nieznane zachowanie przy nieaktualnych urlopach.",
        ),
    }


def parse_rules(value: Optional[dict[str, Any]]) -> AllocationRules:
    """Odczyt łagodny — zepsuta wartość w bazie daje domyślną, nie 500."""
    value = value or {}
    out: dict[str, Any] = {}
    for name, (ok, _message) in _checks().items():
        raw = value.get(name, getattr(_DEFAULTS, name))
        out[name] = raw if ok(raw) else getattr(_DEFAULTS, name)
    return AllocationRules(**out)


def validate_rules(value: dict[str, Any]) -> AllocationRules:
    """Zapis ścisły — błąd po polsku zamiast cichej wartości domyślnej.

    Brak pola = wartość domyślna (stary front wysyła samo ``review_time``).
    """
    out: dict[str, Any] = {}
    for name, (ok, message) in _checks().items():
        raw = value.get(name, getattr(_DEFAULTS, name))
        if not ok(raw):
            raise ValueError(message)
        out[name] = raw
    return AllocationRules(**out)


def changed_fields(before: AllocationRules, after: AllocationRules) -> dict[str, Any]:
    """Pola, które zapis zmienia: ``{pole: [przed, po]}`` — do historii."""
    return {
        f.name: [getattr(before, f.name), getattr(after, f.name)]
        for f in fields(AllocationRules)
        if getattr(before, f.name) != getattr(after, f.name)
    }


async def load_rules(db: AsyncSession) -> AllocationRules:
    row = await db.scalar(select(AppSetting).where(AppSetting.key == RULES_KEY))
    return parse_rules(row.value if row else None)


async def save_rules(
    db: AsyncSession, rules: AllocationRules, *, user_id: Optional[int]
) -> AllocationRules:
    row = await db.scalar(
        select(AppSetting).where(AppSetting.key == RULES_KEY).with_for_update()
    )
    if row is None:
        db.add(AppSetting(key=RULES_KEY, value=rules.as_dict(), updated_by=user_id))
    else:
        row.value = rules.as_dict()
        row.updated_by = user_id
    await db.flush()
    return rules
