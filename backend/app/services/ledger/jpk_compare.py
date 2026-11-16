"""Porównanie JPK_V7M z NEXUSA z plikiem z Symfonii (K5b-3b).

Decyzja Artura z 15.11.2026: w miesiącach równoległych NEXUS pokazuje różnice
między swoim JPK a plikiem z Symfonii — wiersz po wierszu i sumy pól
deklaracji. Prawdziwy plik (październik 2026) przyśle Finanse.

* Plik z Symfonii czytamy bez sieci i bez encji (lxml), po nazwach elementów
  bez przestrzeni nazw — wzór (3) i wcześniejsze mają te same nazwy pól.
  Okres pliku musi być miesiącem porównania. Pliku nie zapisujemy.
* Strona NEXUSA = rejestry miesiąca (pełne — D2) i deklaracja liczona jak przy
  „Przygotuj JPK”, z P_39 z pliku Symfonii (nadwyżka jest wejściem, nie
  wynikiem; jej różnica widać osobno).
* Wiersz = numer dowodu (bez spacji i wielkości liter) i numer kontrahenta
  (bez kodu kraju); te same klucze się sumują. Różnice: pola ``K_`` w groszach,
  znaczniki GTU/TP, wiersze tylko po jednej stronie.
* Plik zawiera faktury osób zespołu — porównuje osoba z Płacami albo
  administrator (jak pobranie JPK).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from lxml import etree
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.finance_ledger.costs import LedgerError
from app.services.ledger import jpk, vat
from app.services.ledger.documents import Viewer
from app.services.ledger.settings import MARKERS, LedgerSettings

#: Plik JPK z Symfonii: do 20 MB (miesiąc to kilka tysięcy wierszy).
MAX_BYTES = 20 * 1024 * 1024
LISTED_MAX = 200
ONLY_COMPARE = (
    "JPK zawiera faktury osób zespołu — porównuje go osoba z Płacami albo "
    "administrator."
)
SALES = ("SprzedazWiersz", "DowodSprzedazy", "NrKontrahenta", jpk.SALES_K)
PURCHASES = ("ZakupWiersz", "DowodZakupu", "NrDostawcy", jpk.PURCHASE_K)

Key = tuple[str, str]


def _local(node: Any) -> str:
    tag = node.tag
    return tag.split("}", 1)[1] if isinstance(tag, str) and "}" in tag else str(tag)


def _child(node: Any, name: str) -> Optional[str]:
    for child in node:
        if _local(child) == name:
            return (child.text or "").strip()
    return None


def _grosze(text: Optional[str]) -> int:
    try:
        return int((Decimal(text or "0") * 100).to_integral_value())
    except (InvalidOperation, ValueError):
        raise LedgerError(
            f"Plik z Symfonii: niepoprawna kwota „{(text or '')[:20]}”.", status=422
        ) from None


def party_number(raw: Optional[str], country: Optional[str]) -> str:
    """Numer kontrahenta bez kodu kraju po obu stronach (Symfonia pisze VAT UE
    z prefiksem, NEXUS bez); „BRAK” zostaje „BRAK” (przegląd K5b-3b)."""

    compact = "".join(ch for ch in (raw or "") if ch.isalnum()).upper()
    if not compact or compact == jpk.BRAK:
        return jpk.BRAK
    return jpk.counterparty(compact, country)[1]


def doc_key(number: Optional[str], party: Optional[str]) -> Key:
    """Klucz wiersza: numer dowodu i kontrahenta bez spacji i wielkości liter."""

    clean = "".join((number or "").split()).upper()
    who = "".join(ch for ch in (party or "") if ch.isalnum()).upper()
    return clean, who


def parse(content: bytes) -> dict[str, Any]:
    """JPK_V7M z Symfonii → okres, wiersze (pola K w groszach, znaczniki), P_."""

    if len(content) > MAX_BYTES:
        raise LedgerError("Plik z Symfonii jest za duży (najwyżej 20 MB).", status=413)
    parser = etree.XMLParser(
        resolve_entities=False, no_network=True, huge_tree=False, load_dtd=False
    )
    try:
        root = etree.fromstring(content, parser)
    except etree.XMLSyntaxError:
        raise LedgerError("To nie jest plik XML JPK.", status=422) from None
    if _local(root) != "JPK":
        raise LedgerError("To nie jest plik JPK_V7M (brak elementu JPK).", status=422)
    head = next((node for node in root if _local(node) == "Naglowek"), None)
    try:
        year = int(_child(head, "Rok") or "")
        month = int(_child(head, "Miesiac") or "")
    except (TypeError, ValueError):
        raise LedgerError(
            "Plik JPK bez roku i miesiąca w nagłówku.", status=422
        ) from None
    out: dict[str, Any] = {"year": year, "month": month, "declaration": {}}
    for kind, (row_tag, number_tag, party_tag, fields) in (
        ("sales", SALES),
        ("purchases", PURCHASES),
    ):
        rows: dict[Key, dict[str, Any]] = {}
        for node in root.iter():
            if _local(node) != row_tag:
                continue
            key = doc_key(
                _child(node, number_tag),
                party_number(
                    _child(node, party_tag), _child(node, "KodKrajuNadaniaTIN")
                ),
            )
            entry = rows.setdefault(
                key,
                {
                    "number": _child(node, number_tag) or "",
                    "party": _child(node, "NazwaKontrahenta")
                    or _child(node, "NazwaDostawcy")
                    or "",
                    "fields": defaultdict(int),
                    "markers": set(),
                },
            )
            for child in node:
                name = _local(child)
                if name in fields:
                    entry["fields"][name] += _grosze(child.text)
                elif name in MARKERS and (child.text or "").strip() == "1":
                    entry["markers"].add(name)
        out[kind] = rows
    positions = next(
        (node for node in root.iter() if _local(node) == "PozycjeSzczegolowe"), None
    )
    for child in positions if positions is not None else []:
        name = _local(child)
        if name.startswith("P_") and name != "P_ORDZU":
            try:
                out["declaration"][name] = int(Decimal((child.text or "0").strip()))
            except (InvalidOperation, ValueError):
                continue
    return out


def _nexus_rows(rows: list[dict[str, Any]], kind: str) -> dict[Key, dict[str, Any]]:
    sales = kind == "sales"
    out: dict[Key, dict[str, Any]] = {}
    for row in rows:
        key = doc_key(
            row["number"], party_number(row.get("tax_id"), row.get("country"))
        )
        entry = out.setdefault(
            key,
            {
                "number": row["number"],
                "party": row.get("counterparty") or "",
                "fields": defaultdict(int),
                "markers": set(),
                "document_id": row.get("document_id"),
            },
        )
        for name, value in jpk.row_fields(row["groups"]).items():
            entry["fields"][name] += value
        if sales:
            entry["markers"].update(row.get("markers") or ())
    return out


def _diff_rows(
    kind: str, nexus: dict[Key, dict[str, Any]], symfonia: dict[Key, dict[str, Any]]
) -> dict[str, Any]:
    only_nexus, only_symfonia, different = [], [], []
    matched = 0
    for key, mine in nexus.items():
        theirs = symfonia.get(key)
        if theirs is None:
            only_nexus.append(_side(kind, mine))
            continue
        fields = {
            name: {
                "nexus": mine["fields"].get(name, 0),
                "symfonia": theirs["fields"].get(name, 0),
            }
            for name in sorted(set(mine["fields"]) | set(theirs["fields"]))
            if mine["fields"].get(name, 0) != theirs["fields"].get(name, 0)
        }
        markers = sorted(mine["markers"] ^ theirs["markers"])
        if fields or markers:
            different.append(
                {
                    **_side(kind, mine),
                    "fields": fields,
                    "markers": {
                        "nexus": sorted(mine["markers"]),
                        "symfonia": sorted(theirs["markers"]),
                    }
                    if markers
                    else None,
                }
            )
        else:
            matched += 1
    for key, theirs in symfonia.items():
        if key not in nexus:
            only_symfonia.append(_side(kind, theirs))
    return {
        "kind": kind,
        "nexus_rows": len(nexus),
        "symfonia_rows": len(symfonia),
        "matched": matched,
        "only_nexus": only_nexus[:LISTED_MAX],
        "only_nexus_count": len(only_nexus),
        "only_symfonia": only_symfonia[:LISTED_MAX],
        "only_symfonia_count": len(only_symfonia),
        "different": different[:LISTED_MAX],
        "different_count": len(different),
    }


def _side(kind: str, entry: dict[str, Any]) -> dict[str, Any]:
    fields = entry["fields"]
    tax = jpk.TAX_PLUS if kind == "sales" else jpk.INPUT_TAX
    return {
        "number": entry["number"],
        "party": entry["party"],
        "document_id": entry.get("document_id"),
        "vat": sum(fields.get(name, 0) for name in tax)
        - (
            sum(fields.get(name, 0) for name in jpk.TAX_MINUS) if kind == "sales" else 0
        ),
    }


def compare(data: dict[str, Any], symfonia: dict[str, Any]) -> dict[str, Any]:
    """Różnice rejestrów NEXUSA (``vat.registers``) i pliku z Symfonii."""

    sums: dict[str, int] = defaultdict(int)
    for kind in ("sales", "purchases"):
        for row in data[kind]:
            for name, value in jpk.row_fields(row["groups"]).items():
                sums[name] += value
    surplus = int(symfonia["declaration"].get("P_39", 0))
    mine = jpk.declaration(dict(sums), surplus=surplus)
    theirs = symfonia["declaration"]
    declaration = [
        {"field": name, "nexus": mine.get(name, 0), "symfonia": theirs.get(name, 0)}
        for name in jpk.P_ORDER
        if name in mine or name in theirs
    ]
    rows = [
        _diff_rows(kind, _nexus_rows(data[kind], kind), symfonia[kind])
        for kind in ("sales", "purchases")
    ]
    differences = sum(1 for item in declaration if item["nexus"] != item["symfonia"])
    differences += sum(
        item["only_nexus_count"] + item["only_symfonia_count"] + item["different_count"]
        for item in rows
    )
    return {
        "year": data["year"],
        "month": data["month"],
        "declaration": declaration,
        "rows": rows,
        "differences": differences,
        "problems": [
            {"number": row["number"], "detail": row["problem"]}
            for kind in ("sales", "purchases")
            for row in data[kind]
            if row.get("problem")
        ][:LISTED_MAX],
    }


async def run(
    db: AsyncSession,
    viewer: Viewer,
    settings: LedgerSettings,
    *,
    year: int,
    month: int,
    content: bytes,
) -> dict[str, Any]:
    if not jpk.can_download(viewer):
        raise LedgerError(ONLY_COMPARE, status=403)
    symfonia = parse(content)
    if (symfonia["year"], symfonia["month"]) != (year, month):
        raise LedgerError(
            f"Plik z Symfonii jest za {symfonia['month']:02d}.{symfonia['year']}, "
            f"a porównujesz {month:02d}.{year}.",
            status=422,
        )
    data = await vat.registers(
        db, replace(viewer, payroll=True), settings, year=year, month=month
    )
    return compare(data, symfonia)
