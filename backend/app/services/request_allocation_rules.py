"""Zasady automatu przydziału requestów — edytowane w Ustawieniach.

Dwie liczby, które Artur chce zmieniać bez deployu:

* ``sourcer_threshold`` — od ilu pasujących osób w bazie wystarczy sam
  sourcer (poniżej idzie rekruter, bo będzie szukał na LinkedInie);
* ``review_time`` — o której (czas warszawski) automat robi codzienny pełny
  przegląd przydziałów, przed daily.

Trzymane w ``app_settings['request_allocation_rules']``. Brak wiersza =
wartości domyślne, więc świeża baza działa bez konfiguracji.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import time
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting

RULES_KEY = "request_allocation_rules"
_TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


@dataclass(frozen=True)
class AllocationRules:
    sourcer_threshold: int = 15
    review_time: str = "08:30"

    @property
    def review_clock(self) -> time:
        hour, minute = self.review_time.split(":")
        return time(int(hour), int(minute))

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_rules(value: Optional[dict[str, Any]]) -> AllocationRules:
    """Odczyt łagodny — zepsuta wartość w bazie daje domyślną, nie 500."""
    defaults = AllocationRules()
    value = value or {}
    threshold = value.get("sourcer_threshold")
    review = value.get("review_time")
    return AllocationRules(
        sourcer_threshold=(
            threshold
            if isinstance(threshold, int) and 1 <= threshold <= 500
            else defaults.sourcer_threshold
        ),
        review_time=(
            review
            if isinstance(review, str) and _TIME.match(review)
            else defaults.review_time
        ),
    )


def validate_rules(value: dict[str, Any]) -> AllocationRules:
    """Zapis ścisły — błąd po polsku zamiast cichej wartości domyślnej."""
    threshold = value.get("sourcer_threshold")
    review = value.get("review_time")
    if (
        isinstance(threshold, bool)
        or not isinstance(threshold, int)
        or not 1 <= threshold <= 500
    ):
        raise ValueError("Próg bazy musi być liczbą od 1 do 500.")
    if not isinstance(review, str) or not _TIME.match(review):
        raise ValueError("Godzina przeglądu musi mieć postać GG:MM, np. 08:30.")
    return AllocationRules(sourcer_threshold=threshold, review_time=review)


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
