"""Parser arkusza MD z Finansów — rozpoznawanie nagłówków po synonimach.

Arkusze z Finansów nie mają ustalonego formatu: kolumna z osobą bywa
„Konsultant", „Imię i nazwisko" albo „Pracownik", a liczba MD — „MD",
„Osobodni" albo „Man-days". Bywa też kilka wierszy tytułowych nad nagłówkiem.
Sztywny kontrakt kolumn odrzucałby poprawne pliki, więc parser SZUKA wiersza
nagłówka i mapuje kolumny po słowniku synonimów.

Świadomie nie zgaduje **miesiąca** — ten wybiera operator przy imporcie.
Miesiąc jest kluczem idempotencji, a nazwy plików kłamią dokładnie wtedy, gdy
import dotyczy okresu zaległego („raport_listopad.xlsx" wgrany w styczniu).

Ten moduł nie dotyka bazy — dostaje bajty, oddaje wiersze. Dzięki temu jego
testy nie potrzebują ani Postgresa, ani aplikacji.
"""

from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from openpyxl import load_workbook

# Ile wierszy od góry przeszukać w poszukiwaniu nagłówka. Wystarcza na tytuł,
# datę i pustą linię nad tabelą; więcej oznaczałoby już inny kształt pliku.
_MAX_HEADER_SCAN_ROWS = 25

# Po tylu pustych wierszach z rzędu uznajemy tabelę za skończoną — arkusze
# z Finansów miewają pod tabelą podsumowania i stopki, których nie chcemy
# potraktować jako danych.
_MAX_BLANK_RUN = 15

_NAME_HEADERS = (
    "konsultant",
    "imie i nazwisko",
    "nazwisko i imie",
    "imie nazwisko",
    "nazwisko imie",
    "pracownik",
    "osoba",
    "wykonawca",
    "kontraktor",
    "consultant",
    "full name",
    "name",
    "employee",
)

_MD_HEADERS = (
    "md zaraportowane",
    "zaraportowane md",
    "liczba md",
    "ilosc md",
    "suma md",
    "md",
    "mdy",
    "osobodni",
    "osobodnie",
    "osobodzien",
    "man-days",
    "man days",
    "mandays",
    "roboczodni",
    "dni",
)

# „Uwagi" to JEDYNE miejsce w arkuszu, które niesie numer zamówienia — plik
# nie ma osobnej kolumny na numer, a rozliczenie kosztowe potrzebuje go, żeby
# wiedzieć, z którego budżetu zdjąć kwotę.
# Nagłówki, które ZAWIERAJĄ „MD", ale opisują STAWKĘ, nie liczbę dni.
#
# Realny arkusz z Finansów ma obie kolumny obok siebie: „Średnia Stawka MD"
# i „Ilość MD". Bez tego wykluczenia wygrywała pierwsza z brzegu — czyli
# stawka — i system odejmowałby z budżetu 1000 „dni" zamiast 15. Błąd byłby
# CICHY: liczba jest poprawna arytmetycznie, tylko opisuje co innego.
_MD_ANTI_HEADERS = (
    "stawka",
    "rate",
    "cena",
    "price",
    "koszt",
    "wartosc",
    "kwota",
)

_NOTES_HEADERS = (
    "uwagi",
    "uwaga",
    "notatki",
    "komentarz",
    "opis",
    "notes",
    "comment",
)

_INVOICE_HEADERS = (
    "kwota faktury",
    "wartosc faktury",
    "faktura netto",
    "faktura",
    "invoice",
)

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _norm_header(value: Any) -> str:
    """Nagłówek → porównywalny klucz (bez diakrytyków, wielkości liter, spacji)."""
    text = str(value or "").strip()
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text.replace("ł", "l").replace("Ł", "l"))
    ascii_text = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _NON_ALNUM.sub(" ", ascii_text.casefold()).strip()


def _match_header(normalized: str, needles: tuple[str, ...]) -> Optional[int]:
    """Indeks trafionego synonimu (im niższy, tym bardziej dosłowny) albo ``None``.

    Kolejność ma znaczenie: „MD zaraportowane" musi wygrać z gołym „MD", żeby
    w arkuszu mającym obie kolumny wybrać tę właściwą. Dopasowanie jest
    dosłowne ALBO jako całe słowo — bez tego „dni" trafiałoby w „tygodnie",
    a „md" w „komandytowa".
    """
    for index, needle in enumerate(needles):
        if normalized == needle:
            return index
        if re.search(rf"(?:^| ){re.escape(needle)}(?:$| )", normalized):
            return index
    return None


