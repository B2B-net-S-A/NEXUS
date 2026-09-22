"""Miesiąc roboczy w przeliczeniach stawek — JEDNA stała dla całego systemu.

Decyzja Artura z 22.09.2026 (audyt statystyk): stawkę godzinową i dzienną
przeliczamy na kwotę miesięczną ZAWSZE tym samym miesiącem roboczym —
**21 MD × 8 h = 168 h**. Dotyczy MRR, marży, przychodu, prognoz, analityki,
eksportów i UI, a także przeliczania stawek między jednostkami (godzina ↔ MD
↔ miesiąc).

Do tej daty w repo żyły trzy różne miesiące: 160 h (domyślne godziny
rozliczeniowe kontraktu i zamówienia), 176 h (kontrakt przeliczony z MD,
22 MD × 8 h) i 22 MD (stawka dzienna w ``Contract.monthly_rate``, raportach
i analityce kontraktów) — obok 168 h w normalizacji budżetu
(``rate_normalization``). Ta sama stawka godzinowa dawała więc MRR różny
o ~10% zależnie od tego, która ścieżka go policzyła.

Lustro po stronie frontendu: ``frontend/src/lib/work-time.ts``. Test
``test_work_time_constant_guard.py`` pilnuje, żeby w modułach pieniędzy nie
wróciły gołe liczby 160/176/22.

``billing_hours_per_month`` zostaje kolumną kontraktu i zamówienia (jawnie
wpisana inna liczba godzin nadal wygrywa), ale jej domyślną wartością
i fallbackiem jest :data:`HOURS_PER_MONTH`.
"""

from __future__ import annotations

from decimal import Decimal

__all__ = [
    "HOURS_PER_MD",
    "HOURS_PER_MD_DEC",
    "HOURS_PER_MONTH",
    "HOURS_PER_MONTH_DEC",
    "MD_PER_MONTH",
    "MD_PER_MONTH_DEC",
]

# 1 MD (dzień roboczy) = 8 godzin.
HOURS_PER_MD: int = 8
# Miesiąc roboczy = 21 MD.
MD_PER_MONTH: int = 21
# Miesiąc roboczy w godzinach = 21 × 8 = 168.
HOURS_PER_MONTH: int = MD_PER_MONTH * HOURS_PER_MD

HOURS_PER_MD_DEC = Decimal(HOURS_PER_MD)
MD_PER_MONTH_DEC = Decimal(MD_PER_MONTH)
HOURS_PER_MONTH_DEC = Decimal(HOURS_PER_MONTH)
