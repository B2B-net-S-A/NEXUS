"""PDF faktury wystawionej w NEXUSIE — wizualizacja z numerem KSeF i kodem QR (E4).

Faktura przyjęta w KSeF dostaje kod QR weryfikacji (KOD I) — MF wymaga go na
wizualizacji faktury z KSeF przekazywanej nabywcy poza KSeF. Adres:
``https://qr.ksef.mf.gov.pl/invoice/{NIP sprzedawcy}/{DD-MM-RRRR daty
wystawienia}/{SHA-256 pliku faktury, Base64URL bez „=”}`` (środowisko testowe:
``qr-test``); pod kodem numer KSeF. Szkic i faktura bez przyjęcia mają znak
„SZKIC — dokument nie jest fakturą” i nie mają kodu.

Kwoty i pozycje z zapisanej faktury (te same, z których powstał XML).
WeasyPrint i fonty DejaVu jak pozostałe PDF-y; renderowanie synchroniczne —
z kodu async przez ``asyncio.to_thread``.
"""

from __future__ import annotations

import base64
import hashlib
from datetime import date
from decimal import Decimal
from html import escape
from typing import Any, Optional

from app.models.client_issued_invoice import ClientIssuedInvoice
from app.services.client_invoicing import fa3_build, issue_settings
from app.services.hr.payroll_rates import format_pln

QR_BASES = {
    "prod": "https://qr.ksef.mf.gov.pl/invoice",
    "test": "https://qr-test.ksef.mf.gov.pl/invoice",
}
#: Arkusz stylów PDF-u faktury — wspólny z wizualizacją faktury z KSeF
#: (``hr/ksef/fa_visual.py``), żeby obie wyglądały tak samo.
STYLE = (
    "@page{size:A4;margin:14mm 14mm 18mm}"
    "body{font-family:'DejaVu Sans','Liberation Sans',sans-serif;font-size:9pt;color:#1f2933}"
    ".head{display:flex;justify-content:space-between;align-items:flex-start}"
    "h1{font-size:16pt;margin:0}.number{font-size:11pt;margin:2pt 0 6pt}"
    ".meta{margin:1pt 0;color:#52606d}"
    ".ksef{text-align:center;font-size:7pt}.ksef img{width:34mm;height:34mm}"
    ".parties{display:flex;gap:12mm;margin:10pt 0}.party{flex:1}"
    ".party h3,h3{font-size:9pt;color:#52606d;margin:6pt 0 2pt}.party p{margin:0}"
    "table{border-collapse:collapse;width:100%;margin-top:4pt}"
    "th{text-align:left;border-bottom:1px solid #9aa5b1;padding:3pt;font-size:7.5pt;color:#52606d}"
    "td{border-bottom:0.5px solid #d9e2ec;padding:3pt;vertical-align:top}"
    ".num{text-align:right;white-space:nowrap}"
    ".sum{width:60%;margin-left:40%}.total td{font-weight:700;border-bottom:none}"
    ".gross{text-align:right;font-size:11pt;font-weight:700;margin:6pt 0}"
    ".note{font-size:8pt;color:#52606d;margin:3pt 0}"
    ".draft{color:#b42318;font-weight:700;font-size:11pt;border:1px solid #b42318;"
    "padding:3pt;text-align:center}"
)
TITLES = {
    "VAT": "Faktura VAT",
    "KOR": "Faktura korygująca",
    "ZAL": "Faktura zaliczkowa",
}


def qr_url(
    environment: Optional[str], seller_nip: str, issue_day: Any, xml: bytes
) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(xml).digest()).decode("ascii")
    base = QR_BASES.get(environment or "prod", QR_BASES["prod"])
    return f"{base}/{seller_nip}/{issue_day.strftime('%d-%m-%Y')}/{digest.rstrip('=')}"


def qr_svg(url: str) -> str:
    import segno  # leniwy import: tylko przy generowaniu PDF-u

    return segno.make(url, error="m").svg_data_uri(scale=3, border=1)


def _money(value: Optional[Any], currency: str) -> str:
    if value in (None, ""):
        return "—"
    amount = Decimal(str(value))
    return f"{format_pln(amount)} {'zł' if currency == 'PLN' else currency}"


def _qty(value: Optional[str]) -> str:
    return (value or "—").replace(".", ",")


def _rate_label(code: Optional[str]) -> str:
    rate = fa3_build.VAT_RATES.get(code or "")
    return rate.label if rate else (code or "—")


def _price_cell(line: dict[str, Any], currency: str) -> str:
    """Cena netto; z rabatem %: cena przed, rabat i cena po rabacie (jak w eBI24)."""

    price = escape(_money(line.get("unit_price"), currency))
    discount = fa3_build.line_discount_pct(line)
    if discount is None:
        return price
    after = fa3_build.discounted_price(line)
    rate = fa3_build.plain(discount).replace(".", ",")
    return (
        f"{price}<br><span class='note'>rabat {escape(rate)}% → "
        f"{escape(_money(str(after), currency))}</span>"
    )