# Numer zamówienia bywa wpisany na kilka sposobów („SAP 4500719650",
# „4500719650", „zam. 4500719650 - II transza"), więc szukamy CIĄGÓW CYFR,
# a nie ustalonego prefiksu. Próg 3 cyfr, bo numery bywają krótkie
# („Zamówienie nr 445"); odsiewanie fałszywych trafień robi dopiero
# konfrontacja z listą istniejących zamówień, nie sama długość.
_ORDER_NUMBER_RE = re.compile(r"\d{3,}")


def extract_order_number_candidates(notes: Any) -> list[str]:
    """Wszystkie ciągi cyfr z „Uwag", od najdłuższego.

    Zwracana jest LISTA, a nie jeden numer, bo w tej samej komórce potrafią
    stać obok siebie numer zamówienia, rok i numer transzy („SAP 4500719650 /
    2026, II transza"). Który z nich jest numerem zamówienia, wie dopiero
    warstwa, która ma przed sobą listę istniejących zamówień klienta —
    zgadywanie tutaj (najdłuższy, pierwszy) myliłoby się cicho i odejmowałoby
    kwotę z cudzego budżetu.

    Kolejność malejąco po długości daje sensowną wartość domyślną dla
    komunikatu o braku dopasowania: numery SAP mają 10 cyfr, więc przy remisie
    długości wygrywa ten, który pojawił się wcześniej.
    """
    if notes is None:
        return []
    text = str(notes).strip()
    if not text:
        return []
    seen: set[str] = set()
    ordered: list[str] = []
    for match in _ORDER_NUMBER_RE.findall(text):
        if match in seen:
            continue
        seen.add(match)
        ordered.append(match)
    ordered.sort(key=len, reverse=True)
    return ordered


def extract_order_number(notes: Any) -> Optional[str]:
    """Najlepszy pojedynczy kandydat na numer zamówienia (albo ``None``)."""
    candidates = extract_order_number_candidates(notes)
    return candidates[0] if candidates else None


def parse_md_value(raw: Any) -> Optional[Decimal]:
    """Komórka → liczba MD. ``None`` gdy pusta lub nieliczbowa.

    Obsługuje polski przecinek dziesiętny i spacje jako separator tysięcy —
    to najczęstszy kształt liczby w arkuszu eksportowanym z polskiego Excela.
    """
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float, Decimal)):
        return Decimal(str(raw))
    text = str(raw).strip()
    if not text:
        return None
    text = text.replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def parse_money_value(raw: Any) -> Optional[Decimal]:
    """Komórka → kwota. ``None`` gdy pusta lub nieliczbowa.

    Ta sama koercja co przy MD plus zdejmowanie oznaczenia waluty: „20 900,00
    zł" (z twardą spacją) → ``20900.00``. Bez tego kwoty z polskiego Excela
    lądowałyby jako nieczytelne i cały wiersz wypadałby z rozliczenia.
    """
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float, Decimal)):
        return Decimal(str(raw))
    text = str(raw).strip()
    if not text:
        return None
    text = re.sub(r"(?i)(pln|zl|zł)", "", text)
    text = text.replace("\xa0", "").replace(" ", "").replace(",", ".")
    if not text:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


@dataclass(frozen=True)
class ParsedRow:
    row_number: int
    consultant_name: str
    md_reported: Decimal
    # Obie opcjonalne — arkusz bez kolumn „Uwagi"/„Faktura" parsuje się jak
    # dotąd i zasila wyłącznie budżety MD.
    notes_raw: Optional[str] = None
    order_number_hint: Optional[str] = None
    invoice_amount: Optional[Decimal] = None


@dataclass
class ParsedSheet:
    sheet_name: str
    header_row: int
    name_column: int
    md_column: int
    notes_column: Optional[int] = None
    invoice_column: Optional[int] = None
    rows: list[ParsedRow] = field(default_factory=list)
    skipped_rows: list[dict[str, Any]] = field(default_factory=list)


class MdSheetFormatError(ValueError):
    """Plik nie ma rozpoznawalnej tabeli konsultant → MD."""


