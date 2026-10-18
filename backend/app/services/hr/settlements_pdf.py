"""PDF rozliczenia umowy zlecenia (R3) — potwierdzenie godzin z kwotą brutto.

Rachunek na zleceniu nie jest obowiązkowy: wystarczy potwierdzenie liczby
godzin (art. 8b ustawy o minimalnym wynagrodzeniu) i wypłata co najmniej raz
w miesiącu. Ten PDF składa rozliczenie z przyjętego raportu godzin
i zamrożonej linii płac; biuro może go traktować jak rachunek (bez podpisu).
Podatków i składek nie liczy (R4) — to robi program płacowy.

W stopce suma kontrolna treści (``payroll_settlements.document_sha256``,
``settlements_items.document_hash``) — ta sama przy każdym pobraniu.
WeasyPrint i fonty DejaVu jak PDF raportu godzin (``time_pdf``); renderowanie
synchroniczne — z kodu async przez ``asyncio.to_thread``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from html import escape
from typing import Optional, Sequence
from zoneinfo import ZoneInfo

from app.core.scheduling import DEFAULT_TZ
from app.services.b2b_documents.company_party import COMPANY_PL
from app.services.hr.payroll_rates import format_pln
from app.services.hr.settlements_items import SettlementItem, period_text
from app.services.hr.time_pdf import pdf_filename


@dataclass(frozen=True)
class SettlementPdf:
    person_name: str
    year: int
    month: int
    currency: str
    items: Sequence[SettlementItem]
    total: Decimal
    hourly_rate: Optional[Decimal]
    minimum_rate: Optional[Decimal]
    hours_confirmed_on: Optional[date]
    hours_confirmed_by: Optional[str]
    student_exempt_until: Optional[date]
    student_exempt: bool
    document_sha256: str


def _money(value: Decimal, currency: str) -> str:
    return f"{format_pln(value)} {'zł' if currency == 'PLN' else currency}"


def _date(value: Optional[date]) -> str:
    return value.strftime("%d.%m.%Y") if value else "—"


def filename(person_name: str, year: int, month: int) -> str:
    return pdf_filename(person_name, year, month).replace(
        "timesheet-", "rozliczenie-zlecenia-", 1
    )


def render_html(doc: SettlementPdf) -> str:
    period = period_text(doc.year, doc.month)
    rows = "".join(
        f"<tr><td>{escape(item.label)}</td>"
        f"<td class='num'>{_money(item.amount, doc.currency)}</td></tr>"
        for item in doc.items
    )
    notes: list[str] = []
    if doc.hours_confirmed_on:
        who = f" ({escape(doc.hours_confirmed_by)})" if doc.hours_confirmed_by else ""
        notes.append(
            f"Liczba godzin potwierdzona {_date(doc.hours_confirmed_on)}{who} — "
            "art. 8b ustawy o minimalnym wynagrodzeniu za pracę."
        )
    if doc.hourly_rate is not None:
        minimum = (
            f"; minimalna w {doc.year}: {format_pln(doc.minimum_rate)} zł/h"
            if doc.minimum_rate is not None
            else ""
        )
        notes.append(f"Stawka {format_pln(doc.hourly_rate)} zł/h brutto{minimum}.")
    if doc.student_exempt:
        until = (
            f" do {_date(doc.student_exempt_until)}" if doc.student_exempt_until else ""
        )
        notes.append(f"Uczeń albo student do 26 lat — bez składek ZUS{until}.")
    notes.append(
        "Zaliczkę na podatek, składki i kwotę do wypłaty liczy program płacowy."
    )
    generated = datetime.now(ZoneInfo(DEFAULT_TZ)).strftime("%d.%m.%Y %H:%M")
    company = (
        f"{escape(COMPANY_PL['name'])}, {escape(COMPANY_PL['address'])}, "
        f"NIP {escape(COMPANY_PL['nip'])}"
    )
    body = (
        "<h1>Rozliczenie umowy zlecenia</h1>"
        f"<p class='period'>{escape(period)}</p>"
        "<table class='meta'>"
        f"<tr><th>Zleceniobiorca</th><td>{escape(doc.person_name)}</td></tr>"
        f"<tr><th>Zleceniodawca</th><td>{company}</td></tr>"
        f"<tr><th>Okres</th><td>{escape(period)}</td></tr>"
        "</table>"
        "<table class='items'><thead><tr><th>Pozycja</th>"
        "<th class='num'>Kwota</th></tr></thead><tbody>"
        + rows
        + "<tr class='total'><td>Wynagrodzenie brutto</td>"
        f"<td class='num'>{_money(doc.total, doc.currency)}</td></tr>"
        "</tbody></table>" + "".join(f"<p class='note'>{note}</p>" for note in notes)
    )
    footer = (
        f"Wygenerowano: {generated} · Suma kontrolna rozliczenia SHA-256: "
        f"{escape(doc.document_sha256)}"
    )
    return (
        "<!DOCTYPE html><html lang='pl'><head><meta charset='utf-8'>"
        f"<title>Rozliczenie umowy zlecenia {escape(period)}</title><style>"
        "@page{size:A4;margin:16mm 14mm 22mm;"
        "@bottom-left{content:element(footer)}}"
        "body{font-family:'DejaVu Sans','Liberation Sans',sans-serif;font-size:9.5pt;"
        "color:#1f2933}"
        "h1{font-size:16pt;margin:0}.period{font-size:11pt;color:#52606d;margin:2pt 0 10pt}"
        "table{border-collapse:collapse;width:100%}"
        ".meta{width:auto;margin-bottom:12pt}.meta th{text-align:left;padding:1pt 12pt 1pt 0;"
        "font-weight:600;color:#52606d}.meta td{padding:1pt 0}"
        ".items th{text-align:left;border-bottom:1px solid #9aa5b1;padding:4pt;"
        "font-size:8pt;color:#52606d}"
        ".items td{border-bottom:0.5px solid #d9e2ec;padding:4pt;vertical-align:top}"
        ".num{text-align:right;white-space:nowrap}"
        ".total td{font-weight:700;border-bottom:none;border-top:1px solid #9aa5b1}"
        ".note{font-size:8.5pt;color:#52606d;margin:6pt 0 0}"
        ".footer{position:running(footer);font-size:7pt;color:#52606d}"
        "</style></head><body>"
        f"<div class='footer'>{footer}</div>{body}</body></html>"
    )


def render_pdf(doc: SettlementPdf) -> bytes:
    from weasyprint import HTML

    return HTML(string=render_html(doc)).write_pdf()


__all__ = ["SettlementPdf", "filename", "render_html", "render_pdf"]
