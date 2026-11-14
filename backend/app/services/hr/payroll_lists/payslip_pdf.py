"""Paski wynagrodzenia (K7a) — PDF z pozycji listy płac.

Jedna strona na pozycję listy (osoba × tytuł). Pasek pokazuje stronę osoby:
brutto i z czego się wzięło, składki osoby, zdrowotną, koszty, podstawę,
zaliczkę (albo podatek ryczałtowy), PPK i kwotę do wypłaty; koszty
pracodawcy są w osobnym bloku dla Płac (``employer=True``). Bez PESEL-u
i rachunku. Lista niezatwierdzona — znak wodny „PROJEKT”.

WeasyPrint i fonty DejaVu jak pozostałe PDF-y modułu (``settlements_pdf``);
renderowanie synchroniczne — z kodu async przez ``asyncio.to_thread``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from html import escape
from typing import Any, Optional, Sequence

from app.services.b2b_documents.company_party import COMPANY_PL
from app.services.hr.payroll_lists.engine import NOTE_LABELS
from app.services.hr.payroll_periods import MONTHS_PL

KIND_TITLES = {
    "uop": "Umowa o pracę",
    "zlecenie": "Umowa zlecenia",
    "dzielo": "Umowa o dzieło",
}


@dataclass(frozen=True)
class Payslip:
    list_number: str
    year: int
    month: int
    pay_date: date
    approved: bool
    person_name: str
    kind: str
    source_label: str
    basis: dict[str, Any]
    result: dict[str, Any]


def _d(raw: Any) -> Decimal:
    try:
        return Decimal(str(raw if raw not in (None, "") else "0"))
    except ArithmeticError:
        return Decimal("0")


def money(raw: Any) -> str:
    value = _d(raw).quantize(Decimal("0.01"))
    sign = "−" if value < 0 else ""
    whole, _, cents = f"{abs(value):.2f}".partition(".")
    groups = []
    while len(whole) > 3:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    groups.insert(0, whole)
    return f"{sign}{' '.join(groups)},{cents}"


def _row(label: str, amount: Any, *, strong: bool = False, minus: bool = False) -> str:
    value = money(amount)
    if minus and _d(amount) > 0:
        value = f"−{value}"
    cls = " class='total'" if strong else ""
    return f"<tr{cls}><td>{escape(label)}</td><td class='num'>{value} zł</td></tr>"


def _basis_rows(slip: Payslip) -> str:
    basis = slip.basis or {}
    rows: list[str] = []
    if slip.kind != "dzielo" and basis.get("hours") and basis.get("hourly_rate"):
        rows.append(
            f"<tr><td>Godziny × stawka ({escape(str(basis['hours']))} h × "
            f"{money(basis['hourly_rate'])} zł)</td>"
            f"<td class='num'>{money(basis.get('hours_amount'))} zł</td></tr>"
        )
    if (
        _d(basis.get("bonus_total")) > 0
        and slip.source_label != "kwota wpisana przez Rozliczenia"
    ):
        rows.append(_row("Premie", basis.get("bonus_total")))
    if basis.get("note"):
        rows.append(
            f"<tr><td colspan='2' class='hint'>Kwota wpisana przez Rozliczenia: "
            f"{escape(str(basis['note']))}</td></tr>"
        )
    return "".join(rows)


def _page(slip: Payslip, *, employer: bool) -> str:
    r = slip.result or {}
    period = f"{MONTHS_PL[slip.month - 1]} {slip.year}"
    tax_label = (
        "Podatek ryczałtowy"
        if r.get("tax_kind") == "flat"
        else "Zaliczka na podatek dochodowy"
    )
    employee = "".join(
        [
            _row("Wynagrodzenie brutto", r.get("gross"), strong=True),
            _basis_rows(slip),
            _row("Składka emerytalna", r.get("pension_employee"), minus=True),
            _row("Składka rentowa", r.get("disability_employee"), minus=True),
            _row("Składka chorobowa", r.get("sickness_employee"), minus=True),
            _row("Składka zdrowotna", r.get("health"), minus=True),
            _row(tax_label, r.get("pit"), minus=True),
            _row("Wpłata PPK", r.get("ppk_employee"), minus=True)
            if _d(r.get("ppk_employee")) > 0
            else "",
            _row("Do wypłaty", r.get("net"), strong=True),
        ]
    )
    tax = "".join(
        [
            _row("Przychód", r.get("revenue")),
            _row("w tym zwolniony (ulga)", r.get("exempt_revenue"))
            if _d(r.get("exempt_revenue")) > 0
            else "",
            _row("Koszty uzyskania przychodu", r.get("kup")),
            _row("Podstawa opodatkowania", r.get("tax_base")),
            _row("Kwota zmniejszająca (PIT-2)", r.get("tax_reduction"))
            if _d(r.get("tax_reduction")) > 0
            else "",
            _row("Wpłata pracodawcy PPK w przychodzie", r.get("ppk_employer_taxable"))
            if _d(r.get("ppk_employer_taxable")) > 0
            else "",
        ]
    )
    employer_block = ""
    if employer:
        employer_block = (
            "<h2>Koszty pracodawcy</h2><table class='items'><tbody>"
            + "".join(
                [
                    _row("Emerytalna", r.get("pension_employer")),
                    _row("Rentowa", r.get("disability_employer")),
                    _row("Wypadkowa", r.get("accident_employer")),
                    _row("Fundusz Pracy i FS", r.get("labour_fund")),
                    _row("FGŚP", r.get("fgsp")),
                    _row("PPK pracodawcy", r.get("ppk_employer"))
                    if _d(r.get("ppk_employer")) > 0
                    else "",
                    _row("Koszt razem", r.get("employer_cost"), strong=True),
                ]
            )
            + "</tbody></table>"
        )
    notes = "".join(
        f"<li>{escape(NOTE_LABELS.get(code, code))}</li>"
        for code in r.get("notes", [])
        if code in NOTE_LABELS
    )
    company = (
        f"{escape(COMPANY_PL['name'])}, {escape(COMPANY_PL['address'])}, "
        f"NIP {escape(COMPANY_PL['nip'])}"
    )
    watermark = "" if slip.approved else "<div class='draft'>PROJEKT</div>"
    return (
        "<section class='page'>" + watermark + "<h1>Pasek wynagrodzenia</h1>"
        f"<p class='period'>{escape(period)} · wypłata "
        f"{slip.pay_date.strftime('%d.%m.%Y')} · lista {escape(slip.list_number)}</p>"
        "<table class='meta'>"
        f"<tr><th>Osoba</th><td>{escape(slip.person_name)}</td></tr>"
        f"<tr><th>Tytuł</th><td>{escape(KIND_TITLES.get(slip.kind, slip.kind))}</td></tr>"
        f"<tr><th>Płatnik</th><td>{company}</td></tr>"
        "</table>"
        f"<table class='items'><tbody>{employee}</tbody></table>"
        f"<h2>Podatek</h2><table class='items'><tbody>{tax}</tbody></table>"
        + employer_block
        + (f"<ul class='notes'>{notes}</ul>" if notes else "")
        + "</section>"
    )


def render_html(slips: Sequence[Payslip], *, employer: bool = False) -> str:
    pages = "".join(_page(slip, employer=employer) for slip in slips)
    return (
        "<!DOCTYPE html><html lang='pl'><head><meta charset='utf-8'>"
        "<title>Paski wynagrodzenia</title><style>"
        "@page{size:A4;margin:16mm 14mm 18mm}"
        "body{font-family:'DejaVu Sans','Liberation Sans',sans-serif;font-size:9.5pt;"
        "color:#1f2933}"
        ".page{page-break-after:always;position:relative}"
        ".page:last-child{page-break-after:auto}"
        "h1{font-size:16pt;margin:0}h2{font-size:11pt;margin:12pt 0 4pt}"
        ".period{font-size:10pt;color:#52606d;margin:2pt 0 10pt}"
        "table{border-collapse:collapse;width:100%}"
        ".meta{width:auto;margin-bottom:10pt}.meta th{text-align:left;"
        "padding:1pt 12pt 1pt 0;font-weight:600;color:#52606d}.meta td{padding:1pt 0}"
        ".items td{border-bottom:0.5px solid #d9e2ec;padding:3pt 4pt}"
        ".num{text-align:right;white-space:nowrap}"
        ".total td{font-weight:700}"
        ".hint{font-size:8pt;color:#52606d}"
        ".notes{font-size:8pt;color:#52606d;margin-top:10pt;padding-left:12pt}"
        ".draft{position:absolute;top:220pt;left:60pt;font-size:72pt;color:#e4e7eb;"
        "transform:rotate(-30deg);z-index:-1}"
        "</style></head><body>" + pages + "</body></html>"
    )


def render_pdf(slips: Sequence[Payslip], *, employer: bool = False) -> bytes:
    from weasyprint import HTML

    return HTML(string=render_html(slips, employer=employer)).write_pdf()


def filename(list_number: str, person: Optional[str] = None) -> str:
    base = "paski-" + list_number.replace("/", "-").lower()
    if person:
        safe = "".join(ch if ch.isalnum() else "-" for ch in person).strip("-")
        base += f"-{safe.lower()}"
    return f"{base}.pdf"


__all__ = ["Payslip", "filename", "money", "render_html", "render_pdf"]
