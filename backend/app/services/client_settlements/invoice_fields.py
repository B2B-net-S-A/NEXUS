"""Pola faktury kontraktora z XML-a KSeF: data sprzedaży, miesiąc w nazwie, płatność.

Najczęstsze powody maili rozliczeń z prośbą o korektę (IX–X 2026: 16 × data
sprzedaży, 5 × nazwa pozycji z innym miesiącem, 13 × forma płatności albo
„ZAPŁACONO”). Metadane z zapytania KSeF tych pól nie mają, więc kontrola
czyta treść z ``details`` (``contractor_details``: XML pobierany raz po
przypięciu faktury do kontraktu). Korekt nie sprawdzamy — powtarzają pola
faktury pierwotnej, a ich treść ocenia łańcuch korekt (``invoice_chain``).

Każda reguła ma domyślnie poziom ``off``; Finanse włączają ją per klient.
Faktura bez pobranej treści dostaje uwagę „nie sprawdzono”, nigdy błąd.
"""

from __future__ import annotations

import calendar
import re
from datetime import date
from typing import Any, Iterable, Optional

from app.services.client_settlements import invoice_chain

SALE_DATE, ITEM_MONTH, PAYMENT_FORM = "ci.sale_date", "ci.item_month", "ci.payment_form"
RULE_KEYS = (SALE_DATE, ITEM_MONTH, PAYMENT_FORM)
TRANSFER = "6"

#: ``Platnosc/FormaPlatnosci`` FA(2)/FA(3).
PAYMENT_LABELS = {
    "1": "gotówka",
    "2": "karta",
    "3": "bon",
    "4": "czek",
    "5": "kredyt",
    "6": "przelew",
    "7": "płatność mobilna",
    "other": "inna forma płatności",
}

MONTH_NAMES = (
    "styczeń",
    "luty",
    "marzec",
    "kwiecień",
    "maj",
    "czerwiec",
    "lipiec",
    "sierpień",
    "wrzesień",
    "październik",
    "listopad",
    "grudzień",
)
#: Odmiany nazw miesięcy (z ogonkami i bez) → numer miesiąca.
_MONTH_FORMS: dict[str, int] = {}
for _number, _forms in enumerate(
    (
        "styczeń styczen stycznia styczniu",
        "luty lutego lutym",
        "marzec marca marcu",
        "kwiecień kwiecien kwietnia kwietniu",
        "maj maja maju",
        "czerwiec czerwca czerwcu",
        "lipiec lipca lipcu",
        "sierpień sierpien sierpnia sierpniu",
        "wrzesień wrzesien września wrzesnia wrześniu wrzesniu",
        "październik pazdziernik października pazdziernika październiku pazdzierniku",
        "listopad listopada listopadzie",
        "grudzień grudzien grudnia grudniu",
    ),
    start=1,
):
    for _form in _forms.split():
        _MONTH_FORMS[_form] = _number

#: Nazwa miesiąca, opcjonalnie z rokiem tuż za nią („październik 2026”).
_NAME_RE = re.compile(r"([^\W\d_]+)(?:\s+(20\d\d)(?!\d))?")
#: ``10.2026``, ``10/2026``, ``10-2026`` (też z dniem przed: ``31.10.2026``).
#: Miesiąc dwiema cyframi — „3/2026” to zwykle numer zamówienia.
_MONTH_YEAR_RE = re.compile(r"(?<!\d)(0[1-9]|1[0-2])[./-](20\d\d)(?!\d)")
#: ``2026-10``, ``2026.10``, ``2026/10`` (też z dniem po: ``2026-10-31``).
_YEAR_MONTH_RE = re.compile(r"(?<!\d)(20\d\d)[./-](0[1-9]|1[0-2])(?!\d)")


def _level(rules: dict[str, Any], key: str) -> str:
    return str((rules.get(key) or {}).get("level") or "off")


def _bad(level: str) -> str:
    return "fail" if level == "block" else "warn"


def _period(month: Optional[str]) -> Optional[tuple[int, int]]:
    try:
        year, number = (int(part) for part in str(month or "").split("-"))
    except ValueError:
        return None
    return (year, number) if 1 <= number <= 12 else None


def _day(raw: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(raw)) if raw else None
    except ValueError:
        return None


def _name(doc: Any) -> str:
    return doc.invoice_number or doc.ksef_number


def _fmt(day: date) -> str:
    return day.strftime("%d.%m.%Y")


