"""Wizualizacja faktury FA(2)/FA(3) z KSeF do PDF (podgląd faktury kosztowej).

Finanse dostają z KSeF tylko XML, a ten jest nieczytelny — karta faktury
kosztowej pokazuje go jako PDF w tym samym układzie co faktury wystawiane
w NEXUSIE (``client_invoicing/invoice_pdf.py``: arkusz ``STYLE``, kod QR
KOD I, WeasyPrint). Sam ``invoice_pdf.render_html`` się nie nadaje — pracuje
na zapisanej fakturze NEXUSA (``ClientIssuedInvoice``, nasze stawki i rachunki),
nie na cudzym XML-u; szablon zewnętrzny byłby nową zależnością w backendzie.
Wizualizacja e-faktury (``peppol/pdf.py`` + ``fa_reader``) też nie: to
dwujęzyczny załącznik wysyłany klientom (zmiana byłaby widoczna na
zewnątrz), ``fa_reader`` odrzuca pozycje liczone od brutto i waluty spoza
PLN/EUR/USD (``fa.parse_invoice``), a nie pokazuje stawek, MPP, kodu QR ani
podmiotów trzecich, których potrzebuje księgowa.

Co pokazujemy (wszystko z pliku, nic nie liczymy od nowa): rodzaj i numer,
daty (wystawienia z miejscem, sprzedaży albo okres), sprzedawcę, nabywcę
i podmioty trzecie z adresami, pozycje (w korekcie osobno „przed” i „po”),
podsumowanie stawek z pól ``P_13_*``/``P_14_*`` (w walucie obcej też VAT w
złotych ``P_14_*W`` i kurs), ``P_15`` do zapłaty, adnotacje (MPP, odwrotne
obciążenie, metoda kasowa, samofakturowanie, zwolnienie z podstawą), dane
korygowanej faktury i przyczynę korekty, płatność (termin, forma, rachunki,
rachunek faktora, zapłacono), zamówienia i umowy, dodatkowy opis i stopkę.
Faktura z ``Zalacznik`` dostaje dopisek, że załącznik jest w pliku XML.

Plik z zewnątrz czyta ``fa.load_root`` (limit, bez DTD i sieci). Każdy tekst
idzie przez ``html.escape``. Renderowanie synchroniczne — z kodu async przez
``asyncio.to_thread``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from html import escape
from typing import Any, Optional

from app.services.client_invoicing import invoice_pdf
from app.services.hr.ksef import fa
from app.services.hr.payroll_rates import format_pln

TITLES = {
    "VAT": "Faktura VAT",
    "KOR": "Faktura korygująca",
    "ZAL": "Faktura zaliczkowa",
    "ROZ": "Faktura rozliczeniowa",
    "UPR": "Faktura uproszczona",
    "KOR_ZAL": "Korekta faktury zaliczkowej",
    "KOR_ROZ": "Korekta faktury rozliczeniowej",
}
#: Pola sum ``Fa``: (netto, VAT, VAT w złotych, etykieta) w kolejności schematu.
RATE_FIELDS = (
    ("P_13_1", "P_14_1", "P_14_1W", "23% (22%)"),
    ("P_13_2", "P_14_2", "P_14_2W", "8% (7%)"),
    ("P_13_3", "P_14_3", "P_14_3W", "5%"),
    ("P_13_4", "P_14_4", "P_14_4W", "ryczałt taksówek"),
    ("P_13_5", "P_14_5", None, "procedura OSS"),
    ("P_13_6_1", None, None, "0% (kraj)"),
    ("P_13_6_2", None, None, "0% WDT"),
    ("P_13_6_3", None, None, "0% eksport"),
    ("P_13_7", None, None, "zwolnione"),
    ("P_13_8", None, None, "np. (poza krajem)"),
    ("P_13_9", None, None, "np. (usługi art. 100 ust. 1 pkt 4)"),
    ("P_13_10", None, None, "odwrotne obciążenie"),
    ("P_13_11", None, None, "marża"),
)
RATE_LABELS = {
    "23": "23%",
    "22": "22%",
    "8": "8%",
    "7": "7%",
    "5": "5%",
    "4": "4%",
    "3": "3%",
    "0": "0%",
    "0 KR": "0% (kraj)",
    "0 WDT": "0% WDT",
    "0 EX": "0% eksport",
    "zw": "zw.",
    "oo": "o.o.",
    "np": "np.",
    "np I": "np. (poza krajem)",
    "np II": "np. (usługi w UE)",
}
PAYMENT_FORMS = {
    "1": "gotówka",
    "2": "karta",
    "3": "bon",
    "4": "czek",
    "5": "kredyt",
    "6": "przelew",
    "7": "płatność mobilna",
}
THIRD_PARTY_ROLES = {
    "1": "Faktor",
    "2": "Odbiorca",
    "3": "Podmiot pierwotny",
    "4": "Dodatkowy nabywca",
    "5": "Wystawca faktury",
    "6": "Dokonujący płatności",
    "7": "Jednostka samorządu terytorialnego — wystawca",
    "8": "Jednostka samorządu terytorialnego — odbiorca",
    "9": "Członek grupy VAT — wystawca",
    "10": "Członek grupy VAT — odbiorca",
    "11": "Pracownik",
}
MAX_EXTRA = 50
NOTICE = (
    "Wizualizacja faktury z KSeF przygotowana w NEXUSIE z pliku XML. "
    "Fakturą jest plik XML zapisany w KSeF."
)


@dataclass(frozen=True)
class Visual:
    html: str
    title: str
    invoice_number: str
    seller_nip: str


def _text(node: Any, *path: str, limit: int = 512) -> Optional[str]:
    return fa._text(node, *path, limit=limit)


def _amount(raw: Optional[str]) -> Optional[Decimal]:
    if raw is None:
        return None
    try:
        value = Decimal(raw.replace(",", "."))
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


def _money(raw: Optional[str], currency: str) -> str:
    value = _amount(raw)
    if value is None:
        return "—"
    label = "zł" if currency == "PLN" else currency
    return f"{format_pln(value.quantize(Decimal('0.01')))} {label}"


def _number(raw: Optional[str]) -> str:
    value = _amount(raw)
    if value is None:
        return raw or ""
    return format(value.normalize(), "f").replace(".", ",")


def _day(raw: Optional[str]) -> Optional[str]:
    day = fa._date(raw)
    return day.strftime("%d.%m.%Y") if day else None


def _address(node: Any) -> list[str]:
    if node is None:
        return []
    lines = [_text(node, "AdresL1"), _text(node, "AdresL2")]
    country = _text(node, "KodKraju", limit=2)
    if country and country != "PL":
        lines.append(country)
    return [line for line in lines if line]


def _ident(ident: Any) -> str:
    if ident is None:
        return ""
    nip = _text(ident, "NIP", limit=16)
    if nip:
        return f"NIP {nip}"
    vat_eu = _text(ident, "NrVatUE", limit=32)
    if vat_eu:
        return f"VAT UE {_text(ident, 'KodUE', limit=2) or ''}{vat_eu}"
    other = _text(ident, "NrID", limit=64)
    if other:
        return f"Nr identyfikacyjny {_text(ident, 'KodKraju', limit=2) or ''}{other}"
    if _text(ident, "BrakID") == "1":
        return "Bez identyfikatora podatkowego"
    return ""


def _party(title: str, node: Any) -> str:
    if node is None:
        return ""
    ident = fa._child(node, "DaneIdentyfikacyjne")
    lines = [_text(ident, "Nazwa") or ""] if ident is not None else []
    lines += _address(fa._child(node, "Adres"))
    ident_line = _ident(ident)
    if ident_line:
        lines.append(ident_line)
    for contact in node.iterfind("{*}DaneKontaktowe"):
        for key in ("Email", "Telefon"):
            value = _text(contact, key, limit=255)
            if value:
                lines.append(value)
    customer = _text(node, "NrKlienta", limit=256)
    if customer:
        lines.append(f"Nr klienta: {customer}")
    body = "<br>".join(escape(line) for line in lines if line)
    return f"<div class='party'><h3>{escape(title)}</h3><p>{body}</p></div>"


def _third_parties(root: Any) -> str:
    out = []
    for node in list(root.iterfind("{*}Podmiot3"))[:MAX_EXTRA]:
        role = _text(node, "Rola", limit=4)
        title = (
            THIRD_PARTY_ROLES.get(role or "")
            or _text(node, "OpisRoli")
            or "Podmiot trzeci"
        )
        out.append(_party(title, node))
    if not out:
        return ""
    return "<div class='parties'>" + "".join(out) + "</div>"


def _rate_label(code: Optional[str]) -> str:
    return RATE_LABELS.get(code or "", code or "—")


def _rows(rows: list[Any], currency: str) -> str:
    gross_based = any(_text(row, "P_11A") for row in rows) and not any(
        _text(row, "P_11") for row in rows
    )
    head = (
        "<table><thead><tr><th>Lp.</th><th>Nazwa</th><th class='num'>Ilość</th>"
        f"<th class='num'>Cena {'brutto' if gross_based else 'netto'}</th>"
        "<th class='num'>Rabat</th><th class='num'>VAT</th>"
        f"<th class='num'>Wartość {'brutto' if gross_based else 'netto'}</th></tr></thead><tbody>"
    )
    body = []
    for index, row in enumerate(rows, start=1):
        price = _text(row, "P_9B" if gross_based else "P_9A")
        value = _text(row, "P_11A" if gross_based else "P_11")
        discount = _text(row, "P_10")
        name = escape(_text(row, "P_7") or "")
        extra = [
            f"{label} {escape(code)}"
            for label, code in (
                ("Indeks", _text(row, "Indeks", limit=64)),
                ("PKWiU", _text(row, "PKWiU", limit=64)),
                ("GTU", _text(row, "GTU", limit=16)),
                ("Data", _day(_text(row, "P_6A"))),
            )
            if code
        ]
        if extra:
            name += "<br><span class='note'>" + ", ".join(extra) + "</span>"
        body.append(
            "<tr>"
            f"<td>{escape(_text(row, 'NrWierszaFa', limit=8) or str(index))}</td>"
            f"<td>{name}</td>"
            f"<td class='num'>{escape(_number(_text(row, 'P_8B')))} "
            f"{escape(_text(row, 'P_8A', limit=32) or '')}</td>"
            f"<td class='num'>{escape(_money(price, currency)) if price else '—'}</td>"
            f"<td class='num'>{escape(_money(discount, currency)) if discount else ''}</td>"
            f"<td class='num'>{escape(_rate_label(_text(row, 'P_12', limit=8)))}</td>"
            f"<td class='num'>{escape(_money(value, currency)) if value else '—'}</td>"
            "</tr>"
        )
    return head + "".join(body) + "</tbody></table>"


def _items(invoice: Any, currency: str, correction: bool) -> str:
    rows = list(invoice.iterfind("{*}FaWiersz"))[: fa.MAX_ITEMS]
    if not rows:
        return ""
    before = [row for row in rows if _text(row, "StanPrzed") == "1"]
    after = [row for row in rows if _text(row, "StanPrzed") != "1"]
    if correction and before:
        return (
            "<h3>Stan przed korektą</h3>"
            + _rows(before, currency)
            + "<h3>Stan po korekcie</h3>"
            + _rows(after, currency)
        )
    return _rows(rows, currency)


def _summary(invoice: Any, currency: str, correction: bool) -> str:
    foreign = currency != "PLN"
    rows = []
    for net_field, vat_field, vat_pln_field, label in RATE_FIELDS:
        net = _text(invoice, net_field)
        vat = _text(invoice, vat_field) if vat_field else None
        if net is None and vat is None:
            continue
        vat_pln = _text(invoice, vat_pln_field) if vat_pln_field and foreign else None
        rows.append(
            f"<tr><td>{escape(label)}</td>"
            f"<td class='num'>{escape(_money(net, currency))}</td>"
            f"<td class='num'>{escape(_money(vat, currency)) if vat_field else '—'}</td>"
            + (
                f"<td class='num'>{escape(_money(vat_pln, 'PLN')) if vat_pln else '—'}</td>"
                if foreign
                else ""
            )
            + "</tr>"
        )
    pln_head = "<th class='num'>VAT w zł</th>" if foreign else ""
    table = (
        "<table class='sum'><thead><tr><th>Stawka</th><th class='num'>Netto</th>"
        f"<th class='num'>VAT</th>{pln_head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"
        if rows
        else ""
    )
    label = "Różnica do zapłaty" if correction else "Do zapłaty"
    return (
        table
        + f"<p class='gross'>{label}: {escape(_money(_text(invoice, 'P_15'), currency))}</p>"
    )


def _annotations(invoice: Any) -> list[str]:
    notes = fa._child(invoice, "Adnotacje")
    if notes is None:
        return []
    out = []
    for field, label in (
        ("P_16", "Metoda kasowa."),
        ("P_17", "Samofakturowanie."),
        ("P_18", "Odwrotne obciążenie."),
        ("P_18A", "Mechanizm podzielonej płatności."),
    ):
        if _text(notes, field) == "1":
            out.append(label)
    exemption = fa._child(notes, "Zwolnienie")
    if exemption is not None and _text(exemption, "P_19") == "1":
        basis = next(
            (
                _text(exemption, key)
                for key in ("P_19A", "P_19B", "P_19C")
                if _text(exemption, key)
            ),
            None,
        )
        out.append(f"Zwolnienie z VAT{': ' + basis if basis else ''}.")
    margin = fa._child(notes, "PMarzy")
    if margin is not None and _text(margin, "P_PMarzy") == "1":
        out.append("Procedura marży.")
    return out


def _correction(invoice: Any) -> list[str]:
    out = []
    for node in list(invoice.iterfind("{*}DaneFaKorygowanej"))[:MAX_EXTRA]:
        parts = [_text(node, "NrFaKorygowanej", limit=256) or "—"]
        day = _day(_text(node, "DataWystFaKorygowanej"))
        if day:
            parts.append(f"z {day}")
        ksef = _text(node, "NrKSeFFaKorygowanej", limit=64)
        if ksef:
            parts.append(f"nr KSeF {ksef}")
        out.append("Korygowana faktura: " + " ".join(parts) + ".")
    reason = _text(invoice, "PrzyczynaKorekty")
    if reason:
        out.append(f"Przyczyna korekty: {reason}.")
    period = fa._child(invoice, "OkresFaKorygowanej")
    if period is not None and period.text:
        out.append(f"Okres korekty: {' '.join(period.text.split())[:256]}.")
    return out


def _payment(invoice: Any, currency: str) -> list[str]:
    payment = fa._child(invoice, "Platnosc")
    if payment is None:
        return []
    out = []
    if _text(payment, "Zaplacono") == "1":
        day = _day(_text(payment, "DataZaplaty"))
        out.append(f"Zapłacono{' ' + day if day else ''}.")
    for part in list(payment.iterfind("{*}ZaplataCzesciowa"))[:MAX_EXTRA]:
        out.append(
            f"Zapłata częściowa {_money(_text(part, 'KwotaZaplatyCzesciowej'), currency)}"
            f" {_day(_text(part, 'DataZaplatyCzesciowej')) or ''}.".replace(" .", ".")
        )
    for term in list(payment.iterfind("{*}TerminPlatnosci"))[:MAX_EXTRA]:
        day = _day(_text(term, "Termin"))
        described = fa._child(term, "TerminOpis")
        if day:
            out.append(f"Termin płatności: {day}.")
        elif described is not None and described.text:
            out.append(f"Termin płatności: {' '.join(described.text.split())[:128]}.")
    form = PAYMENT_FORMS.get(_text(payment, "FormaPlatnosci", limit=2) or "")
    if form is None and _text(payment, "PlatnoscInna") == "1":
        form = _text(payment, "OpisPlatnosci", limit=256)
    if form:
        out.append(f"Forma płatności: {form}.")
    for node_name, label in (
        ("RachunekBankowy", "Rachunek"),
        ("RachunekBankowyFaktora", "Rachunek faktora"),
    ):
        for account in list(payment.iterfind(f"{{*}}{node_name}"))[:MAX_EXTRA]:
            number = _text(account, "NrRB", limit=64)
            if not number:
                continue
            extra = [
                value
                for value in (
                    _text(account, "NazwaBanku", limit=256),
                    f"SWIFT {_text(account, 'SWIFT', limit=16)}"
                    if _text(account, "SWIFT", limit=16)
                    else None,
                )
                if value
            ]
            out.append(
                f"{label}: {number}{' (' + ', '.join(extra) + ')' if extra else ''}."
            )
    discount = fa._child(payment, "Skonto")
    if discount is not None:
        terms = _text(discount, "WarunkiSkonta")
        amount = _text(discount, "WysokoscSkonta", limit=64)
        out.append(f"Skonto: {', '.join(v for v in (terms, amount) if v)}.")
    return out


def _transaction(invoice: Any) -> list[str]:
    terms = fa._child(invoice, "WarunkiTransakcji")
    if terms is None:
        return []
    out = []
    for node_name, number_field, date_field, label in (
        ("Umowy", "NrUmowy", "DataUmowy", "Umowa"),
        ("Zamowienia", "NrZamowienia", "DataZamowienia", "Zamówienie"),
    ):
        for node in list(terms.iterfind(f"{{*}}{node_name}"))[:MAX_EXTRA]:
            number = _text(node, number_field, limit=256)
            day = _day(_text(node, date_field))
            if number or day:
                out.append(
                    f"{label}: {' '.join(v for v in (number, 'z ' + day if day else None) if v)}."
                )
    return out


def _extra(invoice: Any) -> list[str]:
    out = []
    for node in list(invoice.iterfind("{*}DodatkowyOpis"))[:MAX_EXTRA]:
        key = _text(node, "Klucz", limit=256)
        value = _text(node, "Wartosc")
        if key or value:
            out.append(f"{key}: {value}" if key and value else (key or value or ""))
    return out


def _footer(root: Any) -> list[str]:
    footer = fa._child(root, "Stopka")
    if footer is None:
        return []
    out = []
    for info in list(footer.iterfind("{*}Informacje"))[:MAX_EXTRA]:
        text = _text(info, "StopkaFaktury", limit=3500)
        if text:
            out.append(text)
    for register in list(footer.iterfind("{*}Rejestry"))[:MAX_EXTRA]:
        parts = [
            f"{label} {value}"
            for label, value in (
                ("", _text(register, "PelnaNazwa")),
                ("KRS", _text(register, "KRS", limit=16)),
                ("REGON", _text(register, "REGON", limit=16)),
                ("BDO", _text(register, "BDO", limit=16)),
            )
            if value
        ]
        if parts:
            out.append(", ".join(part.strip() for part in parts))
    return out


def _dates(invoice: Any) -> list[str]:
    out = []
    issued = _day(_text(invoice, "P_1"))
    place = _text(invoice, "P_1M", limit=256)
    if issued:
        out.append(f"Data wystawienia: {issued}{', ' + place if place else ''}")
    period = fa._child(invoice, "OkresFa")
    if period is not None:
        start, end = _day(_text(period, "P_6_Od")), _day(_text(period, "P_6_Do"))
        if start or end:
            out.append(f"Okres: {start or '—'} – {end or '—'}")
    sale = _day(_text(invoice, "P_6"))
    if sale:
        out.append(f"Data dostawy lub wykonania usługi: {sale}")
    return out


def render_html(
    xml: bytes, *, ksef_number: Optional[str], environment: Optional[str]
) -> Visual:
    """HTML wizualizacji z pliku faktury; zły plik = ``fa.InvoiceParseError``."""

    root = fa.load_root(xml)
    invoice = fa._child(root, "Fa")
    if invoice is None:
        raise fa.InvoiceParseError("not_invoice")
    seller = fa._child(root, "Podmiot1")
    seller_nip = (
        _text(seller, "DaneIdentyfikacyjne", "NIP", limit=16)
        if seller is not None
        else None
    )
    number = _text(invoice, "P_2", limit=256)
    if not seller_nip:
        raise fa.InvoiceParseError("missing_seller")
    if not number:
        raise fa.InvoiceParseError("missing_number")
    kind = (_text(invoice, "RodzajFaktury", limit=16) or "VAT").upper()
    correction = kind in fa.CORRECTION_TYPES
    currency = (_text(invoice, "KodWaluty", limit=3) or "PLN").upper()
    title = TITLES.get(kind, "Faktura")

    notes = _annotations(invoice) + _correction(invoice)
    rate = _text(invoice, "KursWalutyZ", limit=32)
    if currency != "PLN":
        notes.append(f"Waluta faktury: {currency}.")
        if rate:
            notes.append(f"Kurs waluty do VAT: {_number(rate)} zł.")
    notes += _payment(invoice, currency) + _transaction(invoice) + _extra(invoice)
    if fa._child(root, "Zalacznik") is not None:
        notes.append("Faktura ma załącznik — jego treść jest w pliku XML w KSeF.")
    footer = _footer(root)

    ksef = ""
    issue_day: Optional[date] = fa._date(_text(invoice, "P_1"))
    if ksef_number and issue_day is not None:
        url = invoice_pdf.qr_url(environment, seller_nip, issue_day, xml)
        ksef = (
            "<div class='ksef'>"
            f"<img src='{invoice_pdf.qr_svg(url)}' alt='Kod QR weryfikacji faktury w KSeF'>"
            f"<p>{escape(ksef_number)}</p></div>"
        )
    body = (
        f"<div class='head'><div><h1>{escape(title)}</h1>"
        f"<p class='number'>nr {escape(number)}</p>"
        + "".join(f"<p class='meta'>{escape(line)}</p>" for line in _dates(invoice))
        + f"</div>{ksef}</div>"
        "<div class='parties'>"
        + _party("Sprzedawca", seller)
        + _party("Nabywca", fa._child(root, "Podmiot2"))
        + "</div>"
        + _third_parties(root)
        + _items(invoice, currency, correction)
        + _summary(invoice, currency, correction)
        + "".join(f"<p class='note'>{escape(note)}</p>" for note in notes)
        + "".join(f"<p class='note'>{escape(line)}</p>" for line in footer)
        + f"<p class='note'>{escape(NOTICE)}</p>"
    )
    html = (
        "<!DOCTYPE html><html lang='pl'><head><meta charset='utf-8'>"
        f"<title>{escape(title)} {escape(number)}</title>"
        f"<style>{invoice_pdf.STYLE}</style></head><body>{body}</body></html>"
    )
    return Visual(html=html, title=title, invoice_number=number, seller_nip=seller_nip)


def render_pdf(visual: Visual) -> bytes:
    return invoice_pdf.render_pdf(visual.html)


def filename(visual: Visual) -> str:
    stem = "".join(
        ch if ch.isalnum() or ch in "-_" else "-" for ch in visual.invoice_number
    )
    return f"faktura-{stem[:80] or 'ksef'}.pdf"


def xml_digest(xml: bytes) -> str:
    return hashlib.sha256(xml).hexdigest()


__all__ = ["Visual", "filename", "render_html", "render_pdf", "xml_digest"]
