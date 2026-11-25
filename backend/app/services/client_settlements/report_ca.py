"""Raport zbiorczy Credit Agricole „Raport rozliczenia outsourcingu” → MD osoby.

Bez bazy. Klient generuje raport dla dostawcy co miesiąc, DL przekazuje go na
rozliczenia@ w ZIP-ie z hasłem (rozpakowuje ``consultant_portal/zip_files``).
Jeden arkusz ma wszystkie osoby dostawcy:

* „Raport za miesiąc: 2026.09”, potem wiersz nagłówka „Pracownik Nazwisko Imie ·
  Nr Ewid · PID · … · Czas 0% · Czas 100% · Czas 150% · Czas 200% · TE · Stawka
  Netto · Kwota Netto”, wiersz na osobę i projekt (PID), na końcu „Podsumowanie”;
* „TE” to MD: próba IX–X 2026, trzy kontrakty, 6 z 6 równych fakturom Finansów;
  MD osoby to suma TE jej wierszy (kilka projektów w miesiącu);
* „Czas 0%” to godziny bez wynagrodzenia (wiersz „ABS”), więc nie są MD; na karcie
  stoją jako informacja, a „Czas 150% / 200%” (nadgodziny) jako uwaga dla Finansów.

Osobę wybieramy po imieniu i nazwisku z kontraktu (kolejność dowolna); osoba,
której w raporcie nie ma, nie dostaje z niego nic (``None``).
"""

from __future__ import annotations

import logging
import re
import unicodedata
import warnings
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Optional

from app.services.client_settlements import declared, xlsx
from app.services.client_settlements.rcp_checks import (
    ProofResult,
    _fmt,
    _Group,
    name_tokens,
)

logger = logging.getLogger(__name__)

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SOURCE = "Raport rozliczenia CA"
_TITLE = "raport rozliczenia outsourcingu"
_MONTH_LABEL = "raport za miesiac"
_SUMMARY = "podsumowanie"
_MAX_ROWS = 500
_ZERO = Decimal("0")


@dataclass(frozen=True)
class CaPerson:
    #: Jak w raporcie: „Nazwisko Imię”.
    name: str
    md: Decimal
    amount: Decimal
    unpaid_hours: Decimal
    overtime_hours: Decimal


@dataclass(frozen=True)
class CaReport:
    #: ``RRRR-MM``.
    month: Optional[str]
    people: tuple[CaPerson, ...]


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _plain(value: Any) -> str:
    """Tekst komórki bez ogonków i znaków, w kolejności słów: „Czas 0%” → „czas 0”."""

    folded = unicodedata.normalize(
        "NFKD", _text(value).replace("ł", "l").replace("Ł", "L")
    )
    ascii_text = folded.encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", ascii_text).split())


def _number(value: Any) -> Decimal:
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        return Decimal(str(value))
    try:
        return Decimal(_text(value).replace(" ", "").replace(",", ".") or "0")
    except InvalidOperation:
        return _ZERO


def _month(value: Any) -> Optional[str]:
    text = _text(value).replace(".", "-").replace("/", "-")
    parts = text.split("-")
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        year, month = int(parts[0]), int(parts[1])
        if 2000 <= year <= 2100 and 1 <= month <= 12:
            return f"{year}-{month:02d}"
    return None


@dataclass(frozen=True)
class _Columns:
    person: int
    te: int
    amount: Optional[int]
    unpaid: Optional[int]
    overtime: tuple[int, ...]


def _columns(header: list[Any]) -> Optional[_Columns]:
    names = [_plain(cell) for cell in header]
    person = next((i for i, n in enumerate(names) if "nazwisko" in n.split()), None)
    te = next((i for i, n in enumerate(names) if n == "te"), None)
    if person is None or te is None:
        return None
    return _Columns(
        person=person,
        te=te,
        amount=next((i for i, n in enumerate(names) if n == "kwota netto"), None),
        unpaid=next((i for i, n in enumerate(names) if n == "czas 0"), None),
        overtime=tuple(i for i, n in enumerate(names) if n in ("czas 150", "czas 200")),
    )


