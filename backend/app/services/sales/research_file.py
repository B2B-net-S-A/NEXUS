"""Lista osób z researchu (CSV albo Excel): odczyt i walidacja na granicy.

Plik wgrywa człowiek, ale jego treść pochodzi z researchu cudzych stron, więc
to dane niezaufane: limit rozmiaru, wierszy i kolumn, rozmiar po rozpakowaniu
(xlsx to archiwum zip), znaki sterujące wycięte, długość każdej komórki,
linki tylko http(s). Błąd w wierszu nie wywraca pliku: wiersz bez firmy albo
osoby trafia na listę pominiętych z powodem, a zła wartość pola opcjonalnego
(adres, link, telefon) odpada z ostrzeżeniem przy wierszu.

Moduł jest czysty (bez bazy); co stanie się z wierszem, ustala
``research_import.py``. Poziom decyzji bierze się z kolumny pliku, a bez niej
z nazwy stanowiska (decyzja Artura z 10.11.2026): zarząd i VP to poziom 1,
Head i Director poziom 2, reszta poziom 3. Człowiek zmienia go w przeglądzie.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Optional

from app.services.m365.matcher import PUBLIC_EMAIL_DOMAINS
from app.services.sales.companies import http_url

MAX_FILE_BYTES = 2 * 1024 * 1024
#: Lista z researchu to dziesiątki osób; limit chroni przegląd i proces web.
MAX_ROWS = 500
MAX_COLUMNS = 40
#: Arkusz 500 wierszy to po rozpakowaniu ułamek megabajta; zapas zatrzymuje plik,
#: który z 2 MB rozwija się do dziesiątek megabajtów XML-a.
MAX_UNZIPPED_BYTES = 10 * 1024 * 1024
MAX_ZIP_MEMBERS = 500
ALLOWED_EXTENSIONS: tuple[str, ...] = (".csv", ".xlsx")
MIN_PHONE_DIGITS = 7
MAX_PHONE_DIGITS = 15

CONFIRMED = "confirmed"
TO_VERIFY = "to_verify"
DEFAULT_LEVEL = 3

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
NO_PERSON_COLUMN_DETAIL = (
    "W pliku brakuje kolumny z osobą (np. „Imię i nazwisko” albo „Imię” i „Nazwisko”)."
)

NO_COMPANY_REASON = "brak nazwy firmy"
NO_PERSON_REASON = "brak imienia i nazwiska"

#: Limity jak w mapie decyzyjnej (``decision_map._DecisionPersonFields``).
_LIMITS: dict[str, int] = {
    "company": 500,
    "name": 255,
    "first_name": 120,
    "last_name": 120,
    "title": 255,
    "email": 320,
    "phone": 50,
    "linkedin": 512,
    "source_url": 1000,
    "website": 255,
    "confidence": 60,
    "level": 60,
    "note": 2000,
}

_HEADERS: dict[str, tuple[str, ...]] = {
    "company": (
        "firma",
        "nazwa firmy",
        "spolka",
        "organizacja",
        "pracodawca",
        "company",
        "company name",
        "employer",
        "organization",
    ),
    "name": (
        "osoba",
        "imie i nazwisko",
        "nazwisko i imie",
        "osoba kontaktowa",
        "kontakt",
        "name",
        "full name",
        "person",
        "contact",
    ),
    "first_name": ("imie", "first name"),
    "last_name": ("nazwisko", "last name", "surname"),
    "title": (
        "stanowisko",
        "rola",
        "funkcja",
        "tytul",
        "title",
        "job title",
        "position",
        "role",
    ),
    "email": ("e mail", "email", "mail", "adres e mail", "adres email"),
    "phone": (
        "telefon",
        "tel",
        "nr telefonu",
        "numer telefonu",
        "komorka",
        "phone",
        "mobile",
    ),
    "linkedin": ("linkedin", "profil linkedin", "linkedin url", "profil"),
    "source_url": (
        "zrodlo",
        "link zrodlowy",
        "link do zrodla",
        "link",
        "source",
        "source url",
    ),
    "website": ("www", "strona", "strona www", "domena", "website", "domain"),
    "confidence": (
        "pewnosc",
        "pewne",
        "weryfikacja",
        "status weryfikacji",
        "status",
        "confidence",
        "verified",
    ),
    "level": ("poziom", "poziom decyzji", "level", "decision level"),
    "note": (
        "notatka",
        "uwagi",
        "komentarz",
        "opis",
        "uzasadnienie",
        "note",
        "notes",
    ),
}
_FIELD_BY_HEADER = {
    header: field for field, headers in _HEADERS.items() for header in headers
}

_CONFIRMED_WORDS = frozenset(
    """pewne pewny pewna potwierdzone potwierdzony potwierdzona zweryfikowane
    zweryfikowany zweryfikowana tak yes true 1 confirmed verified high wysoka""".split()
)

# Znaki sterujące, niewidoczne odstępy i znaczniki kierunku tekstu.
_CONTROL = re.compile("[\x00-\x1f\x7f-\x9f​-‏ - ⁠-⁯﻿]")
_SPACES = re.compile(r"\s+")
_EMAIL = re.compile(r"^[^@\s]+@([a-z0-9-]+\.)+[a-z]{2,}$")
_DOMAIN = re.compile(r"^([a-z0-9-]+\.)+[a-z]{2,}$")
_SITE = re.compile(r"^([a-z]+://)?(www\.)?([^/:?#\s]+)")
_XLSX_MAGIC = b"PK\x03\x04"

_LEVEL_1 = re.compile(
    r"\b(?:chief|ceo|cto|cio|cdo|cfo|coo|cmo|cpo|cso|cro|ciso|cdao|caio"
    r"|vp|svp|evp|vice president|president|prezes|wiceprezes"
    r"|czlon\w* zarzadu|board member|member of the board)\b"
)
_LEVEL_2 = re.compile(r"\b(?:head|director|dyrektor\w*)\b")


class ResearchFileError(ValueError):
    """Plik nie przechodzi walidacji; treść jest komunikatem dla użytkownika."""

    def __init__(self, detail: str, *, too_large: bool = False) -> None:
        super().__init__(detail)
        self.detail = detail
        self.too_large = too_large


@dataclass(frozen=True)
class ResearchRow:
    #: Numer wiersza w pliku (nagłówek to 1), żeby dało się go znaleźć w arkuszu.
    line: int
    company: str
    name: str
    title: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    linkedin_url: Optional[str] = None
    source_url: Optional[str] = None
    #: Domena firmy ze strony albo z adresu osoby; trafia na nową kartę firmy.
    domain: Optional[str] = None
    confidence: str = TO_VERIFY
    decision_level: int = DEFAULT_LEVEL
    note: Optional[str] = None
    #: Pola opcjonalne, które odpadły przy walidacji (zły adres, link, telefon).
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class SkippedRow:
    line: int
    reason: str


@dataclass(frozen=True)
class ResearchFile:
    rows: list[ResearchRow]
    skipped: list[SkippedRow]


# ── Wartości ──────────────────────────────────────────────────────────────


def clean_text(value: Any, limit: int) -> Optional[str]:
    """Tekst bez znaków sterujących, z pojedynczymi odstępami, przycięty do limitu."""

    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        # Excel trzyma numer telefonu jako liczbę: 600100200.0.
        value = int(value)
    text = _SPACES.sub(" ", _CONTROL.sub(" ", str(value))).strip()
    return text[:limit].strip() or None


def fold(value: Any) -> str:
    """Do porównań: małe litery, bez ogonków i interpunkcji, pojedyncze odstępy."""

    text = unicodedata.normalize("NFKD", str(value or "").lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).replace("ł", "l")
    return _SPACES.sub(" ", re.sub(r"[^a-z0-9]+", " ", text)).strip()


def person_key(name: Optional[str]) -> Optional[str]:
    """Klucz osoby do wykrywania powtórzeń: „Kowalski Jan” to „Jan Kowalski”."""

    return " ".join(sorted(fold(name).split())) or None


def valid_email(value: Optional[str]) -> Optional[str]:
    text = (value or "").strip().lower()
    return text if _EMAIL.match(text) else None


def valid_phone(value: Optional[str]) -> Optional[str]:
    digits = re.sub(r"\D", "", value or "")
    return value if MIN_PHONE_DIGITS <= len(digits) <= MAX_PHONE_DIGITS else None


def valid_link(value: Optional[str], limit: int) -> Optional[str]:
    """Adres http(s) nie dłuższy niż kolumna; wszystko inne to ``None``."""

    try:
        url = http_url(value)
    except ValueError:
        return None
    return url if url and len(url) <= limit else None


def site_domain(value: Optional[str]) -> Optional[str]:
    """Domena z adresu strony albo samej domeny; bez schematu, „www.” i ścieżki."""

    match = _SITE.match((value or "").strip().lower())
    domain = match.group(3) if match else ""
    return domain if _DOMAIN.match(domain) else None


def company_domain(website: Optional[str], email: Optional[str]) -> Optional[str]:
    """Domena firmy: ze strony, a bez niej z adresu osoby (nie z poczty publicznej)."""

    domain = site_domain(website)
    if domain:
        return domain
    if not email:
        return None
    domain = email.rsplit("@", 1)[1]
    return None if domain in PUBLIC_EMAIL_DOMAINS else domain


def confidence_of(value: Optional[str]) -> str:
    """„Pewne” tylko dla jasnego potwierdzenia; brak wartości to „do weryfikacji”."""

    return CONFIRMED if fold(value) in _CONFIRMED_WORDS else TO_VERIFY


def level_from_title(title: Optional[str]) -> int:
    """Poziom decyzji z nazwy stanowiska; bez rozpoznania poziom 3 (kierownicy)."""

    text = fold(title)
    if _LEVEL_1.search(text):
        return 1
    if _LEVEL_2.search(text):
        return 2
    return DEFAULT_LEVEL


def _level(value: Optional[str], title: Optional[str]) -> int:
    match = re.match(r"\s*([1-4])(?!\d)", value or "")
    return int(match.group(1)) if match else level_from_title(title)


# ── Odczyt ────────────────────────────────────────────────────────────────


def _extension(filename: str) -> str:
    dot = filename.rfind(".")
    return filename[dot:].lower() if dot >= 0 else ""


def _csv_rows(payload: bytes) -> Iterable[list[Any]]:
    if b"\x00" in payload:
        raise ResearchFileError(UNREADABLE_DETAIL)
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
        raise ResearchFileError(UNREADABLE_DETAIL) from exc


def _xlsx_rows(payload: bytes) -> Iterable[tuple[Any, ...]]:
    if not payload.startswith(_XLSX_MAGIC):
        raise ResearchFileError(UNREADABLE_DETAIL)
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            members = archive.infolist()
            if (
                len(members) > MAX_ZIP_MEMBERS
                or sum(member.file_size for member in members) > MAX_UNZIPPED_BYTES
            ):
                raise ResearchFileError(TOO_BIG_DETAIL, too_large=True)
        from openpyxl import load_workbook

        workbook = load_workbook(io.BytesIO(payload), read_only=True, data_only=True)
    except ResearchFileError:
        raise
    except Exception as exc:  # noqa: BLE001 — każdy błąd biblioteki to zły plik
        raise ResearchFileError(UNREADABLE_DETAIL) from exc
    try:
        sheet = workbook.worksheets[0] if workbook.worksheets else None
        if sheet is None:
            raise ResearchFileError(EMPTY_DETAIL)
        yield from sheet.iter_rows(
            values_only=True, max_row=MAX_ROWS + 50, max_col=MAX_COLUMNS
        )
    finally:
        workbook.close()


def _columns(header: Iterable[Any]) -> dict[str, int]:
    columns: dict[str, int] = {}
    for index, cell in enumerate(header):
        if index >= MAX_COLUMNS:
            break
        field = _FIELD_BY_HEADER.get(fold(cell))
        if field is not None:
            columns.setdefault(field, index)
    if "company" not in columns:
        raise ResearchFileError(NO_COMPANY_COLUMN_DETAIL)
    if "name" not in columns and not {"first_name", "last_name"} <= columns.keys():
        raise ResearchFileError(NO_PERSON_COLUMN_DETAIL)
    return columns


def _row(
    line: int, cells: list[Any], columns: dict[str, int]
) -> Optional[ResearchRow | SkippedRow]:
    values = {
        field: clean_text(cells[index] if index < len(cells) else None, _LIMITS[field])
        for field, index in columns.items()
    }
    if not any(values.values()):
        return None
    name = values.get("name") or " ".join(
        part for part in (values.get("first_name"), values.get("last_name")) if part
    )
    name = name[: _LIMITS["name"]].strip()
    company = values.get("company")
    if not company:
        return SkippedRow(line=line, reason=NO_COMPANY_REASON)
    if not name:
        return SkippedRow(line=line, reason=NO_PERSON_REASON)

    warnings = []
    email = valid_email(values.get("email"))
    if values.get("email") and not email:
        warnings.append("pominięto adres e-mail (niepełny)")
    phone = valid_phone(values.get("phone"))
    if values.get("phone") and not phone:
        warnings.append("pominięto telefon (nie wygląda na numer)")
    linkedin = valid_link(values.get("linkedin"), _LIMITS["linkedin"])
    if values.get("linkedin") and not linkedin:
        warnings.append("pominięto LinkedIn (tylko adres http albo https)")
    source_url = valid_link(values.get("source_url"), _LIMITS["source_url"])
    if values.get("source_url") and not source_url:
        warnings.append("pominięto link źródła (tylko adres http albo https)")
    if linkedin is None and source_url and "linkedin.com/" in source_url.lower():
        # Jedna kolumna „Źródło” z publicznym profilem: to także kanał kontaktu.
        linkedin = valid_link(source_url, _LIMITS["linkedin"])
    return ResearchRow(
        line=line,
        company=company,
        name=name,
        title=values.get("title"),
        email=email,
        phone=phone,
        linkedin_url=linkedin,
        source_url=source_url,
        domain=company_domain(values.get("website"), email),
        confidence=confidence_of(values.get("confidence")),
        decision_level=_level(values.get("level"), values.get("title")),
        note=values.get("note"),
        warnings=tuple(warnings),
    )


def parse_research_file(filename: str, payload: bytes) -> ResearchFile:
    """Wiersze listy z pliku; ``ResearchFileError`` z komunikatem, gdy plik odpada."""

    extension = _extension(filename or "")
    if extension not in ALLOWED_EXTENSIONS:
        raise ResearchFileError(BAD_TYPE_DETAIL)
    if len(payload) > MAX_FILE_BYTES:
        raise ResearchFileError(TOO_BIG_DETAIL, too_large=True)
    if not payload.strip():
        raise ResearchFileError(EMPTY_DETAIL)
    raw = _xlsx_rows(payload) if extension == ".xlsx" else _csv_rows(payload)

    columns: Optional[dict[str, int]] = None
    rows: list[ResearchRow] = []
    skipped: list[SkippedRow] = []
    for line, cells in enumerate(raw, start=1):
        cells = list(cells or ())
        if columns is None:
            if not any(clean_text(cell, 255) for cell in cells):
                continue
            columns = _columns(cells)
            continue
        parsed = _row(line, cells, columns)
        if parsed is None:
            continue
        if len(rows) + len(skipped) >= MAX_ROWS:
            raise ResearchFileError(TOO_MANY_ROWS_DETAIL)
        if isinstance(parsed, SkippedRow):
            skipped.append(parsed)
        else:
            rows.append(parsed)
    if columns is None or (not rows and not skipped):
        raise ResearchFileError(EMPTY_DETAIL)
    return ResearchFile(rows=rows, skipped=skipped)
