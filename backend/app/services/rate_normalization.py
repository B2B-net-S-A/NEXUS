"""Normalizacja stawek do wspólnej jednostki miesięcznej (M4 audyt P0.5, PR-02).

Gate budżetowy pending-verification porównywał surowe liczby bez jednostki i
waluty: ``150 PLN/h > 25 000 PLN/mc`` było "w budżecie", bo 150 < 25 000.
``Job.salary_max`` jest budżetem miesięcznym w PLN, więc stawkę kandydata
normalizujemy do PLN/miesiąc przed porównaniem.

Polityka (decyzja biznesowa Artura, 2026-07-16 — sekcja 20.4 planu):

- **hourly → monthly: × 168** (21 dni × 8 h — standard polskiego kontraktingu),
- **daily → monthly: × 21**,
- **monthly → monthly: × 1**,
- **waluta inna niż PLN → brak auto-przeliczenia** (żadnych kursów FX w gate);
  wynik ``None`` = manual review → ruch dostaje ``verification_status=pending``,
- **nieznana/pusta jednostka → manual review** (fail-closed, nigdy
  auto-approve — wymóg audytu).

Zmiana polityki = bump ``POLICY_VERSION`` (trafia do Activity audit trail).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

POLICY_VERSION = "168h-21d-v1"

MONTHLY_HOURS = Decimal("168")
MONTHLY_DAYS = Decimal("21")

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

    ``None`` w pierwszym polu oznacza "nie da się bezpiecznie porównać" —
    caller MUSI potraktować to jako manual review (pending), nigdy jako
    auto-approve.
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
