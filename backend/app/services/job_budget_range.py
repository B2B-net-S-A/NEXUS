"""Budżet rekrutacji jako przedział „od–do” (0420, 06.10.2026).

Klienci piszą „60–80 zł/h”. Do tej daty pole budżetu przyjmowało jedną
liczbę, więc DL wpisywał środek (70) — kandydat za 75 zł/h dostawał wtedy
plakietkę „ponad budżet”, a Brief mówił „Do 70 zł”.

Reguła jest jedna: **budżetem jest górna granica** (`rate_budget_hourly`,
`resolve_job_budget_hourly`) — czytają ją plakietki, ocena, bramki,
gotowość i Talent Radar. Dolna granica (`rate_budget_hourly_min`) służy
WYŁĄCZNIE do wyświetlania: kandydat tańszy niż „od” nie jest problemem
budżetowym (to pytanie o staż, nie o stawkę).
"""

from __future__ import annotations

from typing import Any, Optional

COLUMN_DDL = (
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS rate_budget_hourly_min NUMERIC(8,2) NULL"
)

MSG_MIN_NOT_BELOW_MAX = "Stawka „od” musi być mniejsza niż „do”."


def _positive(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def min_below_max(low: Any, high: Any) -> bool:
    """Para jest poprawna, gdy którejś nie ma albo „od” < „do”."""
    lo, hi = _positive(low), _positive(high)
    return lo is None or hi is None or lo < hi


def effective_min(job: Any) -> Optional[float]:
    """Dolna granica budżetu do wyświetlenia, albo None.

    1. kolumna `rate_budget_hourly_min`, gdy jest mniejsza od budżetu;
    2. bez kolumny — przedział z tekstu stawki Championa (`basics.rate_raw`,
       np. „120–140 zł/h” z dokumentu), gdy jego góra JEST budżetem;
    3. inaczej None: „od” nie mniejsze niż budżet (zostało po obniżeniu
       budżetu) nie jest pokazywane.
    """
    from app.services.dealbreaker_filters import resolve_job_budget_hourly

    budget = resolve_job_budget_hourly(job)
    if budget is None:
        return None
    explicit = _positive(getattr(job, "rate_budget_hourly_min", None))
    if explicit is not None:
        return explicit if explicit < budget else None

    from app.services import champion_view
    from app.services.champion_intake import pln_hourly_bounds

    basics = champion_view.basics(job)
    bounds = pln_hourly_bounds(basics.get("rate_raw"))
    if not bounds:
        return None
    low, high = bounds
    if 0 < low < high and abs(high - budget) < 0.005:
        return low
    return None
