"""Dokument z jedną deklarowaną liczbą godzin albo MD za miesiąc i jego kontrole.

Bez bazy. Wspólne dla wzorów, w których klient albo konsultant podaje sumę,
a nie dni pracy: potwierdzenie godzin ERGO (``confirmation_ergo``), protokół
Orlenu (``protocol_orlen``) i mail rozliczeń NN z „Ilość MD” (``mail_nn``).

MD = godziny / ``fields.md_hours``; gdy dokument podaje MD wprost (NN, Orlen
„22 x 1360 PLN”), bierzemy je bez przeliczania. Miesiąc dokumentu inny niż
rozliczany to kontrola ``proof.month`` bez MD: liczba z pliku za inny okres
nie może trafić do rozliczenia.
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Mapping, Optional

from app.services.client_settlements.mail_text import (
    _MONTH_WORD,
    _month_index,
    month_label,
)
from app.services.client_settlements.rcp_checks import (
    ProofResult,
    _fmt,
    _Group,
    _param_dec,
    name_tokens,
)
from app.services.client_settlements.timesheet_pko import month_limit

logger = logging.getLogger(__name__)

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MD_Q = Decimal("0.001")
MAX_PAGES = 10
#: Dłuższa linia nie jest wierszem żadnego wzoru. Odcinamy ją przed regexami,
#: bo ciąg cyfr i spacji z obcego pliku dawał kwadratowe cofanie (sekundy na wątku).
MAX_LINE = 1000


@dataclass(frozen=True)
class Declared:
    #: Nazwa wzoru na karcie kontroli, np. „Potwierdzenie godzin ERGO”.
    source: str
    consultant: Optional[str]
    #: ``RRRR-MM`` z dokumentu.
    month: Optional[str]
    hours: Optional[Decimal] = None
    #: MD podane wprost w dokumencie (pierwszeństwo przed godzinami).
    md: Optional[Decimal] = None
    #: Kwota netto z dokumentu, tylko do wglądu.
    amount: Optional[Decimal] = None
    #: Numer umowy, który wskazał osobę mimo innego imienia w dokumencie
    #: (protokół CeZ, ``protocol_collective.by_agreement``).
    agreement: Optional[str] = None


def pdf_text(content: bytes) -> Optional[str]:
    """Tekst stron PDF albo ``None`` dla pliku nieczytelnego."""

    import pdfplumber

    quiet = logging.getLogger("pdfminer")
    previous = quiet.level
    quiet.setLevel(logging.ERROR)
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            return "\n".join(
                (page.extract_text() or "") for page in pdf.pages[:MAX_PAGES]
            )
    except Exception as exc:  # noqa: BLE001 — uszkodzony PDF nie blokuje przyjęcia
        logger.info("rozliczenia: PDF nieczytelny (%s)", type(exc).__name__)
        return None
    finally:
        quiet.setLevel(previous)


def docx_text(content: bytes) -> Optional[str]:
    """Akapity i wiersze tabel DOCX (komórki z ``docx_cells``) jako tekst."""

    import docx

    from app.core.docx_cells import row_texts

    try:
        document = docx.Document(io.BytesIO(content))
    except Exception as exc:  # noqa: BLE001
        logger.info("rozliczenia: DOCX nieczytelny (%s)", type(exc).__name__)
        return None
    lines = [p.text for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            lines.append(" | ".join(t for t in row_texts(row) if t))
    return "\n".join(lines)


def short_lines(text: str) -> str:
    """Tekst bez linii dłuższych niż ``MAX_LINE``."""

    return "\n".join(line for line in text.splitlines() if len(line) <= MAX_LINE)


def number(text: str) -> Optional[Decimal]:
    """„21 780”, „168,00”, „22.875” → liczba; spacje to separator tysięcy."""

    cleaned = text.replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        return Decimal(cleaned)
    except ArithmeticError:
        return None


_ENGLISH_MONTHS = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)
_DMY = re.compile(r"(?<!\d)\d{1,2}[-./](\d{1,2})[-./](20\d{2})(?!\d)")
_MY = re.compile(r"(?<![\d./-])(\d{1,2})[-./](20\d{2})(?!\d)")
_ENGLISH = re.compile(r"\b(" + "|".join(_ENGLISH_MONTHS) + r")\s+(20\d{2})\b", re.I)


def month_in(text: str) -> Optional[str]:
    """Pierwszy miesiąc z rokiem w tekście: „01-09-2026”, „09-2026”,
    „September 2026”, „WRZESIEŃ 2026” (każdy przypadek, też bez ogonków)."""

    text = text.replace("_", " ")
    for pattern in (_DMY, _MY):
        found = pattern.search(text)
        if found and 1 <= int(found.group(1)) <= 12:
            return f"{found.group(2)}-{int(found.group(1)):02d}"
    found = _ENGLISH.search(text)
    if found:
        index = _ENGLISH_MONTHS.index(found.group(1).lower()) + 1
        return f"{found.group(2)}-{index:02d}"
    for found in _MONTH_WORD.finditer(text):
        index = _month_index(found.group(1))
        if index is not None and found.group(2):
            return f"{found.group(2)}-{index:02d}"
    return None


def month_mismatch(group: _Group, title: str, detail: str) -> None:
    """Plik za inny miesiąc niż rozliczany: MD z niego nie wpisujemy. Włączona
    ``proof.month`` daje kontrolę z jej poziomem, wyłączona — informację, żeby
    przypadek w „Sprawdzaniu” nie stał bez powodu."""

    detail = f"{detail} MD z tego pliku nie wpisujemy."
    if group.on("proof.month"):
        group.fail("proof.month", title, detail)
    else:
        group.info(title, detail)


def _per_md(rules: Mapping[str, Mapping[str, Any]]) -> Decimal:
    value = _param_dec(rules, "fields.md_hours", "hours", "8")
    return value if value > 0 else Decimal("8")


def evaluate(
    parsed: Declared,
    *,
    month: str,
    person_name: str,
    rules: Mapping[str, Mapping[str, Any]],
    working_days: int,
    other_md: Decimal = Decimal("0"),
) -> ProofResult:
    result = ProofResult(md_regular=None, md_extra=None)
    group = _Group(result, rules, parsed.source)
    per_md = _per_md(rules)
    if parsed.md is not None:
        md = parsed.md.quantize(MD_Q, rounding=ROUND_HALF_UP)
        detail = f"W dokumencie {_fmt(md)} MD."
    elif parsed.hours is not None:
        md = (parsed.hours / per_md).quantize(MD_Q, rounding=ROUND_HALF_UP)
        detail = f"{_fmt(parsed.hours)} h / {_fmt(per_md)} = {_fmt(md)} MD."
    else:
        md = None
        detail = ""
    if md is None or md <= 0:
        group.info(
            f"{parsed.source} bez godzin",
            "Nie ma liczby godzin ani MD. MD wpisują Finanse; plik zostaje w NEXUS-ie.",
        )
        result.warn = True
        group.close()
        return result

    if parsed.month == month:
        group.ok(f"Miesiąc z dokumentu: {month_label(month)}")
        result.md_regular = md
        result.md_extra = Decimal("0")
    elif parsed.month is not None:
        month_mismatch(
            group,
            f"{parsed.source} za inny miesiąc",
            f"W dokumencie: {month_label(parsed.month)}.",
        )
    else:
        group.fail(
            "proof.month",
            f"{parsed.source} bez miesiąca",
            "MD z tego pliku nie wpisujemy.",
        )

    on_doc = name_tokens(parsed.consultant)
    person = name_tokens(person_name)
    if on_doc and person and (on_doc <= person or person <= on_doc):
        group.ok("Imię i nazwisko jak w kontrakcie")
    elif parsed.agreement:
        group.ok(
            f"Osoba z numeru umowy {parsed.agreement}",
            f"W dokumencie: {' '.join((parsed.consultant or '').split())}. "
            "Na tej umowie w tym miesiącu "
            "pracuje tylko osoba z kontraktu.",
        )
    elif on_doc:
        group.fail("proof.name_match", "Inne imię lub nazwisko niż w kontrakcie")
    else:
        group.fail("proof.name_match", f"{parsed.source} bez imienia i nazwiska")
    if parsed.amount is not None:
        group.info(f"Kwota w dokumencie: {_fmt(parsed.amount)} zł netto")
        if result.md_regular is not None:
            # Kontrola ``cl.protocol_amount`` w ``engine.compute`` (kwota do faktury).
            result.meta["document_amount"] = str(parsed.amount)
    group.close()

    sums = _Group(result, rules, "Pola i sumy")
    if result.md_regular is not None:
        if sums.on("fields.md_hours"):
            sums.ok("MD z dokumentu", detail)
        month_limit(sums, result.md_regular, working_days, other_md)
    sums.close()
    return result
