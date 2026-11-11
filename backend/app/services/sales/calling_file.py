"""Lista do kampanii dzwonienia z pliku CSV albo Excela: odczyt i walidacja na granicy.

Plik przygotowuje człowiek, więc nagłówki bywają różne: kolumny rozpoznajemy po
nazwie bez polskich znaków i wielkości liter. Wymagane są dwie: firma i telefon.
Moduł jest czysty (bez bazy), a los wierszy ustala ``calling_import.py``.

Granice: rozszerzenie i sygnatura pliku, rozmiar, liczba wierszy i kolumn, rozmiar
po rozpakowaniu (xlsx to archiwum zip), znaki sterujące i długość każdej komórki.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from app.services.m365.matcher import PUBLIC_EMAIL_DOMAINS

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_ROWS = 2000
MAX_COLUMNS = 60
#: Lista 2000 wierszy to po rozpakowaniu poniżej 1 MB; zapas chroni proces web przed
#: arkuszem, który z 2 MB rozwija się do dziesiątek megabajtów XML-a.
MAX_UNZIPPED_BYTES = 10 * 1024 * 1024
MAX_ZIP_MEMBERS = 500
ALLOWED_EXTENSIONS: tuple[str, ...] = (".csv", ".xlsx")
MIN_PHONE_DIGITS = 7
MAX_PHONE_DIGITS = 15

BAD_TYPE_DETAIL = "Import przyjmuje plik CSV albo Excel (.xlsx)."
TOO_BIG_DETAIL = "Plik przekracza limit 2 MB."
EMPTY_DETAIL = "Plik jest pusty albo nie ma w nim wierszy pod nagłówkiem."
TOO_MANY_ROWS_DETAIL = (
    f"Plik ma więcej niż {MAX_ROWS} wierszy. Podziel listę na mniejsze części."
)
UNREADABLE_DETAIL = (
    "Nie udało się odczytać pliku. Zapisz go ponownie jako CSV albo .xlsx."
)
NO_COMPANY_COLUMN_DETAIL = "W pliku brakuje kolumny z nazwą firmy (np. „Firma”)."
NO_PHONE_COLUMN_DETAIL = "W pliku brakuje kolumny z telefonem (np. „Telefon”)."

_LIMITS: dict[str, int] = {
    "company": 500,
    "person": 255,
    "first_name": 120,
    "last_name": 120,
    "title": 255,
    "phone": 60,
    "email": 255,
    "website": 255,
    "nip": 20,
    "industry": 255,
    "note": 1000,
    "linkedin": 500,
}

_HEADERS: dict[str, tuple[str, ...]] = {
    "company": (
        "firma",
        "nazwa firmy",
        "nazwa",
        "spolka",
        "organizacja",
        "company",
        "company name",
    ),
    "person": (
        "osoba",
        "imie i nazwisko",
        "osoba kontaktowa",
        "kontakt",
        "name",
        "full name",
        "contact",
    ),
    "first_name": ("imie", "first name"),
    "last_name": ("nazwisko", "last name"),
    "title": ("stanowisko", "rola", "funkcja", "title", "job title", "position"),
    "phone": (
        "telefon",
        "tel",
        "nr telefonu",
        "numer telefonu",
        "numer",
        "komorka",
        "telefon komorkowy",
        "phone",
        "mobile",
    ),
    "email": ("e mail", "email", "mail", "adres e mail", "adres email"),
    "website": ("www", "strona", "strona www", "domena", "website", "url"),
    "nip": ("nip",),
    "industry": ("branza", "industry"),
    "note": ("notatka", "uwagi", "komentarz", "opis", "note", "notes"),
    "linkedin": ("linkedin", "profil linkedin", "linkedin url", "link linkedin"),
}
_FIELD_BY_HEADER = {
    header: field for field, headers in _HEADERS.items() for header in headers
}

_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f​-‏ - ﻿]")
_SPACES = re.compile(r"\s+")
_EMAIL = re.compile(r"^[^@\s]+@([a-z0-9-]+\.)+[a-z]{2,}$")
_DOMAIN = re.compile(r"^([a-z0-9-]+\.)+[a-z]{2,}$")
_SITE = re.compile(r"^([a-z]+://)?(www\.)?([^/:?#\s]+)")
_XLSX_MAGIC = b"PK\x03\x04"


class ListFileError(ValueError):
    """Plik nie przechodzi walidacji; treść jest komunikatem dla użytkownika."""

    def __init__(self, detail: str, *, too_large: bool = False) -> None:
        super().__init__(detail)
        self.detail = detail
        self.too_large = too_large


@dataclass(frozen=True)
class ListRow:
    #: Numer wiersza w pliku (nagłówek to 1), żeby dało się go znaleźć w arkuszu.
    line: int
    company: str
    person: Optional[str] = None
    title: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    nip: Optional[str] = None
    industry: Optional[str] = None
    note: Optional[str] = None
    #: Profil LinkedIn osoby (tylko adres linkedin.com po http/https).
    linkedin: Optional[str] = None


@dataclass(frozen=True)
class ListFile:
    rows: list[ListRow]
    #: Wiersze z danymi, ale bez nazwy firmy: nie ma do czego ich przypiąć.
    without_company: int


# ── Wartości ──────────────────────────────────────────────────────────────


def clean_cell(value: Any, limit: int) -> Optional[str]:
    """Tekst komórki bez znaków sterujących, przycięty do długości kolumny."""

    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        # Excel trzyma numer telefonu i NIP jako liczbę: 600100200.0.
        value = int(value)
    text = _SPACES.sub(" ", _CONTROL.sub(" ", str(value))).strip()
    return text[:limit].strip() or None


def header_key(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).replace("ł", "l")
    return _SPACES.sub(" ", re.sub(r"[^a-z0-9]+", " ", text)).strip()


def phone_digits(value: Optional[str]) -> Optional[str]:
    """Numer do porównań: same cyfry bez polskiego prefiksu; ``None`` dla śmieci."""

    digits = re.sub(r"\D", "", value or "")
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 11 and digits.startswith("48"):
        digits = digits[2:]
    if not MIN_PHONE_DIGITS <= len(digits) <= MAX_PHONE_DIGITS:
        return None
    return digits


def valid_email(value: Optional[str]) -> Optional[str]:
    text = (value or "").strip().lower()
    return text if _EMAIL.match(text) else None


def site_domain(value: Optional[str]) -> Optional[str]:
    """Domena z adresu strony albo samej domeny; bez schematu, „www.” i ścieżki."""

    match = _SITE.match((value or "").strip().lower())
    domain = match.group(3) if match else ""
    return domain if _DOMAIN.match(domain) else None


def row_domain(row: ListRow) -> Optional[str]:
    """Domena firmy z wiersza: ze strony, a bez niej z adresu osoby (nie z poczty publicznej)."""

    domain = site_domain(row.website)
    if domain:
        return domain
    email = valid_email(row.email)
    if not email:
        return None
    domain = email.rsplit("@", 1)[1]
    return None if domain in PUBLIC_EMAIL_DOMAINS else domain


def person_key(value: Optional[str]) -> Optional[str]:
    return header_key(value) or None


# ── Odczyt ────────────────────────────────────────────────────────────────


def _extension(filename: str) -> str:
    dot = filename.rfind(".")
    return filename[dot:].lower() if dot >= 0 else ""


def _csv_rows(payload: bytes) -> Iterable[list[Any]]:
    if b"\x00" in payload:
        raise ListFileError(UNREADABLE_DETAIL)
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Excel na Windows zapisuje „CSV (rozdzielany przecinkami)” w cp1250.
        text = payload.decode("cp1250", errors="replace")
    first_line = text.split("\n", 1)[0]
    delimiter = max(";,\t|", key=first_line.count)
    try:
        yield from csv.reader(io.StringIO(text), delimiter=delimiter)
    except csv.Error as exc:
        raise ListFileError(UNREADABLE_DETAIL) from exc


def _xlsx_rows(payload: bytes) -> Iterable[tuple[Any, ...]]:
    if not payload.startswith(_XLSX_MAGIC):
        raise ListFileError(UNREADABLE_DETAIL)
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            members = archive.infolist()
            if (
                len(members) > MAX_ZIP_MEMBERS
                or sum(member.file_size for member in members) > MAX_UNZIPPED_BYTES
            ):
                raise ListFileError(TOO_BIG_DETAIL, too_large=True)
        from openpyxl import load_workbook

        workbook = load_workbook(io.BytesIO(payload), read_only=True, data_only=True)
    except ListFileError:
        raise
    except Exception as exc:  # noqa: BLE001 — każdy błąd biblioteki to zły plik
        raise ListFileError(UNREADABLE_DETAIL) from exc
    try:
        sheet = workbook.worksheets[0] if workbook.worksheets else None
        if sheet is None:
            raise ListFileError(EMPTY_DETAIL)
        yield from sheet.iter_rows(
            values_only=True, max_row=MAX_ROWS + 2, max_col=MAX_COLUMNS
        )
    finally:
        workbook.close()


def _columns(header: Iterable[Any]) -> dict[str, int]:
    columns: dict[str, int] = {}
    for index, cell in enumerate(header):
        if index >= MAX_COLUMNS:
            break
        field = _FIELD_BY_HEADER.get(header_key(cell))
        if field is not None:
            columns.setdefault(field, index)
    if "company" not in columns:
        raise ListFileError(NO_COMPANY_COLUMN_DETAIL)
    if "phone" not in columns:
        raise ListFileError(NO_PHONE_COLUMN_DETAIL)
    return columns


_LINKEDIN = re.compile(r"^https?://([a-z]{2,3}\.)?linkedin\.com/\S+$", re.IGNORECASE)


def linkedin_url(value: Optional[str]) -> Optional[str]:
    """Adres profilu z komórki; inne adresy i tekst odpadają na granicy."""

    if not value:
        return None
    candidate = value.strip()
    if candidate.lower().startswith(("linkedin.com/", "www.linkedin.com/")):
        candidate = f"https://{candidate}"
    return candidate if _LINKEDIN.match(candidate) else None


def _row(
    line: int, cells: list[Any], columns: dict[str, int]
) -> Optional[dict[str, Any]]:
    values = {
        field: clean_cell(cells[index] if index < len(cells) else None, _LIMITS[field])
        for field, index in columns.items()
    }
    if not any(values.values()):
        return None
    person = values.get("person") or " ".join(
        part for part in (values.get("first_name"), values.get("last_name")) if part
    )
    return {
        "line": line,
        "company": values.get("company") or "",
        "person": (person or "")[: _LIMITS["person"]] or None,
        "title": values.get("title"),
        "phone": values.get("phone") if phone_digits(values.get("phone")) else None,
        "email": valid_email(values.get("email")),
        "website": values.get("website"),
        "nip": values.get("nip"),
        "industry": values.get("industry"),
        "note": values.get("note"),
        "linkedin": linkedin_url(values.get("linkedin")),
    }


def parse_list_file(filename: str, payload: bytes) -> ListFile:
    """Wiersze listy z pliku; ``ListFileError`` z komunikatem, gdy plik odpada."""

    extension = _extension(filename or "")
    if extension not in ALLOWED_EXTENSIONS:
        raise ListFileError(BAD_TYPE_DETAIL)
    if len(payload) > MAX_FILE_BYTES:
        raise ListFileError(TOO_BIG_DETAIL, too_large=True)
    if not payload.strip():
        raise ListFileError(EMPTY_DETAIL)
    raw = _xlsx_rows(payload) if extension == ".xlsx" else _csv_rows(payload)

    columns: Optional[dict[str, int]] = None
    rows: list[ListRow] = []
    without_company = 0
    for line, cells in enumerate(raw, start=1):
        cells = list(cells or ())
        if columns is None:
            if not any(clean_cell(cell, 255) for cell in cells):
                continue
            columns = _columns(cells)
            continue
        values = _row(line, cells, columns)
        if values is None:
            continue
        if len(rows) + without_company >= MAX_ROWS:
            raise ListFileError(TOO_MANY_ROWS_DETAIL)
        if not values["company"]:
            without_company += 1
            continue
        rows.append(ListRow(**values))
    if columns is None or (not rows and not without_company):
        raise ListFileError(EMPTY_DETAIL)
    return ListFile(rows=rows, without_company=without_company)
