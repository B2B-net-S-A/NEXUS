"""Sprawozdania roczne dla Rady (R4): e-Sprawozdanie XML, księga NEXUSA, wpis ręczny.

Wszystkie trzy źródła sprowadzamy do jednej listy pól (``FIELDS``, PLN):
pozycje bilansu i RZiS, z których liczą się wskaźniki (``analysis``).

**Pozycja = ścieżka w układzie załącznika nr 1 do ustawy o rachunkowości**,
np. ``assets:B.III.1.c`` (środki pieniężne) albo ``income:A`` (przychody).

* Plik e-Sprawozdania (schemat MF ``JednostkaInna…``) nazywa elementy
  ścieżką: ``Aktywa_B_III_1_C``, ``Pasywa_B_III_3_A``; w RZiS i rachunku
  przepływów litera i numer (``B_I``) pod ``RZiSPor`` / ``RZiSKalk`` /
  ``PrzeplywyPosr``. Kwoty w ``KwotaA`` (rok bieżący) i ``KwotaB`` (rok
  poprzedni). Parser nie zna całego schematu — zbiera każdą pozycję
  z kwotą (``raw``), a pola bierze ze ścieżek. Dzięki temu nowsza wersja
  schematu z dodatkową pozycją nie psuje odczytu, a Rada może porównać
  surowe pozycje z PDF-em.
* Księga NEXUSA (``services/ledger/statements.py``, K8a) zwraca drzewo
  pozycji z numeracją A / I / 1 / a) — ta sama ścieżka.

Plik z obcej strony nie jest wykonywany: dokument z DTD albo encjami
odrzucamy przed parsowaniem (XXE, „billion laughs”).
"""

from __future__ import annotations

import base64
import binascii
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable, Optional

#: (klucz, etykieta, grupa, ścieżki w kolejności zapasowej).
#: Ścieżka ``assets:`` = aktywa, ``liabilities:`` = pasywa, ``income:`` = RZiS
#: porównawczy, ``income_calc:`` = RZiS kalkulacyjny, ``cashflow:`` =
#: przepływy metodą pośrednią. Pole z kilkoma ścieżkami połączonymi „+” to suma.
FIELDS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    (
        "revenue",
        "Przychody netto ze sprzedaży",
        "income",
        ("income:A", "income_calc:A"),
    ),
    ("operating_costs", "Koszty działalności operacyjnej", "income", ("income:B",)),
    (
        "depreciation",
        "Amortyzacja",
        "income",
        ("income:B.I", "cashflow:A.II.1"),
    ),
    (
        "external_services",
        "Usługi obce",
        "income",
        ("income:B.III",),
    ),
    (
        "salaries",
        "Wynagrodzenia i ubezpieczenia społeczne",
        "income",
        ("income:B.V+income:B.VI",),
    ),
    (
        "sales_profit",
        "Zysk (strata) ze sprzedaży",
        "income",
        ("income:C", "income_calc:F"),
    ),
    (
        "operating_profit",
        "Zysk (strata) z działalności operacyjnej",
        "income",
        ("income:F", "income_calc:I"),
    ),
    ("financial_costs", "Koszty finansowe", "income", ("income:H", "income_calc:K")),
    ("gross_profit", "Zysk (strata) brutto", "income", ("income:I", "income_calc:L")),
    ("income_tax", "Podatek dochodowy", "income", ("income:J", "income_calc:M")),
    ("net_profit", "Zysk (strata) netto", "income", ("income:L", "income_calc:O")),
    ("total_assets", "Aktywa razem", "assets", ("assets:",)),
    ("fixed_assets", "Aktywa trwałe", "assets", ("assets:A",)),
    ("current_assets", "Aktywa obrotowe", "assets", ("assets:B",)),
    ("inventories", "Zapasy", "assets", ("assets:B.I",)),
    ("st_receivables", "Należności krótkoterminowe", "assets", ("assets:B.II",)),
    (
        "trade_receivables",
        "Należności z tytułu dostaw i usług",
        "assets",
        ("assets:B.II.1.a+assets:B.II.2.a+assets:B.II.3.a",),
    ),
    ("st_investments", "Inwestycje krótkoterminowe", "assets", ("assets:B.III",)),
    ("cash", "Środki pieniężne", "assets", ("assets:B.III.1.c",)),
    (
        "prepayments",
        "Krótkoterminowe rozliczenia międzyokresowe",
        "assets",
        ("assets:B.IV",),
    ),
    ("total_liabilities", "Pasywa razem", "liabilities", ("liabilities:",)),
    ("equity", "Kapitał (fundusz) własny", "liabilities", ("liabilities:A",)),
    ("share_capital", "Kapitał podstawowy", "liabilities", ("liabilities:A.I",)),
    ("provisions", "Rezerwy na zobowiązania", "liabilities", ("liabilities:B.I",)),
    (
        "lt_liabilities",
        "Zobowiązania długoterminowe",
        "liabilities",
        ("liabilities:B.II",),
    ),
    (
        "lt_loans",
        "Kredyty i pożyczki długoterminowe",
        "liabilities",
        ("liabilities:B.II.3.a",),
    ),
    (
        "lt_other_financial",
        "Inne zobowiązania finansowe długoterminowe (leasing)",
        "liabilities",
        ("liabilities:B.II.3.c",),
    ),
    (
        "st_liabilities",
        "Zobowiązania krótkoterminowe",
        "liabilities",
        ("liabilities:B.III",),
    ),
    (
        "st_loans",
        "Kredyty i pożyczki krótkoterminowe",
        "liabilities",
        ("liabilities:B.III.3.a",),
    ),
    (
        "st_other_financial",
        "Inne zobowiązania finansowe krótkoterminowe (leasing)",
        "liabilities",
        ("liabilities:B.III.3.c",),
    ),
    (
        "trade_payables",
        "Zobowiązania z tytułu dostaw i usług",
        "liabilities",
        ("liabilities:B.III.1.a+liabilities:B.III.2.a+liabilities:B.III.3.d",),
    ),
    (
        "accruals",
        "Rozliczenia międzyokresowe (pasywa)",
        "liabilities",
        ("liabilities:B.IV",),
    ),
)