def _rows(content: bytes) -> Optional[list[list[Any]]]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            workbook = xlsx.load_workbook(content, data_only=True, read_only=True)
    except Exception as exc:  # noqa: BLE001 — obcy plik nie blokuje przyjęcia
        logger.info("report_ca: arkusz nieczytelny (%s)", type(exc).__name__)
        return None
    try:
        for sheet in workbook.worksheets:
            rows = [
                list(row)
                for row in sheet.iter_rows(max_row=_MAX_ROWS, values_only=True)
            ]
            if any(row and _plain(row[0]) == _TITLE for row in rows[:5]):
                return rows
        return None
    finally:
        workbook.close()


def parse(content: bytes, mime: str) -> Optional[CaReport]:
    """Raport CA z arkusza albo ``None`` dla innego pliku."""

    if mime != XLSX:
        return None
    rows = _rows(content)
    if rows is None:
        return None
    month: Optional[str] = None
    columns: Optional[_Columns] = None
    totals: dict[frozenset[str], list[Any]] = {}
    for row in rows:
        first = _plain(row[0]) if row else ""
        if columns is None:
            if first == _MONTH_LABEL:
                month = next((m for m in map(_month, row[1:]) if m), None)
            elif any(_plain(cell) == "te" for cell in row):
                columns = _columns(row)
            continue
        if first == _SUMMARY:
            break

        def cell(index: Optional[int]) -> Decimal:
            if index is None or index >= len(row):
                return _ZERO
            return _number(row[index])

        name = _text(row[columns.person]) if columns.person < len(row) else ""
        if len(name_tokens(name)) < 2:
            continue
        entry = totals.setdefault(
            frozenset(name_tokens(name)), [name, _ZERO, _ZERO, _ZERO, _ZERO]
        )
        entry[1] += cell(columns.te)
        entry[2] += cell(columns.amount)
        entry[3] += cell(columns.unpaid)
        entry[4] += sum((cell(i) for i in columns.overtime), _ZERO)
    if columns is None or not totals:
        return None
    return CaReport(
        month=month,
        people=tuple(
            CaPerson(name=n, md=md, amount=a, unpaid_hours=u, overtime_hours=o)
            for n, md, a, u, o in totals.values()
        ),
    )


def person_in(report: CaReport, person_name: str) -> Optional[CaPerson]:
    """Jedyny wiersz raportu z imieniem i nazwiskiem osoby."""

    wanted = name_tokens(person_name)
    if len(wanted) < 2:
        return None
    hits = [p for p in report.people if name_tokens(p.name) == wanted]
    return hits[0] if len(hits) == 1 else None


def evaluate(
    report: CaReport,
    *,
    month: str,
    person_name: str,
    rules: Mapping[str, Mapping[str, Any]],
    working_days: int,
    other_md: Decimal = _ZERO,
) -> Optional[ProofResult]:
    person = person_in(report, person_name)
    if person is None:
        return None
    result = declared.evaluate(
        declared.Declared(
            source=SOURCE,
            consultant=person.name,
            month=report.month,
            md=person.md,
            amount=person.amount or None,
        ),
        month=month,
        person_name=person_name,
        rules=rules,
        working_days=working_days,
        other_md=other_md,
    )
    hours = _Group(result, rules, "Godziny w raporcie")
    if person.unpaid_hours > 0:
        hours.info(
            f"Nieobecność w raporcie: {_fmt(person.unpaid_hours)} h",
            "„Czas 0%” to godziny bez wynagrodzenia, nie wchodzą do MD.",
        )
    if person.overtime_hours > 0:
        hours.warn(
            f"Nadgodziny w raporcie: {_fmt(person.overtime_hours)} h",
            "„Czas 150% / 200%”: sprawdź, czy zamówienie je obejmuje.",
        )
    hours.close()
    return result
