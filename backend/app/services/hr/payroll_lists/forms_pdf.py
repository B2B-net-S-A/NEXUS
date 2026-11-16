"""Wydruk PIT-11, PIT-4R i PIT-8AR (K7a) — czytelne zestawienie, nie formularz urzędowy.

Zestawienie pokazuje te same pozycje co plik XML e-Deklaracji: obie strony
biorą je z ``pit_forms.*_document``, więc kwota na wydruku nie rozjedzie się
z wysłaną. Nagłówek mówi wprost, że to nie jest formularz urzędowy — wiąże
plik XML. PESEL i NIP osoby — kropki i 4 ostatnie cyfry (``pesel.masked``).
PIT-4R i PIT-8AR — tabela miesięcy (wiersze formularza w kolumnach).

WeasyPrint i fonty DejaVu jak pozostałe PDF-y modułu (``settlements_pdf``);
renderowanie synchroniczne — z kodu async przez ``asyncio.to_thread``. Data
wygenerowania przychodzi z wejścia (moduł nie czyta zegara).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from html import escape
from typing import Optional

from app.services.hr.payroll_lists import pit_forms
from app.services.hr.payroll_lists.pesel import last4, masked
from app.services.hr.payroll_lists.pit_forms import (
    FormDocument,
    FormField,
    Pit4rMonth,
    Pit11Amounts,
    Pit11Person,
    TaxPayer,
)
from app.services.hr.time_pdf import name_slug

NBSP = "\u00a0"  # spacja nierozdzielająca w kwotach
MONTHS = ("I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII")


def _grouped(number: str) -> str:
    groups: list[str] = []
    while len(number) > 3:
        groups.insert(0, number[-3:])
        number = number[:-3]
    groups.insert(0, number)
    return NBSP.join(groups)


def display(field: FormField) -> str:
    """Wartość pola po polsku: „1 234,56 zł”, „1 234 zł”, liczba albo kod wyboru."""

    if field.kind == "zl_gr":
        whole, _, cents = field.value.partition(".")
        return f"{_grouped(whole)},{cents or '00'}{NBSP}zł"
    if field.kind == "zl":
        return f"{_grouped(field.value)}{NBSP}zł"
    return field.value


def _total(fields: list[FormField]) -> str:
    kind = fields[0].kind
    if kind not in ("zl", "zl_gr"):
        return "—"
    total = sum((Decimal(f.value) for f in fields), Decimal("0"))
    value = f"{total:.2f}" if kind == "zl_gr" else str(int(total))
    return display(FormField("", "", value, "", kind))


def _masked_id(value: Optional[str]) -> str:
    """PESEL albo NIP osoby na wydruku: kropki i 4 ostatnie cyfry."""

    if not value:
        return "—"
    return masked(last4(value)) or "—"


def _address_line(person: Pit11Person) -> str:
    address = person.address
    if address is None:
        return "—"
    number = "/".join(
        part for part in (address.house_number, address.flat_number) if part
    )
    street = " ".join(part for part in (address.street, number) if part)
    city = " ".join(part for part in (address.postal_code, address.city) if part)
    country = "" if address.country_code == "PL" else address.country_code
    return ", ".join(part for part in (street, city, country) if part)


def _meta(doc: FormDocument) -> str:
    rows = [
        ("Płatnik", doc.payer_name),
        ("NIP płatnika", doc.payer_nip),
        ("Cel złożenia", pit_forms.PURPOSES[doc.purpose]),
    ]
    person = doc.person
    if person is not None:
        rows += [
            ("Podatnik", f"{person.first_name} {person.last_name}"),
            (
                "PESEL" if person.pesel else "NIP",
                _masked_id(person.pesel or person.nip),
            ),
            ("Adres zamieszkania", _address_line(person)),
            ("Urząd skarbowy podatnika", doc.office_code),
        ]
    else:
        rows.append(("Urząd skarbowy płatnika", doc.office_code))
    return (
        "<table class='meta'>"
        + "".join(f"<tr><th>{escape(k)}</th><td>{escape(v)}</td></tr>" for k, v in rows)
        + "</table>"
    )


def _field_tables(fields: list[FormField]) -> str:
    groups: dict[str, list[FormField]] = {}
    for field in fields:
        groups.setdefault(field.group, []).append(field)
    out: list[str] = []
    for group, items in groups.items():
        rows = "".join(
            f"<tr><td class='code'>poz. {escape(f.code[2:])}</td><td>{escape(f.label)}</td>"
            f"<td class='num'>{escape(display(f))}</td></tr>"
            for f in items
        )
        out.append(
            f"<h2>{escape(group)}</h2><table class='items'><thead><tr><th>Pozycja</th>"
            f"<th>Opis</th><th class='num'>Wartość</th></tr></thead><tbody>{rows}</tbody>"
            "</table>"
        )
    return "".join(out)


def _month_table(fields: list[FormField]) -> str:
    columns: dict[str, dict[int, FormField]] = {}
    for field in fields:
        columns.setdefault(field.label, {})[field.month or 0] = field
    head = "".join(f"<th class='num'>{escape(label)}</th>" for label in columns)
    body = "".join(
        f"<tr><td>{MONTHS[m - 1]}</td>"
        + "".join(
            f"<td class='num'>{escape(display(column[m]))}</td>"
            for column in columns.values()
        )
        + "</tr>"
        for m in range(1, 13)
    )
    total = "".join(
        f"<td class='num'>{escape(_total(list(column.values())))}</td>"
        for column in columns.values()
    )
    return (
        "<table class='items months'><thead><tr><th>Miesiąc</th>"
        f"{head}</tr></thead><tbody>{body}<tr class='total'><td>Razem</td>{total}</tr>"
        "</tbody></table>"
    )


def document_html(doc: FormDocument, *, generated_on: Optional[date] = None) -> str:
    """Formularz po walidacji → HTML zestawienia (A4)."""

    spec = doc.spec
    title = (
        f"{spec.form} za {doc.year} — zestawienie z NEXUSA "
        "(nie jest formularzem urzędowym)"
    )
    monthly = [f for f in doc.fields if f.month is not None]
    yearly = [f for f in doc.fields if f.month is None]
    body = (
        f"<h1>{escape(title)}</h1>"
        f"<p class='subtitle'>{escape(spec.title)} · wzór {escape(spec.form)} "
        f"({spec.variant}), schemat {escape(spec.schema_version)}</p>"
        + _meta(doc)
        + (_month_table(monthly) if monthly else "")
        + (
            "<p class='legend'>"
            + " · ".join(
                escape(group) for group in dict.fromkeys(f.group for f in monthly)
            )
            + "</p>"
            if monthly
            else ""
        )
        + _field_tables(yearly)
    )
    generated = f" · Wygenerowano {generated_on:%d.%m.%Y}" if generated_on else ""
    footer = (
        "Zestawienie z NEXUSA — nie jest formularzem urzędowym. Wiąże plik XML "
        f"e-Deklaracji {escape(spec.system_code)}, schemat {escape(spec.schema_version)}"
        f"{generated}"
    )
    return (
        "<!DOCTYPE html><html lang='pl'><head><meta charset='utf-8'>"
        f"<title>{escape(title)}</title><style>"
        "@page{size:A4;margin:16mm 14mm 22mm;"
        "@bottom-left{content:element(footer)}"
        "@bottom-right{content:counter(page) ' / ' counter(pages);font-size:7.5pt;color:#666}}"
        "body{font-family:'DejaVu Sans','Liberation Sans',sans-serif;font-size:9pt;"
        "color:#1f2933}"
        "h1{font-size:14pt;margin:0}h2{font-size:10pt;margin:12pt 0 4pt;color:#334e68}"
        ".subtitle{font-size:9pt;color:#52606d;margin:2pt 0 10pt}"
        "table{border-collapse:collapse;width:100%}"
        ".meta{width:auto;margin-bottom:8pt}.meta th{text-align:left;padding:1pt 12pt 1pt 0;"
        "font-weight:600;color:#52606d}.meta td{padding:1pt 0}"
        ".items th{text-align:left;border-bottom:1px solid #9aa5b1;padding:3pt 4pt;"
        "font-size:8pt;color:#52606d}"
        ".items td{border-bottom:0.5px solid #d9e2ec;padding:3pt 4pt;vertical-align:top}"
        ".months th,.months td{font-size:8pt}"
        ".code{white-space:nowrap;color:#52606d}"
        ".num{text-align:right;white-space:nowrap}"
        ".total td{font-weight:700;border-bottom:none;border-top:1px solid #9aa5b1}"
        ".legend{font-size:7.5pt;color:#52606d;margin:4pt 0 0}"
        ".footer{position:running(footer);font-size:7pt;color:#52606d}"
        "</style></head><body>"
        f"<div class='footer'>{footer}</div>{body}</body></html>"
    )


def _pdf(html: str) -> bytes:
    from weasyprint import HTML

    return HTML(string=html).write_pdf()


def pit11_html(
    year: int,
    payer: TaxPayer,
    person: Pit11Person,
    amounts: Pit11Amounts,
    purpose: str = "1",
    *,
    generated_on: Optional[date] = None,
) -> str:
    doc = pit_forms.pit11_document(year, payer, person, amounts, purpose)
    return document_html(doc, generated_on=generated_on)


def pit4r_html(
    year: int,
    payer: TaxPayer,
    months: Mapping[int, Pit4rMonth],
    purpose: str = "1",
    *,
    generated_on: Optional[date] = None,
) -> str:
    doc = pit_forms.pit4r_document(year, payer, months, purpose)
    return document_html(doc, generated_on=generated_on)


def pit8ar_html(
    year: int,
    payer: TaxPayer,
    months: Mapping[int, Decimal],
    purpose: str = "1",
    *,
    generated_on: Optional[date] = None,
) -> str:
    doc = pit_forms.pit8ar_document(year, payer, months, purpose)
    return document_html(doc, generated_on=generated_on)


def pit11_pdf(
    year: int,
    payer: TaxPayer,
    person: Pit11Person,
    amounts: Pit11Amounts,
    purpose: str = "1",
    *,
    generated_on: Optional[date] = None,
) -> bytes:
    return _pdf(
        pit11_html(year, payer, person, amounts, purpose, generated_on=generated_on)
    )


def pit4r_pdf(
    year: int,
    payer: TaxPayer,
    months: Mapping[int, Pit4rMonth],
    purpose: str = "1",
    *,
    generated_on: Optional[date] = None,
) -> bytes:
    return _pdf(pit4r_html(year, payer, months, purpose, generated_on=generated_on))


def pit8ar_pdf(
    year: int,
    payer: TaxPayer,
    months: Mapping[int, Decimal],
    purpose: str = "1",
    *,
    generated_on: Optional[date] = None,
) -> bytes:
    return _pdf(pit8ar_html(year, payer, months, purpose, generated_on=generated_on))


def filename(form: str, year: int, person_name: Optional[str] = None) -> str:
    """``pit-11-2026-anna-przykladowa.pdf``, ``pit-4r-2026.pdf``."""

    stem = f"{name_slug(form)}-{year}"
    if person_name:
        stem += f"-{name_slug(person_name)}"
    return f"{stem}.pdf"


__all__ = [
    "MONTHS",
    "display",
    "document_html",
    "filename",
    "pit11_html",
    "pit11_pdf",
    "pit4r_html",
    "pit4r_pdf",
    "pit8ar_html",
    "pit8ar_pdf",
]
