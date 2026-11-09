"""Odczyt tabeli widełek z tekstu umowy ramowej (załącznik i aneksy).

Kwot nie ma w repozytorium: leżą w umowie klienta. Parser czyta układ tabeli
z tekstu PDF-a, a wynik jest propozycją, którą Delivery Lead sprawdza i zapisuje.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.bnp_report.calculations import HOURS_PER_MD


@dataclass(frozen=True)
class ParsedBand:
    role: str
    minimum: int
    maximum: int


_ANNEX_HEADER_RE = re.compile(r"Stawki\.?\s+minimalna\s+maksymalna", re.IGNORECASE)
_HOURLY_ROW_RE = re.compile(r"(\d{2,4})\s+(\d{2,4})\s+godz\s+\d{2,5}")
_ANNEX_END_RE = re.compile(r"Strona\s+\d+\s+z\s+\d+|Załącznik\s+nr\s+\d+", re.IGNORECASE)
_HEADER_NOISE_RE = re.compile(
    r"^.*(?:Rozliczenie\s+za\s+MD\s+netto\s+PLN|stawka\s+netto)\s*(?:PLN\s*)*",
    re.IGNORECASE | re.DOTALL,
)
_TAIL_RE = re.compile(r"^\s*([^()]*\))")
_MD_ROW_RE = re.compile(
    r"Nazwa\s+roli\s+Junior\s+Medium\s+Senior\s+min\s+max\s+min\s+max\s+min\s+max\s+"
    r"(?P<role>[^\d]+?)\s+"
    r"(?P<low>\d{2,5})\s+\d{2,5}\s+\d{2,5}\s+\d{2,5}\s+\d{2,5}\s+(?P<high>\d{2,5})\b",
    re.IGNORECASE,
)


def _clean_role(raw: str) -> str:
    role = re.sub(r"\s+", " ", raw).strip(" ,;")
    role = re.sub(r"\s+,", ",", role)
    role = re.sub(r"\.,", ",", role)
    return re.sub(r",(?=\S)", ", ", role)


def _hourly_rows(text: str) -> list[ParsedBand]:
    header = _ANNEX_HEADER_RE.search(text)
    if header is None:
        return []
    body = text[header.end() :]
    body = re.sub(r"\s+", " ", body)
    rows: list[ParsedBand] = []
    cursor = 0
    pending_tail = False
    for match in _HOURLY_ROW_RE.finditer(body):
        name = body[cursor : match.start()]
        # Tabela w PDF-ie łamie dłuższą nazwę: nawias zamyka się za kwotami.
        if pending_tail:
            tail = _TAIL_RE.match(name)
            if tail is not None:
                name = name[tail.end() :]
                previous = rows[-1]
                rows[-1] = ParsedBand(
                    _clean_role(f"{previous.role}, {tail.group(1)}"),
                    previous.minimum,
                    previous.maximum,
                )
        if not rows:
            name = _HEADER_NOISE_RE.sub("", name)
            name = re.sub(r"^(?:\s*PLN)+", "", name)
        minimum, maximum = int(match.group(1)), int(match.group(2))
        role = _clean_role(name)
        if role and minimum <= maximum:
            rows.append(ParsedBand(role, minimum, maximum))
            pending_tail = role.count("(") > role.count(")")
        cursor = match.end()
        following = _ANNEX_END_RE.search(body, cursor)
        if following is not None and not _HOURLY_ROW_RE.search(
            body, cursor, following.start()
        ):
            tail_text = body[cursor : following.start()]
            tail = _TAIL_RE.match(tail_text) if pending_tail else None
            if tail is not None:
                previous = rows[-1]
                rows[-1] = ParsedBand(
                    _clean_role(f"{previous.role}, {tail.group(1)}"),
                    previous.minimum,
                    previous.maximum,
                )
            break
    return rows


def _md_rows(text: str) -> list[ParsedBand]:
    flat = re.sub(r"\s+", " ", text)
    rows: list[ParsedBand] = []
    for match in _MD_ROW_RE.finditer(flat):
        minimum = round(int(match.group("low")) / HOURS_PER_MD)
        maximum = round(int(match.group("high")) / HOURS_PER_MD)
        rows.append(ParsedBand(_clean_role(match.group("role")), minimum, maximum))
    return rows


def parse_rate_annex(agreement_text: str, amendment_texts: list[str]) -> list[ParsedBand]:
    """Widełki w zł/h: wiersze załącznika i role dopisane aneksami."""
    rows = _hourly_rows(agreement_text)
    known = {row.role.lower() for row in rows}
    for text in amendment_texts:
        for row in _md_rows(text):
            if row.role.lower() not in known:
                known.add(row.role.lower())
                rows.append(row)
    return rows
