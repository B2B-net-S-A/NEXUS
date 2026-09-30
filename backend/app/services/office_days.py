"""Dni w biurze rekrutacji: „w tygodniu” albo „w miesiącu” (0407, 30.09.2026).

Klienci piszą „raz w miesiącu”, „2 dni w miesiącu” — do tej daty rekrutacja
znała tylko liczbę dni NA TYDZIEŃ (`onsite_days_per_week`), więc rekruter
wpisywał 0 (co wyłączało sprawdzenia biura i czytało się jak „zdalnie”) albo 1
(zawyżony wymóg).

Reguła jest jedna (lustro frontu: `frontend/src/lib/office-days.ts`, wspólne
przypadki `frontend/src/lib/__fixtures__/office-days-cases.json`):

- człowiek podaje DOKŁADNIE jedno: dni w tygodniu albo dni w miesiącu;
- przy wpisie miesięcznym serwer sam wylicza `onsite_days_per_week`
  (`weekly_from_monthly`) — bramki dopasowań, odcisk requestu i portale czytają
  wyłącznie liczbę tygodniową i nie odróżniają „rzadko w biurze” od „zdalnie”
  tylko dzięki temu, że wyliczenie nigdy nie daje zera;
- wpis tygodniowy czyści miesięczny;
- miesięcznie ma sens wyłącznie przy trybie hybrydowym.
"""

from __future__ import annotations

from typing import Any, Optional

# Średnio 52 tygodnie / 12 miesięcy. Kalendarzowy miesiąc ma 4–5 tygodni.
WEEKS_PER_MONTH = 52 / 12
MONTHLY_MAX = 22  # dni robocze w miesiącu
WEEKLY_MAX = 7

COLUMN_DDL = (
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS onsite_days_per_month INTEGER NULL"
)

MSG_MONTHLY_NOT_HYBRID = (
    "Dni w biurze w miesiącu podaje się tylko przy pracy hybrydowej."
)


def weekly_from_monthly(per_month: int) -> int:
    """Liczba tygodniowa dla bramek: zaokrąglona, ale nigdy zero.

    1–6 dni w miesiącu → 1 dzień w tygodniu, 7–10 → 2 itd. Zero
    znaczyłoby dla bramek „biuro niewymagane” — a klient go wymaga.
    """
    return max(1, min(WEEKLY_MAX, int(per_month / WEEKS_PER_MONTH + 0.5)))


def _as_int(value: Any, low: int, high: int) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float):
        if not value.is_integer():
            return None
        value = int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text.isdigit():
            return None
        value = int(text)
    if not isinstance(value, int) or not low <= value <= high:
        return None
    return value


def normalize(
    per_week: Any,
    per_month: Any,
    mode: Optional[str] = None,
) -> tuple[Optional[int], Optional[int]]:
    """Zwraca spójną parę ``(per_week, per_month)``.

    Miesięczne wygrywa (wyznacza tygodniowe); bez miesięcznego zostaje
    tygodniowe tak, jak je podano. ``mode`` (wartość `remote_policy` albo
    `basics.work_mode`) — gdy znany i nie hybrydowy, miesięczne = ``ValueError``.
    """
    month = _as_int(per_month, 1, MONTHLY_MAX)
    if month is None:
        return _as_int(per_week, 0, WEEKLY_MAX), None
    if mode is not None and mode != "hybrid":
        raise ValueError(MSG_MONTHLY_NOT_HYBRID)
    return weekly_from_monthly(month), month


def _days(n: int) -> str:
    return "1 dzień" if n == 1 else f"{n} dni"


def label(per_week: Optional[int], per_month: Optional[int]) -> Optional[str]:
    """Zdanie dla ludzi: „2 dni w miesiącu” / „3 dni w tygodniu”."""
    if per_month is not None:
        return f"{_days(per_month)} w miesiącu"
    if per_week is not None:
        return f"{_days(per_week)} w tygodniu"
    return None
