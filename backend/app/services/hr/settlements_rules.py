"""Rozliczenia zespołu — reguły bez bazy: stany według formy, terminy, kwoty.

Czyste funkcje (testy bez bazy w ``tests/test_hr_settlements_rules.py``):

* **słowa stanu według formy** — B2B ma fakturę („Czeka na fakturę”,
  „Zgodna”, „Do zapłaty”, „Opłacono”), zlecenie i UoP mają kwotę policzoną
  z godzin („Kwota policzona”, „Przekazano do listy płac”, „Wypłacono”);
  stan w bazie jest jeden (``hr_settlement_schema.SETTLEMENT_STATUSES``),
* **termin** (R8) — B2B: dzień nadania numeru KSeF + dni z danych osoby
  (domyślnie 14, jak we wzorze umowy B2B), zlecenie i UoP: dzień wypłaty
  z ustawień Płac w miesiącu po okresie (domyślnie 10.; 31. w lutym =
  ostatni dzień miesiąca),
* **podstawa kwoty** — B2B porównuje netto faktury, zlecenie i UoP brutto
  (R4: NEXUS nie liczy podatków ani składek),
* **co blokuje zatwierdzenie** (R7, R10) — różnica netto choćby o grosz
  i rachunek spoza białej listy VAT.
"""

from __future__ import annotations

import calendar
from collections.abc import Iterable
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional

from app.services.hr.payroll_periods import add_months

#: Ustawienia płatności (karta w Ustawieniach → Płace, etap 4): ``payout_day``
#: — dzień wypłaty zlecenia i UoP w miesiącu po okresie.
PAYMENT_SETTINGS_KEY = "hr_payment_settings"
DEFAULT_PAYOUT_DAY = 10
DEFAULT_TERMS_DAYS = 14

B2B = "b2b"
#: Stany, w których dokument jeszcze może zmienić rozliczenie.
OPEN_STATUSES: tuple[str, ...] = ("awaiting_document", "mismatch", "ready")
#: Kolejka Płac według pilności (M3): rozbieżności i brakujące faktury na górze.
URGENCY: dict[str, int] = {
    "mismatch": 0,
    "awaiting_document": 1,
    "ready": 2,
    "approved": 3,
    "paid": 4,
    "cancelled": 5,
}

_B2B_LABELS = {
    "awaiting_document": "Czeka na fakturę",
    "mismatch": "Rozbieżność",
    "ready": "Zgodna",
    "approved": "Do zapłaty",
    "paid": "Opłacono",
    "cancelled": "Anulowane",
}
_PAYROLL_LABELS = {
    "awaiting_document": "Czeka na dokument",
    "mismatch": "Rozbieżność",
    "ready": "Kwota policzona",
    "approved": "Przekazano do listy płac",
    "paid": "Wypłacono",
    "cancelled": "Anulowane",
}


def amount_basis(employment_type: str) -> str:
    """B2B porównuje netto faktury, zlecenie i UoP — brutto."""

    return "net" if employment_type == B2B else "gross"


def initial_status(employment_type: str) -> str:
    """B2B czeka na fakturę; zlecenie i UoP mają kwotę od razu (R3, R4)."""

    return "awaiting_document" if employment_type == B2B else "ready"


def status_label(status: str, employment_type: Optional[str]) -> str:
    labels = _B2B_LABELS if employment_type == B2B else _PAYROLL_LABELS
    return labels.get(status, status)


def clamp_payout_day(raw: Any) -> int:
    """Dzień wypłaty 1–31; zła wartość w ustawieniach = domyślny 10."""

    if isinstance(raw, bool):
        return DEFAULT_PAYOUT_DAY
    try:
        day = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_PAYOUT_DAY
    return day if 1 <= day <= 31 else DEFAULT_PAYOUT_DAY


def payout_date(year: int, month: int, payout_day: Any) -> date:
    """Dzień wypłaty zlecenia i UoP: ``payout_day`` miesiąca po okresie."""

    next_year, next_month = add_months(year, month, 1)
    last = calendar.monthrange(next_year, next_month)[1]
    return date(next_year, next_month, min(clamp_payout_day(payout_day), last))


def invoice_due_date(received_on: date, terms_days: Optional[int]) -> date:
    """Termin faktury B2B: dzień nadania numeru KSeF + dni z danych osoby."""

    days = DEFAULT_TERMS_DAYS if terms_days is None else int(terms_days)
    return received_on + timedelta(days=days)


def net_total(amounts: Iterable[Decimal]) -> Decimal:
    """Netto dokumentów rozliczenia: faktura pierwotna + korekty (różnice)."""

    return sum((Decimal(value) for value in amounts), Decimal("0")).quantize(
        Decimal("0.01")
    )


def problems_of(
    *,
    employment_type: str,
    discrepancy: Optional[Decimal],
    account_source: Optional[str],
) -> tuple[str, ...]:
    """Co nie pozwala zatwierdzić faktury bez drugiej osoby (R7, R10).

    ``amount`` — netto faktury różni się od kwoty z NEXUSA choćby o grosz,
    ``white_list`` — rachunek do przelewu nie pochodzi z wykazu VAT (albo go
    nie ma). Zlecenie i UoP nie mają faktury — nic tu nie zgłaszają.
    """

    if employment_type != B2B:
        return ()
    found: list[str] = []
    if discrepancy is not None and discrepancy != 0:
        found.append("amount")
    if account_source != "white_list":
        found.append("white_list")
    return tuple(found)


def override_kind_for(problems: tuple[str, ...]) -> Optional[str]:
    """Rodzaj uznania: różnica kwoty ma pierwszeństwo przed rachunkiem.

    Uznanie obejmuje WSZYSTKIE problemy widoczne w chwili wniosku (lista idzie
    do śladu); nowy dokument albo zmiana rachunku je kasuje.
    """

    if "amount" in problems:
        return "amount"
    if "white_list" in problems:
        return "white_list"
    return None


__all__ = [
    "B2B",
    "DEFAULT_PAYOUT_DAY",
    "DEFAULT_TERMS_DAYS",
    "OPEN_STATUSES",
    "PAYMENT_SETTINGS_KEY",
    "URGENCY",
    "amount_basis",
    "clamp_payout_day",
    "initial_status",
    "invoice_due_date",
    "net_total",
    "override_kind_for",
    "payout_date",
    "problems_of",
    "status_label",
]
