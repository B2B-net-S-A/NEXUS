"""PDF karty pracy (timesheetu) z sumą kontrolną w stopce i ZIP miesiąca.

WeasyPrint (już w obrazie — umowy dla Autenti), fonty DejaVu, więc polskie
znaki są polskie (Compass transliterował je do ASCII). Pełna suma SHA-256
w stopce: każdy może ją porównać z ``pdf_hash`` w NEXUSIE. Pobranie
zaakceptowanego timesheetu liczy sumę bieżących wpisów — rozjazd z zapisaną
= 409 i wpis w śladzie HR (``hash_mismatch``), nie plik.

Funkcje renderujące są synchroniczne — z kodu async przez ``asyncio.to_thread``.
"""

from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from html import escape
from typing import Optional, Sequence
from zoneinfo import ZoneInfo

from app.core.scheduling import DEFAULT_TZ
from app.services.hr.employment_terms import FORM_LABELS, terms
from app.services.hr.payroll_periods import MONTHS_PL

WEEKDAYS = ("pon", "wt", "śr", "czw", "pt", "sob", "nd")


@dataclass(frozen=True)
class PdfEntry:
    work_date: str
    hours: Decimal
    project: Optional[str]
    description: str
    is_overtime: bool


@dataclass(frozen=True)
class PdfTimesheet:
    person_name: str
    person_email: str
    employment_type: Optional[str]
    year: int
    month: int
    pdf_hash: str
    approved_at: Optional[datetime]
    approved_by_name: Optional[str]
    entries: Sequence[PdfEntry]


def _hours(value: Decimal) -> str:
    return f"{value:.2f}".replace(".", ",")


def _local(moment: Optional[datetime]) -> str:
    if moment is None:
        return "—"
    return moment.astimezone(ZoneInfo(DEFAULT_TZ)).strftime("%d.%m.%Y %H:%M")


def name_slug(person_name: str) -> str:
    """Imię i nazwisko w nazwie pliku: ASCII, małe litery, myślniki."""

    ascii_name = (
        unicodedata.normalize("NFKD", person_name.replace("ł", "l").replace("Ł", "L"))
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )
    return re.sub(r"[^a-z0-9]+", "-", ascii_name).strip("-") or "osoba"


def pdf_filename(person_name: str, year: int, month: int) -> str:
    return f"timesheet-{name_slug(person_name)}-{year}-{month:02d}.pdf"