def months_in(text: str) -> set[tuple[Optional[int], int]]:
    """Miesiące wskazane w nazwie pozycji: ``(rok albo None, miesiąc)``."""

    found: set[tuple[Optional[int], int]] = set()
    lowered = text.lower()
    for match in _YEAR_MONTH_RE.finditer(lowered):
        found.add((int(match.group(1)), int(match.group(2))))
    # Zdjęte z tekstu, żeby „2026-10-31” nie dało drugiego trafienia z dnia.
    lowered = _YEAR_MONTH_RE.sub(" ", lowered)
    for match in _MONTH_YEAR_RE.finditer(lowered):
        found.add((int(match.group(2)), int(match.group(1))))
    lowered = _MONTH_YEAR_RE.sub(" ", lowered)
    for match in _NAME_RE.finditer(lowered):
        number = _MONTH_FORMS.get(match.group(1))
        if number is not None:
            found.add((int(match.group(2)) if match.group(2) else None, number))
    return found


def _other_month(
    items: Iterable[Any], period: tuple[int, int]
) -> Optional[tuple[Optional[int], int]]:
    for item in items:
        if not isinstance(item, dict) or item.get("before_correction"):
            continue
        for year, number in sorted(
            months_in(str(item.get("name") or "")), key=lambda m: (m[0] or 0, m[1])
        ):
            if number != period[1] or (year is not None and year != period[0]):
                return year, number
    return None


def _month_label(year: Optional[int], number: int) -> str:
    name = MONTH_NAMES[number - 1]
    return f"{name} {year}" if year else name


def _sale_check(doc: Any, period: tuple[int, int], level: str) -> dict[str, Any]:
    details = doc.details or {}
    # Bez P_6 data sprzedaży = data wystawienia (FA: P_6 tylko, gdy inna niż P_1).
    sale = _day(details.get("sale_date")) or _day(details.get("issue_date"))
    want = date(period[0], period[1], calendar.monthrange(*period)[1])
    if sale == want:
        return {"state": "ok", "title": "Data sprzedaży: ostatni dzień miesiąca"}
    return {
        "state": _bad(level),
        "title": "Data sprzedaży inna niż ostatni dzień miesiąca",
        "detail": f"{_name(doc)}: {_fmt(sale) if sale else 'brak'} zamiast {_fmt(want)}.",
    }


def _item_check(doc: Any, period: tuple[int, int], level: str) -> dict[str, Any]:
    other = _other_month((doc.details or {}).get("items") or [], period)
    if other is None:
        return {"state": "ok", "title": "Nazwy pozycji bez innego miesiąca"}
    return {
        "state": _bad(level),
        "title": "Nazwa pozycji z innym miesiącem niż rozliczany",
        "detail": f"{_name(doc)}: {_month_label(*other)} zamiast "
        f"{_month_label(period[0], period[1])}.",
    }


def _payment_check(doc: Any, level: str) -> dict[str, Any]:
    details = doc.details or {}
    form = details.get("payment_form")
    if details.get("paid"):
        problem = "faktura oznaczona jako zapłacona"
    elif form is not None and form != TRANSFER:
        problem = f"{PAYMENT_LABELS.get(str(form), 'nieznana forma')} zamiast przelewu"
    elif form is None and not details.get("accounts"):
        problem = "bez formy płatności i numeru rachunku"
    else:
        return {"state": "ok", "title": "Płatność przelewem"}
    return {
        "state": _bad(level),
        "title": "Płatność do poprawy na fakturze",
        "detail": f"{_name(doc)}: {problem}.",
    }


def _readable(doc: Any) -> bool:
    details = doc.details or {}
    return details.get("state") == "ok" and "paid" in details


def field_checks(docs: list[Any], rules: dict[str, Any]) -> list[dict[str, Any]]:
    """Kontrole włączonych reguł pól dla faktur osoby za miesiąc (bez korekt)."""

    levels = {key: _level(rules, key) for key in RULE_KEYS}
    if all(level == "off" for level in levels.values()):
        return []
    originals = [d for d in docs if not invoice_chain.is_correction(d)]
    unread = [d for d in originals if not _readable(d)]
    checks: list[dict[str, Any]] = []
    if unread:
        failed = any((d.details or {}).get("state") == "failed" for d in unread)
        checks.append(
            {
                "state": "none",
                "title": "Pola faktury: nie sprawdzono",
                "detail": (
                    "Nie udało się odczytać z KSeF: "
                    if failed
                    else "Treść z KSeF jeszcze nie pobrana: "
                )
                + ", ".join(_name(d) for d in unread)
                + ".",
            }
        )
    for doc in originals:
        if not _readable(doc):
            continue
        period = _period(doc.period_month)
        if period is not None and levels[SALE_DATE] != "off":
            checks.append(_sale_check(doc, period, levels[SALE_DATE]))
        if period is not None and levels[ITEM_MONTH] != "off":
            checks.append(_item_check(doc, period, levels[ITEM_MONTH]))
        if levels[PAYMENT_FORM] != "off":
            checks.append(_payment_check(doc, levels[PAYMENT_FORM]))
    return checks
