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
* **co blokuje zatwierdzenie** (R7, R10) — różnica netto choćby o grosz,
  brutto, które nie wynika z netto i VAT (płacimy brutto, porównujemy netto),
  rachunek spoza białej listy VAT i faktura od innego NIP-u niż w danych do
  rozliczeń (``seller``, audyt A2 19.10.2026),
* **od którego miesiąca** — ``settlements_since`` („RRRR-MM”) w ustawieniach
  płatności: wcześniejsze miesiące płac to archiwum sprzed NEXUSA (wypłacone
  w Compassie). Ich zamknięcie nie zakłada rozliczeń, a premia z nich jest
  wypłacona, gdy miesiąc jest zamknięty (reguła sprzed modułu). Brak albo zła
  wartość = bez progu (19.10.2026, produkcja: 2026-10).
"""

from __future__ import annotations

import calendar
import re
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
#: Klucz w ustawieniach płatności: pierwszy miesiąc rozliczany w NEXUSIE.
SETTLEMENTS_SINCE_KEY = "settlements_since"
_SINCE = re.compile(r"^(\d{4})-(\d{2})$")
#: Najwyższa stawka VAT w Polsce — więcej niż 23% netto to nie VAT od usługi.
VAT_MAX_RATE = Decimal("0.23")
_CENT = Decimal("0.01")

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


def parse_since(raw: Any) -> Optional[tuple[int, int]]:
    """``"2026-10"`` → ``(2026, 10)``; brak albo zła wartość = bez progu (``None``)."""

    match = _SINCE.match(raw) if isinstance(raw, str) else None
    if match is None or not 1 <= int(match.group(2)) <= 12:
        return None
    return int(match.group(1)), int(match.group(2))


def settled_in_nexus(year: int, month: int, since: Optional[tuple[int, int]]) -> bool:
    """Czy miesiąc płac rozlicza NEXUS (od ``since``), a nie archiwum sprzed niego."""

    return since is None or (year, month) >= since


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


def gross_problem(
    amounts: Iterable[tuple[Decimal, Decimal, Decimal]],
    *,
    vat_status: Optional[str],
) -> bool:
    """Brutto do zapłaty nie wynika z netto, które porównujemy (R7).

    ``amounts`` — (netto, VAT, brutto) dopasowanych faktur (korekty niosą
    różnice). Problem, gdy brutto którejkolwiek różni się od netto + VAT
    o więcej niż grosz, gdy suma VAT > 0 u osoby, która nie jest czynnym
    podatnikiem VAT (status z wykazu ≠ ``active``, także niesprawdzony), albo
    gdy VAT przekracza 23% netto (z groszem zapasu na zaokrąglenie każdej
    faktury). Faktury z KSeF przyjmujemy bez zmian — decyzję podejmują Płace.
    """

    rows = [(Decimal(net), Decimal(vat), Decimal(gross)) for net, vat, gross in amounts]
    if not rows:
        return False
    if any(abs(gross - net - vat) > _CENT for net, vat, gross in rows):
        return True
    net_sum = sum((net for net, _vat, _gross in rows), Decimal("0"))
    vat_sum = sum((vat for _net, vat, _gross in rows), Decimal("0"))
    if vat_sum > 0 and vat_status != "active":
        return True
    ceiling = (net_sum * VAT_MAX_RATE).quantize(_CENT) + _CENT * len(rows)
    return vat_sum > ceiling


def _digits(value: Optional[str]) -> str:
    return re.sub(r"\D", "", value or "")


def seller_problem(seller_nips: Iterable[str], billing_nip: Optional[str]) -> bool:
    """Któraś dopasowana faktura jest od innego NIP-u niż w danych do rozliczeń.

    Porównujemy same cyfry. Brak NIP-u w danych przy fakturze z NIP-em to też
    problem: jedna osoba z Płac zmienia NIP w danych, wybiera rachunek z białej
    listy dla nowego NIP-u, a faktura od starego wystawcy zostaje przy
    rozliczeniu — pieniądze poszłyby na rachunek innej firmy bez drugiej
    osoby (audyt A2, 19.10.2026).
    """

    own = _digits(billing_nip)
    return any(_digits(nip) != own for nip in seller_nips if _digits(nip))


def problems_of(
    *,
    employment_type: str,
    discrepancy: Optional[Decimal],
    account_source: Optional[str],
    gross_issue: bool = False,
    seller_issue: bool = False,
) -> tuple[str, ...]:
    """Co nie pozwala zatwierdzić faktury bez drugiej osoby (R7, R10).

    ``amount`` — netto faktury różni się od kwoty z NEXUSA choćby o grosz,
    ``gross`` — brutto (to, co płacimy) nie wynika z netto i VAT
    (``gross_problem``), ``white_list`` — rachunek do przelewu nie pochodzi
    z wykazu VAT (albo go nie ma), ``seller`` — faktura od innego NIP-u niż
    w danych do rozliczeń (``seller_problem``; tego nie uznaje się jako
    różnicy — ``override_covers``). Zlecenie i UoP nie mają faktury — nic tu
    nie zgłaszają.
    """

    if employment_type != B2B:
        return ()
    found: list[str] = []
    if discrepancy is not None and discrepancy != 0:
        found.append("amount")
    if gross_issue:
        found.append("gross")
    if account_source != "white_list":
        found.append("white_list")
    if seller_issue:
        found.append("seller")
    return tuple(found)


def override_covers(kind: Optional[str], problems: tuple[str, ...]) -> bool:
    """Czy potwierdzone uznanie obejmuje obecne problemy.

    Uznanie różnicy kwoty (``amount``) obejmuje wszystko, co było widać przy
    wniosku; uznanie samego rachunku (``white_list``) nie przepuszcza
    problemu z kwotą, który pojawił się później (np. VAT u osoby, która
    w wykazie jest teraz zwolniona). Nowy dokument i zmiana odbiorcy kasują
    uznanie osobno.

    Żadne uznanie nie obejmuje ``seller`` (faktura od innego NIP-u niż
    w danych do rozliczeń): to nie różnica do uznania przez dwie osoby, tylko
    zła faktura albo złe dane — rozwiązaniem jest właściwa faktura („Pomiń”,
    „Przenieś”) albo poprawka NIP-u w danych do rozliczeń.
    """

    if "seller" in problems:
        return False
    if kind == "amount":
        return True
    if kind == "white_list":
        return set(problems) <= {"white_list"}
    return False


def override_kind_for(problems: tuple[str, ...]) -> Optional[str]:
    """Rodzaj uznania: różnica kwoty (netto albo brutto) przed rachunkiem.

    Uznanie obejmuje WSZYSTKIE problemy widoczne w chwili wniosku (lista idzie
    do śladu); nowy dokument albo zmiana rachunku je kasuje. Przy ``seller``
    nie ma czego uznawać (``override_covers``) — ``None``.
    """

    if "seller" in problems:
        return None
    if "amount" in problems or "gross" in problems:
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
    "VAT_MAX_RATE",
    "amount_basis",
    "clamp_payout_day",
    "gross_problem",
    "initial_status",
    "invoice_due_date",
    "net_total",
    "override_covers",
    "override_kind_for",
    "payout_date",
    "problems_of",
    "seller_problem",
    "status_label",
]