def render_html(sheet: PdfTimesheet) -> str:
    rows = []
    total = Decimal("0")
    overtime_days = set()
    words = terms(sheet.employment_type)
    for entry in sorted(sheet.entries, key=lambda e: (e.work_date, e.description)):
        total += entry.hours
        day = date.fromisoformat(entry.work_date)
        tag = ""
        if entry.is_overtime:
            overtime_days.add(entry.work_date)
            tag = f" <span class='tag'>{escape(words['overtime_stat'])}</span>"
        rows.append(
            "<tr>"
            f"<td class='nowrap'>{day.day}.{day.month:02d}</td>"
            f"<td class='muted'>{WEEKDAYS[day.weekday()]}</td>"
            f"<td>{escape(entry.project or '—')}</td>"
            f"<td>{escape(entry.description)}{tag}</td>"
            f"<td class='num'>{_hours(entry.hours)}</td>"
            "</tr>"
        )
    period = f"{MONTHS_PL[sheet.month - 1]} {sheet.year}"
    # Bez formy w kartotece PDF pisze „—” (słowa i tak są jak dla umowy o pracę).
    employment = FORM_LABELS.get(sheet.employment_type or "", "—")
    generated = _local(datetime.now(ZoneInfo(DEFAULT_TZ)))
    # Nazwa dokumentu i role z formy współpracy (D4): ewidencja czasu pracy,
    # raport godzin do faktury albo potwierdzenie liczby godzin (art. 8b).
    title = words["timesheet_document"]
    note = words["timesheet_document_note"]
    body = (
        f"<h1>{escape(title)}</h1>"
        + (f"<p class='legal'>{escape(note)}</p>" if note else "")
        + f"<p class='period'>{escape(period)}</p>"
        "<table class='meta'>"
        f"<tr><th>{escape(words['person'])}</th><td>{escape(sheet.person_name)}</td></tr>"
        f"<tr><th>E-mail</th><td>{escape(sheet.person_email)}</td></tr>"
        f"<tr><th>Forma współpracy</th><td>{escape(employment)}</td></tr>"
        f"<tr><th>Liczba wpisów</th><td>{len(sheet.entries)}</td></tr>"
        f"<tr><th>Suma godzin</th><td>{_hours(total)} h</td></tr>"
        f"<tr><th>Dni z {escape(words['overtime_instrumental'])}</th>"
        f"<td>{len(overtime_days)}</td></tr>"
        "</table>"
        "<table class='entries'><thead><tr>"
        "<th>Data</th><th>Dzień</th><th>Projekt</th><th>Opis</th><th class='num'>Godziny</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + f"<tr class='total'><td colspan='4'>Razem</td><td class='num'>{_hours(total)}</td></tr>"
        "</tbody></table>"
        "<div class='sign'>"
        f"<div>Podpis: {escape(words['person'].lower())}</div>"
        f"<div>Podpis: {escape(words['reviewer'].lower())}</div></div>"
    )
    footer = (
        f"{escape(words['reviewed_by'])}: {escape(sheet.approved_by_name or '—')}, "
        f"{_local(sheet.approved_at)} · Wygenerowano: {generated} · "
        f"Suma kontrolna SHA-256: {escape(sheet.pdf_hash)}"
    )
    return (
        "<!DOCTYPE html><html lang='pl'><head><meta charset='utf-8'>"
        f"<title>{escape(title)} {escape(period)}</title><style>"
        "@page{size:A4;margin:16mm 14mm 22mm;"
        "@bottom-left{content:element(footer)}"
        "@bottom-right{content:counter(page) ' / ' counter(pages);font-size:7.5pt;color:#666}}"
        "body{font-family:'DejaVu Sans','Liberation Sans',sans-serif;font-size:9pt;color:#1f2933}"
        "h1{font-size:16pt;margin:0}.period{font-size:11pt;color:#52606d;margin:2pt 0 10pt}"
        ".legal{font-size:8pt;color:#52606d;margin:2pt 0 0}"
        "table{border-collapse:collapse;width:100%}"
        ".meta{width:auto;margin-bottom:10pt}.meta th{text-align:left;padding:1pt 12pt 1pt 0;"
        "font-weight:600;color:#52606d}.meta td{padding:1pt 0}"
        ".entries th{text-align:left;border-bottom:1px solid #9aa5b1;padding:4pt 4pt;"
        "font-size:8pt;color:#52606d}"
        ".entries td{border-bottom:0.5px solid #d9e2ec;padding:3pt 4pt;vertical-align:top}"
        ".num{text-align:right;white-space:nowrap}.nowrap{white-space:nowrap}.muted{color:#7b8794}"
        ".total td{font-weight:700;border-bottom:none;border-top:1px solid #9aa5b1}"
        ".tag{font-size:7pt;color:#8a4b00;border:0.5px solid #d9a55c;border-radius:2pt;"
        "padding:0 2pt}"
        ".sign{display:flex;justify-content:space-between;margin-top:36pt}"
        ".sign div{width:42%;border-top:0.5px solid #7b8794;padding-top:3pt;color:#52606d;"
        "font-size:8pt}"
        ".footer{position:running(footer);font-size:7pt;color:#52606d}"
        "</style></head><body>"
        f"<div class='footer'>{footer}</div>"
        f"{body}</body></html>"
    )


def render_pdf(sheet: PdfTimesheet) -> bytes:
    from weasyprint import HTML

    return HTML(string=render_html(sheet)).write_pdf()


def render_zip(sheets: Sequence[PdfTimesheet], skipped: Sequence[str]) -> bytes:
    """ZIP PDF-ów miesiąca; ``skipped`` — osoby bez pliku (rozjazd sumy)."""

    buffer = io.BytesIO()
    used: set[str] = set()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for sheet in sheets:
            name = pdf_filename(sheet.person_name, sheet.year, sheet.month)
            stem, counter = name[:-4], 2
            while name in used:
                name = f"{stem}-{counter}.pdf"
                counter += 1
            used.add(name)
            archive.writestr(name, render_pdf(sheet))
        if skipped:
            archive.writestr(
                "pominiete.txt",
                "Bez pliku — suma kontrolna wpisów nie zgadza się z zapisaną przy "
                "akceptacji (sprawdź ślad HR):\n" + "\n".join(skipped) + "\n",
            )
    return buffer.getvalue()