FIELD_KEYS: tuple[str, ...] = tuple(key for key, *_ in FIELDS)
FIELD_LABELS: dict[str, str] = {key: label for key, label, *_ in FIELDS}
MAX_ABS_PLN = 100_000_000_000

SECTION_TAGS: dict[str, str] = {
    "RZiSPor": "income",
    "RZiSKalk": "income_calc",
    "PrzeplywyPosr": "cashflow",
}
ROMAN = {"I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"}


class StatementError(ValueError):
    """Plik nie jest e-Sprawozdaniem, które umiemy przeczytać."""


@dataclass
class ParsedStatement:
    period_start: Optional[date]
    period_end: Optional[date]
    schema_name: str
    #: ścieżka → (rok bieżący, rok poprzedni)
    raw: dict[str, tuple[Optional[float], Optional[float]]] = field(
        default_factory=dict
    )

    @property
    def year(self) -> int:
        if self.period_end is None:
            raise StatementError("W pliku nie ma daty końca okresu.")
        return self.period_end.year

    def amounts(self, column: int) -> dict[str, Optional[float]]:
        values = {path: pair[column] for path, pair in self.raw.items()}
        return normalize(values)

    def raw_json(self) -> dict[str, list[Optional[float]]]:
        return {path: [a, b] for path, (a, b) in sorted(self.raw.items())}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _number(text: Optional[str]) -> Optional[float]:
    if text is None:
        return None
    cleaned = text.strip().replace(" ", "").replace("\xa0", "").replace(",", ".")
    if not cleaned:
        return None
    try:
        return round(float(cleaned), 2)
    except ValueError:
        return None


def _date(text: Optional[str]) -> Optional[date]:
    if not text:
        return None
    try:
        return date.fromisoformat(text.strip()[:10])
    except ValueError:
        return None


def _segments(name: str) -> list[str]:
    """``B_III_1_C`` → ``['B', 'III', '1', 'c']`` (litera podpunktu małą)."""

    out: list[str] = []
    for index, part in enumerate(name.split("_")):
        if not part:
            continue
        if index > 0 and part not in ROMAN and not part.isdigit() and len(part) == 1:
            out.append(part.lower())
        else:
            out.append(part)
    return out


def element_path(name: str, section: Optional[str]) -> Optional[str]:
    """Ścieżka pozycji z nazwy elementu (``None`` = element bez pozycji)."""

    if name == "Aktywa":
        return "assets:"
    if name == "Pasywa":
        return "liabilities:"
    for prefix, group in (("Aktywa_", "assets"), ("Pasywa_", "liabilities")):
        if name.startswith(prefix):
            return f"{group}:" + ".".join(_segments(name[len(prefix) :]))
    if section is None:
        return None
    for tag in SECTION_TAGS:
        if name.startswith(tag + "_"):
            name = name[len(tag) + 1 :]
            break
    if not re.fullmatch(r"[A-Z](_[A-Za-z0-9]+)*", name):
        return None
    return f"{section}:" + ".".join(_segments(name))


def _reject_entities(content: bytes) -> None:
    head = content[:200_000].upper()
    if b"<!DOCTYPE" in head or b"<!ENTITY" in head:
        raise StatementError("Plik z deklaracją DTD albo encjami nie jest przyjmowany.")


def _root(content: bytes, depth: int = 0) -> ET.Element:
    _reject_entities(content)
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise StatementError("To nie jest poprawny plik XML.") from exc
    if _local(root.tag).startswith("Jednostka"):
        return root
    for element in root.iter():
        if _local(element.tag).startswith("Jednostka"):
            return element
    # Plik podpisany (XAdES) z treścią w base64 w elemencie ``Object``.
    if depth == 0:
        for element in root.iter():
            text = (element.text or "").strip()
            if _local(element.tag) == "Object" and len(text) > 100:
                try:
                    inner = base64.b64decode(text, validate=False)
                except (binascii.Error, ValueError):
                    continue
                if b"Jednostka" in inner[:5000]:
                    return _root(inner, depth + 1)
    raise StatementError(
        "W pliku nie ma sprawozdania jednostki (element „JednostkaInna…”)."
    )


