"""PDF faktury do załącznika e-faktury (``AdditionalDocumentReference``).

KSeF nie daje PDF-a, a EBI24 nie udostępnia go przez API, więc NEXUS składa
wizualizację z tego samego XML-a FA, z którego powstaje UBL: strony, pozycje
(cena przed rabatem, rabat, netto, stawka), podsumowanie, numer KSeF. Tekst
dwujęzyczny jak na fakturach EBI24 dla zagranicznych klientów.
"""

from __future__ import annotations

from decimal import Decimal
from html import escape
from typing import Optional

from app.services.peppol.fa_reader import FaDocument, FaParty

_CSS = (
    "@page{size:A4;margin:16mm 14mm}"
    "body{font-family:'DejaVu Sans','Liberation Sans',sans-serif;font-size:8.5pt;color:#1f2933}"
    "h1{font-size:14pt;margin:0 0 2pt}.sub{color:#52606d;margin:0 0 10pt}"
    ".parties{width:100%;border-collapse:collapse;margin-bottom:10pt}"
    ".parties td{vertical-align:top;width:50%;padding:0 8pt 0 0}"
    ".label{color:#52606d;font-size:7.5pt;text-transform:uppercase;letter-spacing:.04em}"
    ".lines{width:100%;border-collapse:collapse}"
    ".lines th{text-align:left;border-bottom:1px solid #9aa5b1;padding:3pt;font-size:7.5pt;color:#52606d}"
    ".lines td{border-bottom:1px solid #e4e7eb;padding:3pt;vertical-align:top}"
    ".num{text-align:right;white-space:nowrap}"
    ".total{margin-top:8pt;text-align:right;font-size:10pt;font-weight:700}"
    ".foot{margin-top:14pt;font-size:7.5pt;color:#7b8794}"
)


def _amount(value: Optional[Decimal]) -> str:
    if value is None:
        return ""
    text = f"{value:,.2f}".replace(",", " ").replace(".", ",")
    return text


def _qty(value: Optional[Decimal]) -> str:
    if value is None:
        return ""
    return format(value.normalize(), "f").replace(".", ",")


def _party(party: FaParty) -> str:
    lines = [escape(party.name or "")]
    for line in (party.line1, party.line2):
        if line:
            lines.append(escape(line))
    if party.vat_id:
        lines.append(f"VAT: {escape(party.vat_id)}")
    return "<br>".join(lines)


def render(doc: FaDocument, *, ksef_number: Optional[str]) -> bytes:
    title = "Faktura korygująca / Credit note" if doc.kind == "correction" else "Faktura / Invoice"
    rows = []
    for index, line in enumerate(doc.lines, start=1):
        state = " (przed korektą / before)" if line.before else ""
        rows.append(
            "<tr>"
            f"<td>{index}</td><td>{escape(line.name)}{state}</td>"
            f"<td class='num'>{_qty(line.quantity)} {escape(line.unit or '')}</td>"
            f"<td class='num'>{_amount(line.unit_price)}</td>"
            f"<td class='num'>{_amount(line.discount)}</td>"
            f"<td class='num'>{_amount(line.net)}</td>"
            f"<td class='num'>{escape(line.vat_rate or '')}</td>"
            "</tr>"
        )
    corrected = ""
    if doc.corrected:
        refs = ", ".join(escape(c.invoice_number or "") for c in doc.corrected)
        corrected = f"<p>Korygowana faktura / Corrected invoice: {refs}</p>"
    notes = "".join(f"<p>{escape(note)}</p>" for note in doc.notes)
    reverse = "<p>Odwrotne obciążenie / Reverse charge</p>" if doc.reverse_charge else ""
    accounts = "".join(
        f"<p>Rachunek / Account: {escape(a.number)}{(' (SWIFT ' + escape(a.swift) + ')') if a.swift else ''}</p>"
        for a in doc.accounts
    )
    dates = [f"Data wystawienia / Issue date: {doc.issue_date.isoformat()}"]
    if doc.sale_date:
        dates.append(f"Data sprzedaży / Transaction date: {doc.sale_date.isoformat()}")
    if doc.due_date:
        dates.append(f"Termin zapłaty / Due date: {doc.due_date.isoformat()}")
    html = (
        f"<html><head><meta charset='utf-8'><style>{_CSS}</style></head><body>"
        f"<h1>{title} {escape(doc.number)}</h1>"
        f"<p class='sub'>{' · '.join(dates)}</p>"
        "<table class='parties'><tr>"
        f"<td><div class='label'>Sprzedawca / Vendor</div>{_party(doc.seller)}</td>"
        f"<td><div class='label'>Nabywca / Customer</div>{_party(doc.buyer)}</td>"
        "</tr></table>"
        f"{corrected}"
        "<table class='lines'><thead><tr><th>Lp.</th><th>Nazwa / Name</th>"
        "<th class='num'>Ilość / Qty</th><th class='num'>Cena netto / Net price</th>"
        "<th class='num'>Rabat / Discount</th><th class='num'>Netto / Net</th><th class='num'>VAT</th>"
        f"</tr></thead><tbody>{''.join(rows)}</tbody></table>"
        f"<p class='total'>Razem / Total: {_amount(doc.gross_total)} {escape(doc.currency)}</p>"
        f"{reverse}{notes}{accounts}"
        f"<p class='foot'>Wizualizacja faktury z KSeF{(' nr ' + escape(ksef_number)) if ksef_number else ''}. "
        "Dokumentem jest faktura w KSeF. / Visualisation of the invoice from the Polish KSeF.</p>"
        "</body></html>"
    )
    from weasyprint import HTML

    return HTML(string=html).write_pdf()


def filename(number: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-." else "_" for ch in number)
    return f"{safe[:80] or 'faktura'}.pdf"
