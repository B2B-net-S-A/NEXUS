"""Plik paczki przelewów: Elixir-O (format PLI) albo CSV.

Elixir-O — jeden przelew na linię, pola po przecinku, tekst w cudzysłowie,
linie tekstu rozdzielone ``|`` (4 × 35 znaków), kodowanie windows-1250,
koniec linii CRLF. Pola: typ (110 — przelew), data RRRRMMDD, kwota w groszach,
numer rozliczeniowy banku nadawcy, 0, rachunek nadawcy, rachunek odbiorcy,
nazwa nadawcy, nazwa odbiorcy, 0, numer rozliczeniowy banku odbiorcy, tytuł,
dwa puste pola, klasyfikacja („51” — zwykły przelew, „53” — komunikat
podzielonej płatności MPP, pole ``TransferRow.classification``; tytuł MPP
``/VAT/…/IDC/…/INV/…/TXT/…`` składa wywołujący). Ten układ przyjmuje import przelewów
większości bankowości firmowych; przed pierwszym użyciem trzeba go sprawdzić
w banku firmy (raport etapu 4).

Santander (rachunek nadawcy z numerem banku 1090…) dostaje układ pliku, który
robi dla niego eBI24 (próbka „Płatności_…pli” z 17.11.2026, przyjmowana przez
bank): 17 pól, pierwsze puste, numery rozliczeniowe obu banków w polach 4 i 5
w cudzysłowie, nazwy jednym tekstem (bez ``|``), pola 10, 11 i 13–17 puste.
Jak eBI24 oznacza w nim MPP, nie wiemy (próbka to zwykły przelew), więc MPP
w tym układzie jest zablokowane (``SantanderLayoutError``) do próbki MPP.

Układ Santandera wybiera wywołujący (``render_santander``) — na razie tylko
przelewy faktur kosztowych (E3); paczki Płac zostają w Elixir-O.

CSV — średnik, przecinek dziesiętny, UTF-8 z BOM (Excel po polsku), każda
komórka przez ``safe_cell``.

Funkcje są czyste: dostają gotowe wiersze (rachunki 26 cyfr NRB).
"""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.core.export_safety import safe_row
from app.services.hr.bank.accounts import bank_sort_code, grouped_iban
from app.services.hr.bank.titles import LINE_LENGTH, MAX_LINES, clean

TRANSFER_TYPE = "110"
CLASSIFICATION = "51"
#: Komunikat przelewu w mechanizmie podzielonej płatności (Elixir-O, pole 15).
CLASSIFICATION_MPP = "53"
ENCODING = "windows-1250"
#: Numer banku Santander Bank Polska w NRB (cyfry 3–6).
SANTANDER_BANK = "1090"
#: Nazwa w układzie eBI24 to jeden tekst; więcej niż 4 × 35 znaków nie ma
#: w Elixirze miejsca.
SANTANDER_NAME_MAX = LINE_LENGTH * MAX_LINES


class SantanderLayoutError(ValueError):
    """Przelewu nie umiemy zapisać w układzie eBI24 dla Santandera."""


@dataclass(frozen=True)
class TransferRow:
    recipient_name: str
    recipient_account: str
    amount: Decimal
    title_lines: tuple[str, ...]
    execution_date: date
    classification: str = CLASSIFICATION


@dataclass(frozen=True)
class Sender:
    name: str
    account: str


def _lines(text: str) -> list[str]:
    """Tekst nazwy → najwyżej 4 linie po 35 znaków (cięcie po słowach)."""

    words = clean(text).split(" ")
    lines: list[str] = []
    current = ""
    for word in words:
        while len(word) > LINE_LENGTH:
            if current:
                lines.append(current)
                current = ""
            lines.append(word[:LINE_LENGTH])
            word = word[LINE_LENGTH:]
        candidate = f"{current} {word}".strip()
        if len(candidate) > LINE_LENGTH:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines[:MAX_LINES]