def _rows(lines: list[dict[str, Any]], currency: str, start: int) -> str:
    out = []
    for index, line in enumerate(lines, start=start):
        out.append(
            "<tr>"
            f"<td>{index}</td><td>{escape(line.get('name') or '')}</td>"
            f"<td class='num'>{escape(_qty(line.get('quantity')))} {escape(line.get('unit') or '')}</td>"
            f"<td class='num'>{_price_cell(line, currency)}</td>"
            f"<td class='num'>{escape(_rate_label(line.get('vat_rate')))}</td>"
            f"<td class='num'>{escape(_money(line.get('net'), currency))}</td>"
            "</tr>"
        )
    return "".join(out)


def _party(title: str, party: dict[str, Any], ident: str) -> str:
    lines = [
        party.get("name") or "",
        party.get("address_l1") or "",
        party.get("address_l2") or "",
    ]
    body = "<br>".join(escape(line) for line in lines if line)
    return f"<div class='party'><h3>{title}</h3><p>{body}<br>{escape(ident)}</p></div>"


def _buyer_ident(number: Optional[str]) -> str:
    ident = fa3_build.buyer_id(number)
    if ident.kind == "nip":
        return f"NIP {ident.nip}"
    if ident.kind == "eu":
        return f"VAT UE {ident.country}{ident.number}"
    if ident.kind == "other":
        return f"Nr identyfikacyjny {ident.country or ''}{ident.number}"
    return ""


def render_html(
    invoice: ClientIssuedInvoice,
    settings: dict[str, Any],
    *,
    corrected_number: Optional[str] = None,
) -> str:
    seller = settings["seller"]
    currency = invoice.currency
    accepted = invoice.status == "accepted" and invoice.ksef_number and invoice.xml
    title = TITLES.get(invoice.invoice_type, "Faktura")
    number = invoice.invoice_number or "(numer nadany przy wysyłce do KSeF)"
    result = fa3_build.totals(
        [line for line in invoice.lines or [] if fa3_build.line_net(line) is not None],
        [
            line
            for line in invoice.lines_before or []
            if fa3_build.line_net(line) is not None
        ],
    )

    dates = [f"Data wystawienia: {invoice.issue_date.strftime('%d.%m.%Y')}"]
    if seller.get("issue_place"):
        dates[0] += f", {escape(seller['issue_place'])}"
    if invoice.period_from and invoice.period_to and invoice.invoice_type != "ZAL":
        dates.append(
            f"Okres usługi: {invoice.period_from.strftime('%d.%m.%Y')} – "
            f"{invoice.period_to.strftime('%d.%m.%Y')}"
        )
    elif invoice.sale_date:
        label = (
            "Data otrzymania zaliczki"
            if invoice.invoice_type == "ZAL"
            else "Data dostawy"
        )
        dates.append(f"{label}: {invoice.sale_date.strftime('%d.%m.%Y')}")
    if invoice.due_date:
        dates.append(
            f"Termin płatności: {invoice.due_date.strftime('%d.%m.%Y')} (przelew)"
        )

    tables = []
    if invoice.lines_before:
        tables.append(
            "<h3>Stan przed korektą</h3>" + _table(invoice.lines_before, currency, 1)
        )
        tables.append(
            "<h3>Stan po korekcie</h3>"
            + _table(invoice.lines or [], currency, len(invoice.lines_before) + 1)
        )
    else:
        tables.append(_table(invoice.lines or [], currency, 1))

    summary = "".join(
        f"<tr><td>{escape(item.rate.label)}</td>"
        f"<td class='num'>{escape(_money(item.net, currency))}</td>"
        f"<td class='num'>{escape(_money(item.vat, currency))}</td></tr>"
        for item in result.rates
    )
    totals = (
        "<table class='sum'><thead><tr><th>Stawka</th><th class='num'>Netto</th>"
        f"<th class='num'>VAT</th></tr></thead><tbody>{summary}"
        f"<tr class='total'><td>Razem{' (różnica)' if invoice.lines_before else ''}</td>"
        f"<td class='num'>{escape(_money(result.net, currency))}</td>"
        f"<td class='num'>{escape(_money(result.vat, currency))}</td></tr></tbody></table>"
        f"<p class='gross'>Do zapłaty: {escape(_money(result.gross, currency))}</p>"
    )

    notes: list[str] = []
    appendix: list[str] = []
    codes = {line.get("vat_rate") for line in invoice.lines or []}
    if codes & fa3_build.REVERSE_CHARGE_RATES:
        notes.append("Odwrotne obciążenie.")
    if "zw" in codes and settings.get("exemption_basis"):
        notes.append(f"Zwolnienie z VAT: {escape(settings['exemption_basis'])}.")
    if currency != "PLN" and invoice.fx_rate is not None:
        vat_pln = result.vat * invoice.fx_rate
        notes.append(
            f"Kurs średni NBP {currency} z {invoice.fx_date.strftime('%d.%m.%Y') if invoice.fx_date else '—'}: "
            f"{escape(fa3_build.plain(invoice.fx_rate))} zł; VAT w złotych: {escape(_money(fa3_build.money(vat_pln), 'PLN'))}."
        )
    collective = (
        invoice.collective_correction if invoice.invoice_type == "KOR" else None
    )
    if collective:
        corrected = list(collective.get("invoices") or [])
        notes.append(
            "Korekta zbiorcza (art. 106j ust. 3 ustawy o VAT) — opust dotyczy "
            f"{len(corrected)} faktur za okres {escape(str(collective.get('period') or ''))}, "
            "wymienionych niżej. "
            f"Przyczyna: {escape(invoice.correction_reason or '')}."
        )
        appendix.append(_corrected_table(corrected))
    elif invoice.invoice_type == "KOR":
        notes.append(
            f"Korekta faktury {escape(corrected_number or '')}. "
            f"Przyczyna: {escape(invoice.correction_reason or '')}."
        )
    if invoice.client_order_number:
        notes.append(f"Zamówienie klienta: {escape(invoice.client_order_number)}.")
    if invoice.notes:
        notes.append(escape(invoice.notes))
    account = (
        issue_settings.account_for(
            settings, invoice.client_id, currency, invoice.series_code
        )
        or {}
    )
    if invoice.series_code in issue_settings.COMPENSATION_SERIES:
        notes.append(f"Forma płatności: {issue_settings.COMPENSATION_LABEL.lower()}.")
    if account.get("number"):
        bank = f" ({escape(account['bank'])})" if account.get("bank") else ""
        swift = f", SWIFT {escape(account['swift'])}" if account.get("swift") else ""
        notes.append(f"Rachunek: {escape(account['number'])}{bank}{swift}.")

    ksef = ""
    if accepted:
        url = qr_url(
            invoice.ksef_environment,
            seller["nip"],
            invoice.issue_date,
            invoice.xml.encode("utf-8"),
        )
        ksef = (
            "<div class='ksef'>"
            f"<img src='{qr_svg(url)}' alt='Kod QR weryfikacji faktury w KSeF'>"
            f"<p>{escape(invoice.ksef_number)}</p></div>"
        )
    watermark = (
        "" if accepted else "<p class='draft'>SZKIC — dokument nie jest fakturą</p>"
    )
    body = (
        f"{watermark}<div class='head'><div><h1>{escape(title)}</h1>"
        f"<p class='number'>nr {escape(number)}</p>"
        + "".join(f"<p class='meta'>{line}</p>" for line in dates)
        + f"</div>{ksef}</div>"
        "<div class='parties'>"
        + _party("Sprzedawca", seller, f"NIP {seller.get('nip') or ''}")
        + _party(
            "Nabywca",
            invoice.buyer or {},
            _buyer_ident((invoice.buyer or {}).get("number")),
        )
        + "</div>"
        + "".join(tables)
        + totals
        + "".join(f"<p class='note'>{note}</p>" for note in notes)
        + "".join(appendix)
    )
    return (
        "<!DOCTYPE html><html lang='pl'><head><meta charset='utf-8'>"
        f"<title>{escape(title)} {escape(number)}</title><style>{STYLE}"
        "</style></head><body>" + body + "</body></html>"
    )


