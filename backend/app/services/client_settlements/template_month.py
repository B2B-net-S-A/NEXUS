"""Raport z szablonu innego miesiąca: kiedy układ godzin dowodzi rozliczanego
miesiąca. Bez bazy.

Decyzja Artura z 25.11.2026: kosmetyka raportu przy dobrym MD (sumy, daty,
szablon przy dobrych datach) nie zatrzymuje automatu „Bez uwag”, ale zostaje na
karcie jako informacja i daje konsultantowi informację zwrotną. Dowód, że plik
jest za rozliczany miesiąc, a nie za miesiąc z szablonu: dni z godzinami to dni
robocze rozliczanego miesiąca, a choć jeden z nich nie jest dniem roboczym
miesiąca z szablonu (wzór ``timesheet.template_year_fixed``). Plik, który
pasuje do obu kalendarzy, niczego nie dowodzi i zostaje uwagą jak dotąd.
"""

from __future__ import annotations

import calendar
import re
from datetime import date
from decimal import Decimal
from functools import lru_cache
from typing import Iterable, Optional

from app.services.person_workdays import business_days

TOLERANCE = Decimal("0.01")
_MONTH = re.compile(r"\d{4}-(0[1-9]|1[0-2])")


@lru_cache(maxsize=64)
def workdays(month: str) -> frozenset[int]:
    """Numery dni roboczych miesiąca ``RRRR-MM`` (bez weekendów i świąt)."""

    year, number = int(month[:4]), int(month[5:7])
    last = calendar.monthrange(year, number)[1]
    return frozenset(
        day.day
        for day in business_days(date(year, number, 1), date(year, number, last))
    )


def days_fit(days: Iterable[int], month: str, template: Optional[str] = None) -> bool:
    """Dni z godzinami to dni robocze ``month``; przy ``template`` (miesiąc
    z szablonu) choć jeden z nich nie jest dniem roboczym ``template``."""

    worked = frozenset(days)
    if not worked or not worked <= workdays(month):
        return False
    if template is None:
        return True
    return bool(_MONTH.fullmatch(template)) and not worked <= workdays(template)


def full_month(hours: Decimal, per_md: Decimal, month: str, template: str) -> bool:
    """Szablon bez kolumn dni (starszy Time Sheet PKO): godziny to pełny rozliczany
    miesiąc (dni robocze × godziny MD), a nie pełny miesiąc z szablonu."""

    if per_md <= 0 or not _MONTH.fullmatch(template):
        return False
    full = len(workdays(month)) * per_md
    other = len(workdays(template)) * per_md
    return abs(hours - full) <= TOLERANCE and abs(hours - other) > TOLERANCE
