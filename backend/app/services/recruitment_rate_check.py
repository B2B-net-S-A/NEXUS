"""Czy stawka z zamówienia albo umowy zgadza się ze stawką z rekrutacji (D7).

Czysta reguła, bez bazy. Stawkę do klienta zapisuje Delivery Lead przy
wysyłce CV — jest punktem odniesienia dla przychodu w zamówieniu klienta;
stawka kandydata od rekrutera jest punktem odniesienia dla kosztu
w zamówieniu i w umowie B2B. Różnica NIGDY nie blokuje zapisu (decyzja
Artura 07.10.2026, D7): zamówienie z maila idzie do kolejki „do sprawdzenia”,
a formularze pokazują notkę.

Trzy wyniki:

* ``equal`` — po sprowadzeniu do PLN/h różnica nie większa niż 0,01 zł/h,
* ``differs`` — porównywalne i różne,
* ``not_comparable`` — brak liczby, nieznana jednostka, waluta inna niż PLN
  albo miesiąc porównywany z godziną/dniem (ryczałt nie niesie godzin).

Jednostki: godzina; dzień i MD = 8 godzin; miesiąc wyłącznie z miesiącem.
Lustro: ``frontend/src/lib/recruitment-rate-check.ts``, wspólne przypadki
``frontend/src/lib/__fixtures__/recruitment-rate-check-cases.json``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Optional, Union

from app.core.work_time import HOURS_PER_MD

EQUAL = "equal"
DIFFERS = "differs"
NOT_COMPARABLE = "not_comparable"

#: Tolerancja porównania: 0,01 zł/h (przy miesiącu — 0,01 zł/mc).
TOLERANCE = Decimal("0.01")

_HOUR = "hour"
_DAY = "day"
_MONTH = "month"

#: Wszystkie nazwy jednostek, które niosą zamówienia, kontrakty, etapy
#: (``rateunit``) i plan poczty zamówień.
_UNIT_ALIASES: dict[str, str] = {
    "hour": _HOUR,
    "hourly": _HOUR,
    "h": _HOUR,
    "day": _DAY,
    "daily": _DAY,
    "md": _DAY,
    "month": _MONTH,
    "monthly": _MONTH,
}

Amount = Union[Decimal, float, int, str, None]


@dataclass(frozen=True)
class RateRef:
    """Stawka z rekrutacji podana regule — kwota, jednostka, waluta, etykieta."""

    value: Optional[Decimal]
    unit: Optional[str]
    currency: Optional[str] = "PLN"
    #: Tytuł rekrutacji — do zdania dla człowieka.
    label: Optional[str] = None


def normalize_unit(unit: Optional[str]) -> Optional[str]:
    if unit is None:
        return None
    return _UNIT_ALIASES.get(str(getattr(unit, "value", unit)).strip().lower())


def _decimal(value: Amount) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        number = Decimal(str(value).replace(",", ".").strip())
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite() or number <= 0:
        return None
    return number


def _is_pln(currency: Optional[str]) -> bool:
    return (currency or "PLN").strip().upper() == "PLN"


def comparable_amount(
    value: Amount, unit: Optional[str], currency: Optional[str] = "PLN"
) -> Optional[tuple[str, Decimal]]:
    """``("hour", zł/h)`` albo ``("month", zł/mc)``; ``None`` = nieporównywalne."""
    number = _decimal(value)
    kind = normalize_unit(unit)
    if number is None or kind is None or not _is_pln(currency):
        return None
    if kind == _DAY:
        return _HOUR, number / Decimal(HOURS_PER_MD)
    return kind, number


def hourly_pln(
    value: Amount, unit: Optional[str], currency: Optional[str] = "PLN"
) -> Optional[Decimal]:
    """Stawka w PLN/h (dzień i MD ÷ 8); miesiąc i inna waluta = ``None``."""
    amount = comparable_amount(value, unit, currency)
    if amount is None or amount[0] != _HOUR:
        return None
    return amount[1]


def compare(
    reference_value: Amount,
    reference_unit: Optional[str],
    reference_currency: Optional[str],
    actual_value: Amount,
    actual_unit: Optional[str],
    actual_currency: Optional[str],
) -> str:
    """Porównanie stawki z rekrutacji (``reference``) ze stawką sprawdzaną."""
    reference = comparable_amount(reference_value, reference_unit, reference_currency)
    actual = comparable_amount(actual_value, actual_unit, actual_currency)
    if reference is None or actual is None or reference[0] != actual[0]:
        return NOT_COMPARABLE
    return EQUAL if abs(reference[1] - actual[1]) <= TOLERANCE else DIFFERS


def compare_ref(
    ref: Optional[RateRef],
    actual_value: Amount,
    actual_unit: Optional[str],
    actual_currency: Optional[str] = "PLN",
) -> str:
    if ref is None:
        return NOT_COMPARABLE
    return compare(
        ref.value, ref.unit, ref.currency, actual_value, actual_unit, actual_currency
    )


_UNIT_LABEL = {_HOUR: "zł/h", _DAY: "zł/MD", _MONTH: "zł/mc"}


def format_rate(value: Amount, unit: Optional[str]) -> str:
    """„165 zł/h”, „1320,50 zł/MD” — do zdania w powodzie kolejki."""
    number = _decimal(value)
    if number is None:
        return "—"
    quantized = number.quantize(Decimal("0.01"))
    text = (
        f"{quantized:.0f}"
        if quantized == quantized.to_integral_value()
        else f"{quantized:.2f}".replace(".", ",")
    )
    kind = normalize_unit(unit)
    return f"{text} {_UNIT_LABEL.get(kind, '')}".strip() if kind else text