def _table(lines: list[dict[str, Any]], currency: str, start: int) -> str:
    return (
        "<table><thead><tr><th>Lp.</th><th>Nazwa usługi</th><th class='num'>Ilość</th>"
        "<th class='num'>Cena netto</th><th class='num'>VAT</th>"
        "<th class='num'>Wartość netto</th></tr></thead><tbody>"
        + _rows(lines, currency, start)
        + "</tbody></table>"
    )


def _corrected_table(items: list[dict[str, Any]]) -> str:
    rows = "".join(
        f"<tr><td>{index}</td><td>{escape(str(item.get('number') or ''))}</td>"
        f"<td>{escape(_day(item.get('issue_date')))}</td>"
        f"<td>{escape(str(item.get('ksef_number') or '—'))}</td></tr>"
        for index, item in enumerate(items, start=1)
    )
    return (
        "<h3>Faktury korygowane</h3><table><thead><tr><th>Lp.</th>"
        "<th>Numer faktury</th><th>Data wystawienia</th><th>Numer KSeF</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>"
    )


def _day(raw: Any) -> str:
    try:
        return date.fromisoformat(str(raw)[:10]).strftime("%d.%m.%Y")
    except ValueError:
        return str(raw or "")


def render_pdf(html: str) -> bytes:
    from weasyprint import HTML

    return HTML(string=html).write_pdf()


def filename(invoice: ClientIssuedInvoice) -> str:
    stem = (invoice.invoice_number or f"szkic-{invoice.id}").replace("/", "-")
    return f"faktura-{stem}.pdf"


__all__ = ["STYLE", "filename", "qr_svg", "qr_url", "render_html", "render_pdf"]
