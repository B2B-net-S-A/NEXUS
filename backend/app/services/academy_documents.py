"""Akademia — komplet dokumentów uczestnika (wzory działu z 24.09.2026).

Pięć plików w jednym ZIP-ie: umowa uczestnictwa, załącznik nr 1
(harmonogram z datami edycji), oświadczenie uczestnika, regulamin programu
i protokół przekazania „Manuala dla Sourcera”. Szablony w
``app/templates/academy`` buduje ``scripts/build_academy_templates.py``.

PESEL i adres zamieszkania wpisuje człowiek w oknie generowania — trafiają
WYŁĄCZNIE do pobieranego pliku, nie do bazy (NEXUS nie przechowuje PESEL-u
kandydatów). Pole puste = linia kropek w dokumencie do uzupełnienia ręcznie.

Edycja programu trwa do 10 dni roboczych (umowa §1 ust. 1): domyślnie od
pierwszego dnia roboczego miesiąca edycji przez 10 dni roboczych, z polskimi
świętami. Daty da się nadpisać przy generowaniu.
"""

from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from docxtpl import DocxTemplate
from jinja2 import Environment, StrictUndefined

from app.core.scheduling import is_business_day

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates" / "academy"
PROGRAM_WORKDAYS = 10
DOTS = "……………………………………………"

# (klucz szablonu, nazwa pliku w ZIP-ie bez rozszerzenia)
DOCUMENTS: tuple[tuple[str, str], ...] = (
    ("umowa", "1_Umowa_uczestnictwa"),
    ("harmonogram", "2_Zalacznik_1_Harmonogram"),
    ("oswiadczenie", "3_Oswiadczenie_uczestnika"),
    ("regulamin", "4_Regulamin_Programu"),
    ("protokol", "5_Protokol_przekazania_Manuala"),
)

_PESEL = re.compile(r"^\d{11}$")
_PESEL_WEIGHTS = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)


def _is_workday(day: date) -> bool:
    return is_business_day(datetime(day.year, day.month, day.day, 12))


def program_dates(cohort_month: date) -> tuple[date, date]:
    """Pierwszy dzień roboczy miesiąca edycji i 10. dzień roboczy od niego."""
    day = date(cohort_month.year, cohort_month.month, 1)
    while not _is_workday(day):
        day += timedelta(days=1)
    start = day
    counted = 1
    while counted < PROGRAM_WORKDAYS:
        day += timedelta(days=1)
        if _is_workday(day):
            counted += 1
    return start, day


def pesel_valid(value: str) -> bool:
    """11 cyfr i poprawna cyfra kontrolna."""
    if not _PESEL.match(value):
        return False
    total = sum(int(d) * w for d, w in zip(value[:10], _PESEL_WEIGHTS))
    return (10 - total % 10) % 10 == int(value[10])


def pl_date(value: Optional[date]) -> str:
    if value is None:
        return DOTS
    return f"{value.day:02d}.{value.month:02d}.{value.year}"


@dataclass(frozen=True)
class DocumentInput:
    participant_name: str
    phone: Optional[str]
    email: Optional[str]
    address: Optional[str]
    pesel: Optional[str]
    signing_date: Optional[date]
    program_start: date
    program_end: date
    handover_name: Optional[str]
    protocol_date: Optional[date]


def context_for(data: DocumentInput) -> dict[str, str]:
    def text(value: Optional[str]) -> str:
        cleaned = " ".join((value or "").split())
        return cleaned or DOTS

    return {
        "participant_name": text(data.participant_name),
        "phone": text(data.phone),
        "email": text(data.email),
        "address": text(data.address),
        "pesel": text(data.pesel),
        "signing_date": pl_date(data.signing_date),
        "program_start": pl_date(data.program_start),
        "program_end": pl_date(data.program_end),
        "handover_name": text(data.handover_name),
        "protocol_date": pl_date(data.protocol_date),
    }


def _env() -> Environment:
    # StrictUndefined: literówka w szablonie ma paść w teście, a nie wyjść do
    # uczestnika jako puste miejsce w umowie.
    return Environment(autoescape=True, undefined=StrictUndefined)


def render_document(key: str, context: dict[str, str]) -> bytes:
    template = DocxTemplate(str(TEMPLATE_DIR / f"{key}.docx"))
    template.render(context, jinja_env=_env())
    buffer = io.BytesIO()
    template.save(buffer)
    return buffer.getvalue()


def file_stem(full_name: str) -> str:
    """„Anna Nowak-Kowalska” → „Anna_Nowak-Kowalska” (bez polskich znaków)."""
    folded = (
        unicodedata.normalize("NFKD", full_name).replace("ł", "l").replace("Ł", "L")
    )
    ascii_only = "".join(ch for ch in folded if not unicodedata.combining(ch))
    stem = re.sub(r"[^A-Za-z0-9-]+", "_", ascii_only).strip("_")
    return stem[:60] or "Uczestnik"


def render_package(data: DocumentInput) -> bytes:
    """ZIP z pięcioma dokumentami uczestnika."""
    context = context_for(data)
    stem = file_stem(data.participant_name)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for key, name in DOCUMENTS:
            archive.writestr(f"{name}_{stem}.docx", render_document(key, context))
    return buffer.getvalue()
