"""Pliki paczki dla Symfonii ERP Kadry i Płace — czyste funkcje renderujące.

Formaty według dokumentacji Symfonii 2026 (``scratchpad/symfonia-research.md``):

* ``zdarzenia_RRRR-MM.xml`` — „Firma › Import zdarzeń”: ``ev-document``
  w windows-1250, słownik osób (``calendar type="employee"``: nazwisko, imię,
  ``guid`` gdy identyfikator z Symfonii jest GUID-em) i zdarzeń (dokładna
  nazwa z „Definicji zdarzeń”), dane ``<event id calendar begin end [start
  stop]/>``. Nadgodziny i pół dnia nieobecności mają godziny ``GG:MM:0``,
* ``premie_RRRR-MM.xlsx`` — szablon „danych kadrowych”: osoba, daty od–do
  (pierwszy i ostatni dzień miesiąca), kolumna na każdy rodzaj premii,
* ``zlecenia_rozliczenia_RRRR-MM.xlsx`` — szablon „rozliczeń umów
  cywilnoprawnych”: rodzaj umowy, forma płatności, data umowy (identyfikacja
  umowy), data rozliczenia, kwota brutto + godziny i stawka do kontroli,
* ``zestawienie_RRRR-MM.pdf`` — sumy kontrolne, skróty plików i lista rzeczy
  do zrobienia ręcznie (WeasyPrint jak PDF timesheetu).

Nazwy kolumn arkuszy są stałe — Płace mapują je raz w szablonie importu
Symfonii. Daty idą jako daty, kwoty jako liczby. PESEL-u nie ma nigdzie.
Tekst do arkuszy przez ``safe_row`` (formuły z danych się nie wykonują).
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from html import escape
from typing import Optional
from xml.sax.saxutils import escape as xml_escape
from xml.sax.saxutils import quoteattr

from app.core.export_safety import safe_row

XML_ENCODING = "windows-1250"
GUID = re.compile(
    r"^\{?[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}?$"
)

PERSON_COLUMNS = ("Nazwisko", "Imię", "Identyfikator")
BONUS_DATE_COLUMNS = ("Data od", "Data do")
MANDATE_COLUMNS = (
    *PERSON_COLUMNS,
    "Rodzaj umowy",
    "Forma płatności",
    "Data umowy",
    "Data rozliczenia",
    "Kwota brutto",
    "Godziny",
    "Stawka",
    "W tym premie",
    "Okres",
)


@dataclass(frozen=True)
class SymfoniaPerson:
    user_id: int
    surname: str
    given_name: str
    symfonia_id: str

    @property
    def guid(self) -> Optional[str]:
        if not GUID.match(self.symfonia_id):
            return None
        return "{" + self.symfonia_id.strip("{}").upper() + "}"


@dataclass(frozen=True)
class SymfoniaEvent:
    person: SymfoniaPerson
    name: str
    begin: date
    end: date
    start: Optional[str] = None
    stop: Optional[str] = None


@dataclass(frozen=True)
class BonusRow:
    person: SymfoniaPerson
    amounts: dict[str, Decimal]


@dataclass(frozen=True)
class MandateRow:
    person: SymfoniaPerson
    contract_date: Optional[date]
    settlement_date: date
    gross: Decimal
    hours: Decimal
    rate: Optional[Decimal]
    bonuses: Decimal


@dataclass
class SummaryFile:
    name: str
    description: str
    rows: int
    sha256: str = ""


@dataclass
class Summary:
    title: str
    generated_by: str
    generated_at: datetime
    files: list[SummaryFile] = field(default_factory=list)
    totals: list[tuple[str, str]] = field(default_factory=list)
    todo: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)


def split_name(full_name: str) -> tuple[str, str]:
    """``Anna Maria Przykładowa`` → (``Przykładowa``, ``Anna Maria``)."""

    parts = (full_name or "").split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[-1], " ".join(parts[:-1])


def time_text(minutes: int) -> str:
    """Minuty od północy → ``GG:MM:0`` (zapis z przykładu dokumentacji)."""

    minutes = max(0, min(minutes, 23 * 60 + 59))
    return f"{minutes // 60:02d}:{minutes % 60:02d}:0"


def events_xml(events: Sequence[SymfoniaEvent], *, export_date: date) -> bytes:
    people: dict[int, tuple[int, SymfoniaPerson]] = {}
    names: dict[str, int] = {}
    for event in events:
        people.setdefault(event.person.user_id, (len(people) + 1, event.person))
        names.setdefault(event.name, len(names) + 1)
    lines = [
        f'<?xml version="1.0" encoding="{XML_ENCODING}" standalone="yes"?>',
        f'<ev-document date="{export_date.isoformat()}" user="NEXUS">',
        " <dictionary>",
    ]
    for number, person in people.values():
        lines.append(f'  <calendar id="{number}" type="employee">')
        lines.append(f"   <surname>{xml_escape(person.surname)}</surname>")
        lines.append(f"   <name>{xml_escape(person.given_name)}</name>")
        if person.guid:
            lines.append(f"   <guid>{person.guid}</guid>")
        lines.append("  </calendar>")
    for name, number in names.items():
        lines.append(f'  <event id="{number}"><name>{xml_escape(name)}</name></event>')
    lines.append(" </dictionary>")
    lines.append(" <data>")
    for event in events:
        number, _person = people[event.person.user_id]
        attrs = (
            f'id="{names[event.name]}" calendar="{number}" '
            f'begin="{event.begin.isoformat()}" end="{event.end.isoformat()}"'
        )
        if event.start and event.stop:
            attrs += f" start={quoteattr(event.start)} stop={quoteattr(event.stop)}"
        lines.append(f"  <event {attrs}/>")
    lines.append(" </data>")
    lines.append("</ev-document>")
    # Znak spoza windows-1250 → odwołanie znakowe XML (czytelne dla parsera).
    return ("\r\n".join(lines) + "\r\n").encode(
        XML_ENCODING, errors="xmlcharrefreplace"
    )


def _person_cells(person: SymfoniaPerson) -> list[object]:
    return [person.surname, person.given_name, person.symfonia_id]


def _workbook_bytes(title: str, header: Sequence[str], rows: Sequence[list]) -> bytes:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = title
    # Nazwy kolumn premii wpisują Płace w Ustawieniach — też przez safe_row.
    sheet.append(safe_row(header))
    for row in rows:
        sheet.append(row)
    for column in sheet.columns:
        for cell in column[1:]:
            if isinstance(cell.value, date):
                cell.number_format = "yyyy-mm-dd"
            elif isinstance(cell.value, float):
                cell.number_format = "0.00"
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def bonuses_xlsx(
    rows: Sequence[BonusRow], columns: Sequence[str], *, first: date, last: date
) -> bytes:
    """CPU — wołać przez ``asyncio.to_thread``."""

    body = []
    for row in rows:
        body.append(
            safe_row(
                [
                    *_person_cells(row.person),
                    first,
                    last,
                    *[
                        float(row.amounts[name]) if name in row.amounts else None
                        for name in columns
                    ],
                ]
            )
        )
    return _workbook_bytes(
        "Premie", [*PERSON_COLUMNS, *BONUS_DATE_COLUMNS, *columns], body
    )


def mandates_xlsx(
    rows: Sequence[MandateRow], *, contract_kind: str, payment_form: str, period: str
) -> bytes:
    """CPU — wołać przez ``asyncio.to_thread``."""

    body = [
        safe_row(
            [
                *_person_cells(row.person),
                contract_kind,
                payment_form,
                row.contract_date,
                row.settlement_date,
                float(row.gross),
                float(row.hours),
                float(row.rate) if row.rate is not None else None,
                float(row.bonuses),
                period,
            ]
        )
        for row in rows
    ]
    return _workbook_bytes("Rozliczenia", MANDATE_COLUMNS, body)


def summary_html(summary: Summary) -> str:
    files = "".join(
        "<tr>"
        f"<td>{escape(item.name)}</td><td>{escape(item.description)}</td>"
        f"<td class='num'>{item.rows}</td>"
        f"<td class='hash'>{escape(item.sha256)}</td>"
        "</tr>"
        for item in summary.files
    )
    totals = "".join(
        f"<tr><th>{escape(label)}</th><td class='num'>{escape(value)}</td></tr>"
        for label, value in summary.totals
    )
    todo = "".join(f"<li>{escape(item)}</li>" for item in summary.todo) or (
        "<li>Nic — wszystkie osoby mają identyfikator z Symfonii.</li>"
    )
    notes = "".join(f"<li>{escape(item)}</li>" for item in summary.notes)
    steps = "".join(f"<li>{escape(item)}</li>" for item in summary.steps)
    generated = summary.generated_at.strftime("%d.%m.%Y %H:%M")
    return (
        "<!DOCTYPE html><html lang='pl'><head><meta charset='utf-8'>"
        f"<title>{escape(summary.title)}</title><style>"
        "@page{size:A4;margin:16mm 14mm 18mm;"
        "@bottom-right{content:counter(page) ' / ' counter(pages);font-size:7.5pt;color:#666}}"
        "body{font-family:'DejaVu Sans','Liberation Sans',sans-serif;font-size:9pt;color:#1f2933}"
        "h1{font-size:15pt;margin:0 0 2pt}h2{font-size:10.5pt;margin:14pt 0 4pt}"
        ".meta{color:#52606d;margin-bottom:8pt}"
        "table{border-collapse:collapse;width:100%}"
        "th,td{text-align:left;padding:3pt 4pt;border-bottom:0.5px solid #d9e2ec;vertical-align:top}"
        ".num{text-align:right;white-space:nowrap}.hash{font-size:6.5pt;color:#52606d;word-break:break-all}"
        "ul,ol{margin:2pt 0 0 14pt;padding:0}li{margin:2pt 0}"
        "</style></head><body>"
        f"<h1>{escape(summary.title)}</h1>"
        f"<p class='meta'>Przygotował(a): {escape(summary.generated_by)} · {generated}</p>"
        "<h2>Pliki w paczce</h2><table><thead><tr><th>Plik</th><th>Co zawiera</th>"
        "<th class='num'>Wiersze</th><th>Suma kontrolna SHA-256</th></tr></thead>"
        f"<tbody>{files}</tbody></table>"
        + (f"<h2>Sumy kontrolne</h2><table>{totals}</table>" if totals else "")
        + f"<h2>Do zrobienia ręcznie w Symfonii</h2><ul>{todo}</ul>"
        + (f"<h2>Uwagi</h2><ul>{notes}</ul>" if notes else "")
        + (f"<h2>Jak zaimportować</h2><ol>{steps}</ol>" if steps else "")
        + "</body></html>"
    )


def summary_pdf(summary: Summary) -> bytes:
    """CPU — wołać przez ``asyncio.to_thread``."""

    from weasyprint import HTML

    return HTML(string=summary_html(summary)).write_pdf()


def zip_bytes(files: Sequence[tuple[str, bytes]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files:
            archive.writestr(name, content)
    return buffer.getvalue()


__all__ = [
    "BonusRow",
    "MANDATE_COLUMNS",
    "MandateRow",
    "PERSON_COLUMNS",
    "Summary",
    "SummaryFile",
    "SymfoniaEvent",
    "SymfoniaPerson",
    "XML_ENCODING",
    "bonuses_xlsx",
    "events_xml",
    "mandates_xlsx",
    "split_name",
    "summary_html",
    "summary_pdf",
    "time_text",
    "zip_bytes",
]
