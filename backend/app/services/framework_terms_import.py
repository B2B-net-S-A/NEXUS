"""Cennik umowy ramowej z załącznika Word (F1, 15.11.2026).

Załącznik „Charges” ma dwa rodzaje tabel:

* stawki — wiersz ``[grupa] | kategoria | liczba`` („IT | IT Developer - Senior | 178”);
* dopłaty — nagłówek ``Technology skills | kategoria-poziom | …`` i wiersze
  ``technologia | 10% | 20% | …``; pusta komórka = brak dopłaty dla tej kategorii.

Wynik to PROPOZYCJA do przejrzenia (jak ``bnp_report/rate_annex``): zapis do
``rate_cards`` / ``rate_card_adders`` robi dopiero zatwierdzenie w aplikacji.
Komórki tylko przez ``app.core.docx_cells`` (``podstawy/tabele-worda-z-wgranych-plikow.md``).
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Optional

from app.core.docx_cells import grid_rows
from app.services.framework_limits import category_label, parse_category_label

MAX_RATE_ROWS = 500
_RATE_RE = re.compile(r"^\d{1,5}(?:[.,]\d{1,2})?$")
_PERCENT_RE = re.compile(r"^(\d{1,3}(?:[.,]\d{1,2})?)\s*%$")
_HEADER_HINT_RE = re.compile(r"technolog", re.IGNORECASE)


@dataclass(frozen=True)
class RateRow:
    role: str
    seniority: Optional[str]
    rate: Decimal

    @property
    def label(self) -> str:
        return category_label(self.role, self.seniority)


@dataclass
class AdderRow:
    technology: str
    percent: Decimal
    eligible: list[dict] = field(default_factory=list)


@dataclass
class TermsProposal:
    rates: list[RateRow] = field(default_factory=list)
    adders: list[AdderRow] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _text(cell) -> str:
    # Wszystkie ``w:t`` komórki, także w kontrolkach zawartości (``w:sdt``):
    # załącznik Nordei trzyma w nich stawki, a ``cell.text`` ich nie widzi.
    from docx.oxml.ns import qn

    text = " ".join(
        "".join(t.text or "" for t in p.iter(qn("w:t"))) for p in cell._tc.iter(qn("w:p"))
    )
    return re.sub(r"\s+", " ", text).strip()


def _decimal(text: str) -> Optional[Decimal]:
    try:
        return Decimal(text.replace(",", "."))
    except InvalidOperation:
        return None


def _rates_from(rows: list[list[str]], out: TermsProposal) -> None:
    for cells in rows:
        values = [c for c in cells if c]
        if len(values) < 2 or not _RATE_RE.match(values[-1]):
            continue
        parsed = parse_category_label(values[-2])
        if parsed is None or len(out.rates) >= MAX_RATE_ROWS:
            continue
        row = RateRow(parsed[0], parsed[1], _decimal(values[-1]))
        if any(r.label == row.label for r in out.rates):
            out.warnings.append(f"Kategoria {row.label} występuje dwa razy — wzięta pierwsza stawka.")
            continue
        out.rates.append(row)


def _adders_from(rows: list[list[str]], out: TermsProposal) -> None:
    header_index = next(
        (i for i, cells in enumerate(rows) if cells and _HEADER_HINT_RE.search(cells[0])), None
    )
    if header_index is None:
        return
    # Nagłówek kategorii bywa w wierszu „Technology skills” albo tuż nad nim
    # („| Competences categories”), więc bierzemy pierwszy wiersz z etykietami.
    categories = rows[header_index][1:]
    if not any(parse_category_label(c) for c in categories) and header_index > 0:
        categories = rows[header_index - 1][1:]
    pairs = [parse_category_label(c) for c in categories]
    for cells in rows[header_index + 1 :]:
        if not cells or not cells[0]:
            continue
        technology = cells[0]
        for pair, value in zip(pairs, cells[1:]):
            match = _PERCENT_RE.match(value or "")
            if pair is None or not match:
                continue
            percent = _decimal(match.group(1))
            adder = next((a for a in out.adders if a.technology.casefold() == technology.casefold()), None)
            if adder is None:
                adder = AdderRow(technology=technology, percent=percent)
                out.adders.append(adder)
            elif adder.percent != percent:
                out.warnings.append(
                    f"{technology}: różne dopłaty w tabelach ({adder.percent}% i {percent}%) — wzięta wyższa."
                )
                adder.percent = max(adder.percent, percent)
            entry = {"role": pair[0], "seniority": pair[1]}
            if entry not in adder.eligible:
                adder.eligible.append(entry)


def parse_terms_docx(data: bytes) -> TermsProposal:
    """Stawki i dopłaty z załącznika .docx. Nie zapisuje niczego."""
    from docx import Document

    out = TermsProposal()
    for table in Document(io.BytesIO(data)).tables:
        rows = [[_text(c) for c in cells] for cells in grid_rows(table)]
        if any(r and _HEADER_HINT_RE.search(r[0]) for r in rows):
            _adders_from(rows, out)
        else:
            _rates_from(rows, out)
    if not out.rates:
        out.warnings.append("Nie znaleziono tabeli stawek (kategoria | stawka).")
    known = {r.label.casefold() for r in out.rates}
    for adder in out.adders:
        missing = [
            category_label(p["role"], p["seniority"])
            for p in adder.eligible
            if category_label(p["role"], p["seniority"]).casefold() not in known
        ]
        if missing:
            out.warnings.append(f"{adder.technology}: kategorie spoza tabeli stawek — {', '.join(missing)}.")
    return out
