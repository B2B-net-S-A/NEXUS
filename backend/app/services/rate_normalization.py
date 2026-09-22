"""Normalizacja stawek do wspólnej jednostki miesięcznej (M4 audyt P0.5, PR-02).

Dawny gate budżetowy porównywał surowe liczby bez jednostki i waluty:
``150 PLN/h > 25 000 PLN/mc`` było "w budżecie", bo 150 < 25 000.
``Job.salary_max`` jest budżetem miesięcznym w PLN, więc stawkę kandydata
normalizujemy do PLN/miesiąc przed porównaniem. Od 17.09.2026 porównanie
niczego nie blokuje — zasila odznakę „ponad budżet" (`budget_exceeded`).

Polityka (decyzja biznesowa Artura, 2026-07-16 — sekcja 20.4 planu):

- **hourly → monthly: × 168** (21 dni × 8 h — standard polskiego kontraktingu),
- **daily → monthly: × 21**,
- **monthly → monthly: × 1**,
- **waluta inna niż PLN → brak auto-przeliczenia** (żadnych kursów FX);
  wynik ``None`` = „nie da się porównać",
- **nieznana/pusta jednostka → ``None``** (tak samo: brak porównania).

Zmiana polityki = bump ``POLICY_VERSION`` (trafia do Activity audit trail).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from app.core.work_time import HOURS_PER_MONTH_DEC, MD_PER_MONTH_DEC

POLICY_VERSION = "168h-21d-v1"

# Od 22.09.2026 ta polityka jest miesiącem roboczym CAŁEGO systemu
# (``app.core.work_time``) — MRR, marża i analityka liczą tym samym.
MONTHLY_HOURS = HOURS_PER_MONTH_DEC
MONTHLY_DAYS = MD_PER_MONTH_DEC

_UNIT_FACTORS: dict[str, Decimal] = {
    "hourly": MONTHLY_HOURS,
    "daily": MONTHLY_DAYS,
    "monthly": Decimal("1"),
}


def normalize_rate_to_monthly(
    value: Decimal,
    unit: Optional[str],
    currency: Optional[str],
) -> tuple[Optional[Decimal], str]:
    """Zwraca ``(znormalizowana_stawka_miesięczna, nota)``.

    ``None`` w pierwszym polu oznacza "nie da się bezpiecznie porównać".
    Caller NIE może czytać tego jako „ponad budżet": brak porównania to nie
    jego wynik (patrz `budget_exceeded` w `/pipeline/move`).
    """
    cur = (currency or "PLN").strip().upper()
    if cur != "PLN":
        return None, f"waluta {cur} ≠ PLN — brak auto-przeliczenia, manual review"

    factor = _UNIT_FACTORS.get((unit or "").strip().lower())
    if factor is None:
        return None, f"nieznana jednostka {unit!r} — manual review"

    normalized = (Decimal(value) * factor).quantize(Decimal("0.01"))
    if factor == Decimal("1"):
        note = "monthly 1:1"
    else:
        note = f"{unit} × {factor} = {normalized} PLN/mc (polityka {POLICY_VERSION})"
    return normalized, note
