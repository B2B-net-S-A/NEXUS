"""Odczyt pliku kontrahentów z eBI24 („Partnerzy → Pobierz”), XLSX albo CSV.

Nagłówków eksportu nie znamy co do litery, więc kolumny dopasowujemy po
aliasach (bez wielkości liter, polskich znaków i spacji): najpierw całe
słowo, potem początek nagłówka („Konto kosztowe (Symfonia)” → konto
kosztowe). Wiersz nagłówka szukamy w pierwszych 10 wierszach — eksport bywa
poprzedzony tytułem.

Wynik to wiersze gotowe do zapisu i błędy z numerem wiersza pliku; sam zapis
(nowe, zmienione, bez zmian) liczy ``counterparties.apply_import``.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from app.services.finance_ledger import identifiers
from app.services.finance_ledger_schema import (
    ACCOUNT_MAX,
    NAME_MAX,
    SYMFONIA_ID_MAX,
)

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 10_000
HEADER_SCAN_ROWS = 10

#: Pole → aliasy nagłówka po ``identifiers.fold``.
ALIASES: dict[str, tuple[str, ...]] = {
    "name": (
        "nazwakontrahenta",
        "nazwapartnera",
        "pelnanazwa",
        "nazwapelna",
        "nazwafirmy",
        "kontrahent",
        "partner",
        "nazwa",
        "name",
    ),
    "id_type": (
        "typidentyfikatora",
        "rodzajidentyfikatora",
        "identyfikatortyp",
        "typnumeru",
        "typid",
    ),
    "identifier": (
        "numeridentyfikacyjny",
        "identyfikatorpodatkowy",
        "nipidentyfikator",
        "identyfikator",
        "nippesel",
        "numernip",
        "nrnip",
        "nipue",
        "vatid",
        "taxid",
        "nip",
    ),
    "pesel": ("pesel",),
    "street": ("adresulica", "ulicainr", "ulica", "adres", "street"),
    "postal_code": ("kodpocztowy", "kodpoczt", "postcode", "zip"),
    "city": ("miejscowosc", "miasto", "city"),
    "country": ("kodkraju", "kraj", "country"),
    "email": ("adresemail", "email", "mail"),
    "symfonia_partner_id": (
        "idkontrahentawsymfonii",
        "idpartnerasymfonia",
        "symfoniapartnerid",
        "idwsymfonii",
        "idsymfonii",
        "symfoniaid",
        "idsymfonia",
        "kodsymfonia",
        "idpartnera",
        "symfonia",
    ),
    "cost_account": (
        "kontokosztowe",
        "kontokosztow",
        "kontokosztu",
        "kontozakupu",
        "kontozakupowe",
    ),
    "revenue_account": (
        "kontoprzychodowe",
        "kontoprzychodow",
        "kontoprzychodu",
        "kontosprzedazy",
        "kontosprzedazowe",
    ),
}
#: Krótkie aliasy, które jako początek nagłówka mylą („Partner handlowy ID”).
_EXACT_ONLY = frozenset({"kraj", "mail", "partner", "typid", "zip"})
_ANYWHERE = frozenset(
    {"symfonia_partner_id", "cost_account", "revenue_account", "postal_code"}
)
_COUNTRY_WORDS = {"polska": "PL", "poland": "PL", "niemcy": "DE", "germany": "DE"}
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_ACCOUNT = re.compile(r"[0-9A-Za-z][0-9A-Za-z\-./]*")


class ImportFileError(ValueError):
    """Plik, którego nie da się przeczytać — zdanie po polsku."""


@dataclass
class ParsedRow:
    line: int
    id_type: Optional[str]
    id_value: Optional[str]
    values: dict[str, Optional[str]]


@dataclass
class ParsedFile:
    columns: dict[str, str] = field(default_factory=dict)
    rows: list[ParsedRow] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    skipped_empty: int = 0


def match_header(raw: Any) -> Optional[str]:
    """Nagłówek kolumny → pole kartoteki albo ``None``."""

    word = identifiers.fold(str(raw or ""))
    if not word:
        return None
    for name, aliases in ALIASES.items():
        if word in aliases:
            return name
    # Początek nagłówka, a dla kont i Symfonii dowolne miejsce; wygrywa
    # najdłuższy alias — „Symfonia: konto kosztowe” to konto, nie ID Symfonii,
    # a „NIP kontrahenta” to NIP, nie nazwa.
    best: Optional[tuple[int, str]] = None
    for name, aliases in ALIASES.items():
        for alias in aliases:
            if alias in _EXACT_ONLY:
                continue
            hit = word.startswith(alias) or (
                name in _ANYWHERE and len(alias) >= 8 and alias in word
            )
            if hit and (best is None or len(alias) > best[0]):
                best = (len(alias), name)
    return best[1] if best else None


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        # Excel trzyma NIP i ID jako liczbę: 5260300517.0 → „5260300517”.
        value = int(value)
    return " ".join(str(value).split())


def _sheet_rows(content: bytes) -> list[list[str]]:
    if content[:4] == b"PK\x03\x04":
        try:
            from openpyxl import load_workbook  # noqa: PLC0415

            book = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        except Exception as exc:  # noqa: BLE001 — uszkodzony plik to błąd pliku
            raise ImportFileError("Nie udało się otworzyć pliku XLSX.") from exc
        try:
            sheet = book.worksheets[0]
            rows = []
            for row in sheet.iter_rows(values_only=True):
                rows.append([_cell(value) for value in row])
                if len(rows) > MAX_ROWS + HEADER_SCAN_ROWS:
                    break
            return rows
        finally:
            book.close()
    for encoding in ("utf-8-sig", "cp1250"):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover — cp1250 dekoduje prawie wszystko
        raise ImportFileError("Nie rozpoznano kodowania pliku CSV.")
    sample = text[:4096]
    delimiter = max((";", ",", "\t"), key=sample.count)
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    return [[_cell(value) for value in row] for row in reader]


def _header(rows: list[list[str]]) -> tuple[int, dict[int, str]]:
    for index, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        columns: dict[int, str] = {}
        for position, raw in enumerate(row):
            name = match_header(raw)
            if name and name not in columns.values():
                columns[position] = name
        if "name" in columns.values() and len(columns) >= 2:
            return index, columns
    raise ImportFileError(
        "Nie znaleziono wiersza nagłówka z kolumną „Nazwa” i przynajmniej jedną "
        "z kolumn: NIP/Identyfikator, Symfonia ID, Konto kosztowe."
    )


def _country(raw: str) -> Optional[str]:
    word = identifiers.fold(raw)
    if not word:
        return None
    if len(word) == 2:
        return word.upper()
    return _COUNTRY_WORDS.get(word)


def _account(raw: str, label: str) -> Optional[str]:
    value = raw.replace(" ", "")
    if not value:
        return None
    if len(value) > ACCOUNT_MAX or not _ACCOUNT.fullmatch(value):
        raise identifiers.IdentifierError(
            f"{label}: niepoprawny numer konta „{raw[:40]}”."
        )
    return value


def clean_values(raw: dict[str, str]) -> dict[str, Optional[str]]:
    """Pola kartoteki z tekstu (import i formularz); błąd = ``IdentifierError``."""

    values: dict[str, Optional[str]] = {}
    name = raw.get("name", "").strip()
    values["name"] = name[:NAME_MAX] or None
    values["street"] = raw.get("street", "").strip()[:255] or None
    values["postal_code"] = raw.get("postal_code", "").strip()[:16] or None
    values["city"] = raw.get("city", "").strip()[:120] or None
    values["country"] = _country(raw.get("country", ""))
    email = raw.get("email", "").strip()
    values["email"] = email[:255] if _EMAIL.fullmatch(email) else None
    symfonia = raw.get("symfonia_partner_id", "").strip()
    if len(symfonia) > SYMFONIA_ID_MAX:
        raise identifiers.IdentifierError("ID Symfonii ma najwyżej 32 znaki.")
    values["symfonia_partner_id"] = symfonia or None
    values["cost_account"] = _account(raw.get("cost_account", ""), "Konto kosztowe")
    values["revenue_account"] = _account(
        raw.get("revenue_account", ""), "Konto przychodowe"
    )
    return values


def _row_error(errors: list[dict[str, Any]], line: int, message: str) -> None:
    errors.append({"line": line, "message": message})


def parse(content: bytes) -> ParsedFile:
    """Plik → wiersze kartoteki i błędy. Duplikat w pliku to błąd drugiego wiersza."""

    if not content:
        raise ImportFileError("Plik jest pusty.")
    if len(content) > MAX_BYTES:
        raise ImportFileError("Plik ma więcej niż 5 MB.")
    rows = _sheet_rows(content)
    header_index, columns = _header(rows)
    parsed = ParsedFile(columns={str(pos): name for pos, name in columns.items()})
    seen_ids: dict[tuple[str, str], int] = {}
    seen_symfonia: dict[str, int] = {}
    data = rows[header_index + 1 :]
    if len(data) > MAX_ROWS:
        raise ImportFileError(f"Plik ma więcej niż {MAX_ROWS} wierszy.")
    for offset, row in enumerate(data):
        line = header_index + offset + 2
        raw = {
            name: (row[pos] if pos < len(row) else "") for pos, name in columns.items()
        }
        if not any(value.strip() for value in raw.values()):
            parsed.skipped_empty += 1
            continue
        try:
            identifier = identifiers.normalize(
                raw.get("identifier") or "", raw.get("id_type")
            )
            if identifier is None and raw.get("pesel"):
                identifier = identifiers.normalize(raw["pesel"], "pesel")
            values = clean_values(raw)
        except identifiers.IdentifierError as exc:
            _row_error(parsed.errors, line, str(exc))
            continue
        if not values["name"]:
            _row_error(parsed.errors, line, "Brak nazwy kontrahenta.")
            continue
        if identifier is None and not values["symfonia_partner_id"]:
            _row_error(parsed.errors, line, "Brak identyfikatora i ID Symfonii.")
            continue
        if identifier is not None:
            key = (identifier.type, identifier.value)
            if key in seen_ids:
                _row_error(
                    parsed.errors,
                    line,
                    f"Ten sam {identifiers.TYPE_LABELS[identifier.type]} co w wierszu "
                    f"{seen_ids[key]}.",
                )
                continue
            seen_ids[key] = line
        symfonia = values["symfonia_partner_id"]
        if symfonia:
            if symfonia in seen_symfonia:
                _row_error(
                    parsed.errors,
                    line,
                    f"To samo ID Symfonii co w wierszu {seen_symfonia[symfonia]}.",
                )
                continue
            seen_symfonia[symfonia] = line
        parsed.rows.append(
            ParsedRow(
                line=line,
                id_type=identifier.type if identifier else None,
                id_value=identifier.value if identifier else None,
                values=values,
            )
        )
    return parsed
