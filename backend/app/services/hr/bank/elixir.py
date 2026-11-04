"""Plik paczki przelewów: Elixir-O (format PLI) albo CSV.

Elixir-O — jeden przelew na linię, pola po przecinku, tekst w cudzysłowie,
linie tekstu rozdzielone ``|`` (4 × 35 znaków), kodowanie windows-1250,
koniec linii CRLF. Pola: typ (110 — przelew), data RRRRMMDD, kwota w groszach,
numer rozliczeniowy banku nadawcy, 0, rachunek nadawcy, rachunek odbiorcy,
nazwa nadawcy, nazwa odbiorcy, 0, numer rozliczeniowy banku odbiorcy, tytuł,
dwa puste pola, klasyfikacja „51”. Ten układ przyjmuje import przelewów
większości bankowości firmowych; przed pierwszym użyciem trzeba go sprawdzić
w banku firmy (raport etapu 4).

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
ENCODING = "windows-1250"


@dataclass(frozen=True)
class TransferRow:
    recipient_name: str
    recipient_account: str
    amount: Decimal
    title_lines: tuple[str, ...]
    execution_date: date


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
        f'"{CLASSIFICATION}"',
    ]
    return ",".join(fields)


def render_elixir(rows: Sequence[TransferRow], sender: Sender) -> bytes:
    text = "".join(f"{elixir_line(row, sender)}\r\n" for row in rows)
    # Znak spoza windows-1250 (np. w nazwie z wykazu) = „?” — bank i tak go nie przyjmie.
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
    "CSV_COLUMNS",
    "ENCODING",
    "Sender",
    "TransferRow",
    "amount_text",
    "elixir_line",
    "grosze",
    "render_csv",
    "render_elixir",
]