def _quoted(lines: Sequence[str]) -> str:
    return '"' + "|".join(clean(line)[:LINE_LENGTH] for line in lines) + '"'


def grosze(amount: Decimal) -> int:
    return int((amount * 100).quantize(Decimal("1")))


def elixir_line(row: TransferRow, sender: Sender) -> str:
    fields = [
        TRANSFER_TYPE,
        row.execution_date.strftime("%Y%m%d"),
        str(grosze(row.amount)),
        bank_sort_code(sender.account),
        "0",
        f'"{sender.account}"',
        f'"{row.recipient_account}"',
        _quoted(_lines(sender.name)),
        _quoted(_lines(row.recipient_name)),
        "0",
        bank_sort_code(row.recipient_account),
        _quoted(row.title_lines[:MAX_LINES]),
        '""',
        '""',
        f'"{row.classification}"',
    ]
    return ",".join(fields)


def uses_santander_layout(sender_account: str) -> bool:
    return bank_sort_code(sender_account).startswith(SANTANDER_BANK)


def santander_line(row: TransferRow, sender: Sender) -> str:
    """Linia w układzie pliku płatności eBI24 dla Santandera (17 pól)."""

    if row.classification != CLASSIFICATION:
        raise SantanderLayoutError(
            "Przelewu MPP nie zapiszemy w pliku dla Santandera, dopóki nie mamy "
            "próbki przelewu MPP z eBI24 — zapłać go w eBI24 albo w banku."
        )
    fields = [
        "",
        row.execution_date.strftime("%Y%m%d"),
        str(grosze(row.amount)),
        f'"{bank_sort_code(sender.account)}"',
        f'"{bank_sort_code(row.recipient_account)}"',
        f'"{sender.account}"',
        f'"{row.recipient_account}"',
        f'"{clean(sender.name)[:SANTANDER_NAME_MAX]}"',
        f'"{clean(row.recipient_name)[:SANTANDER_NAME_MAX]}"',
        '""',
        '""',
        _quoted(row.title_lines[:MAX_LINES]),
        '""',
        '""',
        '""',
        '""',
        '""',
    ]
    return ",".join(fields)


def render_elixir(rows: Sequence[TransferRow], sender: Sender) -> bytes:
    text = "".join(f"{elixir_line(row, sender)}\r\n" for row in rows)
    # Znak spoza windows-1250 (np. w nazwie z wykazu) = „?” — bank i tak go nie przyjmie.
    return text.encode(ENCODING, errors="replace")


def render_santander(rows: Sequence[TransferRow], sender: Sender) -> bytes:
    text = "".join(f"{santander_line(row, sender)}\r\n" for row in rows)
    return text.encode(ENCODING, errors="replace")


CSV_COLUMNS = (
    "Rachunek odbiorcy",
    "Nazwa odbiorcy",
    "Kwota",
    "Tytuł",
    "Data wykonania",
)


def amount_text(amount: Decimal) -> str:
    return f"{amount:.2f}".replace(".", ",")


def render_csv(rows: Sequence[TransferRow]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(CSV_COLUMNS)
    for row in rows:
        writer.writerow(
            safe_row(
                [
                    grouped_iban(row.recipient_account),
                    clean(row.recipient_name),
                    amount_text(row.amount),
                    " ".join(row.title_lines),
                    row.execution_date.isoformat(),
                ]
            )
        )
    return ("﻿" + buffer.getvalue()).encode("utf-8")


__all__ = [
    "CLASSIFICATION",
    "CLASSIFICATION_MPP",
    "CSV_COLUMNS",
    "ENCODING",
    "SANTANDER_BANK",
    "SantanderLayoutError",
    "Sender",
    "TransferRow",
    "amount_text",
    "elixir_line",
    "grosze",
    "render_csv",
    "render_elixir",
    "render_santander",
    "santander_line",
    "uses_santander_layout",
]