def parse_xml(content: bytes) -> ParsedStatement:
    """Pozycje bilansu, RZiS i przepływów z pliku e-Sprawozdania."""

    root = _root(content)
    period_start = period_end = None
    raw: dict[str, tuple[Optional[float], Optional[float]]] = {}

    def walk(element: ET.Element, section: Optional[str], in_balance: bool) -> None:
        nonlocal period_start, period_end
        name = _local(element.tag)
        if name in ("OkresOd", "DataOd") and period_start is None:
            period_start = _date(element.text)
        if name in ("OkresDo", "DataDo") and period_end is None:
            period_end = _date(element.text)
        if name in SECTION_TAGS:
            section = SECTION_TAGS[name]
        if name == "Bilans":
            in_balance = True
        children = list(element)
        amounts = {_local(child.tag): child.text for child in children}
        if "KwotaA" in amounts or "KwotaB" in amounts:
            path = element_path(name, section)
            if path is not None and (
                in_balance or not path.startswith(("assets", "liabilities"))
            ):
                raw.setdefault(
                    path,
                    (_number(amounts.get("KwotaA")), _number(amounts.get("KwotaB"))),
                )
        for child in children:
            walk(child, section, in_balance)

    walk(root, None, False)
    if not raw:
        raise StatementError("W pliku nie ma kwot bilansu ani RZiS.")
    return ParsedStatement(period_start, period_end, _local(root.tag), raw)


def _resolve(values: dict[str, Optional[float]], expression: str) -> Optional[float]:
    parts = expression.split("+")
    found = [values.get(part) for part in parts]
    if all(value is None for value in found):
        return None
    return round(sum(value or 0.0 for value in found), 2)


def normalize(values: dict[str, Optional[float]]) -> dict[str, Optional[float]]:
    """Pola ``FIELDS`` z mapy ścieżka → kwota (pierwsza ścieżka z kwotą wygrywa)."""

    out: dict[str, Optional[float]] = {}
    for key, _label, _group, paths in FIELDS:
        value = None
        for expression in paths:
            value = _resolve(values, expression)
            if value is not None:
                break
        out[key] = value
    return out


def clean_manual(values: dict[str, Any]) -> dict[str, Optional[float]]:
    """Wpis ręczny: tylko znane pola, liczby w granicach rozsądku."""

    out: dict[str, Optional[float]] = {}
    for key in FIELD_KEYS:
        value = values.get(key)
        if value is None or value == "":
            out[key] = None
            continue
        number = float(value)
        if abs(number) > MAX_ABS_PLN:
            raise StatementError(f"Kwota w polu „{FIELD_LABELS[key]}” jest za duża.")
        out[key] = round(number, 2)
    unknown = set(values) - set(FIELD_KEYS)
    if unknown:
        raise StatementError("Nieznane pola: " + ", ".join(sorted(unknown)))
    return out


# ── Księga NEXUSA ────────────────────────────────────────────────────────────


def _ledger_segment(number: str) -> Optional[str]:
    text = (number or "").strip().rstrip(")")
    return text or None


def _flatten_ledger(
    nodes: Iterable[dict[str, Any]], prefix: str, path: list[str], out: dict
) -> None:
    for node in nodes:
        segment = _ledger_segment(node.get("number", ""))
        if segment is None or segment == "–":
            continue
        here = [*path, segment]
        out[prefix + ".".join(here)] = round(node.get("amount", 0) / 100, 2)
        _flatten_ledger(node.get("children") or [], prefix, here, out)


def ledger_paths(report: dict[str, Any]) -> dict[str, Optional[float]]:
    """Ścieżki → kwoty (PLN) z wyniku ``ledger.statements.statements`` (grosze)."""

    out: dict[str, Optional[float]] = {}
    balance = report.get("balance") or {}
    out["assets:"] = round((balance.get("assets_total") or 0) / 100, 2)
    out["liabilities:"] = round((balance.get("liabilities_total") or 0) / 100, 2)
    _flatten_ledger(balance.get("assets") or [], "assets:", [], out)
    _flatten_ledger(balance.get("liabilities") or [], "liabilities:", [], out)
    for line in (report.get("income") or {}).get("lines") or []:
        letter = line.get("number")
        if not letter:
            continue
        out[f"income:{letter}"] = round((line.get("amount") or 0) / 100, 2)
        for child in line.get("children") or []:
            roman = child.get("number")
            if roman:
                out[f"income:{letter}.{roman}"] = round(
                    (child.get("amount") or 0) / 100, 2
                )
    return out