def _locate_header(
    sheet,
) -> Optional[tuple[int, int, int, Optional[int], Optional[int]]]:
    """Pozycje kolumn w rozpoznanym nagłówku albo ``None``.

    Zwraca ``(wiersz, kolumna nazwiska, kolumna MD, kolumna Uwag, kolumna
    Faktury)``. Dwie ostatnie są OPCJONALNE — nagłówek jest rozpoznany, gdy są
    obie wymagane; ich brak nie może odrzucić arkusza, bo tak wyglądały
    wszystkie pliki przed wprowadzeniem rozliczeń kosztowych.
    """
    for row_idx, row in enumerate(
        sheet.iter_rows(min_row=1, max_row=_MAX_HEADER_SCAN_ROWS, values_only=True),
        start=1,
    ):
        name_col: Optional[int] = None
        name_rank = len(_NAME_HEADERS)
        md_col: Optional[int] = None
        md_rank = len(_MD_HEADERS)
        notes_col: Optional[int] = None
        notes_rank = len(_NOTES_HEADERS)
        invoice_col: Optional[int] = None
        invoice_rank = len(_INVOICE_HEADERS)
        for col_idx, cell in enumerate(row or ()):
            normalized = _norm_header(cell)
            if not normalized:
                continue
            rank = _match_header(normalized, _NAME_HEADERS)
            if rank is not None and rank < name_rank:
                name_col, name_rank = col_idx, rank
            rank = _match_header(normalized, _MD_HEADERS)
            if (
                rank is not None
                and rank < md_rank
                and _match_header(normalized, _MD_ANTI_HEADERS) is None
            ):
                md_col, md_rank = col_idx, rank
            rank = _match_header(normalized, _NOTES_HEADERS)
            if rank is not None and rank < notes_rank:
                notes_col, notes_rank = col_idx, rank
            rank = _match_header(normalized, _INVOICE_HEADERS)
            if rank is not None and rank < invoice_rank:
                invoice_col, invoice_rank = col_idx, rank
        if name_col is not None and md_col is not None and name_col != md_col:
            # Kolizja z kolumnami wymaganymi znaczy, że trafiliśmy w ten sam
            # nagłówek dwa razy — wtedy opcjonalna kolumna po prostu nie
            # istnieje. Wpisanie jej i tak dałoby liczbę MD w polu „Faktura".
            if notes_col in (name_col, md_col):
                notes_col = None
            if invoice_col in (name_col, md_col):
                invoice_col = None
            return row_idx, name_col, md_col, notes_col, invoice_col
    return None


def parse_md_sheet(content: bytes) -> ParsedSheet:
    """Bajty XLSX → wiersze (konsultant, MD).

    Przeszukiwane są WSZYSTKIE arkusze, nie tylko pierwszy: raporty z Finansów
    często zaczynają się arkuszem tytułowym albo podsumowaniem, a dane siedzą
    dalej. Wygrywa pierwszy arkusz z rozpoznanym nagłówkiem.
    """
    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:  # openpyxl rzuca różne typy dla uszkodzonych plików
        raise MdSheetFormatError(
            "Nie udało się otworzyć pliku — czy na pewno jest to arkusz XLSX?"
        ) from exc

    try:
        for sheet in workbook.worksheets:
            located = _locate_header(sheet)
            if located is None:
                continue
            header_row, name_col, md_col, notes_col, invoice_col = located
            parsed = ParsedSheet(
                sheet_name=sheet.title,
                header_row=header_row,
                name_column=name_col,
                md_column=md_col,
                notes_column=notes_col,
                invoice_column=invoice_col,
            )
            blank_run = 0
            for row_idx, row in enumerate(
                sheet.iter_rows(min_row=header_row + 1, values_only=True),
                start=header_row + 1,
            ):
                cells = list(row or ())
                name_raw = cells[name_col] if name_col < len(cells) else None
                md_raw = cells[md_col] if md_col < len(cells) else None
                name = str(name_raw or "").strip()
                md_value = parse_md_value(md_raw)

                if not name and md_value is None:
                    blank_run += 1
                    if blank_run >= _MAX_BLANK_RUN:
                        break
                    continue
                blank_run = 0

                if not name:
                    parsed.skipped_rows.append(
                        {"row": row_idx, "reason": "brak nazwiska konsultanta"}
                    )
                    continue
                if md_value is None:
                    parsed.skipped_rows.append(
                        {
                            "row": row_idx,
                            "reason": f"nieczytelna liczba MD ({md_raw!r})",
                            "consultant_name": name,
                        }
                    )
                    continue
                notes_raw: Optional[str] = None
                if notes_col is not None and notes_col < len(cells):
                    notes_text = str(cells[notes_col] or "").strip()
                    notes_raw = notes_text or None
                invoice_value: Optional[Decimal] = None
                if invoice_col is not None and invoice_col < len(cells):
                    invoice_value = parse_money_value(cells[invoice_col])

                parsed.rows.append(
                    ParsedRow(
                        row_number=row_idx,
                        consultant_name=name,
                        md_reported=md_value,
                        notes_raw=notes_raw,
                        order_number_hint=extract_order_number(notes_raw),
                        invoice_amount=invoice_value,
                    )
                )
            return parsed
    finally:
        workbook.close()

    raise MdSheetFormatError(
        "Nie znaleziono tabeli z kolumnami konsultanta i MD. Nagłówki mogą "
        "brzmieć np. Konsultant / Imię i nazwisko oraz MD / Osobodni."
    )
